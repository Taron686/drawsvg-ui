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

        self._tab_widget = QtWidgets.QTabWidget(self)
        self._tab_widget.setDocumentMode(True)

        self._object_table = self._create_table()
        self._text_table = self._create_table()

        self._tab_widget.addTab(self._object_table, "Objekt")
        self._tab_widget.addTab(self._text_table, "Text")
        self._tab_widget.hide()
        layout.addWidget(self._tab_widget, 1)

        layout.addStretch(0)

    def _create_table(self) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(0, 2, self)
        table.setHorizontalHeaderLabels(["Eigenschaft", "Wert"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        return table

    @staticmethod
    def _coerce_pairs(raw: object) -> list[Tuple[str, str]]:
        pairs: list[Tuple[str, str]] = []
        if isinstance(raw, list):
            for entry in raw:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and all(isinstance(val, str) for val in entry)
                ):
                    pairs.append((entry[0], entry[1]))
        return pairs

    def _populate_table(
        self, table: QtWidgets.QTableWidget, items: Iterable[Tuple[str, str]]
    ) -> None:
        entries = list(items)
        table.setRowCount(len(entries))
        for row, (name, value) in enumerate(entries):
            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            value_item = QtWidgets.QTableWidgetItem(value)
            value_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            table.setItem(row, 0, name_item)
            table.setItem(row, 1, value_item)

    def clear(self) -> None:
        self._title_label.setText("Eigenschaften")
        self._info_label.setText("Kein Objekt ausgewählt.")
        self._info_label.show()
        self._tab_widget.hide()
        self._object_table.setRowCount(0)
        self._text_table.setRowCount(0)

    def show_multi_selection(self, count: int) -> None:
        self._title_label.setText("Eigenschaften")
        self._info_label.setText(f"{count} Objekte ausgewählt.")
        self._info_label.show()
        self._tab_widget.hide()
        self._object_table.setRowCount(0)
        self._text_table.setRowCount(0)

    def show_properties(
        self,
        title: str,
        object_properties: Iterable[Tuple[str, str]],
        text_properties: Iterable[Tuple[str, str]] | None = None,
    ) -> None:
        self._title_label.setText(f"Eigenschaften – {title}")
        self._info_label.hide()

        obj_items = list(object_properties)
        text_items = list(text_properties) if text_properties else []

        self._populate_table(self._object_table, obj_items)
        if text_items:
            self._populate_table(self._text_table, text_items)
        else:
            self._text_table.setRowCount(0)

        has_text = bool(text_items)
        if hasattr(self._tab_widget, "setTabVisible"):
            self._tab_widget.setTabVisible(1, has_text)
        else:
            self._tab_widget.setTabEnabled(1, has_text)
            if not has_text and self._tab_widget.currentIndex() == 1:
                self._tab_widget.setCurrentIndex(0)
        self._tab_widget.setCurrentIndex(0)
        self._tab_widget.show()

    def update_snapshot(self, payload: object) -> None:
        """Slot for CanvasView selection updates."""
        if not isinstance(payload, dict):
            self.clear()
            return

        selection_type = payload.get("selection_type")
        if selection_type == "single":
            title = str(payload.get("title", "Objekt"))
            properties = self._coerce_pairs(payload.get("properties"))
            text_pairs = self._coerce_pairs(payload.get("text_properties"))
            self.show_properties(title, properties, text_pairs if text_pairs else None)
        elif selection_type == "multi":
            count = int(payload.get("count", 0))
            self.show_multi_selection(count)
        else:
            self.clear()
