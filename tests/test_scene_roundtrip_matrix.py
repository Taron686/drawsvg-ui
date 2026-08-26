from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from canvas_view import CanvasView, GroupItem
from constants import SHAPES
from items import (
    BlockArrowItem,
    CurvyBracketItem,
    FolderTreeItem,
    LineItem,
    ShapeLabelMixin,
    SplitRoundedRectItem,
    TextItem,
)
from scene_codec import KEY_ITEM_ID, KEY_TRANSIENT

POLYGON_GEOMETRY_XFAIL = pytest.mark.xfail(
    strict=True,
    reason="Legacy snapshots serialize the pen-inflated polygon boundingRect as size.",
)
ROUNDTRIP_SHAPES = tuple(
    pytest.param(
        shape,
        marks=POLYGON_GEOMETRY_XFAIL
        if shape in {"Triangle", "Diamond", "Block Arrow"}
        else (),
        id=shape,
    )
    for shape in SHAPES
)


def _styled_pen() -> QtGui.QPen:
    color = QtGui.QColor("#315b9d")
    color.setAlphaF(0.72)
    pen = QtGui.QPen(color, 3.25)
    pen.setStyle(QtCore.Qt.PenStyle.CustomDashLine)
    pen.setDashPattern([1.5, 2.0, 4.0, 2.0])
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.BevelJoin)
    pen.setCosmetic(True)
    return pen


def _styled_brush(color_name: str) -> QtGui.QBrush:
    color = QtGui.QColor(color_name)
    color.setAlphaF(0.47)
    return QtGui.QBrush(color, QtCore.Qt.BrushStyle.Dense3Pattern)


def _custom_font() -> QtGui.QFont:
    font = QtGui.QFont("Arial")
    font.setPointSizeF(16.5)
    font.setWeight(QtGui.QFont.Weight.DemiBold)
    font.setItalic(True)
    return font


def _configure_common(item: QtWidgets.QGraphicsItem, index: int) -> None:
    item.setPos(31.25 + index * 7.5, -48.5 + index * 5.25)
    item.setRotation(13.75 + index)
    item.setScale(0.65 + index * 0.025)
    item.setZValue(2.5 + index * 0.5)

    set_pen = getattr(item, "setPen", None)
    if callable(set_pen):
        set_pen(_styled_pen())

    set_brush = getattr(item, "setBrush", None)
    if callable(set_brush) and not isinstance(item, (LineItem, CurvyBracketItem)):
        set_brush(_styled_brush("#d27b45"))


def _configure_shape(item: QtWidgets.QGraphicsItem, shape: str, index: int) -> None:
    _configure_common(item, index)

    if isinstance(item, ShapeLabelMixin) and shape not in {"Ellipse", "Circle"}:
        item.set_label_text(f"Label for {shape}")
        item.set_label_alignment(horizontal="right", vertical="bottom")
        item.label_item().setFont(_custom_font())
        item.set_label_color(QtGui.QColor("#722f8f"))

    if isinstance(item, SplitRoundedRectItem):
        item.set_divider_ratio(0.37)
        item.setTopBrush(_styled_brush("#467a9c"))
        item.setBottomBrush(_styled_brush("#b06088"))
    elif isinstance(item, BlockArrowItem):
        item.set_head_ratio(0.43)
        item.set_shaft_ratio(0.58)
    elif isinstance(item, LineItem):
        item.set_arrow_start(shape == "Arrow")
        item.set_arrow_end(True)
        item.set_arrow_head_length(19.5)
        item.set_arrow_head_width(12.25)
    elif isinstance(item, CurvyBracketItem):
        item.set_hook_ratio(0.41)
    elif isinstance(item, TextItem):
        item.setPlainText("Roundtrip text\nwith explicit line break")
        item.setFont(_custom_font())
        item.setDefaultTextColor(QtGui.QColor("#274d37"))
        item.set_document_margin(7.25)
        item.set_text_alignment(horizontal="center", vertical="bottom")
        item.set_text_direction("rtl")
    elif isinstance(item, FolderTreeItem):
        item.set_structure(
            {
                "name": "root",
                "type": "folder",
                "children": [
                    {"name": "src", "type": "folder", "children": []},
                    {"name": "README.md", "type": "file"},
                ],
            }
        )


def _json_copy(payload: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, sort_keys=True))


def _roundtrip_state(source: CanvasView) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = _json_copy(source._serialize_scene_state())
    restored = CanvasView()
    try:
        restored._restore_scene_state(expected)
        actual = _json_copy(restored._serialize_scene_state())
    finally:
        restored.close()
    return expected, actual


@pytest.mark.parametrize("shape", ROUNDTRIP_SHAPES)
def test_each_existing_shape_has_a_reproducible_roundtrip(
    canvas_view: CanvasView,
    shape: str,
) -> None:
    item = canvas_view.add_shape(
        shape,
        QtCore.QPointF(10.0, 20.0),
        snap_to_grid=False,
    )
    assert item is not None
    _configure_shape(item, shape, SHAPES.index(shape))

    expected, actual = _roundtrip_state(canvas_view)

    assert actual == expected


def test_all_existing_shape_types_survive_one_roundtrip(
    canvas_view: CanvasView,
) -> None:
    for index, shape in enumerate(SHAPES):
        item = canvas_view.add_shape(
            shape,
            QtCore.QPointF(index * 250.0, index * 175.0),
            snap_to_grid=False,
        )
        assert item is not None

    _expected, actual = _roundtrip_state(canvas_view)

    assert {entry["shape"] for entry in actual["items"]} == set(SHAPES)


@pytest.mark.parametrize("shape", ["Ellipse", "Circle"])
@pytest.mark.xfail(
    strict=True,
    reason="Legacy restore does not apply serialized labels to ellipse-based items.",
)
def test_ellipse_labels_roundtrip(
    canvas_view: CanvasView,
    shape: str,
) -> None:
    item = canvas_view.add_shape(shape, QtCore.QPointF(), snap_to_grid=False)
    assert isinstance(item, ShapeLabelMixin)
    item.set_label_text(f"Custom {shape} label")
    item.set_label_alignment(horizontal="right", vertical="top")
    item.label_item().setFont(_custom_font())
    item.set_label_color(QtGui.QColor("#722f8f"))

    expected, actual = _roundtrip_state(canvas_view)

    assert actual == expected


@pytest.mark.xfail(
    strict=True,
    reason="Legacy nested-group restore changes saved local positions.",
)
def test_nested_groups_roundtrip(canvas_view: CanvasView) -> None:
    state = {
        "grid_visible": False,
        "items": [
            {
                "shape": "Group",
                "class": "GroupItem",
                "pos": [25.0, 35.0],
                "rotation": 17.5,
                "scale": 0.8,
                "z": 6.0,
                "children": [
                    {
                        "shape": "Group",
                        "class": "GroupItem",
                        "pos": [11.0, 13.0],
                        "rotation": -8.0,
                        "scale": 1.15,
                        "z": 1.0,
                        "children": [],
                    }
                ],
            }
        ],
    }

    canvas_view._restore_scene_state(state)

    assert _json_copy(canvas_view._serialize_scene_state()) == state
    top_group = next(
        item
        for item in canvas_view.scene().items()
        if isinstance(item, GroupItem) and item.parentItem() is None
    )
    assert any(isinstance(child, GroupItem) for child in top_group.childItems())


def test_legacy_handle_objects_are_transient(canvas_view: CanvasView) -> None:
    item = canvas_view.add_shape(
        "Rectangle",
        QtCore.QPointF(),
        snap_to_grid=False,
    )
    assert item is not None
    item.show_handles()

    state = canvas_view._serialize_scene_state()

    assert [entry["shape"] for entry in state["items"]] == ["Rectangle"]
    assert all(not entry["class"].endswith("Handle") for entry in state["items"])


def test_explicit_transient_marker_excludes_item(canvas_view: CanvasView) -> None:
    preview = QtWidgets.QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
    preview.setData(0, "Preview")
    preview.setData(KEY_TRANSIENT, True)
    canvas_view.scene().addItem(preview)

    assert canvas_view._serialize_scene_state()["items"] == []


def test_roundtrip_payload_has_explicit_stack_order(canvas_view: CanvasView) -> None:
    for shape in ("Rectangle", "Ellipse"):
        item = canvas_view.add_shape(shape, QtCore.QPointF(), snap_to_grid=False)
        assert item is not None
        item.setZValue(4.0)

    state = canvas_view._serialize_scene_state()

    assert [entry["stack_order"] for entry in state["items"]] == [0, 1]


def test_equal_z_values_preserve_insertion_order(canvas_view: CanvasView) -> None:
    insertion_order = ("Rectangle", "Ellipse", "Text")
    for shape in insertion_order:
        item = canvas_view.add_shape(shape, QtCore.QPointF(), snap_to_grid=False)
        assert item is not None
        item.setZValue(9.0)

    expected, actual = _roundtrip_state(canvas_view)
    expected["items"] = sorted(
        expected["items"],
        key=lambda entry: insertion_order.index(str(entry["shape"])),
    )

    assert [entry["shape"] for entry in actual["items"]] == list(insertion_order)


def test_scene_codec_payload_has_stable_metadata(canvas_view: CanvasView) -> None:
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(), snap_to_grid=False)
    assert item is not None

    state = canvas_view._serialize_scene_state()
    entry = state["items"][0]

    assert state["schema_version"] == 1
    assert entry["type_id"] == "Rectangle"
    assert entry["layer_id"] == "layer-1"
    assert isinstance(entry["id"], str)
    assert str(UUID(entry["id"])) == entry["id"]
    assert item.data(KEY_ITEM_ID) == entry["id"]

    canvas_view._restore_scene_state(state)

    restored = canvas_view._serialize_scene_state()["items"][0]
    assert restored["id"] == entry["id"]
