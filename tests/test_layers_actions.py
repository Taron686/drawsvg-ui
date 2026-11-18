import pytest
from PySide6 import QtCore, QtTest

from layers_panel import LayersPanel


@pytest.fixture
def layer_panel(canvas_view, application):
    for index, shape in enumerate(("Rectangle", "Line", "Ellipse")):
        canvas_view.add_shape(shape, QtCore.QPointF(index * 150, 0), snap_to_grid=False)
    canvas_view.layer_manager().add_layer("Destination")
    canvas_view.scene().clearSelection()
    panel = LayersPanel(canvas_view)
    panel.resize(380, 400)
    panel.show()
    application.processEvents()
    return panel


def click_row(tree, row, application, modifiers=QtCore.Qt.KeyboardModifier.NoModifier):
    QtTest.QTest.mouseClick(
        tree.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        modifiers,
        tree.visualItemRect(row).center(),
    )
    application.processEvents()


@pytest.mark.parametrize("button, expected_index", [("_up", 0), ("_down", 2)])
def test_move_object_follows_visible_tree_direction(
    layer_panel, application, button, expected_index
):
    tree = layer_panel._tree
    row = tree.topLevelItem(0).child(1)
    item = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
    click_row(tree, row, application)
    getattr(layer_panel, button).click()
    application.processEvents()
    assert (
        tree.topLevelItem(0)
        .child(expected_index)
        .data(0, QtCore.Qt.ItemDataRole.UserRole)
        is item
    )


def test_destination_keeps_source_highlighted_and_explains_assignment(
    layer_panel, canvas_view, application
):
    tree = layer_panel._tree
    click_row(tree, tree.topLevelItem(0).child(1), application)
    item = canvas_view.scene().selectedItems()[0]
    click_row(tree, tree.topLevelItem(1), application)

    assert item.isSelected()
    assert tree.topLevelItem(0).child(1).isSelected()
    assert tree.currentItem() is tree.topLevelItem(1)
    assert "1 object" in layer_panel._assignment_summary.text()
    assert "Destination" in layer_panel._assignment_summary.text()
    layer_panel._assign.click()
    assert canvas_view.layer_manager().layer_for_item(item).name == "Destination"
    assert item.isSelected()


def test_assign_moves_all_selected_objects_and_undo_restores_them(
    layer_panel, canvas_view, application
):
    tree = layer_panel._tree
    click_row(tree, tree.topLevelItem(0).child(0), application)
    click_row(
        tree,
        tree.topLevelItem(0).child(1),
        application,
        QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    items = tuple(canvas_view.scene().selectedItems())
    assert len(items) == 2
    original_layer = canvas_view.layer_manager().layer_for_item(items[0]).id
    click_row(tree, tree.topLevelItem(1), application)
    destination = canvas_view.layer_manager().layers()[1].id
    layer_panel._assign.click()
    application.processEvents()
    assert all(
        canvas_view.layer_manager().layer_for_item(item).id == destination
        for item in items
    )
    canvas_view.undo()
    assert len(canvas_view.layer_manager().items_for_layer(original_layer)) == 3


def test_move_layer_uses_destination_not_highlighted_source(
    layer_panel, canvas_view, application
):
    tree = layer_panel._tree
    click_row(tree, tree.topLevelItem(0).child(1), application)
    click_row(tree, tree.topLevelItem(1), application)
    layer_panel._up.click()
    application.processEvents()
    assert canvas_view.layer_manager().layers()[0].name == "Destination"
    layer_panel._down.click()
    assert canvas_view.layer_manager().layers()[1].name == "Destination"
