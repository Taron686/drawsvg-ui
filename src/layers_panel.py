"""Layers and object-tree sidebar for the canvas."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from items import GroupItem
from layer_manager import Layer, LayerManager

_KIND_ROLE = QtCore.Qt.ItemDataRole.UserRole.value + 1
# kind, target (layer id or graphics item), label, visible, locked, child rows
_RowSpec = tuple[str, Any, str, bool, bool, list[Any]]


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
        self._tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.ActionsContextMenu)
        for label, callback in (
            ("Collapse all", self._tree.collapseAll),
            ("Expand all", self._tree.expandAll),
        ):
            action = QtGui.QAction(label, self._tree)
            action.triggered.connect(callback)
            self._tree.addAction(action)
        self._tree.header().setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.ActionsContextMenu
        )
        self._tree.header().addActions(self._tree.actions())

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

        controls = QtWidgets.QGridLayout()
        controls.addWidget(self._add, 0, 0)
        controls.addWidget(self._remove, 0, 1)
        controls.addWidget(self._rename, 1, 0)
        controls.addWidget(self._assign, 1, 1)
        controls.addWidget(self._up, 2, 0)
        controls.addWidget(self._down, 2, 1)
        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(1, 1)
        self._assignment_summary = QtWidgets.QLabel(self)
        self._assignment_summary.setWordWrap(True)
        self._assign.setToolTip(
            "Select objects, then click their target layer. "
            "The object selection is kept until you assign it."
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._tree)
        layout.addWidget(self._assignment_summary)
        layout.addLayout(controls)

        self._tree.currentItemChanged.connect(self._update_assignment_summary)
        self._manager.changed.connect(self.refresh)
        self._canvas.selectionSnapshotChanged.connect(self._sync_selection)
        self.refresh()

    def refresh(self) -> None:
        if self._syncing:
            return
        current = self._tree.currentItem()
        current_column = self._tree.currentColumn()
        selected_ids = {
            id(item)
            for item in self._canvas.scene().selectedItems()
            if self._canvas.is_serializable_item(item)
        }
        specs = [
            (
                "layer",
                layer.id,
                layer.name,
                layer.visible,
                layer.locked,
                [
                    self._object_spec(item, layer)
                    for item in reversed(self._manager.items_for_layer(layer.id))
                ],
            )
            for layer in self._manager.layers()
        ]
        self._syncing = True
        try:
            # Reconcile in place: rows that still match keep their scroll
            # position, expansion and selection, and nothing is rebuilt.
            self._sync_rows(self._tree.invisibleRootItem(), specs, selected_ids)
            if (
                current is not None
                and current.treeWidget() is self._tree
                and self._tree.currentItem() is not current
            ):
                self._tree.setCurrentItem(
                    current,
                    current_column,
                    QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                )
        finally:
            self._syncing = False
        self._update_assignment_summary()

    def _rows(self) -> Iterator[QtWidgets.QTreeWidgetItem]:
        iterator = QtWidgets.QTreeWidgetItemIterator(self._tree)
        while iterator.value() is not None:
            yield iterator.value()
            iterator += 1

    def _object_spec(self, item: QtWidgets.QGraphicsItem, layer: Layer) -> _RowSpec:
        children = (
            [
                self._object_spec(child, layer)
                for child in item.childItems()
                if not child.__class__.__name__.endswith("Handle")
            ]
            if isinstance(item, GroupItem)
            else []
        )
        return (
            "item",
            item,
            str(item.data(0) or item.__class__.__name__),
            layer.visible and self._manager.item_visible(item),
            layer.locked or self._manager.item_locked(item),
            children,
        )

    def _sync_rows(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        specs: list[_RowSpec],
        selected_ids: set[int],
    ) -> None:
        for index, (kind, target, text, visible, locked, children) in enumerate(specs):
            row = parent.child(index)
            created = False
            if row is None or not self._row_matches(row, kind, target):
                row = self._take_matching_row(parent, index + 1, kind, target)
                created = row is None
                if row is None:
                    row = self._new_row(kind, target)
                    parent.insertChild(index, row)
                else:
                    self._reinsert_row(parent, index, row)
            if row.text(0) != text:
                row.setText(0, text)
            for column, value in ((1, visible), (2, locked)):
                state = self._check_state(value)
                if row.checkState(column) != state:
                    row.setCheckState(column, state)
            if kind == "item" and row.isSelected() != (id(target) in selected_ids):
                row.setSelected(id(target) in selected_ids)
            self._sync_rows(row, children, selected_ids)
            if created and kind == "layer":
                row.setExpanded(True)
        while parent.childCount() > len(specs):
            parent.removeChild(parent.child(parent.childCount() - 1))

    @staticmethod
    def _row_matches(row: QtWidgets.QTreeWidgetItem, kind: str, target: object) -> bool:
        if row.data(0, _KIND_ROLE) != kind:
            return False
        current = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
        return current == target if kind == "layer" else current is target

    def _take_matching_row(
        self, parent: QtWidgets.QTreeWidgetItem, start: int, kind: str, target: object
    ) -> QtWidgets.QTreeWidgetItem | None:
        # ponytail: linear scan per mismatch, quadratic only when a whole layer
        # is reordered at once; index rows by target if that ever shows up.
        for index in range(start, parent.childCount()):
            row = parent.child(index)
            if self._row_matches(row, kind, target):
                return row
        return None

    @staticmethod
    def _reinsert_row(
        parent: QtWidgets.QTreeWidgetItem, index: int, row: QtWidgets.QTreeWidgetItem
    ) -> None:
        """Move a row; Qt forgets expansion and selection of detached rows."""
        subtree = [row]
        for entry in subtree:
            subtree.extend(entry.child(i) for i in range(entry.childCount()))
        state = [(entry, entry.isExpanded(), entry.isSelected()) for entry in subtree]
        parent.removeChild(row)
        parent.insertChild(index, row)
        for entry, expanded, selected in state:
            entry.setExpanded(expanded)
            entry.setSelected(selected)

    @staticmethod
    def _new_row(kind: str, target: object) -> QtWidgets.QTreeWidgetItem:
        row = QtWidgets.QTreeWidgetItem(["", "", ""])
        row.setData(0, QtCore.Qt.ItemDataRole.UserRole, target)
        row.setData(0, _KIND_ROLE, kind)
        row.setFlags(
            row.flags()
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        # Qt draws a checkbox only once the column holds a check state.
        row.setCheckState(1, QtCore.Qt.CheckState.Unchecked)
        row.setCheckState(2, QtCore.Qt.CheckState.Unchecked)
        if kind == "item":
            row.setToolTip(
                1, "A hidden layer hides all its objects. Show the layer first."
            )
            row.setToolTip(
                2, "A locked layer locks all its objects. Unlock the layer first."
            )
        return row

    @staticmethod
    def _check_state(value: bool) -> QtCore.Qt.CheckState:
        return QtCore.Qt.CheckState.Checked if value else QtCore.Qt.CheckState.Unchecked

    def _item_changed(self, row: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._syncing or column not in (1, 2):
            return
        kind = row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1)
        value = row.checkState(column) == QtCore.Qt.CheckState.Checked
        if kind == "item":
            layer_row = row
            while layer_row.parent() is not None:
                layer_row = layer_row.parent()
            overriding = (
                QtCore.Qt.CheckState.Unchecked
                if column == 1
                else QtCore.Qt.CheckState.Checked
            )
            if layer_row.checkState(column) == overriding:
                # A hidden or locked layer decides for its objects. Reject the
                # click instead of storing a flag that changes nothing visible.
                self._syncing = True
                try:
                    row.setCheckState(column, overriding)
                finally:
                    self._syncing = False
                return
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
        # Repaint the effective state even when the layer overrides an object
        # toggle and the object's stored flag was already at the requested value.
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
            # A layer row chooses the destination, not a new canvas selection.
            # Keep the source objects highlighted without rebuilding Qt's rows.
            selected_items = set(self._canvas.scene().selectedItems())
            with QtCore.QSignalBlocker(self._tree):
                for row in self._rows():
                    if row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1) == "item":
                        row.setSelected(
                            row.data(0, QtCore.Qt.ItemDataRole.UserRole)
                            in selected_items
                        )
            self._update_assignment_summary()
            return
        # Qt is still processing the click/key event. Do not rebuild its rows
        # from the synchronous scene-selection feedback while it does so.
        self._syncing = True
        try:
            self._canvas.scene().clearSelection()
            for item in items:
                if (
                    item.flags()
                    & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                ):
                    item.setSelected(True)
        finally:
            self._syncing = False
        self._update_assignment_summary()

    def _target_layer_row(self) -> QtWidgets.QTreeWidgetItem | None:
        row = self._tree.currentItem()
        while row is not None:
            if row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1) == "layer":
                return row
            row = row.parent()
        return None

    def _assignment_items(self) -> tuple[QtWidgets.QGraphicsItem, ...]:
        return tuple(
            item
            for item in self._canvas.scene().selectedItems()
            if item.parentItem() is None and self._canvas.is_serializable_item(item)
        )

    def _update_assignment_summary(self, *_args: object) -> None:
        if self._syncing:
            return
        items = self._assignment_items()
        row = self._target_layer_row()
        count = len(items)
        target = row.text(0) if row is not None else "Choose a layer"
        noun = "object" if count == 1 else "objects"
        self._assignment_summary.setText(f"{count} {noun} selected\nTarget: {target}")
        layer_id = (
            row.data(0, QtCore.Qt.ItemDataRole.UserRole) if row is not None else None
        )
        self._assign.setEnabled(
            layer_id is not None
            and any(self._manager.layer_for_item(item).id != layer_id for item in items)
        )

    def _sync_selection(self, _payload: dict[str, Any]) -> None:
        if not self._syncing:
            self.refresh()

    def _add_layer(self) -> None:
        with self._canvas.history().transaction():
            self._manager.add_layer()
            self._canvas.history().mark_dirty()

    def _remove_layer(self) -> None:
        row = self._target_layer_row()
        if row is None:
            return
        with self._canvas.history().transaction():
            if self._manager.remove_layer(row.data(0, QtCore.Qt.ItemDataRole.UserRole)):
                self._canvas.history().mark_dirty()

    def _rename_layer(self) -> None:
        row = self._target_layer_row()
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
        row = self._tree.currentItem()
        if row is None:
            return
        with self._canvas.history().transaction():
            kind = row.data(0, QtCore.Qt.ItemDataRole.UserRole.value + 1)
            target = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
            changed = (
                self._manager.move_layer(target, offset)
                if kind == "layer"
                # Object rows are shown in descending stacking order.
                else self._manager.move_item(target, -offset)
                if kind == "item"
                else False
            )
            if changed:
                self._canvas.history().mark_dirty()

    def _assign_selected(self) -> None:
        row = self._target_layer_row()
        if row is None:
            return
        layer_id = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
        items = self._assignment_items()
        self._syncing = True
        try:
            with self._canvas.history().transaction():
                changed = False
                for item in items:
                    changed = self._manager.assign_item(item, layer_id) or changed
                if changed:
                    self._canvas.history().mark_dirty()
        finally:
            self._syncing = False
        self.refresh()
