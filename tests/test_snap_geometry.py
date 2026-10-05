from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items import GroupItem, LineItem, RectItem, TextItem
from items.shapes.paths import FreePathItem


def _bounds(item, view):
    from snap_geometry import item_snap_bounds
    return item_snap_bounds(item, view)


@pytest.mark.parametrize("kind", ["line", "path"])
@pytest.mark.parametrize("width,bottom", [(2, 171), (8, 174)])
def test_line_bounds_use_paint_not_click_padding(canvas_view, kind, width, bottom):
    if kind == "line":
        item = LineItem(0, 0, points=[
            QtCore.QPointF(65, -250), QtCore.QPointF(65, 170), QtCore.QPointF(350, 170)])
    else:
        item = FreePathItem(0, 0, start=(65, -250), segments=[
            {"kind": "line", "end": (65, 170)}, {"kind": "line", "end": (350, 170)}])
    item.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, width))
    canvas_view.scene().addItem(item)
    bounds = _bounds(item, canvas_view)
    assert bounds is not None
    assert bounds.bottom() == pytest.approx(bottom)
    # Easier clicking is independent of the narrower snap envelope.
    assert item.shape().contains(QtCore.QPointF(200, bottom + 1))


@pytest.mark.parametrize("cosmetic", [False, True])
@pytest.mark.parametrize("width,zoom,scale,half", [
    (0, 1, 1, .5), (0, 4, 2, .125),
    (2, 1, 2, 2), (2, 4, 2, 2),
])
def test_cosmetic_width_is_measured_in_view_pixels(
    canvas_view, cosmetic, width, zoom, scale, half
):
    item = LineItem(0, 0, length=100)
    pen = QtGui.QPen(QtCore.Qt.GlobalColor.black, width)
    pen.setCosmetic(cosmetic)
    item.setPen(pen)
    item.setScale(scale)
    canvas_view.setTransform(QtGui.QTransform.fromScale(zoom, zoom))
    canvas_view.scene().addItem(item)
    bounds = _bounds(item, canvas_view)
    dpr = canvas_view.viewport().devicePixelRatioF()
    expected = (width or 1) / (2 * zoom * dpr) if pen.isCosmetic() else half
    assert bounds is not None
    assert bounds.height() == pytest.approx(2 * expected)


@pytest.mark.parametrize("rotation,scale,want", [
    (0, 1, (-1, -1, 102, 2)),
    (90, 1, (49, -51, 2, 102)),
    (0, 2, (-52, -2, 204, 4)),
])
def test_line_transform_applies_to_actual_stroke(canvas_view, rotation, scale, want):
    item = LineItem(0, 0, length=100)
    item.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 2))
    item.setRotation(rotation)
    item.setScale(scale)
    canvas_view.scene().addItem(item)
    bounds = _bounds(item, canvas_view)
    assert bounds is not None
    assert (bounds.x(), bounds.y(), bounds.width(), bounds.height()) == pytest.approx(want)


def test_no_pen_open_path_has_no_snap_geometry(canvas_view):
    item = FreePathItem(0, 0, width=100, height=50)
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(item)
    assert _bounds(item, canvas_view) is None


def test_filled_path_keeps_fill_and_stroke_envelope(canvas_view):
    item = FreePathItem(0, 0, closed=True, start=(0, 0), segments=[
        {"kind": "line", "end": (100, 0)},
        {"kind": "line", "end": (100, 50)},
        {"kind": "line", "end": (0, 50)}])
    pen = QtGui.QPen(QtCore.Qt.GlobalColor.black, 8)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    item.setPen(pen)
    item.setBrush(QtGui.QColor("red"))
    canvas_view.scene().addItem(item)
    bounds = _bounds(item, canvas_view)
    assert bounds is not None
    assert (bounds.left(), bounds.top(), bounds.right(), bounds.bottom()) == pytest.approx((-4, -4, 104, 54))


def test_text_keeps_editable_box_bounds(canvas_view):
    item = TextItem(90, 90, 124, 83, auto_size=False)
    canvas_view.scene().addItem(item)
    assert _bounds(item, canvas_view) == QtCore.QRectF(90, 90, 124, 83)


def test_group_bounds_ignore_old_handles_and_refresh_children(canvas_view):
    group = GroupItem()
    canvas_view.scene().addItem(group)
    child = RectItem(100, 100, 40, 40)
    child.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(child)
    child.setSelected(True)
    group.addToGroup(child)
    child.setSelected(False)
    group.setSelected(True)
    group.update_handles()
    assert _bounds(group, canvas_view) == QtCore.QRectF(100, 100, 40, 40)
    # A child's new geometry cannot depend on Qt's cached group bounds.
    child.setRect(0, 0, 80, 20)
    assert _bounds(group, canvas_view) == QtCore.QRectF(100, 100, 80, 20)
    child.hide()
    assert _bounds(group, canvas_view) is None


def test_scene_roots_do_not_include_children(canvas_view):
    from snap_geometry import scene_root_items
    group = GroupItem()
    canvas_view.scene().addItem(group)
    child = RectItem(100, 100, 40, 40)
    canvas_view.scene().addItem(child)
    group.addToGroup(child)
    roots = scene_root_items(canvas_view.scene().items())
    assert group in roots
    assert child not in roots


@pytest.mark.parametrize("cap,left,right", [
    (QtCore.Qt.PenCapStyle.FlatCap, 0, 100),
    (QtCore.Qt.PenCapStyle.SquareCap, -4, 104),
    (QtCore.Qt.PenCapStyle.RoundCap, -4, 104),
])
def test_caps_and_dashes_use_stable_stroke_envelope(canvas_view, cap, left, right):
    item = LineItem(0, 0, length=100)
    pen = QtGui.QPen(QtCore.Qt.GlobalColor.black, 8)
    pen.setCapStyle(cap)
    pen.setStyle(QtCore.Qt.PenStyle.DashLine)
    item.setPen(pen)
    canvas_view.scene().addItem(item)
    bounds = _bounds(item, canvas_view)
    assert bounds is not None
    assert (bounds.left(), bounds.right(), bounds.top(), bounds.bottom()) == pytest.approx((left, right, -4, 4))


@pytest.mark.parametrize("start,end", [(True, False), (False, True), (True, True)])
def test_arrow_snap_bounds_contain_painted_pixels(canvas_view, start, end):
    item = LineItem(0, 0, length=100, arrow_start=start, arrow_end=end,
                    arrow_head_length=20, arrow_head_width=30)
    item.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 2))
    canvas_view.scene().addItem(item)
    bounds = _bounds(item, canvas_view)
    assert bounds is not None
    image = QtGui.QImage(180, 80, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.translate(40, 40)
    item.paint(painter, QtWidgets.QStyleOptionGraphicsItem())
    painter.end()
    pixels = [(x - 40, y - 40) for y in range(80) for x in range(180)
              if image.pixelColor(x, y).alpha() > 128]
    assert pixels
    painted = QtCore.QRectF(min(x for x, _ in pixels), min(y for _, y in pixels),
                           max(x for x, _ in pixels) - min(x for x, _ in pixels) + 1,
                           max(y for _, y in pixels) - min(y for _, y in pixels) + 1)
    assert bounds.adjusted(-1, -1, 1, 1).contains(painted)
    assert abs(bounds.left() - painted.left()) <= 2
    assert abs(bounds.right() - painted.right()) <= 2
    assert abs(bounds.top() - painted.top()) <= 2
    assert abs(bounds.bottom() - painted.bottom()) <= 2


@pytest.mark.parametrize("width", [2, 8, 18])
@pytest.mark.parametrize("vertical", [False, True])
@pytest.mark.parametrize("cosmetic,zoom", [(False, .25), (True, 4)])
@pytest.mark.parametrize("cap", [QtCore.Qt.PenCapStyle.FlatCap,
                                QtCore.Qt.PenCapStyle.RoundCap,
                                QtCore.Qt.PenCapStyle.SquareCap])
def test_grid_anchor_ignores_stroke_and_view(canvas_view, width, vertical, cosmetic, zoom, cap):
    from snap_geometry import item_grid_anchor
    end = QtCore.QPointF(0, 100) if vertical else QtCore.QPointF(100, 0)
    item = LineItem(100, 100, points=[end, QtCore.QPointF()])
    pen = QtGui.QPen(QtCore.Qt.GlobalColor.black, width)
    pen.setCosmetic(cosmetic)
    pen.setCapStyle(cap)
    item.setPen(pen)
    canvas_view.setTransform(QtGui.QTransform.fromScale(zoom, zoom))
    canvas_view.scene().addItem(item)
    assert item_grid_anchor(item) == QtCore.QPointF(100, 100)


def test_rotated_text_grid_anchor_is_local_field_corner(canvas_view):
    from snap_geometry import item_grid_anchor
    item = TextItem(90, 90, 124, 83, auto_size=False)
    canvas_view.scene().addItem(item)
    item.setRotation(35)
    anchor = item.mapToScene(QtCore.QPointF())
    item.setPlainText("Changed glyphs\nand content")
    font = item.font()
    font.setPointSize(22)
    item.setFont(font)
    assert item_grid_anchor(item) == anchor


def test_group_grid_anchor_uses_current_geometry_without_handles(canvas_view):
    from snap_geometry import item_grid_anchor
    group = GroupItem()
    canvas_view.scene().addItem(group)
    child = LineItem(100, 100, length=100)
    child.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 18))
    canvas_view.scene().addItem(child)
    group.addToGroup(child)
    group.setSelected(True)
    group.update_handles()
    assert item_grid_anchor(group) == QtCore.QPointF(100, 100)
    child.hide()
    assert item_grid_anchor(group) is None


def test_group_grid_frame_includes_zero_height_child_paths(canvas_view):
    from snap_geometry import item_grid_anchor
    group = GroupItem()
    canvas_view.scene().addItem(group)
    for x, y in [(100, 100), (50, 200)]:
        line = LineItem(x, y, length=100)
        canvas_view.scene().addItem(line)
        group.addToGroup(line)
    assert item_grid_anchor(group) == QtCore.QPointF(50, 100)


@pytest.mark.parametrize("start,end,want", [(True, False, (107, 104)),
    (False, True, (53, 83)), (True, True, (53, 83))])
@pytest.mark.parametrize("width", [2, 18])
def test_arrow_grid_anchor_preserves_nearest_tip_reference(canvas_view, start, end, want, width):
    from snap_geometry import item_grid_anchor
    canvas_view._master_origin = QtCore.QPointF(3, -7)
    canvas_view._grid_size_min = 10
    item = LineItem(0, 0, points=[QtCore.QPointF(107, 104), QtCore.QPointF(53, 83)],
                    arrow_start=start, arrow_end=end)
    item.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, width))
    canvas_view.scene().addItem(item)
    assert item_grid_anchor(item) == QtCore.QPointF(*want)


def test_two_arrow_tips_break_equal_grid_distance_ties_by_start(canvas_view):
    from snap_geometry import item_grid_anchor
    canvas_view._master_origin = QtCore.QPointF(3, -7)
    canvas_view._grid_size_min = 10
    item = LineItem(0, 0, points=[QtCore.QPointF(104, 94), QtCore.QPointF(54, 84)],
                    arrow_start=True, arrow_end=True)
    canvas_view.scene().addItem(item)
    assert item_grid_anchor(item) == QtCore.QPointF(104, 94)
