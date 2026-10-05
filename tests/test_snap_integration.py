from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from constants import PALETTE_MIME
from document_controller import DocumentWindowRegistry
from items import LineItem, RectItem, TextItem
from items.base import ResizeHandle, snap_to_grid
from main_window import MainWindow
from snap_geometry import item_grid_anchor


MODES = [(True, True), (True, False), (False, True), (False, False)]


@pytest.fixture(params=["setters", "actions"])
def mode_driver(request, canvas_view, application, tmp_path):
    window = None
    if request.param == "actions":
        window = MainWindow(
            recent_files_path=tmp_path / "recent.json",
            window_registry=DocumentWindowRegistry(),
            settings=QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat),
        )
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.resize(1100, 800)
        window.show()
        view = window.canvas
    else:
        view = canvas_view
        view.resize(800, 600)
        view.show()
    view._grid_size = 10
    view._grid_size_min = 10
    view._master_origin = QtCore.QPointF()
    application.processEvents()
    view.setTransform(QtGui.QTransform())

    def configure(grid, alignment):
        if window is None:
            view.set_grid_snap_enabled(grid)
            view.set_alignment_snap_enabled(alignment)
            view.set_grid_visible(False)
            view.set_guides_visible(False)
        else:
            for action, enabled in ((window.actionSnap_grid, grid),
                                    (window.actionSnap_alignment, alignment),
                                    (window.actionShow_grid, False),
                                    (window.actionShow_guides, False)):
                if action.isChecked() != enabled:
                    action.trigger()
        assert view.grid_snap_enabled() is grid
        assert view.alignment_snap_enabled() is alignment

    try:
        yield view, configure
    finally:
        if window is not None:
            window._force_close = True
            window.close()


def _drag(view, item, application, delta, *, alt=False):
    view.scene().clearSelection()
    item.setSelected(True)
    view.centerOn(item.sceneBoundingRect().center())
    application.processEvents()
    grab = (item.mapToScene(item._points[0] * .75 + item._points[1] * .25)
            if isinstance(item, LineItem) else item.sceneBoundingRect().center())
    start = view.mapFromScene(grab)
    end = start + delta
    modifiers = (QtCore.Qt.KeyboardModifier.AltModifier if alt
                 else QtCore.Qt.KeyboardModifier.NoModifier)
    QtTest.QTest.mousePress(view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, start)
    assert view.scene().mouseGrabberItem() is item
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove, QtCore.QPointF(end),
        QtCore.QPointF(view.viewport().mapToGlobal(end)),
        QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton, modifiers,
    )
    QtWidgets.QApplication.sendEvent(view.viewport(), event)
    active = dict(view._active_snap_guides)
    QtTest.QTest.mouseRelease(view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, end)
    return active


@pytest.mark.parametrize("grid,alignment", MODES)
@pytest.mark.parametrize("path", ["policy", "insert", "drop", "drag", "point", "resize"])
def test_public_modes_drive_policy_insertion_drop_and_drag(
    mode_driver, application, grid, alignment, path
):
    view, configure = mode_driver
    configure(grid, alignment)
    position = QtCore.QPointF(103, 107)
    expected = QtCore.QPointF(100, 110) if grid else position
    if path == "policy":
        result, active = view.snap_scene_position(position)
        assert active == {}
    elif path == "insert":
        result = item_grid_anchor(view.add_shape("Rectangle", position))
    elif path == "drop":
        view.centerOn(position)
        application.processEvents()
        point = view.mapFromScene(position)
        assert view.mapToScene(point) == position
        mime = QtCore.QMimeData()
        mime.setData(PALETTE_MIME, b"Rectangle")
        event = QtGui.QDropEvent(QtCore.QPointF(point), QtCore.Qt.DropAction.CopyAction,
                                mime, QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier)
        view.dropEvent(event)
        assert event.isAccepted()
        result = item_grid_anchor(next(item for item in view.scene().items() if isinstance(item, RectItem)))
    else:
        item = RectItem(100, 100, 100, 100)
        item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        view.scene().addItem(item)
        if path == "drag":
            assert _drag(view, item, application, QtCore.QPoint(3, 7)) == {}
            result = item_grid_anchor(item)
        elif path == "point":
            result = snap_to_grid(item, position)
        else:
            handle = ResizeHandle(item, "bottom_right")
            for event_type, point in [(QtCore.QEvent.Type.GraphicsSceneMousePress, QtCore.QPointF(200, 200)),
                                      (QtCore.QEvent.Type.GraphicsSceneMouseMove, QtCore.QPointF(203, 207)),
                                      (QtCore.QEvent.Type.GraphicsSceneMouseRelease, QtCore.QPointF(203, 207))]:
                event = QtWidgets.QGraphicsSceneMouseEvent(event_type)
                event.setScenePos(point)
                handle_event = {QtCore.QEvent.Type.GraphicsSceneMousePress: handle.mousePressEvent,
                                QtCore.QEvent.Type.GraphicsSceneMouseMove: handle.mouseMoveEvent,
                                QtCore.QEvent.Type.GraphicsSceneMouseRelease: handle.mouseReleaseEvent}[event_type]
                handle_event(event)
            result = QtCore.QPointF(item.rect().width(), item.rect().height())
    assert result == expected


@pytest.mark.parametrize("grid,alignment", MODES)
def test_public_modes_keep_grid_binding_manual_priority_and_reached_feedback(mode_driver, grid, alignment):
    view, configure = mode_driver
    configure(grid, alignment)
    target = RectItem(104, 104, 60, 60)
    target.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    view.scene().addItem(target)
    view.add_guide("vertical", 107)
    view.add_guide("horizontal", 107)
    result, active = view.snap_scene_position(QtCore.QPointF(103, 107))
    assert result == (QtCore.QPointF(100, 110) if grid else
                      QtCore.QPointF(107, 107) if alignment else QtCore.QPointF(103, 107))
    assert active == ({"vertical": 107, "horizontal": 107} if alignment and not grid else {})
    for orientation, position in view.guides():
        view.remove_guide(orientation, position)
    result, active = view.snap_scene_position(QtCore.QPointF(103, 107))
    assert result == (QtCore.QPointF(100, 110) if grid else
                      QtCore.QPointF(104, 104) if alignment else QtCore.QPointF(103, 107))
    assert active == ({"vertical": 104, "horizontal": 104} if alignment and not grid else {})
    view.add_guide("horizontal", 110)
    result, active = view.snap_scene_position(QtCore.QPointF(103, 107))
    if grid:
        assert result == QtCore.QPointF(100, 110)
        assert active == ({"horizontal": 110} if alignment else {})


@pytest.mark.parametrize("grid,alignment", MODES)
@pytest.mark.parametrize("shape", ["Line", "Arrow", "Text"])
def test_public_modes_preserve_origin_main_insert_subgrid_move_and_free_line_length(
    mode_driver, grid, alignment, shape
):
    view, configure = mode_driver
    configure(grid, alignment)
    view._grid_size = 40
    view._grid_size_min = 10
    view._master_origin = QtCore.QPointF(3, -7)
    position = QtCore.QPointF(103, 107)
    result, active = view.snap_scene_position(position)
    assert result == (QtCore.QPointF(103, 103) if grid else position)
    assert active == {}
    item = view.add_shape(shape, position)
    anchor = item_grid_anchor(item)
    if grid:
        assert (anchor.x() - 3) / 40 == pytest.approx(round((anchor.x() - 3) / 40))
        assert (anchor.y() + 7) / 40 == pytest.approx(round((anchor.y() + 7) / 40))
    else:
        assert item.pos() == position
        if shape in ("Line", "Arrow"):
            assert item.path().boundingRect().width() == 150


@pytest.mark.parametrize("width", [2, 8, 18])
def test_real_window_actions_and_pointer_keep_three_line_pattern_and_text_on_grid(
    application, tmp_path, width
):
    window = MainWindow(
        recent_files_path=tmp_path / "recent.json", window_registry=DocumentWindowRegistry(),
        settings=QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat),
    )
    try:
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.resize(1100, 800)
        window.show()
        view = window.canvas
        view._grid_size = 50
        view._grid_size_min = 10
        view._master_origin = QtCore.QPointF()
        window.actionSnap_alignment.trigger()
        assert not view.alignment_snap_enabled()
        application.processEvents()
        view.setTransform(QtGui.QTransform())
        lines = []
        for first, last in [((100, 100), (200, 100)), ((100, 200), (200, 200)),
                            ((200, 100), (200, 200))]:
            line = LineItem(0, 0, points=[QtCore.QPointF(*first), QtCore.QPointF(*last)])
            line.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, width))
            view.scene().addItem(line)
            lines.append(line)
        for line in lines:
            before = [line.mapToScene(point) for point in line._points]
            _drag(view, line, application, QtCore.QPoint(3, 2))
            assert [line.mapToScene(point) for point in line._points] == before
        text = TextItem(100, 100, 124, 83, auto_size=False)
        text.setData(0, "Text")
        view.scene().addItem(text)
        view.add_guide("horizontal", 182)
        window.actionSnap_alignment.trigger()
        _drag(view, text, application, QtCore.QPoint(3, 2))
        assert item_grid_anchor(text) == QtCore.QPointF(100, 100)
        assert text.sceneBoundingRect().bottom() == 183
        assert _drag(view, text, application, QtCore.QPoint(3, 2), alt=True) == {}
        assert text.pos() == QtCore.QPointF(103, 102)
        window.actionSnap_grid.trigger()
        window.actionSnap_alignment.trigger()
        _drag(view, text, application, QtCore.QPoint(3, 2))
        assert text.pos() == QtCore.QPointF(106, 104)
    finally:
        window._force_close = True
        window.close()
