from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from canvas_view import KEY_OWNER_PAGE
from constants import PALETTE_MIME
from items import GroupItem, LineItem, RectItem, TextItem
from items.shapes.paths import FreePathItem
from scene_codec import KEY_ITEM_ID
from snap_geometry import item_snap_bounds


def _show(view, app):
    view.resize(800, 600)
    view.show()
    app.processEvents()
    view.setTransform(QtGui.QTransform())
    view._master_origin = QtCore.QPointF()


def _target(view, kind):
    if kind == "group":
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
        return group
    if kind == "line":
        target = LineItem(0, 0, points=[
            QtCore.QPointF(65, -250), QtCore.QPointF(65, 170), QtCore.QPointF(350, 170)])
        target.setData(0, "Line")
    else:
        target = FreePathItem(0, 0, start=(65, -250), segments=[
            {"kind": "line", "end": (65, 170)}, {"kind": "line", "end": (350, 170)}])
    target.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 8))
    view.scene().addItem(target)
    return target


def _text(view, y=90, height=83):
    text = TextItem(90, y, 124, height, auto_size=False)
    text.setData(0, "Text")
    view.scene().addItem(text)
    text.setSelected(True)
    return text


def _drag(view, text, app, modifiers=QtCore.Qt.KeyboardModifier.NoModifier):
    view.centerOn(text.sceneBoundingRect().center())
    app.processEvents()
    start = view.mapFromScene(text.sceneBoundingRect().center())
    QTest.mousePress(view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, start)
    end = start + QtCore.QPoint(0, 2)
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove, QtCore.QPointF(end),
        QtCore.QPointF(view.viewport().mapToGlobal(end)),
        QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton, modifiers)
    QtWidgets.QApplication.sendEvent(view.viewport(), event)
    active = dict(view._active_snap_guides)
    QTest.mouseRelease(view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, end)
    return active


@pytest.mark.parametrize("kind,bottom", [("line", 174), ("path", 174), ("group", 140)])
def test_real_drag_aligns_text_to_body_geometry(canvas_view, application, kind, bottom):
    _show(canvas_view, application)
    canvas_view._grid_snap_enabled = False
    target = _target(canvas_view, kind)
    text = _text(canvas_view, 77, 60) if kind == "group" else _text(canvas_view)
    active = _drag(canvas_view, text, application)
    assert text.sceneBoundingRect().bottom() == pytest.approx(bottom)
    assert active["horizontal"] == pytest.approx(bottom)
    assert canvas_view._active_snap_guides == {}


def test_alt_drag_bypasses_object_manual_guides_and_grid(canvas_view, application):
    _show(canvas_view, application)
    target = _target(canvas_view, "line")
    canvas_view.add_guide("horizontal", 172)
    text = _text(canvas_view)
    active = _drag(canvas_view, text, application, QtCore.Qt.KeyboardModifier.AltModifier)
    assert text.pos() == QtCore.QPointF(90, 92)
    assert active == {}


@pytest.mark.parametrize("visible", [False, True])
def test_guide_visibility_does_not_change_snap_priority(canvas_view, application, visible):
    _show(canvas_view, application)
    canvas_view._grid_snap_enabled = False
    target = _target(canvas_view, "line")
    canvas_view.add_guide("horizontal", 172)
    canvas_view.set_guides_visible(visible)
    text = _text(canvas_view)
    active = _drag(canvas_view, text, application)
    assert text.sceneBoundingRect().bottom() == pytest.approx(172)
    assert active["horizontal"] == pytest.approx(172)


@pytest.mark.parametrize("zoom", [.25, 1, 4])
def test_object_snap_radius_is_six_view_pixels(canvas_view, zoom):
    canvas_view._grid_snap_enabled = False
    canvas_view._master_origin = QtCore.QPointF()
    target = RectItem(0, 170, 1000, 400)
    target.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(target)
    canvas_view.setTransform(QtGui.QTransform.fromScale(zoom, zoom))
    inside, active = canvas_view.snap_scene_position(QtCore.QPointF(300, 170 + 6 / zoom))
    outside, inactive = canvas_view.snap_scene_position(QtCore.QPointF(300, 170 + 7 / zoom))
    assert inside.y() == pytest.approx(170)
    assert active["horizontal"] == pytest.approx(170)
    assert "horizontal" not in inactive


@pytest.mark.parametrize("hidden", [False, True])
@pytest.mark.parametrize("free", [False, True])
def test_palette_drop_uses_correct_targets_and_alt(canvas_view, application, hidden, free):
    _show(canvas_view, application)
    target = _target(canvas_view, "line")
    target.setVisible(not hidden)
    canvas_view.centerOn(300, 173)
    point = canvas_view.mapFromScene(QtCore.QPointF(300, 173))
    mime = QtCore.QMimeData()
    mime.setData(PALETTE_MIME, b"Rectangle")
    modifiers = (QtCore.Qt.KeyboardModifier.AltModifier if free
                 else QtCore.Qt.KeyboardModifier.NoModifier)
    event = QtGui.QDropEvent(
        QtCore.QPointF(point), QtCore.Qt.DropAction.CopyAction, mime,
        QtCore.Qt.MouseButton.LeftButton, modifiers)
    canvas_view.dropEvent(event)
    created = [item for item in canvas_view.scene().items() if isinstance(item, RectItem)]
    assert len(created) == 1
    assert event.isAccepted()
    assert created[0].y() == pytest.approx(173 if free else 150)


def test_real_snap_drag_can_undo_and_redo(canvas_view, application):
    _show(canvas_view, application)
    canvas_view._grid_snap_enabled = False
    target = _target(canvas_view, "line")
    text = _text(canvas_view)
    for item in (target, text):
        item.setData(KEY_OWNER_PAGE, [0, 0])
    canvas_view.history().mark_dirty()
    before = canvas_view._serialize_scene_state()
    item_id = text.data(KEY_ITEM_ID)
    _drag(canvas_view, text, application)
    assert text.sceneBoundingRect().bottom() == pytest.approx(174)
    after = canvas_view._serialize_scene_state()
    canvas_view.history().undo()
    assert canvas_view._serialize_scene_state() == before
    canvas_view.history().redo()
    assert canvas_view._serialize_scene_state() == after
    restored = next(item for item in canvas_view.scene().items()
                    if item.data(KEY_ITEM_ID) == item_id)
    assert restored.sceneBoundingRect().bottom() == pytest.approx(174)


@pytest.mark.parametrize("width", [0, 2])
def test_cosmetic_envelope_matches_device_pixels(canvas_view, width):
    canvas_view.setTransform(QtGui.QTransform.fromScale(4, 4))
    item = LineItem(0, 0, length=100)
    pen = QtGui.QPen(QtCore.Qt.GlobalColor.black, width)
    pen.setCosmetic(True)
    item.setPen(pen)
    canvas_view.scene().addItem(item)
    bounds = item_snap_bounds(item, canvas_view)
    assert bounds is not None
    dpr = canvas_view.viewport().devicePixelRatioF()
    image = QtGui.QImage(500, 200, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.translate(10, 25)
    painter.scale(4, 4)
    item.paint(painter, QtWidgets.QStyleOptionGraphicsItem())
    painter.end()
    painted_rows = [y for y in range(200) if image.pixelColor(100, y).alpha() > 128]
    assert painted_rows
    assert bounds.height() == pytest.approx(len(painted_rows) / (4 * dpr))


def test_nested_group_snap_tracks_current_visible_child(canvas_view):
    canvas_view._grid_snap_enabled = False
    canvas_view._master_origin = QtCore.QPointF()
    outer = GroupItem()
    inner = GroupItem()
    canvas_view.scene().addItem(outer)
    canvas_view.scene().addItem(inner)
    child = RectItem(100, 100, 40, 40)
    child.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(child)
    child.setSelected(True)
    inner.addToGroup(child)
    child.setSelected(False)
    outer.addToGroup(inner)
    point, active = canvas_view.snap_scene_position(QtCore.QPointF(300, 134))
    assert active["horizontal"] == pytest.approx(140)
    child.setRect(0, 0, 40, 80)
    point, active = canvas_view.snap_scene_position(QtCore.QPointF(300, 174))
    assert active["horizontal"] == pytest.approx(180)
    child.hide()
    point, active = canvas_view.snap_scene_position(QtCore.QPointF(300, 174))
    assert active == {}
    child.show()
    point, active = canvas_view.snap_scene_position(QtCore.QPointF(300, 174))
    assert active["horizontal"] == pytest.approx(180)


@pytest.mark.parametrize("kind", ["line", "path"])
@pytest.mark.parametrize("rotation,skew,reflection", [(35, 0, 1), (90, 0, 1), (35, .4, -1)])
def test_transformed_path_envelope_matches_painted_pixels(
    canvas_view, kind, rotation, skew, reflection
):
    if kind == "line":
        item = LineItem(0, 0, length=100)
    else:
        item = FreePathItem(0, 0, start=(0, 0), segments=[
            {"kind": "line", "end": (100, 0)}])
    item.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 8))
    item.setRotation(rotation)
    transform = QtGui.QTransform()
    transform.scale(reflection * 1.5, .75)
    transform.shear(skew, .2 if skew else 0)
    item.setTransform(transform)
    canvas_view.scene().addItem(item)
    bounds = item_snap_bounds(item, canvas_view)
    assert bounds is not None
    image = QtGui.QImage(600, 600, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.translate(300, 300)
    painter.setWorldTransform(item.sceneTransform(), combine=True)
    item.paint(painter, QtWidgets.QStyleOptionGraphicsItem())
    painter.end()
    pixels = [(x - 300, y - 300) for y in range(600) for x in range(600)
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
def test_whole_line_grid_snap_uses_geometry_in_connected_layout(canvas_view, width):
    from snap_geometry import item_grid_anchor
    canvas_view._master_origin = QtCore.QPointF()
    canvas_view._grid_size_min = 10
    for first, last in [(QtCore.QPointF(100, 100), QtCore.QPointF(200, 100)),
                        (QtCore.QPointF(100, 200), QtCore.QPointF(200, 200)),
                        (QtCore.QPointF(200, 100), QtCore.QPointF(200, 200))]:
        line = LineItem(0, 0, points=[first, last])
        line.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, width))
        canvas_view.scene().addItem(line)
        canvas_view.scene().clearSelection()
        line.setSelected(True)
        before = [line.mapToScene(point) for point in line._points]
        canvas_view._snap_selected_items()
        assert [line.mapToScene(point) for point in line._points] == before
        assert item_grid_anchor(line) == first


@pytest.mark.parametrize("guide,feedback", [(172, False), (173, True)])
@pytest.mark.parametrize("visible", [False, True])
def test_grid_bound_text_only_reports_reached_guide(canvas_view, application, guide, feedback, visible):
    _show(canvas_view, application)
    canvas_view._grid_size_min = 10
    canvas_view.add_guide("horizontal", guide)
    canvas_view.set_guides_visible(visible)
    text = _text(canvas_view)
    active = _drag(canvas_view, text, application)
    assert text.pos() == QtCore.QPointF(90, 90)
    assert text.sceneBoundingRect().bottom() == pytest.approx(173)
    assert active.get("horizontal") == (173 if feedback else None)


@pytest.mark.parametrize("grid,alignment,want_x,want_guide", [
    (True, True, -29, False), (True, False, -29, False),
    (False, True, -30, True), (False, False, -31, False),
])
def test_snap_modes_respect_origin_and_explicit_geometry_anchor(
    canvas_view, grid, alignment, want_x, want_guide
):
    canvas_view._master_origin = QtCore.QPointF(3, -7)
    canvas_view._grid_snap_enabled = grid
    canvas_view._alignment_snap_enabled = alignment
    canvas_view.add_guide("vertical", -30)
    result, active = canvas_view.snap_scene_position(
        QtCore.QPointF(-31, -22), grid_anchor=QtCore.QPointF(-29, -20), grid_spacing=10)
    assert result == QtCore.QPointF(want_x, -19 if grid else -22)
    assert ("vertical" in active) is want_guide


@pytest.mark.parametrize("shape", ["Text", "Line", "Arrow"])
def test_toolbar_add_uses_main_grid_and_scene_origin(canvas_view, application, shape):
    from snap_geometry import item_grid_anchor
    _show(canvas_view, application)
    canvas_view._master_origin = QtCore.QPointF(3, -7)
    canvas_view._grid_size = 50
    canvas_view.centerOn(117, 139)
    item = canvas_view.add_shape_at_view_center(shape)
    anchor = item_grid_anchor(item)
    assert (anchor.x() - 3) / 50 == pytest.approx(round((anchor.x() - 3) / 50))
    assert (anchor.y() + 7) / 50 == pytest.approx(round((anchor.y() + 7) / 50))


def test_disabling_grid_keeps_new_line_default_length(canvas_view):
    from shape_registry import SHAPE_REGISTRY
    canvas_view._grid_snap_enabled = False
    canvas_view._alignment_snap_enabled = False
    canvas_view._grid_size = 40
    item = canvas_view.add_shape("Line", QtCore.QPointF(83, 77))
    assert item.pos() == QtCore.QPointF(83, 77)
    assert item.path().boundingRect().width() == SHAPE_REGISTRY.get("Line").default_size[0]


@pytest.mark.parametrize("shape,axis,guide", [("Line", "vertical", 100),
                                           ("Text", "horizontal", 150)])
def test_insert_grid_feedback_rejects_registry_edges_absent_from_actual_bounds(
    canvas_view, shape, axis, guide
):
    from snap_geometry import item_grid_anchor
    canvas_view._master_origin = QtCore.QPointF()
    canvas_view._grid_size = 50
    canvas_view.add_guide(axis, guide)
    item = canvas_view.add_shape(shape, QtCore.QPointF(100, 100))
    bounds = item_snap_bounds(item, canvas_view)
    values = (bounds.left(), bounds.center().x(), bounds.right()) if axis == "vertical" else (
        bounds.top(), bounds.center().y(), bounds.bottom())
    assert all(abs(value - guide) > 1e-6 for value in values)
    assert axis not in canvas_view._active_snap_guides
    assert item_grid_anchor(item) == QtCore.QPointF(100, 100)


@pytest.mark.parametrize("shape,axis", [("Line", "vertical"), ("Text", "horizontal")])
def test_insert_grid_feedback_reports_actual_off_grid_painted_edge(canvas_view, shape, axis):
    from shape_registry import SHAPE_REGISTRY
    canvas_view._master_origin = QtCore.QPointF()
    canvas_view._grid_size = 50
    definition = SHAPE_REGISTRY.get(shape)
    preview = SHAPE_REGISTRY.create(shape, 100, 100, *definition.default_size)
    bounds = item_snap_bounds(preview, canvas_view)
    guide = bounds.left() if axis == "vertical" else bounds.bottom()
    canvas_view.add_guide(axis, guide)
    item = canvas_view.add_shape(shape, QtCore.QPointF(100, 100))
    assert item_snap_bounds(item, canvas_view) == bounds
    assert canvas_view._active_snap_guides[axis] == pytest.approx(guide)


@pytest.mark.parametrize("shape", ["Line", "Arrow", "Text", "Rectangle", "Block Arrow", "Free Polyline"])
def test_helper_only_insertion_aligns_actual_painted_bounds(canvas_view, shape):
    from shape_registry import SHAPE_REGISTRY
    canvas_view._master_origin = QtCore.QPointF()
    canvas_view._grid_snap_enabled = False
    definition = SHAPE_REGISTRY.get(shape)
    preview = SHAPE_REGISTRY.create(shape, 100, 100, *definition.default_size)
    guide = item_snap_bounds(preview, canvas_view).left() + 3
    canvas_view.add_guide("vertical", guide)
    item = canvas_view.add_shape(shape, QtCore.QPointF(100, 100))
    assert item_snap_bounds(item, canvas_view).left() == pytest.approx(guide)
    assert canvas_view._active_snap_guides["vertical"] == pytest.approx(guide)


@pytest.mark.parametrize("kind", ["line", "text", "arrow_start", "arrow_end", "arrow_both", "group"])
@pytest.mark.parametrize("free", [False, True])
def test_real_drag_snaps_one_geometry_reference_without_deforming(
    canvas_view, application, kind, free
):
    from snap_geometry import item_grid_anchor
    _show(canvas_view, application)
    canvas_view._master_origin = QtCore.QPointF(3, -7)
    canvas_view._grid_size_min = 10
    if kind == "text":
        item = TextItem(43.7, 81.4, 124, 83, auto_size=False)
        item.setRotation(35)
        canvas_view.scene().addItem(item)
        samples = [QtCore.QPointF(), QtCore.QPointF(124, 83)]
        grab = QtCore.QPointF(62, 41)
    else:
        item = LineItem(0, 0, points=[QtCore.QPointF(157.3, 87.4), QtCore.QPointF(43.7, 81.4)],
                        arrow_start=kind in ("arrow_start", "arrow_both"),
                        arrow_end=kind in ("arrow_end", "arrow_both"))
        item.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 18))
        canvas_view.scene().addItem(item)
        samples = list(item._points)
        grab = samples[0] * .75 + samples[1] * .25
        if kind == "group":
            child = item
            item = GroupItem()
            canvas_view.scene().addItem(item)
            item.addToGroup(child)
            samples = [item.mapFromScene(child.mapToScene(p)) for p in samples]
            grab = samples[0] * .75 + samples[1] * .25
    item.setSelected(True)
    canvas_view.centerOn(item.sceneBoundingRect().center())
    application.processEvents()
    original = [item.mapToScene(p) for p in samples]
    start = canvas_view.mapFromScene(item.mapToScene(grab))
    end = start + QtCore.QPoint(13, 7)
    mods = QtCore.Qt.KeyboardModifier.AltModifier if free else QtCore.Qt.KeyboardModifier.NoModifier
    QTest.mousePress(canvas_view.viewport(), QtCore.Qt.MouseButton.LeftButton, mods, start)
    grabber = canvas_view.scene().mouseGrabberItem()
    assert grabber is item or grabber.parentItem() is item
    event = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(end),
        QtCore.QPointF(canvas_view.viewport().mapToGlobal(end)), QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.LeftButton, mods)
    QtWidgets.QApplication.sendEvent(canvas_view.viewport(), event)
    moved = [item.mapToScene(p) for p in samples]
    deltas = [point - previous for point, previous in zip(moved, original)]
    assert deltas[0].x() == pytest.approx(deltas[1].x())
    assert deltas[0].y() == pytest.approx(deltas[1].y())
    if free:
        assert deltas[0] == canvas_view.mapToScene(end) - canvas_view.mapToScene(start)
    else:
        anchor = item_grid_anchor(item)
        assert (anchor.x() - 3) / 10 == pytest.approx(round((anchor.x() - 3) / 10))
        assert (anchor.y() + 7) / 10 == pytest.approx(round((anchor.y() + 7) / 10))
    QTest.mouseRelease(canvas_view.viewport(), QtCore.Qt.MouseButton.LeftButton, mods, end)
