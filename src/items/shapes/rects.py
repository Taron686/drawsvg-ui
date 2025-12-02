"""Rectangular shapes and related handles."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from constants import DEFAULT_FILL, PEN_NORMAL, PEN_SELECTED
from ..base import (
    DIVIDER_HANDLE_COLOR,
    DIVIDER_HANDLE_DIAMETER,
    ResizableItem,
    _should_draw_selection,
)
from ..labels import ShapeLabelMixin


class SplitDividerHandle(QtWidgets.QGraphicsEllipseItem):
    """Drag handle for the horizontal split in :class:`SplitRoundedRectItem`."""

    def __init__(self, parent: "SplitRoundedRectItem"):
        radius = DIVIDER_HANDLE_DIAMETER / 2.0
        super().__init__(
            -radius,
            -radius,
            DIVIDER_HANDLE_DIAMETER,
            DIVIDER_HANDLE_DIAMETER,
            parent,
        )
        self.setBrush(DIVIDER_HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._parent_was_movable = False

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None:
            flags = parent.flags()
            self._parent_was_movable = bool(
                flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            )
            if self._parent_was_movable:
                parent.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                    False,
                )
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None:
            parent._set_divider_from_scene_pos(event.scenePos())  # type: ignore[attr-defined]
        event.accept()

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None and self._parent_was_movable:
            parent.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                True,
            )
        self._parent_was_movable = False
        event.accept()


class RectItem(ShapeLabelMixin, ResizableItem, QtWidgets.QGraphicsRectItem):
    def __init__(self, x, y, w, h, rx: float = 0.0, ry: float = 0.0):
        QtWidgets.QGraphicsRectItem.__init__(self, 0, 0, w, h)
        ResizableItem.__init__(self)
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.rx = rx
        self.ry = ry
        self._init_shape_label()
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

    def _label_base_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.rect())

    def setRect(self, x: float, y: float, w: float, h: float) -> None:  # type: ignore[override]
        QtWidgets.QGraphicsRectItem.setRect(self, x, y, w, h)
        self._update_label_geometry()

    def setPen(self, pen):  # type: ignore[override]
        super().setPen(pen)
        self._update_label_color()

    def mouseDoubleClickEvent(
        self, event: QtWidgets.QGraphicsSceneMouseEvent
    ) -> None:  # type: ignore[override]
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_label_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        if self.rx or self.ry:
            painter.setPen(self.pen())
            painter.setBrush(self.brush())
            painter.drawRoundedRect(self.rect(), self.rx, self.ry)
        else:
            super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()


class SplitRoundedRectItem(ResizableItem, QtWidgets.QGraphicsRectItem):
    def __init__(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        rx: float = 15.0,
        ry: float | None = None,
    ):
        QtWidgets.QGraphicsRectItem.__init__(self, 0, 0, w, h)
        ResizableItem.__init__(self)
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )

        self.rx = rx
        self.ry = ry if ry is not None else rx
        self._split_ratio = 1.0 / 3.0
        self._top_brush = QtGui.QBrush(QtGui.QColor("#f6e3b0"))
        self._bottom_brush = QtGui.QBrush(DEFAULT_FILL)
        self._divider_pen = QtGui.QPen(QtGui.QColor("#777"), 1.5)
        self._divider_pen.setCosmetic(True)

        self.setPen(PEN_NORMAL)

        self._divider_handle = SplitDividerHandle(self)
        self._divider_handle.setZValue(1.0)
        self._divider_handle.hide()
        self._update_divider_handle()

    def _handle_margin(self) -> float:
        bounds = self._divider_handle.boundingRect()
        return max(bounds.width(), bounds.height()) / 2.0

    def _line_y(self) -> float:
        rect = self.rect()
        return rect.top() + rect.height() * self._split_ratio

    def divider_ratio(self) -> float:
        return self._split_ratio

    def set_divider_ratio(self, ratio: float) -> None:
        rect = self.rect()
        if rect.height() <= 0:
            self._split_ratio = 0.5
        else:
            clamped = max(0.0, min(1.0, ratio))
            target = rect.top() + rect.height() * clamped
            self.set_divider_y(target)

    def set_divider_y(self, y: float) -> None:
        rect = self.rect()
        if rect.height() <= 0:
            self._split_ratio = 0.5
        else:
            margin = self._handle_margin()
            min_y = rect.top() + margin
            max_y = rect.bottom() - margin
            if max_y < min_y:
                y = rect.center().y()
            else:
                y = min(max(y, min_y), max_y)
            self._split_ratio = (y - rect.top()) / rect.height()
        self.update()
        self._update_divider_handle()

    def _update_divider_handle(self) -> None:
        rect = self.rect()
        self._divider_handle.setPos(rect.center().x(), self._line_y())

    def _set_divider_from_scene_pos(self, scene_pos: QtCore.QPointF) -> None:
        local = self.mapFromScene(scene_pos)
        self.set_divider_y(local.y())

    def topBrush(self) -> QtGui.QBrush:
        return QtGui.QBrush(self._top_brush)

    def setTopBrush(self, brush: QtGui.QBrush | QtGui.QColor) -> None:
        self._top_brush = QtGui.QBrush(brush)
        self.update()

    def bottomBrush(self) -> QtGui.QBrush:
        return QtGui.QBrush(self._bottom_brush)

    def setBottomBrush(self, brush: QtGui.QBrush | QtGui.QColor) -> None:
        self._bottom_brush = QtGui.QBrush(brush)
        self.update()

    def brush(self) -> QtGui.QBrush:  # type: ignore[override]
        return self.bottomBrush()

    def setBrush(self, brush: QtGui.QBrush | QtGui.QColor) -> None:  # type: ignore[override]
        self.setBottomBrush(brush)

    def setPen(self, pen: QtGui.QPen | QtGui.QColor) -> None:  # type: ignore[override]
        qpen = QtGui.QPen(pen)
        QtWidgets.QGraphicsRectItem.setPen(self, qpen)
        divider_width = max(1.0, qpen.widthF() * 0.75)
        self._divider_pen = QtGui.QPen(qpen.color(), divider_width)
        self._divider_pen.setCosmetic(True)
        self.update()

    def show_handles(self):  # type: ignore[override]
        super().show_handles()
        self._divider_handle.show()
        self._update_divider_handle()

    def hide_handles(self):  # type: ignore[override]
        super().hide_handles()
        self._divider_handle.hide()

    def update_handles(self):  # type: ignore[override]
        super().update_handles()
        self._update_divider_handle()

    def setRect(self, x: float, y: float, w: float, h: float) -> None:  # type: ignore[override]
        QtWidgets.QGraphicsRectItem.setRect(self, x, y, w, h)
        self._update_divider_handle()

    def paint(self, painter, option, widget=None):  # type: ignore[override]
        rect = self.rect()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rx = max(0.0, min(self.rx, rect.width() / 2.0, 50.0))
        ry = max(0.0, min(self.ry, rect.height() / 2.0, 50.0))

        base_path = QtGui.QPainterPath()
        if rx > 0.0 or ry > 0.0:
            base_path.addRoundedRect(rect, rx, ry)
        else:
            base_path.addRect(rect)

        line_y = self._line_y()

        top_clip = QtGui.QPainterPath()
        top_clip.addRect(rect.left(), rect.top(), rect.width(), max(0.0, line_y - rect.top()))
        top_path = base_path.intersected(top_clip)
        if not top_path.isEmpty():
            painter.fillPath(top_path, self._top_brush)

        bottom_clip = QtGui.QPainterPath()
        bottom_clip.addRect(
            rect.left(),
            line_y,
            rect.width(),
            max(0.0, rect.bottom() - line_y),
        )
        bottom_path = base_path.intersected(bottom_clip)
        if not bottom_path.isEmpty():
            painter.fillPath(bottom_path, self._bottom_brush)

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen())
        if rx > 0.0 or ry > 0.0:
            painter.drawRoundedRect(rect, rx, ry)
        else:
            painter.drawRect(rect)

        painter.setPen(self._divider_pen)
        painter.drawLine(rect.left(), line_y, rect.right(), line_y)
        painter.restore()

        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()

    def shape(self) -> QtGui.QPainterPath:  # type: ignore[override]
        rect = self.rect()
        path = QtGui.QPainterPath()
        rx = max(0.0, min(self.rx, rect.width() / 2.0, 50.0))
        ry = max(0.0, min(self.ry, rect.height() / 2.0, 50.0))
        if rx > 0.0 or ry > 0.0:
            path.addRoundedRect(rect, rx, ry)
        else:
            path.addRect(rect)
        return path


__all__ = ["RectItem", "SplitDividerHandle", "SplitRoundedRectItem"]
