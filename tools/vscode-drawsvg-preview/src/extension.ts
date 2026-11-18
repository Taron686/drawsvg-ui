import { ChildProcess, spawn } from "node:child_process";
import * as path from "node:path";
import * as vscode from "vscode";
import { looksLikeDrawsvg } from "./detection";
import { resolvePython } from "./interpreter";
import { PreviewPanel } from "./previewPanel";

const CONTEXT_KEY = "drawsvgPreview.isDrawsvgFile";
const MAX_OUTPUT_BYTES = 64 * 1024 * 1024;

interface RenderResponse {
  ok: boolean;
  svg?: string;
  error?: { kind: string; message: string; line?: number | null; col?: number | null; traceback?: string };
}

function isDrawsvgDocument(document: vscode.TextDocument): boolean {
  return document.languageId === "python" && looksLikeDrawsvg(document.getText());
}

class PreviewController implements vscode.Disposable {
  private panel: PreviewPanel | undefined;
  private tracked: vscode.Uri | undefined;
  private runId = 0;
  private child: ChildProcess | undefined;
  private typingTimer: NodeJS.Timeout | undefined;
  private contextTimer: NodeJS.Timeout | undefined;
  private readonly diagnostics = vscode.languages.createDiagnosticCollection("drawsvg-preview");
  private readonly output = vscode.window.createOutputChannel("drawsvg Preview");
  private readonly helper: string;

  constructor(context: vscode.ExtensionContext) {
    this.helper = path.join(context.extensionPath, "python", "render_drawsvg.py");
  }

  /** Ctrl+D / command palette. */
  open(): void {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !isDrawsvgDocument(editor.document)) {
      void vscode.window.showInformationMessage(
        'drawsvg Preview: the active file is not a drawsvg script (needs "import drawsvg" at the top and an if __name__ == "__main__" block).',
      );
      return;
    }
    if (this.panel) {
      this.panel.reveal();
    } else {
      this.panel = new PreviewPanel(() => {
        this.panel = undefined;
        this.tracked = undefined;
        this.cancel();
        this.diagnostics.clear();
      });
    }
    void this.render(editor.document);
  }

  updateContext(): void {
    const editor = vscode.window.activeTextEditor;
    void vscode.commands.executeCommand(
      "setContext",
      CONTEXT_KEY,
      !!editor && isDrawsvgDocument(editor.document),
    );
  }

  onActiveEditorChanged(editor: vscode.TextEditor | undefined): void {
    this.updateContext();
    // No editor means the webview or another panel took focus: keep following
    // the tracked file. A normal file keeps the last drawing on screen.
    if (!this.panel || !editor) {
      return;
    }
    if (isDrawsvgDocument(editor.document)) {
      if (editor.document.uri.toString() !== this.tracked?.toString()) {
        void this.render(editor.document);
      }
    } else {
      this.cancel();
    }
  }

  onDocumentChanged(event: vscode.TextDocumentChangeEvent): void {
    const document = event.document;
    if (document === vscode.window.activeTextEditor?.document) {
      clearTimeout(this.contextTimer);
      this.contextTimer = setTimeout(() => this.updateContext(), 150);
    }
    if (!this.panel || document.uri.toString() !== this.tracked?.toString()) {
      return;
    }
    const config = vscode.workspace.getConfiguration("drawsvgPreview", document.uri);
    if (config.get<string>("renderOn") === "type") {
      clearTimeout(this.typingTimer);
      this.typingTimer = setTimeout(
        () => void this.render(document),
        config.get<number>("debounceMs", 300),
      );
    }
  }

  onDocumentSaved(document: vscode.TextDocument): void {
    if (this.panel && document.uri.toString() === this.tracked?.toString()) {
      void this.render(document);
    }
  }

  private cancel(): void {
    this.runId++; // any result that still arrives is stale
    clearTimeout(this.typingTimer);
    this.child?.kill();
    this.child = undefined;
  }

  private async render(document: vscode.TextDocument): Promise<void> {
    const panel = this.panel;
    if (!panel) {
      return;
    }
    this.cancel();
    const runId = this.runId;
    const uri = document.uri;
    const version = document.version;
    const name = path.basename(uri.fsPath);
    this.tracked = uri;

    if (!vscode.workspace.isTrusted) {
      panel.showError("Workspace is not trusted. The preview runs the Python file, so rendering is disabled.", name);
      return;
    }
    if (uri.scheme !== "file" || !vscode.workspace.getWorkspaceFolder(uri)) {
      panel.showError("Only saved files inside the opened workspace are rendered.", name);
      return;
    }

    panel.showStatus(`rendering ${name} ...`);
    const python = await resolvePython(uri);
    if (runId !== this.runId) {
      return;
    }
    const timeoutMs = vscode.workspace
      .getConfiguration("drawsvgPreview", uri)
      .get<number>("timeoutMs", 10000);

    let response: RenderResponse;
    try {
      response = await this.runHelper(python, uri.fsPath, document.getText(), timeoutMs);
    } catch (error) {
      response = { ok: false, error: { kind: "bad_output", message: String((error as Error).message) } };
    }
    // Discard results of superseded runs (file switched, newer edit, panel closed).
    if (runId !== this.runId || this.panel !== panel) {
      return;
    }

    if (response.ok && response.svg !== undefined) {
      this.diagnostics.delete(uri);
      panel.showSvg(response.svg, name, uri.toString());
      return;
    }

    const error = response.error ?? { kind: "bad_output", message: "no result" };
    const hint = error.kind === "drawsvg_missing" ? `\nInterpreter: ${python} (setting drawsvgPreview.pythonPath)` : "";
    const where = error.line ? ` (line ${error.line})` : "";
    panel.showError(`${error.message}${where}${hint}`, name);
    this.output.appendLine(`[${name}] ${error.kind}: ${error.message}${where}`);
    if (error.traceback) {
      this.output.appendLine(error.traceback);
    }
    // Only mark a line when the helper reported a real one for this document version.
    if (error.line && document.version === version) {
      const line = Math.min(Math.max(error.line - 1, 0), document.lineCount - 1);
      const diagnostic = new vscode.Diagnostic(
        document.lineAt(line).range,
        error.message,
        vscode.DiagnosticSeverity.Error,
      );
      diagnostic.source = "drawsvg preview";
      this.diagnostics.set(uri, [diagnostic]);
    } else {
      this.diagnostics.delete(uri);
    }
  }

  private runHelper(python: string, file: string, source: string, timeoutMs: number): Promise<RenderResponse> {
    return new Promise((resolve, reject) => {
      // Argument array, never a shell: paths may contain spaces.
      const child = spawn(python, ["-X", "utf8", this.helper, "--stdin", "--path", file], {
        cwd: path.dirname(file),
        windowsHide: true,
      });
      this.child = child;
      const chunks: Buffer[] = [];
      let size = 0;
      let stderr = "";
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        child.kill();
      }, timeoutMs);

      child.stdout.on("data", (chunk: Buffer) => {
        size += chunk.length;
        if (size > MAX_OUTPUT_BYTES) {
          child.kill();
        } else {
          chunks.push(chunk);
        }
      });
      child.stderr.on("data", (chunk: Buffer) => {
        if (stderr.length < 20000) {
          stderr += chunk.toString("utf8");
        }
      });
      child.on("error", (error) => {
        clearTimeout(timer);
        reject(new Error(`Could not start Python "${python}": ${error.message}`));
      });
      child.on("close", () => {
        clearTimeout(timer);
        if (this.child === child) {
          this.child = undefined;
        }
        if (stderr.trim()) {
          this.output.appendLine(stderr.trimEnd());
        }
        if (timedOut) {
          resolve({ ok: false, error: { kind: "timeout", message: `Rendering took longer than ${timeoutMs} ms and was stopped.` } });
          return;
        }
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")) as RenderResponse);
        } catch {
          reject(new Error(`Python returned no valid result. ${stderr.trim().split(/\r?\n/).pop() ?? ""}`));
        }
      });
      child.stdin.on("error", () => undefined); // process may exit before reading
      child.stdin.end(source, "utf8");
    });
  }

  dispose(): void {
    this.cancel();
    clearTimeout(this.contextTimer);
    this.panel?.dispose();
    this.diagnostics.dispose();
    this.output.dispose();
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const controller = new PreviewController(context);
  context.subscriptions.push(
    controller,
    vscode.commands.registerCommand("drawsvgPreview.open", () => controller.open()),
    vscode.window.onDidChangeActiveTextEditor((editor) => controller.onActiveEditorChanged(editor)),
    vscode.workspace.onDidChangeTextDocument((event) => controller.onDocumentChanged(event)),
    vscode.workspace.onDidSaveTextDocument((document) => controller.onDocumentSaved(document)),
  );
  controller.updateContext(); // the editor that triggered activation
}

export function deactivate(): void {
  // Disposables registered in activate() clean up.
}
