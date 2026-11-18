# drawsvg Preview (VS Code extension)

Shows the SVG produced by a drawsvg Python script next to the editor. Nothing
else: it does not depend on the UI_drawsvg application and does not change it.

## Use

- Open a drawsvg script and press **Ctrl+D** (or run *drawsvg: Open Preview*).
- Switching to another drawsvg script loads it automatically. If the file has
  an error, the last valid drawing stays visible and the error is shown.
- The preview updates after a short pause while typing and immediately on save.
  Set `drawsvgPreview.renderOn` to `save` to turn off updates while typing.
- Mouse wheel zooms, drag pans, double click or **Fit** resets,
  **Background** switches white / checkerboard / theme.

Ctrl+D keeps its normal VS Code meaning in every other file.

## What counts as a drawsvg script

1. `import drawsvg`, `import drawsvg as draw` or `from drawsvg import ...`
   at the top (only a docstring, `from __future__` and other imports before it),
2. a `Drawing(...)` call through that import,
3. a top-level `if __name__ == "__main__":` block,
4. a top-level function `build_drawing()` that returns the `Drawing`.

The preview calls `build_drawing().as_svg()`. The `__main__` block is never
run, so no `canvas.svg` is written.

## Security

The preview **executes the Python file** with your interpreter. It therefore
only renders in trusted workspaces and only files inside the workspace.
The script runs in its own folder, so relative file paths resolve there.
File writes in the script or its imports run with your user permissions.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `drawsvgPreview.pythonPath` | empty | Interpreter. Empty: Python extension, then `.venv`, then `python`. |
| `drawsvgPreview.renderOn` | `type` | `type` updates while typing and on save. `save` disables updates while typing. |
| `drawsvgPreview.debounceMs` | 300 | Delay while typing. |
| `drawsvgPreview.timeoutMs` | 10000 | Maximum render time. |

The interpreter needs the `drawsvg` package.

## Install and release

Download the `drawsvg-preview-*.vsix` asset from the
[GitHub Releases page](https://github.com/Taron686/drawsvg-ui/releases).
In VS Code use **Extensions: Install from VSIX...** and select the file.
The extension is licensed under MIT. See [LICENSE](LICENSE).

Maintainers can run **Actions → Release drawsvg Preview → Run workflow**.
The default build-only run provides a VSIX artifact. To publish it, select
`main` and enable `publish`. The workflow uses the version in `package.json`
to create the separate `drawsvg-preview-v<version>` tag and release.

## Develop

```bash
npm install
npm run build      # bundle to dist/
npm test           # detection unit tests
npm run package    # build a .vsix
python -m pytest python/tests
```

Press F5 in this folder to start an Extension Development Host.
