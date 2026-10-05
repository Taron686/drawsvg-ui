import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from items import GroupItem


@pytest.mark.parametrize(
    "shape",
    ("Arrow", "Line", "Free Polyline", "Free Polygon", "Bezier Path", "Rectangle"),
)
def test_grouping_hides_child_handles_until_ungrouped(
    application, canvas_view, shape
):
    rectangle = canvas_view.add_shape(
        "Rectangle", QtCore.QPointF(100.0, 100.0), snap_to_grid=False
    )
    item = canvas_view.add_shape(
        shape, QtCore.QPointF(100.0, 250.0), snap_to_grid=False
    )
    assert rectangle is not None and item is not None
    scene = canvas_view.scene()
    scene.clearSelection()
    rectangle.setSelected(True)
    item.setSelected(True)
    handles = item._handles + getattr(item, "_mid_handles", [])
    rotation_handle = getattr(item, "_rotation_handle", None)
    if rotation_handle is not None:
        handles = handles + [rotation_handle]
    assert handles and all(handle.isVisible() for handle in handles)

    canvas_view._group_selected_items()
    group = item.parentItem()
    assert isinstance(group, GroupItem)
    scene.clearSelection()
    application.processEvents()

    assert not scene.selectedItems()
    assert not item.isSelected()
    assert all(not handle.isVisible() for handle in handles)

    group.setSelected(True)
    assert all(not handle.isVisible() for handle in handles)
    canvas_view._ungroup_selected_items()
    assert item.parentItem() is None
    item.setSelected(True)
    assert all(handle.isVisible() for handle in handles)
    scene.clearSelection()


@pytest.mark.parametrize("grabbed", (0, 1, 2))
@pytest.mark.parametrize("free_move", (False, True))
def test_drag_selection_preserves_relative_positions(
    application, canvas_view, grabbed, free_move
):
    view = canvas_view
    view.resize(900, 700)
    view.show()
    application.processEvents()
    items = [
        view.add_shape(shape, QtCore.QPointF(x, y), snap_to_grid=False)
        for shape, x, y in (
            ("Rectangle", 43.7, -230.4),
            ("Diamond", -63.3, -30.2),
            ("Text", 37.1, 180.6),
        )
    ]
    for item in items:
        item.setSelected(True)
    before = [QtCore.QPointF(item.pos()) for item in items]
    state_before = view._serialize_scene_state()
    history_count = len(view.history()._states)
    start = view.mapFromScene(items[grabbed].sceneBoundingRect().center())
    modifiers = (
        QtCore.Qt.KeyboardModifier.AltModifier
        if free_move else QtCore.Qt.KeyboardModifier.NoModifier
    )
    QTest.mousePress(
        view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, start
    )
    # Check the first tiny movement as well as subsequent drag events.
    for offset in (QtCore.QPoint(2, 1), QtCore.QPoint(25, 17)):
        point = start + offset
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(point),
            QtCore.QPointF(view.viewport().mapToGlobal(point)),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            modifiers,
        )
        QtWidgets.QApplication.sendEvent(view.viewport(), event)
        deltas = [item.pos() - pos for item, pos in zip(items, before)]
        for delta in deltas[1:]:
            assert delta.x() == pytest.approx(deltas[0].x())
            assert delta.y() == pytest.approx(deltas[0].y())
        if free_move:
            expected = view.mapToScene(point) - view.mapToScene(start)
            assert deltas[0].x() == pytest.approx(expected.x())
            assert deltas[0].y() == pytest.approx(expected.y())
        else:
            from snap_geometry import item_grid_anchor
            anchor = item_grid_anchor(items[grabbed])
            origin = view._master_origin
            for value, base in ((anchor.x(), origin.x()), (anchor.y(), origin.y())):
                units = (value - base) / view._grid_size_min
                assert units == pytest.approx(round(units))
    QTest.mouseRelease(
        view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, start + offset
    )
    assert len(view.history()._states) == history_count + 1
    state_after = view._serialize_scene_state()
    assert state_after != state_before
    view.history().undo()
    assert view._serialize_scene_state() == state_before
    view.history().redo()
    assert view._serialize_scene_state() == state_after
