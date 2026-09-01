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
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QSignalSpy

import export_drawsvg
import import_drawsvg
from canvas_view import CanvasView, GroupItem
from constants import SHAPES
from layer_manager import DEFAULT_LAYER_ID
from scene_codec import KEY_ITEM_ID, KEY_LAYER_ID, SceneCodec
from shape_registry import SHAPE_REGISTRY
from items.shapes.paths import FreePathItem


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


@pytest.mark.parametrize("shape", ["Free Polyline", "Free Polygon", "Bezier Path"])
def test_free_paths_roundtrip_through_exported_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shape: str,
) -> None:
    source = CanvasView()
    item = source.add_shape(shape, QtCore.QPointF(25.0, 40.0), snap_to_grid=False)
    assert isinstance(item, FreePathItem)
    item.setPen(QtGui.QPen(QtGui.QColor("#234567"), 3.0, QtCore.Qt.PenStyle.DashLine))
    fill_color = QtGui.QColor("#abc123")
    fill_color.setAlphaF(0.4)
    item.setBrush(QtGui.QBrush(fill_color))
    item.setTransform(QtGui.QTransform(1.0, 0.2, 0.1, 1.1, 15.0, -8.0))
    if shape == "Bezier Path":
        item.move_handle(0, "control1", QtCore.QPointF(20.0, 90.0))
        item.move_handle(0, "control2", QtCore.QPointF(115.0, -30.0))
    else:
        item.move_handle(0, "end", QtCore.QPointF(180.0, 70.0))

    restored = _roundtrip(monkeypatch, tmp_path, source)
    restored_item = next(
        candidate
        for candidate in restored.scene().items()
        if candidate.data(0) == shape
    )

    assert isinstance(restored_item, FreePathItem)
    assert restored_item.path_payload() == item.path_payload()
    assert restored_item.pen().color() == item.pen().color()
    assert restored_item.pen().widthF() == pytest.approx(item.pen().widthF())
    assert restored_item.pen().style() == item.pen().style()
    assert restored_item.brush().color().name() == item.brush().color().name()
    assert restored_item.brush().color().alphaF() == pytest.approx(
        item.brush().color().alphaF(), abs=0.01
    )
    assert _matrix_values(restored_item) == pytest.approx(
        _matrix_values(item), abs=1e-4
    )


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


def test_text_export_uses_visual_lines_but_reimports_original_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = CanvasView()
    text_item = source.add_shape(
        "Text", QtCore.QPointF(100.0, 120.0), snap_to_grid=False
    )
    assert isinstance(text_item, QtWidgets.QGraphicsTextItem)
    raw_text = "A long paragraph that wraps visually inside its narrow text box."
    text_item.set_size(120.0, 200.0)
    text_item.setPlainText(raw_text)
    visual_lines = export_drawsvg._visual_text_lines(text_item)
    assert len(visual_lines) > 1

    export_path = tmp_path / "wrapped_text.py"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "Python (*.py)"),
    )
    export_drawsvg.export_drawsvg_py(source.scene())

    text_call = next(
        line.strip()
        for line in export_path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("_text = draw.Text(")
    )
    args, kwargs = import_drawsvg._parse_call(text_call)
    assert args[0] == visual_lines
    assert kwargs["data_raw_text"] == raw_text

    restored = CanvasView()
    loaded_path = import_drawsvg.import_drawsvg_py(
        restored.scene(),
        path=export_path,
    )
    restored_text = _shape_items(restored)["Text"]

    assert loaded_path == export_path.resolve()
    assert isinstance(restored_text, QtWidgets.QGraphicsTextItem)
    assert restored_text.toPlainText() == raw_text


def test_affine_transform_survives_clone_and_undo(tmp_path: Path) -> None:
    import_path = tmp_path / "affine.py"
    import_path.write_text(
        "import drawsvg as draw\n"
        "d = draw.Drawing(320, 240, origin=(0, 0))\n"
        "_rect = draw.Rectangle(0, 0, 80, 40, "
        "transform='matrix(-1 0 0.5 2 100 50)')\n"
        "d.append(_rect)\n",
        encoding="utf-8",
    )
    view = CanvasView()

    loaded_path = import_drawsvg.import_drawsvg_py(view.scene(), path=import_path)

    assert loaded_path == import_path.resolve()
    item = _shape_items(view)["Rectangle"]
    expected_transform = QtGui.QTransform(item.transform())
    clone = view._clone_item(item)
    assert clone is not None
    assert clone.transform() == expected_transform

    view.history().capture_now()
    item.setPos(item.pos() + QtCore.QPointF(25.0, 10.0))
    view.history().capture_now()
    view.undo()
    restored_item = _shape_items(view)["Rectangle"]

    assert restored_item.transform() == expected_transform


def test_import_replaces_scene_as_one_undo_transaction_and_syncs_layers(
    tmp_path: Path,
) -> None:
    import_path = tmp_path / "replacement.py"
    import_path.write_text(
        "import drawsvg as draw\n"
        "d = draw.Drawing(320, 240, origin=(0, 0))\n"
        "_rect = draw.Rectangle(0, 0, 80, 40)\n"
        "d.append(_rect)\n",
        encoding="utf-8",
    )
    view = CanvasView()
    view.add_shape("Ellipse", QtCore.QPointF(10.0, 20.0), snap_to_grid=False)
    layer_changes = QSignalSpy(view.layer_manager().changed)

    loaded_path = import_drawsvg.import_drawsvg_py(view.scene(), path=import_path)
    view.history().capture_now()

    assert loaded_path == import_path.resolve()
    imported = _shape_items(view)["Rectangle"]
    assert imported.data(KEY_LAYER_ID) == DEFAULT_LAYER_ID
    assert layer_changes.count() == 1

    view.undo()

    assert set(_shape_items(view)) == {"Ellipse"}


def test_folder_tree_import_applies_exported_affine_matrix(tmp_path: Path) -> None:
    import_path = tmp_path / "folder_tree_affine.py"
    import_path.write_text(
        "import drawsvg as draw\n"
        "d = draw.Drawing(320, 240, origin=(0, 0))\n"
        "# FolderTree pos=(100, 50) size=(180, 120) rotation=180 scale=1 "
        'structure={"name": "root", "type": "folder", "children": []}\n'
        "_folder_tree = draw.Group(transform='matrix(-1 0 0.5 2 100 50)')\n"
        "d.append(_folder_tree)\n",
        encoding="utf-8",
    )
    view = CanvasView()

    loaded_path = import_drawsvg.import_drawsvg_py(view.scene(), path=import_path)

    assert loaded_path == import_path.resolve()
    folder_tree = _shape_items(view)["Folder Tree"]
    assert _matrix_values(folder_tree) == pytest.approx(
        (-1.0, 0.0, 0.5, 2.0, 100.0, 50.0),
        abs=1e-6,
    )


@pytest.mark.parametrize(
    "shape",
    [
        "Rectangle",
        "Split Rounded Rectangle",
        "Ellipse",
        "Triangle",
        "Diamond",
        "Block Arrow",
        "Line",
        "Curvy Right Bracket",
    ],
)
def test_clone_preserves_item_scale(shape: str) -> None:
    view = CanvasView()
    item = view.add_shape(shape, QtCore.QPointF(10.0, 20.0), snap_to_grid=False)
    assert item is not None
    item.setScale(1.75)

    clone = view._clone_item(item)

    assert clone is not None
    assert clone.scale() == pytest.approx(1.75)


@pytest.mark.parametrize("shape", ["Hexagon", "Bezier Path"])
def test_clone_restores_registry_shapes_with_new_identity_and_layer(shape: str) -> None:
    view = CanvasView()
    item = view.add_shape(shape, QtCore.QPointF(10.0, 20.0), snap_to_grid=False)
    assert item is not None
    layer = view.layer_manager().add_layer("Clone source")
    assert view.layer_manager().assign_item(item, layer.id)
    item.setZValue(7.0)
    source_id = SceneCodec._item_id(item)

    clone = view._clone_item(item)

    assert clone is not None
    assert SHAPE_REGISTRY.serialize(clone) == SHAPE_REGISTRY.serialize(item)
    assert clone.data(KEY_LAYER_ID) == layer.id
    assert clone.zValue() == pytest.approx(7.0)
    assert clone.data(KEY_ITEM_ID) != source_id


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


def test_roundtrip_preserves_nonzero_local_shape_coordinates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = CanvasView()
    circle = source.add_shape(
        "Circle", QtCore.QPointF(-46.850394, -261.259843), snap_to_grid=False
    )
    assert isinstance(circle, QtWidgets.QGraphicsEllipseItem)
    circle.setRect(15.0, -15.0, 170.0, 170.0)
    circle.setTransformOriginPoint(circle.rect().center())
    expected_center = circle.mapToScene(circle.rect().center())

    restored = _roundtrip(monkeypatch, tmp_path, source)
    restored_circle = _shape_items(restored)["Circle"]
    actual_center = restored_circle.mapToScene(restored_circle.rect().center())

    assert actual_center.x() == pytest.approx(expected_center.x(), abs=1e-4)
    assert actual_center.y() == pytest.approx(expected_center.y(), abs=1e-4)


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
