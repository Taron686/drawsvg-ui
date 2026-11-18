from PySide6 import QtCore, QtGui

from items import LineItem


def _zoom_in(canvas_view) -> None:
    position = QtCore.QPointF(canvas_view.viewport().rect().center())
    event = QtGui.QWheelEvent(
        position,
        canvas_view.viewport().mapToGlobal(position),
        QtCore.QPoint(),
        QtCore.QPoint(0, 120),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.ControlModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    canvas_view.wheelEvent(event)


def test_zoom_during_drag_discards_cached_snap_candidates(canvas_view, application):
    # A cosmetic pen is measured in device pixels, so its snap envelope in
    # scene units depends on the view transform.
    line = LineItem(100.0, 100.0, length=20.0)
    pen = QtGui.QPen(line.pen())
    pen.setWidthF(10.0)
    pen.setCosmetic(True)
    line.setPen(pen)
    canvas_view.scene().addItem(line)
    canvas_view.set_grid_snap_enabled(False)
    application.processEvents()
    probe = QtCore.QPointF(96.0, 110.0)

    canvas_view._begin_snap_drag()
    try:
        canvas_view.snap_scene_position(probe)
        assert canvas_view._snap_drag_cache
        _zoom_in(canvas_view)
        assert canvas_view._snap_drag_cache == {}
        cached = canvas_view.snap_scene_position(probe)
    finally:
        canvas_view._end_snap_drag()

    assert cached == canvas_view.snap_scene_position(probe)
