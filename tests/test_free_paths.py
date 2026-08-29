from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from clipboard_service import ClipboardService
from export_drawsvg import export_drawsvg_py
from items.shapes.paths import BezierPathItem, FreePathItem
from shape_registry import SHAPE_REGISTRY


@pytest.mark.parametrize("shape", ["Free Polyline", "Free Polygon", "Bezier Path"])
def test_free_path_registry_roundtrip_preserves_editable_geometry(
    application: QtWidgets.QApplication, shape: str
) -> None:
    item = SHAPE_REGISTRY.create(shape, 12.0, 34.0)

    assert isinstance(item, FreePathItem)
    item.move_handle(-1, "start", QtCore.QPointF(5.0, 7.0))
    item.move_handle(0, "end", QtCore.QPointF(90.0, 40.0))
    if isinstance(item, BezierPathItem):
        item.move_handle(0, "control1", QtCore.QPointF(30.0, 80.0))
        item.move_handle(0, "control2", QtCore.QPointF(70.0, -20.0))
    item.setPen(QtGui.QPen(QtGui.QColor("#123456"), 3.0))
    item.setBrush(QtGui.QBrush(QtGui.QColor("#aabbcc")))

    payload = SHAPE_REGISTRY.serialize(item)
    restored = SHAPE_REGISTRY.restore(payload or {})

    assert isinstance(restored, FreePathItem)
    assert restored.path_payload() == item.path_payload()
    assert restored.pen().color() == item.pen().color()
    assert restored.brush().color() == item.brush().color()


def test_bezier_path_exposes_node_and_control_handles(
    application: QtWidgets.QApplication,
) -> None:
    item = BezierPathItem(0.0, 0.0)
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(item)
    item.setSelected(True)

    item.show_handles()

    assert [(handle.segment, handle.role) for handle in item._handles] == [
        (-1, "start"),
        (0, "end"),
        (0, "control1"),
        (0, "control2"),
    ]
    assert all(handle.isVisible() for handle in item._handles)


def test_free_polygon_closes_its_painter_path(application: QtWidgets.QApplication) -> None:
    item = FreePathItem(
        0.0,
        0.0,
        closed=True,
        start=[0.0, 0.0],
        segments=[
            {"kind": "line", "end": [100.0, 0.0]},
            {"kind": "line", "end": [50.0, 60.0]},
        ],
    )

    assert item.path().contains(QtCore.QPointF(50.0, 20.0))


def test_free_path_scene_roundtrip_and_clipboard_remap(canvas_view) -> None:
    item = canvas_view.add_shape(
        "Bezier Path", QtCore.QPointF(40.0, 60.0), snap_to_grid=False
    )
    assert isinstance(item, FreePathItem)
    item.move_handle(0, "end", QtCore.QPointF(160.0, 80.0))
    state = canvas_view._serialize_scene_state()

    restored = type(canvas_view)()
    try:
        restored._restore_scene_state(json.loads(json.dumps(state)))
        restored_item = next(
            candidate
            for candidate in restored.scene().items()
            if isinstance(candidate, FreePathItem) and candidate.parentItem() is None
        )
        assert isinstance(restored_item, FreePathItem)
        assert restored_item.path_payload() == item.path_payload()
        encoded = ClipboardService.encode(state["items"])
        pasted = ClipboardService.prepare_paste(encoded)
        assert UUID(pasted.items[0]["id"])
        assert pasted.items[0]["id"] != state["items"][0]["id"]
        assert pasted.items[0]["segments"] == state["items"][0]["segments"]
    finally:
        restored.close()


def test_free_path_addition_is_restored_by_scene_history(canvas_view) -> None:
    canvas_view._history.capture_initial_state()
    item = canvas_view.add_shape(
        "Free Polyline", QtCore.QPointF(20.0, 30.0), snap_to_grid=False
    )
    assert isinstance(item, FreePathItem)

    canvas_view._history.undo()
    assert not any(
        isinstance(candidate, FreePathItem) and candidate.parentItem() is None
        for candidate in canvas_view.scene().items()
    )

    canvas_view._history.redo()
    assert any(
        isinstance(candidate, FreePathItem) and candidate.parentItem() is None
        for candidate in canvas_view.scene().items()
    )


def test_free_path_python_export_compiles(
    application: QtWidgets.QApplication, monkeypatch, tmp_path: Path
) -> None:
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create("Bezier Path", 10.0, 20.0)
    assert isinstance(item, FreePathItem)
    scene.addItem(item)
    output = tmp_path / "free_path.py"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "Python (*.py)"),
    )

    export_drawsvg_py(scene)

    code = output.read_text(encoding="utf-8")
    compile(code, str(output), "exec")
    assert "draw.Path" in code


def test_free_path_is_registered_for_context_menu_stack_order(canvas_view) -> None:
    item = canvas_view.add_shape(
        "Free Polyline", QtCore.QPointF(20.0, 30.0), snap_to_grid=False
    )
    assert isinstance(item, FreePathItem)

    stack_items = [
        candidate
        for candidate in canvas_view.scene().items()
        if SHAPE_REGISTRY.definition_for_item(candidate) is not None
    ]

    assert item in stack_items
