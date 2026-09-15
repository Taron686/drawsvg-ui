from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from clipboard_service import ClipboardService
import export_drawsvg
import import_drawsvg
from canvas_view import CanvasView
from items import DiagramItem, ShapeLabelMixin
from shape_registry import SHAPE_REGISTRY


DIAGRAM_TYPES = (
    "Hexagon",
    "Parallelogram",
    "Database",
    "Document",
    "Multiple Document",
    "Cloud",
    "Callout",
    "Table",
    "Swimlane",
)


def _json_state(view: CanvasView) -> dict[str, object]:
    return json.loads(json.dumps(view._serialize_scene_state(), sort_keys=True))


@pytest.mark.parametrize("type_id", DIAGRAM_TYPES)
def test_diagram_shape_project_roundtrip_preserves_labels_and_parameters(
    canvas_view: CanvasView, type_id: str
) -> None:
    item = canvas_view.add_shape(
        type_id, QtCore.QPointF(10.0, 20.0), snap_to_grid=False
    )

    assert isinstance(item, DiagramItem)
    assert isinstance(item, ShapeLabelMixin)
    item.set_size(140.0, 90.0)
    item.set_label_text(f"{type_id} label")
    if type_id == "Table":
        item.set_table_dimensions(4, 5)
    elif type_id == "Swimlane":
        item.set_swimlane_count(4)

    expected = _json_state(canvas_view)
    restored = CanvasView()
    try:
        restored._restore_scene_state(expected)
        assert _json_state(restored) == expected
    finally:
        restored.close()


def test_diagram_shapes_are_palette_extensions_with_independent_parameters() -> None:
    extension_ids = {
        definition.type_id for definition in SHAPE_REGISTRY.extension_definitions()
    }

    assert set(DIAGRAM_TYPES) <= extension_ids
    table = SHAPE_REGISTRY.create("Table", 0.0, 0.0)
    swimlane = SHAPE_REGISTRY.create("Swimlane", 0.0, 0.0)

    assert isinstance(table, DiagramItem)
    assert isinstance(swimlane, DiagramItem)
    table.set_table_dimensions(2, 6)
    swimlane.set_swimlane_count(5)
    assert table.parameters() == {"rows": 2, "columns": 6}
    assert swimlane.parameters() == {"lanes": 5}


def test_database_shape_draws_a_lower_ellipse_edge(canvas_view: CanvasView) -> None:
    item = canvas_view.add_shape(
        "Database", QtCore.QPointF(), snap_to_grid=False
    )

    assert isinstance(item, DiagramItem)
    item.set_size(140.0, 90.0)

    assert item.shape().contains(QtCore.QPointF(70.0, 90.0))


def test_rotated_diagram_resize_defers_transform_origin_adjustment(application) -> None:
    item = DiagramItem(25.0, 40.0, 160.0, 100.0, "hexagon")
    item.setRotation(35.0)
    before_origin = QtCore.QPointF(item.transformOriginPoint())
    before_left_anchor = item.mapToScene(QtCore.QPointF(0.0, 50.0))

    assert before_origin == QtCore.QPointF(80.0, 50.0)

    item.set_size(200.0, 100.0, adjust_origin=False)

    assert item.transformOriginPoint() == before_origin
    assert item.mapToScene(QtCore.QPointF(0.0, 50.0)) == before_left_anchor


def test_diagram_shapes_roundtrip_through_drawsvg_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = CanvasView()
    for index, type_id in enumerate(DIAGRAM_TYPES):
        item = source.add_shape(
            type_id, QtCore.QPointF(index * 320.0, 20.0), snap_to_grid=False
        )
        assert isinstance(item, DiagramItem)
        item.set_size(120.0 + index * 11.0, 70.0 + index * 7.0)
        item.set_label_text(type_id)
        if type_id == "Table":
            item.set_table_dimensions(4, 2)
        elif type_id == "Swimlane":
            item.set_swimlane_count(4)

    export_path = tmp_path / "diagram_shapes.py"
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
    drawing = runpy.run_path(str(export_path))["build_drawing"]()
    assert drawing.as_svg()

    restored = CanvasView()
    try:
        import_drawsvg.import_drawsvg_py(restored.scene())
        restored_items = {
            str(item.data(0)): item
            for item in restored.scene().items()
            if isinstance(item, DiagramItem)
        }
        assert set(restored_items) == set(DIAGRAM_TYPES)
        assert restored_items["Table"].parameters() == {"rows": 4, "columns": 2}
        assert restored_items["Swimlane"].parameters() == {"lanes": 4}
        assert restored_items["Cloud"].label_item().toPlainText() == "Cloud"
        for index, type_id in enumerate(DIAGRAM_TYPES):
            restored_item = restored_items[type_id]
            assert restored_item._w == pytest.approx(120.0 + index * 11.0)
            assert restored_item._h == pytest.approx(70.0 + index * 7.0)
    finally:
        restored.close()
        source.close()


@pytest.mark.parametrize("type_id", DIAGRAM_TYPES)
def test_diagram_shape_size_survives_clipboard_and_undo(
    canvas_view: CanvasView, type_id: str
) -> None:
    item = canvas_view.add_shape(
        type_id, QtCore.QPointF(10.0, 20.0), snap_to_grid=False
    )
    assert isinstance(item, DiagramItem)
    item.set_size(173.0, 91.0)
    canvas_view.history().capture_now()

    canvas_view.undo()
    canvas_view.redo()
    restored = next(
        scene_item
        for scene_item in canvas_view.scene().items()
        if isinstance(scene_item, DiagramItem)
    )
    assert restored._w == pytest.approx(173.0)
    assert restored._h == pytest.approx(91.0)

    encoded = ClipboardService.encode(_json_state(canvas_view)["items"])
    pasted = ClipboardService.prepare_paste(encoded)
    assert pasted.items[0]["size"] == [173.0, 91.0]
