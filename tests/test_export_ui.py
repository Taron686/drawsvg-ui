from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items import RectItem
from main_window import MainWindow


def test_file_menu_exposes_all_shared_renderer_exports(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    window = MainWindow(recent_files_path=tmp_path / "recent.json")
    file_menu = window.menuBar().findChild(QtWidgets.QMenu, "menuFile")

    assert file_menu is not None
    assert [
        action.text()
        for action in file_menu.actions()
        if action in {
            window.actionExport_svg,
            window.actionExport_png,
            window.actionExport_pdf,
        }
    ] == ["Export SVG…", "Export PNG…", "Export PDF…"]

    window.close()


@pytest.mark.parametrize("export_format", ["svg", "png", "pdf"])
def test_file_menu_export_writes_format_without_mutating_scene_or_history(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    export_format: str,
) -> None:
    window = MainWindow(recent_files_path=tmp_path / "recent.json")
    scene = window.canvas.scene()
    item = RectItem(0.0, 0.0, 40.0, 30.0)
    item.setBrush(QtGui.QColor("#d94f4f"))
    scene.addItem(item)
    item.setSelected(True)

    history = window.canvas.history()
    history.capture_now()
    history._timer.stop()
    scene_before = window.canvas._serialize_scene_state()
    states_before = list(history._states)
    index_before = history._index
    selected_before = tuple(scene.selectedItems())
    visibility_before = tuple((scene_item, scene_item.isVisible()) for scene_item in scene.items())

    selected_path = tmp_path / f"review-{export_format}"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(selected_path), ""),
    )

    getattr(window, f"actionExport_{export_format}").trigger()

    output_path = selected_path.with_suffix(f".{export_format}")
    assert output_path.is_file()
    if export_format == "svg":
        assert ElementTree.parse(output_path).getroot().tag.endswith("svg")
    elif export_format == "png":
        assert not QtGui.QImageReader(str(output_path)).read().isNull()
    else:
        assert output_path.read_bytes().startswith(b"%PDF-")

    assert window.canvas._serialize_scene_state() == scene_before
    assert list(history._states) == states_before
    assert history._index == index_before
    assert tuple(scene.selectedItems()) == selected_before
    assert tuple((scene_item, scene_item.isVisible()) for scene_item in scene.items()) == visibility_before

    window.close()


def test_file_menu_png_export_crops_to_content_instead_of_page(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    window = MainWindow(recent_files_path=tmp_path / "recent.json")
    item = RectItem(100.0, 120.0, 40.0, 30.0)
    window.canvas.scene().addItem(item)
    item.setSelected(True)
    output_path = tmp_path / "content.png"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(output_path), ""),
    )

    window.actionExport_png.trigger()

    expected_size = item.sceneBoundingRect().size().toSize()
    assert QtGui.QImage(str(output_path)).size() == expected_size
    window.close()
