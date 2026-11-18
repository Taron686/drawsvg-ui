from PySide6 import QtCore

from layers_panel import LayersPanel


def test_layer_visibility_checkbox_updates_all_objects(canvas_view, application):
    first = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    second = canvas_view.add_shape("Line", QtCore.QPointF(150, 0), snap_to_grid=False)
    manager = canvas_view.layer_manager()
    manager.set_item_visible(first, False)
    other_layer = manager.add_layer()
    other = canvas_view.add_shape("Ellipse", QtCore.QPointF(300, 0), snap_to_grid=False)
    manager.assign_item(other, other_layer.id)
    panel = LayersPanel(canvas_view)

    for visible in (False, True):
        state = (
            QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked
        )
        panel._tree.topLevelItem(0).setCheckState(1, state)
        application.processEvents()
        row = panel._tree.topLevelItem(0)
        assert all(row.child(i).checkState(1) == state for i in range(2))
        assert all(item.isVisible() == visible for item in (first, second))
        assert all(manager.item_visible(item) == visible for item in (first, second))
        assert other.isVisible()


def test_layer_visibility_reaches_group_children_and_undo(canvas_view, application):
    first = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    second = canvas_view.add_shape(
        "Ellipse", QtCore.QPointF(150, 0), snap_to_grid=False
    )
    first.setSelected(True)
    second.setSelected(True)
    canvas_view._group_selected_items()
    group = canvas_view.scene().selectedItems()[0]
    manager = canvas_view.layer_manager()
    manager.set_item_visible(first, False)
    panel = LayersPanel(canvas_view)

    for visible in (False, True):
        state = (
            QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked
        )
        panel._tree.topLevelItem(0).setCheckState(1, state)
        application.processEvents()
        row = panel._tree.topLevelItem(0).child(0)
        assert row.checkState(1) == state
        assert row.childCount() == 2
        assert all(row.child(i).checkState(1) == state for i in range(2))
        assert all(item.isVisible() == visible for item in (group, first, second))

    canvas_view.undo()
    application.processEvents()
    assert not manager.layers()[0].visible
    restored_group = manager.items_for_layer(manager.layers()[0].id)[0]
    assert not restored_group.isVisible()
    assert all(not child.isVisible() for child in restored_group.childItems())
    canvas_view.redo()
    application.processEvents()
    restored_group = manager.items_for_layer(manager.layers()[0].id)[0]
    assert restored_group.isVisible()
    assert all(
        child.isVisible()
        for child in restored_group.childItems()
        if canvas_view.is_serializable_item(child)
    )


def test_object_checkbox_stays_unchecked_inside_hidden_layer(canvas_view, application):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    panel = LayersPanel(canvas_view)
    panel._tree.topLevelItem(0).setCheckState(1, QtCore.Qt.CheckState.Unchecked)
    application.processEvents()
    for _ in range(2):
        row = panel._tree.topLevelItem(0).child(0)
        assert row.checkState(1) == QtCore.Qt.CheckState.Unchecked
        row.setCheckState(1, QtCore.Qt.CheckState.Checked)
        application.processEvents()
        assert not item.isVisible()
        assert (
            panel._tree.topLevelItem(0).child(0).checkState(1)
            == QtCore.Qt.CheckState.Unchecked
        )
