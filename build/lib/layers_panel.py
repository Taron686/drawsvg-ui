"""Layers and object-tree sidebar for the canvas."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from items import GroupItem
from layer_manager import LayerManager


class LayersPanel(QtWidgets.QWidget):
    """A small tree view that delegates all state changes to LayerManager."""

    def __init__(self, canvas: Any, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._manager: LayerManager = canvas.layer_manager()
        self._syncing = False
        self._tree = QtWidgets.QTreeWidget(self)
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Object", "Visible", "Locked"])
        self._tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemChanged.connect(self._item_changed)
        self._tree.itemSelectionChanged.connect(self._tree_selection_changed)

        self._add = QtWidgets.QPushButton("+ Layer", self)
        self._remove = QtWidgets.QPushButton("- Layer", self)
        self._rename = QtWidgets.QPushButton("Rename", self)
        self._assign = QtWidgets.QPushButton("Assign selected", self)
        self._up = QtWidgets.QPushButton("Move up", self)
        self._down = QtWidgets.QPushButton("Move down", self)
        self._add.clicked.connect(self._add_layer)
        self._remove.clicked.connect(self._remove_layer)
        self._rename.clicked.connect(self._rename_layer)
        self._assign.clicked.connect(self._assign_selected)
        self._up.clicked.connect(lambda: self._move_selected(-1))
        self._down.clicked.connect(lambda: self._move_selected(1))

        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(self._add)
        controls.addWidget(self._remove)
        controls.addWidget(self._rename)
        controls.addWidget(self._assign)
        controls.addStretch(1)
        controls.addWidget(self._up)
        controls.addWidget(self._down)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._tree)
        layout.addLayout(controls)

        self._manager.changed.connect(self.refresh)
        self._canvas.selectionSnapshotChanged.connect(self._sync_selection)
        self.refresh()

    def refresh(self) -> None:
        if self._syncing:
            return
        selected_ids = {
            id(item)
            for item in self._canvas.scene().selectedItems()
            if self._canvas._is_serializable_item(item)
        }
        self._syncing = True
        try:
            self._tree.clear()
            for layer in self._manager.layers():
                layer_row = QtWidgets.QTreeWidgetItem([layer.name, "", ""])
                layer_row.setData(0, QtCore.Qt.ItemDataRole.UserRole, layer.id)
                layer_row.setData(0, QtCore.Qt.ItemDataRole.UserRole.value + 1, "layer")
                layer_row.setFlags(
                    layer_row.flags()
                    | QtCore.Qt.ItemFlag.ItemIsUserCheckable
                    | QtCore.Qt.ItemFlag.ItemIsSelectable
                )
                layer_row.setCheckState(1, self._check_state(layer.visible))
                layer_row.setCheckState(2, self._check_state(layer.locked))
                self._tree.addTopLevelItem(layer_row)
                for item in reversed(self._manager.items_for_layer(layer.id)):
                    self._add_object_row(layer_row, item, selected_ids)
                layer_row.setExpanded(True)
        finally:
            self._syncing = False

    def _add_object_row(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        item: QtWidgets.QGraphicsItem,
        selected_ids: set[int],
    ) -> None:
        name = str(item.data(0) or item.__class__.__name__)
        row = QtWidgets.QTreeWidgetItem([name, "", ""])
        row.setData(0, QtCore.Qt.ItemDataRole.UserRole, item)
        row.setData(0, QtCore.Qt.ItemDataRole.UserRole.value + 1, "item")
        row.setFlags(
            row.flags()
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        row.setCheckState(1, self._check_state(self._manager.item_visible(item)))
        row.setCheckState(2, self._check_state(self._manager.item_locked(item)))
        parent.addChild(row)
        if id(item) in selected_ids:
            row.setSelected(True)
        if isinstance(item, GroupItem):
            for child in item.childItems():
                if child.__class__.__name__.endswith("Handle"):
                    continue
                self._add_object_row(row, child, selected_ids)

    @staticmethod
    def _check_state(value: bool) -> QtCore.Qt.CheckState:
        return QtCore.Qt.CheckState.Checked if value else QtCore.Qt.CheckState.Unchecked

    def _item_changed(self, row: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._syncing or column not in (1, 2):
            return
        kind = row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1)
        value = row.checkState(column) == QtCore.Qt.CheckState.Checked
        self._syncing = True
        try:
            with self._canvas.history().transaction():
                if kind == "layer":
                    layer_id = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
                    changed = (
                        self._manager.set_layer_visible(layer_id, value)
                        if column == 1
                        else self._manager.set_layer_locked(layer_id, value)
                    )
                else:
                    item = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
                    changed = (
                        self._manager.set_item_visible(item, value)
                        if column == 1
                        else self._manager.set_item_locked(item, value)
                    )
                if changed:
                    self._canvas.history().mark_dirty()
        finally:
            self._syncing = False
        if changed:
            QtCore.QTimer.singleShot(0, self.refresh)

    def _tree_selection_changed(self) -> None:
        if self._syncing:
            return
        selected = self._tree.selectedItems()
        items = [
            row.data(0, QtCore.Qt.ItemDataRole.UserRole)
            for row in selected
            if row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1) == "item"
        ]
        if not items:
            return
        self._canvas.scene().clearSelection()
        for item in items:
            if item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                item.setSelected(True)

    def _sync_selection(self, _payload: dict[str, Any]) -> None:
        if not self._syncing:
            self.refresh()

    def _add_layer(self) -> None:
        with self._canvas.history().transaction():
            self._manager.add_layer()
            self._canvas.history().mark_dirty()

    def _remove_layer(self) -> None:
        selected = self._tree.selectedItems()
        if not selected:
            return
        row = selected[0]
        if row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1) != "layer":
            row = row.parent()
        if row is None:
            return
        with self._canvas.history().transaction():
            if self._manager.remove_layer(row.data(0, QtCore.Qt.ItemDataRole.UserRole)):
                self._canvas.history().mark_dirty()

    def _rename_layer(self) -> None:
        selected = self._tree.selectedItems()
        if not selected:
            return
        row = selected[0]
        if row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1) != "layer":
            row = row.parent()
        if row is None:
            return
        name, accepted = QtWidgets.QInputDialog.getText(
            self, "Rename layer", "Name:", text=row.text(0)
        )
        if not accepted:
            return
        with self._canvas.history().transaction():
            if self._manager.rename_layer(
                row.data(0, QtCore.Qt.ItemDataRole.UserRole), name
            ):
                self._canvas.history().mark_dirty()

    def _move_selected(self, offset: int) -> None:
        selected = self._tree.selectedItems()
        if not selected:
            return
        row = selected[0]
        with self._canvas.history().transaction():
            kind = row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1)
            target = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
            changed = (
                self._manager.move_layer(target, offset)
                if kind == "layer"
                else self._manager.move_item(target, offset)
                if kind == "item"
                else False
            )
            if changed:
                self._canvas.history().mark_dirty()

    def _assign_selected(self) -> None:
        selected = self._tree.selectedItems()
        if not selected:
            return
        row = selected[0]
        if row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1) != "layer":
            row = row.parent()
        if row is None:
            return
        layer_id = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
        with self._canvas.history().transaction():
            changed = any(
                self._manager.assign_item(item, layer_id)
                for item in self._canvas.scene().selectedItems()
            )
            if changed:
                self._canvas.history().mark_dirty()
