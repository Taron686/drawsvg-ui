from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items import BlockArrowItem, LineItem, RectItem
from items.base import ResizeHandle, snap_to_grid
from items.shapes.paths import BezierPathItem


def _event(event_type, position, *, alt=False):
    event = QtWidgets.QGraphicsSceneMouseEvent(event_type)
    event.setScenePos(position)
    event.setModifiers(
        QtCore.Qt.KeyboardModifier.AltModifier
        if alt else QtCore.Qt.KeyboardModifier.NoModifier
    )
    return event


@pytest.mark.parametrize("grid,alignment", [(True, True), (True, False), (False, True), (False, False)])
def test_point_snap_obeys_grid_mode_independently_of_visibility(canvas_view, grid, alignment):
    canvas_view._master_origin = QtCore.QPointF(3, -7)
    item = QtWidgets.QGraphicsRectItem(0, 0, 50, 50)
    canvas_view.scene().addItem(item)
    canvas_view.set_grid_visible(False)
    canvas_view.set_guides_visible(False)
    canvas_view.set_grid_snap_enabled(grid)
    canvas_view.set_alignment_snap_enabled(alignment)

    expected = QtCore.QPointF(-7, 13) if grid else QtCore.QPointF(-9, 16)
    assert snap_to_grid(item, QtCore.QPointF(-9, 16)) == expected
    assert canvas_view.grid_snap_enabled() is grid
    assert canvas_view.alignment_snap_enabled() is alignment
    assert canvas_view._grid_size_min == 10


def test_legacy_view_keeps_point_snapping_without_new_modes(application):
    scene = QtWidgets.QGraphicsScene()
    view = QtWidgets.QGraphicsView(scene)
    item = QtWidgets.QGraphicsRectItem()
    scene.addItem(item)
    try:
        assert snap_to_grid(item, QtCore.QPointF(103, 107)) == QtCore.QPointF(100, 110)
    finally:
        view.close()


@pytest.mark.parametrize("shape", ["rectangle", "block_arrow"])
@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("grid,alt", [(False, False), (True, True), (True, False)])
def test_resize_bypasses_pointer_and_size_rounding_when_grid_is_disabled(
    canvas_view, shape, rotation, grid, alt
):
    canvas_view._master_origin = QtCore.QPointF()
    item = RectItem(0, 0, 50, 50) if shape == "rectangle" else BlockArrowItem(0, 0, 50, 50)
    if shape == "block_arrow":
        item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(item)
    item.setRotation(rotation)
    handle = ResizeHandle(item, "bottom_right")
    start = item.mapToScene(QtCore.QPointF(50, 50))
    end = item.mapToScene(QtCore.QPointF(63, 67))
    handle.mousePressEvent(_event(QtCore.QEvent.Type.GraphicsSceneMousePress, start))
    canvas_view.set_grid_snap_enabled(grid)
    handle.mouseMoveEvent(_event(QtCore.QEvent.Type.GraphicsSceneMouseMove, end, alt=alt))
    handle.mouseReleaseEvent(_event(QtCore.QEvent.Type.GraphicsSceneMouseRelease, end, alt=alt))

    if shape == "rectangle":
        assert item.rect().width() == pytest.approx(60 if grid and not alt else 63)
        assert item.rect().height() == pytest.approx(70 if grid and not alt else 67)
    else:
        # Block arrows retain their polygon and resize with uniform scale.
        assert item.scale() == pytest.approx(1.4 if grid and not alt else 1.34)
    assert canvas_view._grid_size_min == 10


def test_free_resize_preserves_minimum_size(canvas_view):
    item = RectItem(0, 0, 50, 50)
    canvas_view.scene().addItem(item)
    canvas_view.set_grid_snap_enabled(False)
    handle = ResizeHandle(item, "bottom_right")
    handle.mousePressEvent(_event(QtCore.QEvent.Type.GraphicsSceneMousePress, QtCore.QPointF(50, 50)))
    handle.mouseMoveEvent(_event(QtCore.QEvent.Type.GraphicsSceneMouseMove, QtCore.QPointF(-13, -17)))
    assert item.rect().width() == 10
    assert item.rect().height() == 10


@pytest.mark.parametrize("kind", ["line", "path_end", "path_control", "block_head", "block_body"])
@pytest.mark.parametrize("grid,alt", [(False, False), (True, True), (True, False)])
def test_point_handles_follow_mode_changes_and_alt(canvas_view, kind, grid, alt):
    canvas_view._master_origin = QtCore.QPointF()
    if kind == "line":
        item = LineItem(0, 0, 100)
    elif kind.startswith("path"):
        item = BezierPathItem(0, 0)
    else:
        item = BlockArrowItem(0, 0, 100, 100)
    canvas_view.scene().addItem(item)
    item.setSelected(True)
    item.show_handles()
    if kind == "line":
        handle = item._handles[0]
    elif kind.startswith("path"):
        role = "end" if kind == "path_end" else "control1"
        handle = next(handle for handle in item._handles if handle.role == role)
    else:
        handle = item._head_handle if kind == "block_head" else item._body_handle
    target = QtCore.QPointF(63, 67)
    handle.mousePressEvent(_event(QtCore.QEvent.Type.GraphicsSceneMousePress, handle.scenePos()))
    canvas_view.set_grid_snap_enabled(False)
    canvas_view.set_grid_snap_enabled(grid)
    handle.mouseMoveEvent(_event(QtCore.QEvent.Type.GraphicsSceneMouseMove, target, alt=alt))
    handle.mouseReleaseEvent(_event(QtCore.QEvent.Type.GraphicsSceneMouseRelease, target, alt=alt))

    snapped = grid and not alt
    if kind == "block_head":
        assert item.head_ratio() == pytest.approx(0.4 if snapped else 0.37)
    elif kind == "block_body":
        assert item.shaft_ratio() == pytest.approx(0.4 if snapped else 0.34)
    else:
        point = item.mapToScene(handle.pos())
        assert point.x() == pytest.approx(60 if snapped else 63)
        assert point.y() == pytest.approx(70 if snapped else 67)


def test_mode_changes_leave_document_geometry_and_history_untouched(canvas_view):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(103, 107), snap_to_grid=False)
    before = canvas_view._serialize_scene_state()
    canvas_view.history().capture_initial_state()
    assert canvas_view.grid_snap_enabled()
    assert canvas_view.alignment_snap_enabled()
    for enabled in (False, True):
        canvas_view.set_grid_snap_enabled(enabled)
        canvas_view.set_alignment_snap_enabled(enabled)
    assert canvas_view._serialize_scene_state() == before
    assert item.pos() == QtCore.QPointF(103, 107)
    assert not canvas_view.history().can_undo()
