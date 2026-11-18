from PySide6 import QtCore


def test_rerouted_connector_discards_cached_snap_candidates(canvas_view, application):
    source = canvas_view.add_shape(
        "Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False
    )
    target = canvas_view.add_shape(
        "Rectangle", QtCore.QPointF(400, 300), snap_to_grid=False
    )
    canvas_view.add_connector(source, target)
    application.processEvents()

    canvas_view._begin_snap_drag()
    try:
        canvas_view.snap_scene_position(QtCore.QPointF(10, 10), exclude=(source,))
        assert canvas_view._snap_drag_cache

        # Same route again: the cache stays valid.
        canvas_view.connector_manager().notify_item_geometry_changed(source)
        assert canvas_view._snap_drag_cache

        source.setPos(source.pos() + QtCore.QPointF(120, 80))
        canvas_view.connector_manager().notify_item_geometry_changed(source)
        assert canvas_view._snap_drag_cache == {}
    finally:
        canvas_view._end_snap_drag()
