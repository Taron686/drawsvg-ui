from __future__ import annotations

from contextlib import contextmanager

import pytest
from PySide6 import QtCore, QtWidgets

from properties_panel import PropertiesPanel
from property_command_service import PropertyCommandService


class RecordingHistory:
    def __init__(self) -> None:
        self.started = 0
        self.finished = 0

    @contextmanager
    def transaction(self):
        self.started += 1
        try:
            yield
        finally:
            self.finished += 1


def _item(x: float, y: float) -> QtWidgets.QGraphicsRectItem:
    item = QtWidgets.QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
    item.setPos(x, y)
    return item


def test_common_descriptors_are_typed_and_shared(application) -> None:
    service = PropertyCommandService()
    first = _item(10.0, 20.0)
    second = _item(10.0, 40.0)

    assert [
        descriptor.key for descriptor in service.descriptors_for([first, second])
    ] == [
        "position_x",
        "position_y",
        "rotation",
        "scale",
        "z_value",
    ]
    assert service.common_value([first, second], "position_x") == 10.0
    assert service.common_value([first, second], "position_y") is None


def test_multi_selection_uses_one_undo_transaction(application) -> None:
    history = RecordingHistory()
    service = PropertyCommandService(history)
    first = _item(10.0, 20.0)
    second = _item(30.0, 40.0)

    assert service.apply([first, second], "position_x", 75.0)
    assert first.x() == 75.0
    assert second.x() == 75.0
    assert (history.started, history.finished) == (1, 1)


def test_locked_items_are_read_only_and_mixed_selection_skips_them(application) -> None:
    history = RecordingHistory()
    service = PropertyCommandService(history)
    locked = _item(10.0, 20.0)
    locked.locked = True
    writable = _item(30.0, 40.0)

    assert service.apply([locked, writable], "rotation", 45.0)
    assert locked.rotation() == 0.0
    assert writable.rotation() == 45.0
    assert service.can_write([locked, writable])

    writable.locked = True
    assert not service.apply([locked, writable], "rotation", 90.0)
    assert writable.rotation() == 45.0
    assert not service.can_write([locked, writable])
    assert (history.started, history.finished) == (1, 1)


def test_invalid_or_unsupported_properties_do_not_mutate(application) -> None:
    service = PropertyCommandService()
    item = _item(10.0, 20.0)

    with pytest.raises(ValueError, match="Invalid value"):
        service.apply([item], "scale", 0.0)
    with pytest.raises(KeyError, match="not available"):
        service.apply([item], "unknown", 1.0)
    assert not service.apply([item], "position_x", 10.0)
    assert item.scale() == 1.0


def test_panel_exposes_only_the_new_explicit_multi_selection_api(application) -> None:
    history = RecordingHistory()
    service = PropertyCommandService(history)
    first = _item(10.0, 20.0)
    second = _item(30.0, 40.0)
    panel = PropertiesPanel()

    panel.show_selected_item_properties([first, second], service)
    panel._spin_pos_x.setValue(90.0)

    assert first.x() == 90.0
    assert second.x() == 90.0
    assert (history.started, history.finished) == (1, 1)

    first.locked = True
    second.locked = True
    panel.show_selected_item_properties([first, second], service)
    assert not panel._spin_pos_x.isEnabled()
    panel.close()


def test_half_width_limit_uses_half_panel_width_with_minimum(application) -> None:
    panel = PropertiesPanel()
    panel.setMinimumWidth(0)

    panel.resize(200, 400)
    assert panel._half_width_limit() == 100

    panel.resize(60, 400)
    assert panel._half_width_limit() == 40
    panel.close()


def test_position_values_are_read_only_displays(application) -> None:
    panel = PropertiesPanel()

    for spin in (panel._spin_pos_x, panel._spin_pos_y):
        assert spin.isReadOnly()
        assert spin.buttonSymbols() == QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons
        assert spin.focusPolicy() == QtCore.Qt.FocusPolicy.NoFocus

    panel.close()


def test_clear_reenables_transform_controls_after_locked_multi_selection(application) -> None:
    service = PropertyCommandService()
    first = _item(10.0, 20.0)
    second = _item(30.0, 40.0)
    first.locked = True
    second.locked = True
    panel = PropertiesPanel()

    panel.show_selected_item_properties([first, second], service)
    assert not panel._spin_pos_x.isEnabled()

    panel.clear()

    assert all(
        spin.isEnabledTo(panel._tab_widget)
        for spin in (
            panel._spin_pos_x,
            panel._spin_pos_y,
            panel._spin_rotation,
            panel._spin_scale,
            panel._spin_z_value,
        )
    )
    panel.close()


def test_single_selection_reenables_transform_controls_after_locked_multi_selection(
    application,
) -> None:
    service = PropertyCommandService()
    first = _item(10.0, 20.0)
    second = _item(30.0, 40.0)
    first.locked = True
    second.locked = True
    panel = PropertiesPanel()

    panel.show_selected_item_properties([first, second], service)
    assert not panel._spin_pos_x.isEnabled()

    panel.update_snapshot(
        {
            "selection_type": "single",
            "item": first,
            "title": "Rectangle",
            "object_data": {},
            "text_data": {},
        }
    )

    assert all(
        spin.isEnabled()
        for spin in (
            panel._spin_pos_x,
            panel._spin_pos_y,
            panel._spin_rotation,
            panel._spin_scale,
            panel._spin_z_value,
        )
    )
    panel.close()


def test_service_creates_one_real_canvas_undo_step(canvas_view) -> None:
    first = canvas_view.add_shape("Rectangle", QtCore.QPointF(10.0, 10.0))
    second = canvas_view.add_shape("Ellipse", QtCore.QPointF(100.0, 10.0))
    assert first is not None
    assert second is not None
    history = canvas_view.history()
    before = len(history._states)

    service = PropertyCommandService(history)
    assert service.apply([first, second], "rotation", 30.0)

    assert len(history._states) == before + 1
    history.undo()
    restored = [
        item
        for item in canvas_view.scene().items()
        if type(item) in {type(first), type(second)}
    ]
    assert len(restored) == 2
    assert all(item.rotation() == 0.0 for item in restored)
