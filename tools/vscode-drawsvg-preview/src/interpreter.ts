import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";

/**
 * Interpreter for a document: explicit setting, then the environment selected
 * in the Python extension, then a `.venv` in the workspace folder, then `python`.
 */
export async function resolvePython(uri: vscode.Uri): Promise<string> {
  const configured = vscode.workspace
    .getConfiguration("drawsvgPreview", uri)
    .get<string>("pythonPath", "")
    .trim();
  if (configured) {
    return configured;
  }

  const fromExtension = await pythonExtensionInterpreter(uri);
  if (fromExtension) {
    return fromExtension;
  }

  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (folder) {
    const relative =
      process.platform === "win32" ? [".venv", "Scripts", "python.exe"] : [".venv", "bin", "python"];
    const candidate = path.join(folder.uri.fsPath, ...relative);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return "python";
}

async function pythonExtensionInterpreter(uri: vscode.Uri): Promise<string | undefined> {
  const extension = vscode.extensions.getExtension("ms-python.python");
  if (!extension) {
    return undefined;
  }
  try {
    const api = extension.isActive ? extension.exports : await extension.activate();
    const environments = api?.environments;
    if (!environments) {
      return undefined;
    }
    const resolved = await environments.resolveEnvironment(
      environments.getActiveEnvironmentPath(uri),
    );
    return resolved?.executable?.uri?.fsPath;
  } catch {
    return undefined; // API changed or failed: fall back to the next source.
  }
}
