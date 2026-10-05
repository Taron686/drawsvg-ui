# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Edit export margins without changing preferences until the caller accepts."""

from PySide6 import QtCore, QtWidgets

from export_margins import ExportMargins


class ExportMarginsDialog(QtWidgets.QDialog):
    def __init__(self, margins: ExportMargins | None, linked: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Margins")
        layout = QtWidgets.QVBoxLayout(self)
        self.custom_margins = QtWidgets.QCheckBox("Use custom margins")
        self.custom_margins.setChecked(margins is not None)
        layout.addWidget(self.custom_margins)
        layout.addWidget(QtWidgets.QLabel("Drawing units"))

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        self.left = QtWidgets.QDoubleSpinBox()
        self.top = QtWidgets.QDoubleSpinBox()
        self.right = QtWidgets.QDoubleSpinBox()
        self.bottom = QtWidgets.QDoubleSpinBox()
        self._fields = (self.left, self.top, self.right, self.bottom)
        initial = margins if margins is not None else ExportMargins(5, 5, 5, 5)
        for name, field in zip(("left", "top", "right", "bottom"), self._fields):
            field.setDecimals(2)
            field.setRange(0, 10000)
            field.setValue(getattr(initial, name))
        for label, field in (
            ("Top", self.top), ("Right", self.right),
            ("Bottom", self.bottom), ("Left", self.left),
        ):
            form.addRow(label, field)

        self.link_sides = QtWidgets.QCheckBox("Link all sides")
        self.link_sides.setChecked(linked)
        layout.addWidget(self.link_sides)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            | QtWidgets.QDialogButtonBox.StandardButton.Reset
        )
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Reset).clicked.connect(self._reset)
        self.custom_margins.toggled.connect(self._update_enabled)
        self.link_sides.toggled.connect(self._link_toggled)
        for field in self._fields:
            field.valueChanged.connect(self._side_changed)
        self._update_enabled()

    def margins(self) -> ExportMargins | None:
        if not self.custom_margins.isChecked():
            return None
        return ExportMargins(*(field.value() for field in self._fields))

    def linked(self) -> bool:
        return self.link_sides.isChecked()

    def _update_enabled(self) -> None:
        enabled = self.custom_margins.isChecked()
        for field in self._fields:
            field.setEnabled(enabled)
        self.link_sides.setEnabled(enabled)

    def _set_all_values(self, value: float) -> None:
        for field in self._fields:
            with QtCore.QSignalBlocker(field):
                field.setValue(value)

    def _side_changed(self, value: float) -> None:
        if self.linked():
            self._set_all_values(value)

    def _link_toggled(self, checked: bool) -> None:
        if checked:
            self._set_all_values(self.left.value())

    def _reset(self) -> None:
        self.custom_margins.setChecked(False)
        self._set_all_values(5)
        self.link_sides.setChecked(True)
