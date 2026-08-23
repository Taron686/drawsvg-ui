from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import pytest
from PySide6 import QtCore, QtWidgets

import export_drawsvg
import import_drawsvg
from canvas_view import CanvasView, GroupItem
from constants import SHAPES


@pytest.fixture(scope="session", autouse=True)
def application() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: CanvasView,
) -> CanvasView:
    export_path = tmp_path / "canvas_drawsvg.py"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "Python (*.py)"),
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(export_path), "Python (*.py)"),
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *args: None)

    export_drawsvg.export_drawsvg_py(source.scene())
    exported_module = runpy.run_path(str(export_path))
    exported_module["build_drawing"]().as_svg()
    result = CanvasView()
    import_drawsvg.import_drawsvg_py(result.scene())
    return result


def _shape_items(view: CanvasView) -> dict[str, QtWidgets.QGraphicsItem]:
    return {
        str(item.data(0)): item
        for item in view.scene().items()
        if item.data(0) in SHAPES
    }


def _matrix_values(item: QtWidgets.QGraphicsItem) -> tuple[float, ...]:
    transform = item.sceneTransform()
    return (
        transform.m11(),
        transform.m12(),
        transform.m21(),
        transform.m22(),
        transform.m31(),
        transform.m32(),
    )


def test_all_palette_shapes_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = CanvasView()
    for index, shape in enumerate(SHAPES):
        source.add_shape(
            shape,
            QtCore.QPointF(index * 120.0, index * 80.0),
            snap_to_grid=False,
        )

    restored = _roundtrip(monkeypatch, tmp_path, source)

    assert set(_shape_items(restored)) == set(SHAPES)


def test_text_roundtrip_preserves_explicit_content_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = CanvasView()
    text_item = source.add_shape(
        "Text", QtCore.QPointF(100.0, 120.0), snap_to_grid=False
    )
    assert isinstance(text_item, QtWidgets.QGraphicsTextItem)
    text_item.setPlainText("Text\nwith an explicit break")

    restored = _roundtrip(monkeypatch, tmp_path, source)
    restored_text = _shape_items(restored)["Text"]

    assert isinstance(restored_text, QtWidgets.QGraphicsTextItem)
    assert restored_text.toPlainText() == "Text\nwith an explicit break"


def test_group_transform_is_flattened_without_moving_children(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = CanvasView()
    for index, shape in enumerate(SHAPES):
        item = source.add_shape(
            shape,
            QtCore.QPointF(300.0 + index * 120.0, 400.0 + index * 80.0),
            snap_to_grid=False,
        )
        assert item is not None
        item.setSelected(True)
    source._group_selected_items()

    group = next(
        item for item in source.scene().items() if isinstance(item, GroupItem)
    )
    group.setPos(group.pos() + QtCore.QPointF(100.0, 50.0))
    group.setRotation(20.0)
    group.setScale(1.5)
    expected = {
        shape: _matrix_values(item) for shape, item in _shape_items(source).items()
    }

    restored = _roundtrip(monkeypatch, tmp_path, source)
    actual = {
        shape: _matrix_values(item) for shape, item in _shape_items(restored).items()
    }

    assert actual.keys() == expected.keys()
    for shape in expected:
        assert actual[shape] == pytest.approx(expected[shape], abs=1e-4)


@pytest.mark.parametrize(
    "contents",
    [
        "_rect = draw.Rectangle(not_valid +, 0, 1, 1)\n",
        "print('unrelated Python file')\n",
    ],
)
def test_failed_import_preserves_existing_scene(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    contents: str,
) -> None:
    import_path = tmp_path / "invalid.py"
    import_path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(import_path), "Python (*.py)"),
    )
    errors: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "critical",
        lambda _parent, _title, message: errors.append(str(message)),
    )
    view = CanvasView()
    view.add_shape(
        "Rectangle", QtCore.QPointF(10.0, 20.0), snap_to_grid=False
    )
    state_before = view._serialize_scene_state()

    import_drawsvg.import_drawsvg_py(view.scene())

    assert view._serialize_scene_state() == state_before
    assert errors
