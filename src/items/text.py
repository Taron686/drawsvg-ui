"""Text and grouping items."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .base import ResizableItem, ResizeHandle, RotationHandle, _should_draw_selection
from ..constants import PEN_SELECTED


class TextItem(ResizableItem, QtWidgets.QGraphicsTextItem):
    def __init__(self, x, y, w, h):
        QtWidgets.QGraphicsTextItem.__init__(self, "Text")
        ResizableItem.__init__(self)
        self.setPos(x, y)
        font = QtGui.QFont("Arial")
        font.setPointSizeF(24.0)
        self.setFont(font)
        self.setDefaultTextColor(QtGui.QColor("#222"))
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable,
        )
        br = self.boundingRect()
        self.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)

    def setPlainText(self, text: str) -> None:  # type: ignore[override]
        super().setPlainText(text)
        br = self.boundingRect()
        self.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
        if _should_draw_selection(self):
            self.update_handles()

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus()
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self.setPlainText(self.toPlainText())


class GroupItem(ResizableItem, QtWidgets.QGraphicsItemGroup):
    """Group of multiple items with shared handles."""

    def __init__(self):
        QtWidgets.QGraphicsItemGroup.__init__(self)
        ResizableItem.__init__(self)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setData(0, "Group")
        self.setHandlesChildEvents(False)

    def _handle_rect(self) -> QtCore.QRectF:  # type: ignore[override]
        tight = self._contentRect()
        if not tight.isNull():
            return tight
        return QtWidgets.QGraphicsItemGroup.boundingRect(self)

    def _contentRect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF()
        first = True
        for child in self.childItems():
            if isinstance(child, (ResizeHandle, RotationHandle)):
                continue
            child_rect = child.mapToParent(child.boundingRect()).boundingRect()
            rect = child_rect if first else rect.united(child_rect)
            first = False
        return rect if not first else QtCore.QRectF()

    def update_handles(self):  # type: ignore[override]
        rect = self._handle_rect()
        if not rect.isNull():
            self.setTransformOriginPoint(rect.center())
        else:
            self.setTransformOriginPoint(QtCore.QPointF())
        super().update_handles()

    def paint(self, painter, option, widget=None):
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            tight = self._contentRect()
            if not tight.isNull():
                half = PEN_SELECTED.widthF() * 0.5
                painter.drawRect(tight.adjusted(half, half, -half, -half))
            else:
                painter.drawRect(self.boundingRect())
            painter.restore()


__all__ = ["GroupItem", "TextItem"]
