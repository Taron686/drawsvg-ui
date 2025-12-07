# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Interactive folder tree widget item."""

from __future__ import annotations

from typing import Any, Mapping

from PySide6 import QtCore, QtGui, QtWidgets

from constants import PEN_SELECTED, DEFAULT_FONT_FAMILY
from ..base import HandleAwareItemMixin, _should_draw_selection


class FolderTreeNode:
    __slots__ = ("name", "is_folder", "children", "parent")

    def __init__(
        self,
        name: str,
        is_folder: bool = True,
        parent: "FolderTreeNode | None" = None,
    ) -> None:
        self.name = name
        self.is_folder = is_folder
        self.parent = parent
        self.children: list["FolderTreeNode"] = []

    def add_child(self, child: "FolderTreeNode") -> "FolderTreeNode":
        child.parent = self
        self.children.append(child)
        return child

    def remove_child(self, child: "FolderTreeNode") -> None:
        try:
            self.children.remove(child)
            child.parent = None
        except ValueError:
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "folder": self.is_folder,
            "children": [child.to_dict() for child in self.children],
        }

    @staticmethod
    def from_dict(
        data: Mapping[str, Any],
        parent: "FolderTreeNode | None" = None,
    ) -> "FolderTreeNode":
        name = str(data.get("name", "node"))
        is_folder = bool(data.get("folder", True))
        node = FolderTreeNode(name, is_folder, parent)
        for child_data in data.get("children", []):
            if isinstance(child_data, Mapping):
                node.add_child(FolderTreeNode.from_dict(child_data, node))
        return node


class FolderTreeBranchDot(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, tree: "FolderTreeItem", node: FolderTreeNode, radius: float):
        super().__init__(-radius, -radius, radius * 2.0, radius * 2.0, tree)
        self._tree = tree
        self._node = node
        self.setBrush(QtGui.QColor("#f28c28"))
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(
            QtCore.Qt.MouseButton.LeftButton | QtCore.Qt.MouseButton.RightButton
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
            True,
        )
        self.setZValue(1.0)

    def node(self) -> FolderTreeNode:
        return self._node

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() in (
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.RightButton,
        ):
            self._tree.open_branch_menu(self._node, event.screenPos())
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QtWidgets.QGraphicsSceneContextMenuEvent) -> None:
        self._tree.open_branch_menu(self._node, event.screenPos())
        event.accept()


class FolderTreeItem(HandleAwareItemMixin, QtWidgets.QGraphicsItem):
    LINE_COLOR = QtGui.QColor("#7a7a7a")
    FOLDER_COLOR = QtGui.QColor("#000000")
    FILE_COLOR = QtGui.QColor("#000000")
    TEXT_COLOR = QtGui.QColor("#000000")

    def __init__(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        structure: Mapping[str, Any] | None = None,
    ) -> None:
        QtWidgets.QGraphicsItem.__init__(self)
        self.setPos(x, y)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)

        self._padding = 18.0
        self._indent = 54.0
        self._line_height = 28.0
        self._dot_radius = 6.0
        self._text_gap = 10.0
        self._font = QtGui.QFont(DEFAULT_FONT_FAMILY, 11)

        self._line_pen = QtGui.QPen(self.LINE_COLOR, 1.6)
        self._line_pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        self._folder_pen = QtGui.QPen(self.FOLDER_COLOR)
        self._file_pen = QtGui.QPen(self.FILE_COLOR)

        if structure:
            self._root = FolderTreeNode.from_dict(structure)
        else:
            self._root = self._build_default_structure()

        self._node_info: dict[FolderTreeNode, dict[str, Any]] = {}
        self._order: list[FolderTreeNode] = []
        self._bounding_rect = QtCore.QRectF()
        self._dot_items: dict[FolderTreeNode, FolderTreeBranchDot] = {}

        self._rebuild_layout()
        self.setTransformOriginPoint(self.boundingRect().center())

    def update_handles(self) -> None:
        """Folder trees do not expose resize handles."""

        return

    def show_handles(self):
        return

    def hide_handles(self):
        return

    def boundingRect(self) -> QtCore.QRectF:  # type: ignore[override]
        return QtCore.QRectF(self._bounding_rect)

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()

        painter.setPen(self._line_pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        for node in self._order:
            parent = node.parent
            if parent is None:
                continue
            info = self._node_info[node]
            parent_info = self._node_info[parent]
            parent_center: QtCore.QPointF = parent_info["dot_center"]
            child_center: QtCore.QPointF = info["dot_center"]
            offset = self._dot_radius - 1.0
            start = QtCore.QPointF(parent_center.x(), parent_center.y() + offset)
            end = QtCore.QPointF(parent_center.x(), child_center.y())
            painter.drawLine(start, end)
            start_horizontal = QtCore.QPointF(parent_center.x(), child_center.y())
            end_horizontal = QtCore.QPointF(
                child_center.x() - (self._dot_radius - 1.0), child_center.y()
            )
            painter.drawLine(start_horizontal, end_horizontal)

        painter.setFont(self._font)
        for node in self._order:
            info = self._node_info[node]
            text_rect: QtCore.QRectF = info["text_rect"]
            label = self._node_label(node)
            painter.setPen(self._folder_pen if node.is_folder else self._file_pen)
            painter.drawText(
                text_rect,
                QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
                label,
            )

    def _node_label(self, node: FolderTreeNode) -> str:
        return f"{node.name}/" if node.is_folder else node.name

    def _build_default_structure(self) -> FolderTreeNode:
        root = FolderTreeNode("projekt", True)
        docs = root.add_child(FolderTreeNode("docs", True))
        api = docs.add_child(FolderTreeNode("api", True))
        api.add_child(FolderTreeNode("index.md", False))
        src = root.add_child(FolderTreeNode("src", True))
        src.add_child(FolderTreeNode("app", True))
        src.add_child(FolderTreeNode("main.py", False))
        tests = root.add_child(FolderTreeNode("tests", True))
        tests.add_child(FolderTreeNode("test_main.py", False))
        return root

    def _rebuild_layout(self) -> None:
        fm = QtGui.QFontMetricsF(self._font)
        self._line_height = max(self._line_height, fm.height() + 8.0)

        self._node_info.clear()
        self._order.clear()

        def traverse(node: FolderTreeNode, depth: int) -> None:
            info = {"depth": depth, "row": len(self._order)}
            self._node_info[node] = info
            self._order.append(node)
            for child in node.children:
                traverse(child, depth + 1)

        traverse(self._root, 0)

        max_text_right = self._padding
        for node in self._order:
            info = self._node_info[node]
            depth = info["depth"]
            row = info["row"]
            y = self._padding + row * self._line_height
            x = self._padding + depth * self._indent
            text_x = x + self._dot_radius + self._text_gap
            label = self._node_label(node)
            text_width = fm.horizontalAdvance(label)
            max_text_right = max(max_text_right, text_x + text_width)
            info["dot_center"] = QtCore.QPointF(x, y + self._line_height / 2.0)
            info["text_x"] = text_x
            info["y"] = y

        width = max_text_right + self._padding
        min_width = self._padding * 2.0 + self._indent
        width = max(width, min_width)
        height = self._padding * 2.0 + max(1, len(self._order)) * self._line_height

        self.prepareGeometryChange()
        self._bounding_rect = QtCore.QRectF(0.0, 0.0, width, height)

        for node in self._order:
            info = self._node_info[node]
            text_rect = QtCore.QRectF(
                info["text_x"],
                info["y"],
                width - info["text_x"] - self._padding,
                self._line_height,
            )
            info["text_rect"] = text_rect

        self._update_branch_dots()
        self.setTransformOriginPoint(self._bounding_rect.center())
        self.update()

    def _update_branch_dots(self) -> None:
        current_nodes = set(self._order)
        for node in list(self._dot_items.keys()):
            if node not in current_nodes:
                dot = self._dot_items.pop(node)
                dot.setParentItem(None)
                if dot.scene() is not None:
                    dot.scene().removeItem(dot)
        for node in self._order:
            info = self._node_info[node]
            dot = self._dot_items.get(node)
            if dot is None:
                dot = FolderTreeBranchDot(self, node, self._dot_radius)
                self._dot_items[node] = dot
            dot.setPos(info["dot_center"])

    def open_branch_menu(
        self,
        node: FolderTreeNode,
        global_pos: QtCore.QPointF | QtCore.QPoint,
    ) -> None:
        menu = QtWidgets.QMenu()
        add_folder_action = None
        add_file_action = None
        delete_action = None

        if node.is_folder:
            add_folder_action = menu.addAction("Add Folder")
            add_file_action = menu.addAction("Add File")
        if node.parent is not None:
            if menu.actions():
                menu.addSeparator()
            delete_action = menu.addAction("Remove Entry")

        if isinstance(global_pos, QtCore.QPointF):
            global_point = QtCore.QPoint(round(global_pos.x()), round(global_pos.y()))
        else:
            global_point = global_pos

        selected = menu.exec(global_point)
        if not selected:
            return
        if selected is add_folder_action:
            self._create_child(node, True)
        elif selected is add_file_action:
            self._create_child(node, False)
        elif selected is delete_action:
            self._delete_node(node)

    def _view_widget(self) -> QtWidgets.QWidget | None:
        scene = self.scene()
        if scene and scene.views():
            return scene.views()[0]
        return None

    def _prompt_name(
        self,
        title: str,
        label: str,
        default: str = "",
    ) -> str | None:
        parent = self._view_widget()
        text, ok = QtWidgets.QInputDialog.getText(
            parent,
            title,
            label,
            QtWidgets.QLineEdit.EchoMode.Normal,
            default,
        )
        if not ok:
            return None
        name = text.strip()
        return name or None

    def _create_child(self, parent: FolderTreeNode, is_folder: bool) -> None:
        title = "Add Folder" if is_folder else "Add File"
        prompt = "Folder name:" if is_folder else "File name:"
        name = self._prompt_name(title, prompt)
        if not name:
            return
        parent.add_child(FolderTreeNode(name, is_folder))
        self._rebuild_layout()

    def _delete_node(self, node: FolderTreeNode) -> None:
        if node.parent is None:
            return
        parent_widget = self._view_widget()
        reply = QtWidgets.QMessageBox.question(
            parent_widget,
            "Remove Entry",
            f"Remove '{self._node_label(node)}'?",
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        node.parent.remove_child(node)
        self._rebuild_layout()

    def _rename_node(self, node: FolderTreeNode) -> None:
        current = node.name
        title = "Rename Entry"
        prompt = "New name:"
        name = self._prompt_name(title, prompt, current)
        if not name or name == current:
            return
        node.name = name
        self._rebuild_layout()

    def structure(self) -> dict[str, Any]:
        return self._root.to_dict()

    def set_structure(self, structure: Mapping[str, Any]) -> None:
        self._root = FolderTreeNode.from_dict(structure)
        self._rebuild_layout()

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        super().mousePressEvent(event)
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return

        local_pos = event.pos()
        for node in self._order:
            if self._node_info[node]["text_rect"].contains(local_pos):
                event.accept()
                return

    def mouseDoubleClickEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        local_pos = event.pos()
        for node in self._order:
            text_rect: QtCore.QRectF = self._node_info[node]["text_rect"]
            if text_rect.contains(local_pos):
                self._rename_node(node)
                event.accept()
                return

        super().mouseDoubleClickEvent(event)


__all__ = ["FolderTreeBranchDot", "FolderTreeItem", "FolderTreeNode"]
