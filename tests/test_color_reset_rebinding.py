from PySide6 import QtGui, QtWidgets

from properties_panel import ColorButton, PropertiesPanel


def test_rebinding_color_reset_disconnects_previous_callback(application):
    panel = PropertiesPanel()
    color = ColorButton()
    reset = QtWidgets.QPushButton()
    calls = []
    for name in ("first", "second"):
        panel._bind_color_field(
            color,
            lambda: QtGui.QColor("black"),
            lambda value: None,
            reset_button=reset,
            resetter=lambda name=name: calls.append(name),
        )
    reset.click()
    assert calls == ["second"]
