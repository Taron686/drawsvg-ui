# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Polygon-based shape items."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from constants import DEFAULT_FILL, PEN_NORMAL, PEN_SELECTED
from ..base import (
    DIVIDER_HANDLE_COLOR,
    DIVIDER_HANDLE_DIAMETER,
    ResizableItem,
    _should_draw_selection,
    snap_to_grid,
)
from ..labels import ShapeLabelMixin


class TriangleItem(ResizableItem, QtWidgets.QGraphicsPolygonItem):
    def __init__(self, x, y, w, h):
        QtWidgets.QGraphicsPolygonItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = w
        self._h = h
        self._update_polygon()
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

    def _update_polygon(self):
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(self._w / 2.0, 0.0),
                QtCore.QPointF(0.0, self._h),
                QtCore.QPointF(self._w, self._h),
            ]
        )
        self.setPolygon(poly)

    def set_size(self, w, h, adjust_origin: bool = True):
        self._w = w
        self._h = h
        self._update_polygon()
        if adjust_origin:
            self.setTransformOriginPoint(w / 2.0, h / 2.0)

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


class DiamondItem(ShapeLabelMixin, ResizableItem, QtWidgets.QGraphicsPolygonItem):
    def __init__(self, x: float, y: float, w: float, h: float):
        QtWidgets.QGraphicsPolygonItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = w
        self._h = h
        self._update_polygon()
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self._init_shape_label()
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

    def _label_base_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.boundingRect())

    def _update_polygon(self) -> None:
        half_w = self._w / 2.0
        half_h = self._h / 2.0
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(half_w, 0.0),
                QtCore.QPointF(self._w, half_h),
                QtCore.QPointF(half_w, self._h),
                QtCore.QPointF(0.0, half_h),
            ]
        )
        self.setPolygon(poly)
        if hasattr(self, "_label"):
            self._update_label_geometry()

    def set_size(self, w: float, h: float, adjust_origin: bool = True) -> None:
        self._w = w
        self._h = h
        self._update_polygon()
        if adjust_origin:
            self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self._update_label_geometry()

    def setPen(self, pen: QtGui.QPen | QtGui.QColor) -> None:  # type: ignore[override]
        super().setPen(pen)
        self._update_label_color()

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

    def mouseDoubleClickEvent(
        self, event: QtWidgets.QGraphicsSceneMouseEvent
    ) -> None:  # type: ignore[override]
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_label_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class BlockArrowHandle(QtWidgets.QGraphicsEllipseItem):
    """Special orange handles for :class:`BlockArrowItem`."""

    def __init__(self, parent: "BlockArrowItem", role: str):
        radius = DIVIDER_HANDLE_DIAMETER / 2.0
        super().__init__(
            -radius,
            -radius,
            DIVIDER_HANDLE_DIAMETER,
            DIVIDER_HANDLE_DIAMETER,
            parent,
        )
        self._role = role
        self.setBrush(DIVIDER_HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        if role == "head":
            self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
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
        parent: "BlockArrowItem" = self.parentItem()  # type: ignore[assignment]
        if parent is not None:
            parent._handle_special_drag(self._role, event)
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


class BlockArrowItem(ResizableItem, QtWidgets.QGraphicsPolygonItem):
    def __init__(self, x: float, y: float, w: float, h: float):
        QtWidgets.QGraphicsPolygonItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = w
        self._h = h
        self._head_ratio = 0.35
        self._shaft_ratio = 0.35
        self._head_handle: BlockArrowHandle | None = None
        self._body_handle: BlockArrowHandle | None = None
        self._update_polygon()
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

    def _clamp_head_ratio(self, ratio: float) -> float:
        return max(0.05, min(0.8, ratio))

    def _clamp_shaft_ratio(self, ratio: float) -> float:
        return max(0.1, min(0.9, ratio))

    def head_ratio(self) -> float:
        return self._head_ratio

    def set_head_ratio(self, ratio: float) -> None:
        self._head_ratio = self._clamp_head_ratio(ratio)
        self._update_polygon()

    def shaft_ratio(self) -> float:
        return self._shaft_ratio

    def set_shaft_ratio(self, ratio: float) -> None:
        self._shaft_ratio = self._clamp_shaft_ratio(ratio)
        self._update_polygon()

    def _head_width(self) -> float:
        return self._w * self._clamp_head_ratio(self._head_ratio)

    def _shaft_bounds(self) -> tuple[float, float]:
        shaft_h = self._h * self._clamp_shaft_ratio(self._shaft_ratio)
        top = (self._h - shaft_h) / 2.0
        return top, top + shaft_h

    def _update_polygon(self) -> None:
        self.prepareGeometryChange()
        w = self._w
        h = self._h
        head_w = self._head_width()
        shaft_top, shaft_bottom = self._shaft_bounds()
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(0.0, shaft_top),
                QtCore.QPointF(w - head_w, shaft_top),
                QtCore.QPointF(w - head_w, 0.0),
                QtCore.QPointF(w, h / 2.0),
                QtCore.QPointF(w - head_w, h),
                QtCore.QPointF(w - head_w, shaft_bottom),
                QtCore.QPointF(0.0, shaft_bottom),
            ]
        )
        self.setPolygon(poly)
        self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)
        self._update_custom_handles()

    def _update_custom_handles(self) -> None:
        if not (self._head_handle and self._body_handle):
            return
        head_w = self._head_width()
        shaft_top, shaft_bottom = self._shaft_bounds()
        tail_width = self._w - head_w
        margin = DIVIDER_HANDLE_DIAMETER / 2.0
        head_pos = QtCore.QPointF(self._w - head_w, shaft_top - margin)
        body_pos = QtCore.QPointF(max(0.0, tail_width / 2.0), shaft_bottom + margin)
        self._head_handle.setPos(head_pos)
        self._body_handle.setPos(body_pos)

    def _handle_special_drag(self, role: str, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        scene_pos = event.scenePos()
        if not (event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier):
            scene_pos = snap_to_grid(self, scene_pos)
        local = self.mapFromScene(scene_pos)
        if role == "head":
            self._apply_head_drag(local.x())
        else:
            self._apply_body_drag(local.y())

    def _apply_head_drag(self, local_x: float) -> None:
        w = self._w
        if w <= 0:
            return
        min_tail = max(8.0, min(w - 8.0, w * 0.1))
        min_head = max(8.0, w * 0.1)
        max_x = max(min_tail, w - min_head)
        min_x = min_tail
        if max_x < min_x:
            min_x = max_x = w / 2.0
        clamped_x = max(min_x, min(local_x, max_x))
        ratio = (w - clamped_x) / w
        self.set_head_ratio(ratio)

    def _apply_body_drag(self, local_y: float) -> None:
        h = self._h
        if h <= 0:
            return
        center = h / 2.0
        min_shaft = max(8.0, h * 0.15)
        min_bottom = center + min_shaft / 2.0
        clamped_y = max(min_bottom, min(local_y, h))
        shaft_height = (clamped_y - center) * 2.0
        ratio = shaft_height / h
        self.set_shaft_ratio(ratio)

    def update_handles(self):  # type: ignore[override]
        super().update_handles()
        if self._handles:
            tip: QtCore.QPointF | None = None
            poly = self.polygon()
            if len(poly) >= 4:
                tip = QtCore.QPointF(poly[3])
            else:
                tip = QtCore.QPointF(self._w, self._h / 2.0)
            for handle in self._handles:
                if getattr(handle, "_direction", None) == "right":
                    handle.setPos(tip)
                    break
        self._update_custom_handles()

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

    def show_handles_once(self):
        if not self._head_handle:
            self._head_handle = BlockArrowHandle(self, "head")
            self._head_handle.setZValue(1.0)
        if not self._body_handle:
            self._body_handle = BlockArrowHandle(self, "body")
            self._body_handle.setZValue(1.0)
        self._update_custom_handles()

    def show_handles(self):  # type: ignore[override]
        self.show_handles_once()
        super().show_handles()
        if self._head_handle:
            self._head_handle.show()
        if self._body_handle:
            self._body_handle.show()

    def hide_handles(self):  # type: ignore[override]
        super().hide_handles()
        if self._head_handle:
            self._head_handle.hide()
        if self._body_handle:
            self._body_handle.hide()


__all__ = ["BlockArrowHandle", "BlockArrowItem", "DiamondItem", "TriangleItem"]
