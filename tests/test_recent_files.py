from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import pytest
from PySide6 import QtWidgets

import import_drawsvg
import main_window
from canvas_view import CanvasView
from main_window import MainWindow


@pytest.fixture(scope="session", autouse=True)
def application() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_history_file_is_created_and_limited_to_ten(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "recent_files.json"
    window = MainWindow(recent_files_path=history_path)

    assert not history_path.exists()

    files = [tmp_path / f"drawing_{index}.py" for index in range(11)]
    for path in files:
        window._remember_recent_file(path)

    stored = json.loads(history_path.read_text(encoding="utf-8"))
    assert stored == [str(path.resolve()) for path in reversed(files[1:])]

    window._remember_recent_file(files[5])
    stored = json.loads(history_path.read_text(encoding="utf-8"))
    assert stored[0] == str(files[5].resolve())
    assert len(stored) == 10


def test_corrupt_history_is_not_overwritten(tmp_path: Path) -> None:
    history_path = tmp_path / "recent_files.json"
    corrupt_contents = "{not valid json"
    history_path.write_text(corrupt_contents, encoding="utf-8")

    window = MainWindow(recent_files_path=history_path)

    assert window._recent_files == []
    assert history_path.read_text(encoding="utf-8") == corrupt_contents


def test_unwritable_history_does_not_prevent_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "recent_files.json"
    drawing_path = tmp_path / "drawing.py"
    history_path.write_text(
        json.dumps([str(drawing_path), str(drawing_path)]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main_window.tempfile,
        "NamedTemporaryFile",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read-only")),
    )

    window = MainWindow(recent_files_path=history_path)
    window._remember_recent_file(tmp_path / "another.py")

    assert window._recent_files[0] == str((tmp_path / "another.py").resolve())


def test_failed_recent_file_is_removed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "recent_files.json"
    missing_path = tmp_path / "missing.py"
    history_path.write_text(
        json.dumps([str(missing_path.resolve())]),
        encoding="utf-8",
    )
    monkeypatch.setattr(main_window, "import_drawsvg_py", lambda *_args: None)
    window = MainWindow(recent_files_path=history_path)

    window._open_recent_file(str(missing_path))

    assert window._recent_files == []
    assert json.loads(history_path.read_text(encoding="utf-8")) == []
    assert not window.recent_files_menu.isEnabled()


def test_successful_load_updates_recently_opened_menu(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "recent_files.json"
    drawing_path = tmp_path / "drawing.py"
    window = MainWindow(recent_files_path=history_path)
    monkeypatch.setattr(
        main_window,
        "import_drawsvg_py",
        lambda *_args: drawing_path.resolve(),
    )

    window.load_drawsvg_py()

    assert window.recent_files_menu.title() == "Recently Opened"
    assert window.recent_files_menu.isEnabled()
    assert window.recent_files_menu.actions()[0].text() == "&1 drawing.py"


def test_recent_file_action_loads_selected_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "recent_files.json"
    drawing_path = tmp_path / "drawing.py"
    history_path.write_text(
        json.dumps([str(drawing_path.resolve())]),
        encoding="utf-8",
    )
    loaded_paths: list[Path] = []
    monkeypatch.setattr(
        main_window,
        "import_drawsvg_py",
        lambda _scene, _parent, path: loaded_paths.append(Path(path)) or Path(path),
    )
    window = MainWindow(recent_files_path=history_path)

    window.recent_files_menu.actions()[0].trigger()

    assert loaded_paths == [drawing_path.resolve()]


def test_import_accepts_explicit_recent_file_path(tmp_path: Path) -> None:
    drawing_path = tmp_path / "drawing.py"
    drawing_path.write_text(
        "import drawsvg as draw\n"
        "d = draw.Drawing(320, 240, origin=(0, 0))\n",
        encoding="utf-8",
    )
    view = CanvasView()

    loaded_path = import_drawsvg.import_drawsvg_py(
        view.scene(),
        path=drawing_path,
    )

    assert loaded_path == drawing_path.resolve()
    assert view.scene().sceneRect().width() == 320
    assert view.scene().sceneRect().height() == 240
