"""Tests for the drawsvg preview render helper."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "render_drawsvg.py"

_spec = importlib.util.spec_from_file_location("render_drawsvg", HELPER)
render_drawsvg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_drawsvg)

MAIN = 'if __name__ == "__main__":\n    build_drawing().save_svg("canvas.svg")\n'
BODY = "def build_drawing():\n    d = draw.Drawing(100, 50)\n    return d\n\n"
EXPORTER_STYLE = "# Auto-generated\nimport drawsvg as draw\n\n" + BODY + MAIN


def run_helper(tmp_path: Path, source: str, *extra: str, stdin: str | None = None) -> dict:
    script = tmp_path / "scripts" / "sample_drawsvg.py"
    script.parent.mkdir()
    script.write_text(source, encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    result = subprocess.run(
        [sys.executable, str(HELPER), "--path", str(script), *extra],
        input=stdin.encode("utf-8") if stdin is not None else None,
        capture_output=True,
        cwd=cwd,
        timeout=60,
        check=True,
    )
    response = json.loads(result.stdout.decode("utf-8"))
    # Neither the script folder nor the working directory may gain files.
    assert list(cwd.iterdir()) == []
    assert [p.name for p in script.parent.iterdir() if p.is_file()] == [script.name]
    return response


@pytest.mark.parametrize(
    "source",
    [
        EXPORTER_STYLE,
        EXPORTER_STYLE.replace('"__main__"', "'__main__'"),
        EXPORTER_STYLE.replace('__name__ == "__main__"', '"__main__" == __name__'),
        "import drawsvg\n\ndef build_drawing():\n    return drawsvg.Drawing(1, 1)\n\n" + MAIN,
        "from drawsvg import Drawing, Circle\n\n"
        "def build_drawing():\n    return Drawing(1, 1)\n\n" + MAIN,
        "from drawsvg import Drawing as D\n\ndef build_drawing():\n    return D(1, 1)\n\n" + MAIN,
        '"""Doc."""\nfrom __future__ import annotations\n# comment\nimport math\n'
        "import drawsvg as draw\n\n" + BODY + MAIN,
    ],
)
def test_detect_accepts(source):
    info = render_drawsvg.detect(source)
    assert info["is_drawsvg"] is True
    assert info["entry"] == "build_drawing"


@pytest.mark.parametrize(
    ("source", "failed_check"),
    [
        ("import math\n\n" + BODY.replace("draw.", "math.") + MAIN, "import"),
        ("def helper():\n    pass\n\nimport drawsvg as draw\n\n" + BODY + MAIN, "import"),
        ("import drawsvg as draw\n\ndef build_drawing():\n    return None\n\n" + MAIN, "usage"),
        ('import drawsvg as draw\n\nTEXT = "draw.Drawing(1, 1)"\n\n' + MAIN, "usage"),
        ("import drawsvg as draw\n\n" + BODY, "main"),
        (
            "import drawsvg as draw\n\n" + BODY + '# if __name__ == "__main__":\n',
            "main",
        ),
    ],
)
def test_detect_rejects(source, failed_check):
    info = render_drawsvg.detect(source)
    assert info["is_drawsvg"] is False
    assert info["checks"][failed_check] is False


def test_detect_raises_on_syntax_error():
    with pytest.raises(SyntaxError):
        render_drawsvg.detect("import drawsvg as draw\ndef (:\n")


def test_render_exporter_style_without_side_effects(tmp_path):
    response = run_helper(tmp_path, EXPORTER_STYLE)
    assert response["ok"] is True
    assert response["svg"].lstrip().startswith("<?xml") or "<svg" in response["svg"]
    assert 'width="100"' in response["svg"]


def test_render_uses_stdin_instead_of_file(tmp_path):
    unsaved = EXPORTER_STYLE.replace("Drawing(100, 50)", "Drawing(321, 50)")
    response = run_helper(tmp_path, EXPORTER_STYLE, "--stdin", stdin=unsaved)
    assert response["ok"] is True
    assert 'width="321"' in response["svg"]


def test_render_reads_relative_file_next_to_script(tmp_path, monkeypatch):
    drawings = tmp_path / "drawing files"
    drawings.mkdir()
    (drawings / "width.txt").write_text("137", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    source = (
        "import drawsvg as draw\n\n"
        "def build_drawing():\n"
        '    with open("width.txt", encoding="utf-8") as handle:\n'
        "        return draw.Drawing(int(handle.read()), 50)\n\n"
        + MAIN
    )

    response = render_drawsvg.render(source, str(drawings / "sample_drawsvg.py"))

    assert response["ok"] is True, response.get("error")
    assert 'width="137"' in response["svg"]
    assert Path.cwd() == tmp_path
    assert not (drawings / "canvas.svg").exists()


def test_render_keeps_stdout_clean_when_script_prints(tmp_path):
    source = EXPORTER_STYLE.replace("    return d\n", '    print("noise")\n    return d\n')
    assert run_helper(tmp_path, source)["ok"] is True


def test_render_does_not_execute_non_drawsvg_file(tmp_path):
    source = "import pathlib\npathlib.Path('executed.txt').write_text('x')\n"
    response = run_helper(tmp_path, source)
    assert response["error"]["kind"] == "not_drawsvg"


def test_render_reports_syntax_error_with_line(tmp_path):
    response = run_helper(tmp_path, "import drawsvg as draw\n\ndef (:\n")
    assert response["error"]["kind"] == "syntax_error"
    assert response["error"]["line"] == 3


def test_render_reports_runtime_error_with_line(tmp_path):
    source = EXPORTER_STYLE.replace("    return d\n", "    1 / 0\n    return d\n")
    response = run_helper(tmp_path, source)
    assert response["error"]["kind"] == "runtime_error"
    assert "ZeroDivisionError" in response["error"]["message"]
    assert response["error"]["line"] == 6


def test_render_requires_build_drawing(tmp_path):
    source = (
        "import drawsvg as draw\n\n"
        'if __name__ == "__main__":\n    draw.Drawing(1, 1).save_svg("canvas.svg")\n'
    )
    response = run_helper(tmp_path, source)
    assert response["error"]["kind"] == "no_drawing"


def test_render_rejects_wrong_return_type(tmp_path):
    source = EXPORTER_STYLE.replace("    return d\n", "    return 42\n")
    response = run_helper(tmp_path, source)
    assert response["error"]["kind"] == "no_drawing"


def test_render_reports_other_import_error(tmp_path):
    source = EXPORTER_STYLE.replace(
        "import drawsvg as draw\n", "import drawsvg as draw\nimport no_such_module_xyz\n"
    )
    response = run_helper(tmp_path, source)
    assert response["error"]["kind"] == "import_error"
    assert response["error"]["line"] == 3


def test_render_reports_system_exit(tmp_path):
    source = EXPORTER_STYLE.replace("    return d\n", "    raise SystemExit(3)\n")
    response = run_helper(tmp_path, source)
    assert response["error"]["kind"] == "system_exit"


def test_missing_drawsvg_is_classified():
    exc = ModuleNotFoundError("No module named 'drawsvg'", name="drawsvg")
    assert render_drawsvg._exception_error(exc, "x.py")["kind"] == "drawsvg_missing"


def test_detect_only_mode_never_executes(tmp_path):
    source = EXPORTER_STYLE.replace("    return d\n", "    raise RuntimeError('ran')\n")
    response = run_helper(tmp_path, source, "--detect")
    assert response == {"ok": True, "detect": render_drawsvg.detect(source)}
