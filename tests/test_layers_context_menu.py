import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from layers_panel import LayersPanel


@pytest.mark.parametrize("location", [0, 1, 2, "empty", "header"])
def test_context_menu_expands_and_collapses_all_without_losing_selection(
    canvas_view, application, location
):
    first = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    second = canvas_view.add_shape(
        "Ellipse", QtCore.QPointF(150, 0), snap_to_grid=False
    )
    first.setSelected(True)
    second.setSelected(True)
    canvas_view._group_selected_items()
    selected = set(canvas_view.scene().selectedItems())
    canvas_view.layer_manager().add_layer("Other")
    panel = LayersPanel(canvas_view)
    panel.resize(450, 500)
    panel.show()
    application.processEvents()
    tree = panel._tree

    for command, expanded in (("Collapse all", False), ("Expand all", True)):
        surface = tree.header().viewport() if location == "header" else tree.viewport()
        if isinstance(location, int):
            point = QtCore.QPoint(
                tree.columnViewportPosition(location) + tree.columnWidth(location) // 2,
                tree.visualItemRect(tree.topLevelItem(0)).center().y(),
            )
        elif location == "empty":
            point = surface.rect().bottomRight() - QtCore.QPoint(10, 10)
            assert tree.itemAt(point) is None
        else:
            point = surface.rect().center()
        observed = []

        def choose_action(command=command, observed=observed):
            popup = application.activePopupWidget()
            if isinstance(popup, QtWidgets.QMenu):
                try:
                    observed.extend(action.text() for action in popup.actions())
                    for action in popup.actions():
                        if action.text() == command:
                            action.trigger()
                            break
                finally:
                    popup.close()

        QtCore.QTimer.singleShot(0, choose_action)
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Reason.Mouse, point, surface.mapToGlobal(point)
        )
        application.sendEvent(surface, event)
        application.processEvents()
        assert observed == ["Collapse all", "Expand all"]
        assert tree.topLevelItem(0).isExpanded() == expanded
        assert tree.topLevelItem(0).child(0).isExpanded() == expanded
        assert set(canvas_view.scene().selectedItems()) == selected
        panel.refresh()
        assert tree.topLevelItem(0).isExpanded() == expanded
        assert tree.topLevelItem(0).child(0).isExpanded() == expanded
    panel.close()
