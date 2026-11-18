import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from layers_panel import LayersPanel


@pytest.fixture
def populated_panel(canvas_view, application):
    with canvas_view.history().suspended():
        for index in range(40):
            canvas_view.add_shape(
                "Rectangle", QtCore.QPointF(index * 5, 0), snap_to_grid=False
            )
    canvas_view.scene().clearSelection()
    panel = LayersPanel(canvas_view)
    panel.resize(360, 300)
    panel.show()
    application.processEvents()
    return panel


def test_selecting_lower_object_preserves_scroll(populated_panel, application):
    tree = populated_panel._tree
    row = tree.topLevelItem(0).child(32)
    item = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
    tree.scrollToItem(row, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
    application.processEvents()
    scroll = tree.verticalScrollBar().value()
    assert scroll > 0

    QtTest.QTest.mouseClick(
        tree.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=tree.visualItemRect(row).center(),
    )
    application.processEvents()

    assert item.isSelected()
    assert tree.verticalScrollBar().value() == scroll
    assert tree.currentItem().data(0, QtCore.Qt.ItemDataRole.UserRole) is item


def test_arrow_keys_select_adjacent_canvas_objects(
    populated_panel, canvas_view, application
):
    tree = populated_panel._tree
    first = tree.topLevelItem(0).child(0)
    first_item = first.data(0, QtCore.Qt.ItemDataRole.UserRole)
    second_item = tree.topLevelItem(0).child(1).data(0, QtCore.Qt.ItemDataRole.UserRole)
    QtTest.QTest.mouseClick(
        tree.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=tree.visualItemRect(first).center(),
    )
    application.processEvents()

    QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Down)
    application.processEvents()
    assert canvas_view.scene().selectedItems() == [second_item]
    assert tree.currentItem().data(0, QtCore.Qt.ItemDataRole.UserRole) is second_item

    QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Up)
    application.processEvents()
    assert canvas_view.scene().selectedItems() == [first_item]


def test_refresh_preserves_current_row_scroll_and_collapsed_layer(
    populated_panel, canvas_view, application
):
    tree = populated_panel._tree
    manager = canvas_view.layer_manager()
    other_layer = manager.add_layer("Other")
    tree.topLevelItem(1).setExpanded(False)
    row = tree.topLevelItem(0).child(30)
    item = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
    tree.setCurrentItem(row)
    application.processEvents()
    tree.scrollToItem(tree.currentItem())
    application.processEvents()
    scroll = tree.verticalScrollBar().value()

    manager.rename_layer(other_layer.id, "Renamed")
    application.processEvents()

    assert tree.currentItem().data(0, QtCore.Qt.ItemDataRole.UserRole) is item
    assert tree.verticalScrollBar().value() == scroll
    assert not tree.topLevelItem(1).isExpanded()


def test_shift_arrow_keeps_multiple_canvas_objects_selected(
    populated_panel, canvas_view, application
):
    tree = populated_panel._tree
    first = tree.topLevelItem(0).child(0)
    expected = {
        tree.topLevelItem(0).child(index).data(0, QtCore.Qt.ItemDataRole.UserRole)
        for index in (0, 1)
    }
    tree.setCurrentItem(first)
    application.processEvents()
    QtTest.QTest.keyClick(
        tree, QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.ShiftModifier
    )
    application.processEvents()

    assert set(canvas_view.scene().selectedItems()) == expected
