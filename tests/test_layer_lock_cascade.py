from PySide6 import QtCore, QtWidgets

from layers_panel import LayersPanel


def test_layer_checkbox_locks_and_unlocks_all_object_checkboxes(
    canvas_view, application
):
    first = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    second = canvas_view.add_shape("Line", QtCore.QPointF(150, 0), snap_to_grid=False)
    manager = canvas_view.layer_manager()
    manager.set_item_locked(first, True)
    panel = LayersPanel(canvas_view)

    panel._tree.topLevelItem(0).setCheckState(2, QtCore.Qt.CheckState.Checked)
    application.processEvents()
    layer_row = panel._tree.topLevelItem(0)
    assert all(
        layer_row.child(i).checkState(2) == QtCore.Qt.CheckState.Checked
        for i in range(2)
    )
    assert first.locked and second.locked

    layer_row.setCheckState(2, QtCore.Qt.CheckState.Unchecked)
    application.processEvents()
    layer_row = panel._tree.topLevelItem(0)
    assert all(
        layer_row.child(i).checkState(2) == QtCore.Qt.CheckState.Unchecked
        for i in range(2)
    )
    assert not first.locked and not second.locked
    assert all(
        item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        for item in (first, second)
    )


def test_layer_unlock_clears_nested_item_locks_and_undo_restores_them(
    canvas_view, application
):
    first = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    second = canvas_view.add_shape(
        "Ellipse", QtCore.QPointF(150, 0), snap_to_grid=False
    )
    first.setSelected(True)
    second.setSelected(True)
    canvas_view._group_selected_items()
    group = canvas_view.scene().selectedItems()[0]
    manager = canvas_view.layer_manager()
    manager.set_item_locked(first, True)
    panel = LayersPanel(canvas_view)
    panel._tree.topLevelItem(0).setCheckState(2, QtCore.Qt.CheckState.Checked)
    application.processEvents()
    row = panel._tree.topLevelItem(0).child(0)
    assert row.checkState(2) == QtCore.Qt.CheckState.Checked
    assert all(
        row.child(i).checkState(2) == QtCore.Qt.CheckState.Checked
        for i in range(row.childCount())
    )
    panel._tree.topLevelItem(0).setCheckState(2, QtCore.Qt.CheckState.Unchecked)
    application.processEvents()
    assert all(
        not item.locked and not manager.item_locked(item)
        for item in (group, first, second)
    )
    canvas_view.undo()
    application.processEvents()
    assert manager.layers()[0].locked
    assert all(item.locked for item in manager.items_for_layer(manager.layers()[0].id))


def test_object_checkbox_cannot_claim_unlocked_inside_locked_layer(
    canvas_view, application
):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    panel = LayersPanel(canvas_view)
    panel._tree.topLevelItem(0).setCheckState(2, QtCore.Qt.CheckState.Checked)
    application.processEvents()
    for _ in range(2):
        row = panel._tree.topLevelItem(0).child(0)
        assert row.checkState(2) == QtCore.Qt.CheckState.Checked
        row.setCheckState(2, QtCore.Qt.CheckState.Unchecked)
        application.processEvents()
        assert item.locked
        assert (
            panel._tree.topLevelItem(0).child(0).checkState(2)
            == QtCore.Qt.CheckState.Checked
        )
