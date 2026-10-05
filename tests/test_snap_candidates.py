from __future__ import annotations

import gc

import pytest
import shiboken6
from PySide6 import QtCore, QtGui

from items import GroupItem, LineItem, RectItem, TextItem
from items.shapes.paths import FreePathItem
from scene_codec import KEY_TRANSIENT


def _setup(view):
    view._master_origin = QtCore.QPointF()
    view.setTransform(QtGui.QTransform())


def _text(view):
    item = TextItem(90, 90, 124, 83, auto_size=False)
    view.scene().addItem(item)
    item.setSelected(True)
    return item


@pytest.mark.parametrize("kind", ["line", "path"])
def test_text_snaps_to_visible_stroke_edge(canvas_view, kind):
    _setup(canvas_view)
    canvas_view._grid_snap_enabled = False
    if kind == "line":
        target = LineItem(0, 0, points=[
            QtCore.QPointF(65, -250), QtCore.QPointF(65, 170), QtCore.QPointF(350, 170)])
    else:
        target = FreePathItem(0, 0, start=(65, -250), segments=[
            {"kind": "line", "end": (65, 170)}, {"kind": "line", "end": (350, 170)}])
    target.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 8))
    canvas_view.scene().addItem(target)
    text = _text(canvas_view)
    canvas_view._snap_selected_items()
    assert text.sceneBoundingRect().bottom() == pytest.approx(174)
    assert canvas_view._active_snap_guides["horizontal"] == pytest.approx(174)


@pytest.mark.parametrize("kind", ["hidden", "zero_opacity", "transient", "hidden_layer"])
def test_invisible_targets_do_not_override_grid(canvas_view, kind):
    _setup(canvas_view)
    target = RectItem(0, 0, 250, 170)
    target.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(target)
    if kind == "hidden":
        target.hide()
    elif kind == "zero_opacity":
        target.setOpacity(0)
    elif kind == "transient":
        target.setData(KEY_TRANSIENT, True)
    else:
        manager = canvas_view.layer_manager()
        target.setData(0, "Rectangle")
        manager.register_item(target)
        layer = manager.add_layer("Hidden")
        assert manager.assign_item(target, layer.id)
        assert manager.set_layer_visible(layer.id, False)
    text = _text(canvas_view)
    canvas_view._snap_selected_items()
    assert text.pos() == QtCore.QPointF(90, 90)
    assert canvas_view._active_snap_guides == {}


def test_visible_locked_target_can_still_align_text(canvas_view):
    _setup(canvas_view)
    canvas_view._grid_snap_enabled = False
    target = RectItem(0, 0, 250, 170)
    target.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(target)
    canvas_view.layer_manager().set_item_locked(target, True)
    text = _text(canvas_view)
    canvas_view._snap_selected_items()
    assert text.sceneBoundingRect().bottom() == pytest.approx(170)
    assert canvas_view._active_snap_guides["horizontal"] == pytest.approx(170)


def _handled_group(view):
    group = GroupItem()
    view.scene().addItem(group)
    child = RectItem(100, 100, 40, 40)
    child.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    view.scene().addItem(child)
    child.setSelected(True)
    group.addToGroup(child)
    child.setSelected(False)
    group.setSelected(True)
    group.update_handles()
    group.setSelected(False)
    return group, child


def test_old_group_handles_are_not_independent_snap_edges(canvas_view):
    _setup(canvas_view)
    group, child = _handled_group(canvas_view)
    point, guides = canvas_view.snap_scene_position(QtCore.QPointF(300, 154))
    assert point.y() == pytest.approx(150)
    assert "horizontal" not in guides


def test_group_source_snaps_by_content_not_handles(canvas_view):
    _setup(canvas_view)
    group, child = _handled_group(canvas_view)
    group.setSelected(True)
    canvas_view._snap_selected_items()
    assert child.sceneBoundingRect() == QtCore.QRectF(100, 100, 40, 40)


def test_line_source_uses_same_visible_envelope_as_targets(canvas_view):
    from snap_geometry import item_grid_anchor
    _setup(canvas_view)
    item = LineItem(0, 0, points=[
        QtCore.QPointF(65, -250), QtCore.QPointF(65, 170), QtCore.QPointF(350, 170)])
    item.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 2))
    canvas_view.scene().addItem(item)
    item.setSelected(True)
    canvas_view._snap_selected_items()
    assert item_grid_anchor(item) == QtCore.QPointF(60, -250)


@pytest.mark.parametrize("child_state", ["hidden", "zero_opacity", "transient"])
def test_group_children_do_not_supply_invisible_bounds(canvas_view, child_state):
    _setup(canvas_view)
    group, child = _handled_group(canvas_view)
    if child_state == "hidden":
        child.hide()
    elif child_state == "zero_opacity":
        child.setOpacity(0)
    else:
        child.setData(KEY_TRANSIENT, True)
    point, guides = canvas_view.snap_scene_position(QtCore.QPointF(300, 100))
    assert point == QtCore.QPointF(300, 100)
    assert guides == {}


def test_snap_preserves_cpp_items_after_gc(canvas_view):
    _setup(canvas_view)
    canvas_view._grid_snap_enabled = False
    def add_target():
        item = RectItem(0, 0, 250, 170)
        item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        canvas_view.scene().addItem(item)
    add_target()
    text = _text(canvas_view)
    def identities():
        return sorted(shiboken6.getCppPointer(item)[0] for item in canvas_view.scene().items())
    before = identities()
    canvas_view._snap_selected_items()
    gc.collect()
    assert identities() == before
    assert text.sceneBoundingRect().bottom() == pytest.approx(170)
