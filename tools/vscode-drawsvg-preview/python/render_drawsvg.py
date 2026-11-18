"""Render helper for the drawsvg preview VS Code extension.

Reads a Python source file (or stdin), checks statically that it is a drawsvg
script, and prints exactly one JSON object on stdout:

    {"ok": true, "svg": "<svg ...>", "detect": {...}, "duration_ms": 12}
    {"ok": false, "error": {"kind": "...", "message": "...", "line": 3}, "detect": {...}}

The script's ``if __name__ == "__main__"`` block is never executed; the SVG is
taken from ``build_drawing().as_svg()``. Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import os
import sys
import time
import traceback

PREVIEW_RUN_NAME = "__drawsvg_preview__"
ENTRY = "build_drawing"


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    test = node.test
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    sides = [test.left, test.comparators[0]]
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    has_main = any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides)
    return has_name and has_main


def detect(source: str, filename: str = "<source>") -> dict:
    """Statically classify ``source``. Raises SyntaxError for invalid code."""
    tree = ast.parse(source, filename=filename)

    module_aliases: set[str] = set()  # names bound to the drawsvg module
    drawing_names: set[str] = set()  # names bound to drawsvg.Drawing
    import_line = None
    for index, node in enumerate(tree.body):
        is_docstring = (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        if is_docstring:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "drawsvg":
                    module_aliases.add(alias.asname or "drawsvg")
                    import_line = import_line or node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module == "drawsvg" and node.level == 0:
                import_line = import_line or node.lineno
                for alias in node.names:
                    if alias.name in ("Drawing", "*"):
                        drawing_names.add(alias.asname or "Drawing")
        else:
            break  # first real statement ends the import header

    has_import = import_line is not None

    has_usage = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "Drawing"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        ) or (isinstance(func, ast.Name) and func.id in drawing_names):
            has_usage = True
            break

    has_main = any(_is_main_guard(node) for node in tree.body)
    has_entry = any(
        isinstance(node, ast.FunctionDef) and node.name == ENTRY for node in tree.body
    )

    reasons = []
    if has_import:
        reasons.append(f"drawsvg import found at line {import_line}")
    else:
        reasons.append("no drawsvg import at the top of the file")
    if not has_usage:
        reasons.append("no Drawing(...) call through the drawsvg import")
    if not has_main:
        reasons.append('no top-level if __name__ == "__main__" block')

    return {
        "is_drawsvg": has_import and has_usage and has_main,
        "checks": {"import": has_import, "usage": has_usage, "main": has_main},
        "entry": ENTRY if has_entry else None,
        "reasons": reasons,
    }


def _error(kind: str, message: str, **extra) -> dict:
    return {"kind": kind, "message": message, **extra}


def _line_in_file(tb, path: str):
    """Line of the innermost traceback frame that belongs to ``path``."""
    line = None
    for frame in traceback.extract_tb(tb):
        if frame.filename == path:
            line = frame.lineno
    return line


def _exception_error(exc: BaseException, path: str) -> dict:
    if isinstance(exc, ModuleNotFoundError) and (exc.name or "").split(".")[0] == "drawsvg":
        kind = "drawsvg_missing"
        message = f"drawsvg is not installed for this interpreter ({sys.executable})"
    elif isinstance(exc, ImportError):
        kind, message = "import_error", str(exc)
    elif isinstance(exc, SystemExit):
        kind, message = "system_exit", f"script called sys.exit({exc.code!r})"
    else:
        kind, message = "runtime_error", f"{type(exc).__name__}: {exc}"
    return _error(
        kind,
        message,
        line=_line_in_file(exc.__traceback__, path),
        traceback="".join(traceback.format_exception(exc)),
    )


def render(source: str, path: str) -> dict:
    """Detect, then build the drawing and return the response dict."""
    started = time.perf_counter()
    try:
        info = detect(source, path)
    except SyntaxError as exc:
        return {
            "ok": False,
            "detect": None,
            "error": _error(
                "syntax_error", exc.msg or "invalid syntax", line=exc.lineno, col=exc.offset
            ),
        }

    if not info["is_drawsvg"]:
        failed = [r for r in info["reasons"] if r.startswith("no ")]
        return {
            "ok": False,
            "detect": info,
            "error": _error("not_drawsvg", "; ".join(failed)),
        }
    if info["entry"] is None:
        return {
            "ok": False,
            "detect": info,
            "error": _error("no_drawing", f"no top-level function {ENTRY}() in this file"),
        }

    script_dir = os.path.dirname(path) or os.getcwd()
    namespace = {"__name__": PREVIEW_RUN_NAME, "__file__": path, "__builtins__": __builtins__}
    old_cwd = os.getcwd()
    sys.path.insert(0, script_dir)
    try:
        os.chdir(script_dir)
        try:
            # Keep the script's print() output out of the JSON response.
            with contextlib.redirect_stdout(sys.stderr):
                exec(compile(source, path, "exec"), namespace)  # noqa: S102
                drawing = namespace[ENTRY]()
                import drawsvg

                if not isinstance(drawing, drawsvg.Drawing):
                    return {
                        "ok": False,
                        "detect": info,
                        "error": _error(
                            "no_drawing",
                            f"{ENTRY}() returned {type(drawing).__name__}, "
                            "expected drawsvg.Drawing",
                        ),
                    }
                svg = drawing.as_svg()
        finally:
            os.chdir(old_cwd)
    except BaseException as exc:  # noqa: BLE001 - includes SystemExit from the script
        if isinstance(exc, KeyboardInterrupt):
            raise
        return {"ok": False, "detect": info, "error": _exception_error(exc, path)}
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(script_dir)

    return {
        "ok": True,
        "svg": svg,
        "detect": info,
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", required=True, help="path of the drawsvg script")
    parser.add_argument("--stdin", action="store_true", help="read the source from stdin")
    parser.add_argument("--detect", action="store_true", help="only classify, never execute")
    args = parser.parse_args(argv)

    path = os.path.abspath(args.path)
    if args.stdin:
        source = sys.stdin.buffer.read().decode("utf-8")
    else:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()

    if args.detect:
        try:
            response = {"ok": True, "detect": detect(source, path)}
        except SyntaxError as exc:
            response = {
                "ok": False,
                "detect": None,
                "error": _error("syntax_error", exc.msg or "invalid syntax", line=exc.lineno),
            }
    else:
        response = render(source, path)

    sys.__stdout__.buffer.write(json.dumps(response).encode("utf-8"))
    sys.__stdout__.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
