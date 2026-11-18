from PySide6 import QtCore, QtWidgets

from layers_panel import LayersPanel

_MARK = QtCore.Qt.ItemDataRole.UserRole.value + 9


def _panel_with_shapes(canvas_view, application, count=3):
    panel = LayersPanel(canvas_view)
    items = [
        canvas_view.add_shape(
            "Rectangle", QtCore.QPointF(index * 150, 0), snap_to_grid=False
        )
        for index in range(count)
    ]
    canvas_view.scene().clearSelection()
    application.processEvents()
    panel.refresh()
    return panel, items


def _object_rows(panel):
    layer_row = panel._tree.topLevelItem(0)
    return [layer_row.child(index) for index in range(layer_row.childCount())]


def _row_for(panel, item):
    return next(
        row
        for row in _object_rows(panel)
        if row.data(0, QtCore.Qt.ItemDataRole.UserRole) is item
    )


def test_every_row_shows_both_checkboxes(canvas_view, application):
    panel, _items = _panel_with_shapes(canvas_view, application)
    role = QtCore.Qt.ItemDataRole.CheckStateRole
    for row in [panel._tree.topLevelItem(0), *_object_rows(panel)]:
        assert row.data(1, role) is not None
        assert row.data(2, role) is not None


def test_refresh_reuses_rows_and_only_touches_what_changed(
    canvas_view, application, monkeypatch
):
    panel, items = _panel_with_shapes(canvas_view, application)
    for row in [panel._tree.topLevelItem(0), *_object_rows(panel)]:
        row.setData(0, _MARK, "kept")
    created = []
    original = LayersPanel._new_row
    monkeypatch.setattr(
        LayersPanel,
        "_new_row",
        staticmethod(
            lambda kind, target: created.append(kind) or original(kind, target)
        ),
    )

    panel.refresh()
    assert created == []

    added = canvas_view.add_shape("Ellipse", QtCore.QPointF(0, 300), snap_to_grid=False)
    application.processEvents()
    panel.refresh()
    assert created == ["item"]
    assert _row_for(panel, added).data(0, _MARK) is None
    assert all(_row_for(panel, item).data(0, _MARK) == "kept" for item in items)

    canvas_view.scene().removeItem(items[1])
    panel.refresh()
    targets = [
        row.data(0, QtCore.Qt.ItemDataRole.UserRole) for row in _object_rows(panel)
    ]
    assert items[1] not in targets
    assert len(targets) == 3
    assert created == ["item"]


def test_refresh_follows_stacking_order_and_keeps_moved_rows(canvas_view, application):
    panel, items = _panel_with_shapes(canvas_view, application)
    for row in _object_rows(panel):
        row.setData(0, _MARK, "kept")
    manager = canvas_view.layer_manager()

    assert manager.move_item(items[0], 2)
    panel.refresh()

    expected = list(reversed(manager.items_for_layer(manager.layers()[0].id)))
    rows = _object_rows(panel)
    assert [row.data(0, QtCore.Qt.ItemDataRole.UserRole) for row in rows] == expected
    assert all(row.data(0, _MARK) == "kept" for row in rows)


def test_object_checkbox_under_overriding_layer_records_no_undo_step(
    canvas_view, application
):
    panel, items = _panel_with_shapes(canvas_view, application)
    manager = canvas_view.layer_manager()
    history = canvas_view.history()
    layer_id = manager.layers()[0].id
    manager.set_layer_locked(layer_id, True)
    manager.set_layer_visible(layer_id, False)
    application.processEvents()
    history.capture_now()
    states = len(history._states)

    row = _row_for(panel, items[0])
    row.setCheckState(2, QtCore.Qt.CheckState.Unchecked)
    row.setCheckState(1, QtCore.Qt.CheckState.Checked)
    application.processEvents()
    history.capture_now()

    row = _row_for(panel, items[0])
    assert row.checkState(2) == QtCore.Qt.CheckState.Checked
    assert row.checkState(1) == QtCore.Qt.CheckState.Unchecked
    assert manager.item_locked(items[0])
    assert not manager.item_visible(items[0])
    assert len(history._states) == states
    assert isinstance(panel, QtWidgets.QWidget)
