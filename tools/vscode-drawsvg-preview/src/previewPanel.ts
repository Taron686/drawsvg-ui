import * as crypto from "node:crypto";
import * as vscode from "vscode";

/** Single webview that shows one SVG with zoom and pan. */
export class PreviewPanel {
  private readonly panel: vscode.WebviewPanel;

  constructor(onDispose: () => void) {
    this.panel = vscode.window.createWebviewPanel(
      "drawsvgPreview",
      "drawsvg Preview",
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [] },
    );
    this.panel.webview.html = html();
    this.panel.onDidDispose(onDispose);
  }

  reveal(): void {
    this.panel.reveal(undefined, true);
  }

  dispose(): void {
    this.panel.dispose();
  }

  /** `key` identifies the file; zoom and position are kept while it stays the same. */
  showSvg(svg: string, name: string, key: string): void {
    this.panel.title = `Preview: ${name}`;
    const src = `data:image/svg+xml;base64,${Buffer.from(svg, "utf8").toString("base64")}`;
    void this.panel.webview.postMessage({ type: "svg", src, name, key });
  }

  showError(message: string, name: string): void {
    void this.panel.webview.postMessage({ type: "error", message, name });
  }

  showStatus(text: string): void {
    void this.panel.webview.postMessage({ type: "status", text });
  }
}

function html(): string {
  const nonce = crypto.randomBytes(16).toString("base64");
  // The SVG is shown through <img>, so scripts inside the SVG never run.
  const csp = `default-src 'none'; img-src data:; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'`;
  return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style nonce="${nonce}">
  html, body { height: 100%; margin: 0; overflow: hidden; }
  body { display: flex; flex-direction: column; color: var(--vscode-foreground);
         background: var(--vscode-editor-background); font: var(--vscode-font-size) var(--vscode-font-family); }
  #bar { display: flex; gap: 8px; align-items: center; padding: 4px 8px;
         border-bottom: 1px solid var(--vscode-panel-border); }
  #name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #status { opacity: .7; flex: 1; white-space: nowrap; }
  button { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground);
           border: 0; padding: 2px 8px; cursor: pointer; }
  button:hover { background: var(--vscode-button-secondaryHoverBackground); }
  #error { display: none; margin: 0; padding: 6px 8px; white-space: pre-wrap; max-height: 30%; overflow: auto;
           color: var(--vscode-inputValidation-errorForeground, var(--vscode-foreground));
           background: var(--vscode-inputValidation-errorBackground);
           border-bottom: 1px solid var(--vscode-inputValidation-errorBorder); }
  #error.on { display: block; }
  #view { flex: 1; position: relative; overflow: hidden; cursor: grab; }
  #view.drag { cursor: grabbing; }
  #img { position: absolute; left: 0; top: 0; transform-origin: 0 0; user-select: none; display: none; }
  #img.white { background: #fff; }
  #img.checker { background: repeating-conic-gradient(#ccc 0% 25%, #fff 0% 50%) 0 0 / 16px 16px; }
  #empty { padding: 12px; opacity: .7; }
</style>
</head>
<body>
<div id="bar">
  <span id="name"></span><span id="status"></span>
  <span id="zoom"></span>
  <button id="fit" title="Fit to window (double click)">Fit</button>
  <button id="one" title="Original size">1:1</button>
  <button id="bg" title="Switch background: white / checkerboard / theme">Background</button>
</div>
<pre id="error"></pre>
<div id="view"><div id="empty">No drawing rendered yet.</div><img id="img" alt="" draggable="false"></div>
<script nonce="${nonce}">
(() => {
  const view = document.getElementById("view"), img = document.getElementById("img");
  const nameEl = document.getElementById("name"), statusEl = document.getElementById("status");
  const errorEl = document.getElementById("error"), zoomEl = document.getElementById("zoom");
  const backgrounds = ["white", "checker", ""];
  let background = 0, scale = 1, x = 0, y = 0, key = null, fitOnLoad = true;
  img.className = backgrounds[background];

  function apply() {
    img.style.transform = "translate(" + x + "px," + y + "px) scale(" + scale + ")";
    zoomEl.textContent = Math.round(scale * 100) + "%";
  }
  function fit() {
    const w = img.naturalWidth || 300, h = img.naturalHeight || 150, pad = 16;
    scale = Math.min((view.clientWidth - pad) / w, (view.clientHeight - pad) / h);
    if (!(scale > 0)) scale = 1;
    x = (view.clientWidth - w * scale) / 2;
    y = (view.clientHeight - h * scale) / 2;
    apply();
  }
  function zoomAt(factor, cx, cy) {
    const next = Math.min(64, Math.max(0.02, scale * factor));
    x = cx - (cx - x) * (next / scale);
    y = cy - (cy - y) * (next / scale);
    scale = next;
    apply();
  }

  img.addEventListener("load", () => {
    document.getElementById("empty").style.display = "none";
    img.style.display = "block";
    if (fitOnLoad) fit();
  });
  view.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = view.getBoundingClientRect();
    zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  view.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    view.setPointerCapture(e.pointerId);
    view.classList.add("drag");
  });
  view.addEventListener("pointermove", (e) => {
    if (!view.hasPointerCapture(e.pointerId)) return;
    x += e.movementX; y += e.movementY;
    apply();
  });
  const release = (e) => { view.classList.remove("drag"); if (view.hasPointerCapture(e.pointerId)) view.releasePointerCapture(e.pointerId); };
  view.addEventListener("pointerup", release);
  view.addEventListener("pointercancel", release);
  view.addEventListener("dblclick", fit);
  document.getElementById("fit").addEventListener("click", fit);
  document.getElementById("one").addEventListener("click", () => {
    const r = view.getBoundingClientRect();
    zoomAt(1 / scale, r.width / 2, r.height / 2);
  });
  document.getElementById("bg").addEventListener("click", () => {
    background = (background + 1) % backgrounds.length;
    img.className = backgrounds[background];
  });

  window.addEventListener("message", (event) => {
    const m = event.data;
    if (m.type === "svg") {
      fitOnLoad = m.key !== key;   // keep zoom and position for the same file
      key = m.key;
      nameEl.textContent = m.name;
      statusEl.textContent = "";
      errorEl.classList.remove("on");
      img.src = m.src;
    } else if (m.type === "error") {
      statusEl.textContent = key ? "error in " + m.name + " - showing last valid drawing" : "error in " + m.name;
      errorEl.textContent = m.message;
      errorEl.classList.add("on");
    } else if (m.type === "status") {
      statusEl.textContent = m.text;
    }
  });
})();
</script>
</body>
</html>`;
}
