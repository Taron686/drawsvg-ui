from __future__ import annotations

from typing import Iterable, Tuple

from PySide6 import QtCore, QtWidgets


class PropertiesPanel(QtWidgets.QWidget):
    """Read-only view that displays properties of the current selection."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(260)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title_label = QtWidgets.QLabel("Eigenschaften")
        font = self._title_label.font()
        font.setBold(True)
        self._title_label.setFont(font)
        layout.addWidget(self._title_label)

        self._info_label = QtWidgets.QLabel("Kein Objekt ausgewählt.")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        self._table = QtWidgets.QTableWidget(0, 2, self)
        self._table.setHorizontalHeaderLabels(["Eigenschaft", "Wert"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._table.hide()
        layout.addWidget(self._table, 1)

        layout.addStretch(0)

    def clear(self) -> None:
        self._title_label.setText("Eigenschaften")
        self._info_label.setText("Kein Objekt ausgewählt.")
        self._info_label.show()
        self._table.hide()
        self._table.setRowCount(0)

    def show_multi_selection(self, count: int) -> None:
        self._title_label.setText("Eigenschaften")
        self._info_label.setText(f"{count} Objekte ausgewählt.")
        self._info_label.show()
        self._table.hide()
        self._table.setRowCount(0)

    def show_properties(
        self, title: str, properties: Iterable[Tuple[str, str]]
    ) -> None:
        self._title_label.setText(f"Eigenschaften – {title}")
        self._info_label.hide()

        items = list(properties)
        self._table.setRowCount(len(items))
        for row, (name, value) in enumerate(items):
            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            value_item = QtWidgets.QTableWidgetItem(value)
            value_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, value_item)
        self._table.show()

    def update_snapshot(self, payload: object) -> None:
        """Slot for CanvasView selection updates."""
        if not isinstance(payload, dict):
            self.clear()
            return

        selection_type = payload.get("selection_type")
        if selection_type == "single":
            title = str(payload.get("title", "Objekt"))
            properties = payload.get("properties", [])
            if isinstance(properties, list):
                pairs: list[Tuple[str, str]] = []
                for entry in properties:
                    if (
                        isinstance(entry, (list, tuple))
                        and len(entry) == 2
                        and all(isinstance(val, str) for val in entry)
                    ):
                        pairs.append((entry[0], entry[1]))
            else:
                pairs = []
            self.show_properties(title, pairs)
        elif selection_type == "multi":
            count = int(payload.get("count", 0))
            self.show_multi_selection(count)
        else:
            self.clear()
