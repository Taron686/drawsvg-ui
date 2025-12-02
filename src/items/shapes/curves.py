"""Curved shapes such as ellipses and curly brackets."""

from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets

from constants import DEFAULT_FILL, PEN_NORMAL, PEN_SELECTED
from ..base import ResizableItem, _should_draw_selection, build_curvy_bracket_path
from ..labels import ShapeLabelMixin


class EllipseItem(ShapeLabelMixin, ResizableItem, QtWidgets.QGraphicsEllipseItem):
    def __init__(self, x, y, w, h):
        QtWidgets.QGraphicsEllipseItem.__init__(self, 0, 0, w, h)
        ResizableItem.__init__(self)
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
        return QtCore.QRectF(self.rect())

    def setRect(self, x: float, y: float, w: float, h: float) -> None:  # type: ignore[override]
        QtWidgets.QGraphicsEllipseItem.setRect(self, x, y, w, h)
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
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()


class CurvyBracketItem(ResizableItem, QtWidgets.QGraphicsPathItem):
    """Resizable right-facing curly bracket."""

    DEFAULT_HOOK_RATIO = 0.3

    def __init__(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        hook_ratio: float | None = None,
    ) -> None:
        QtWidgets.QGraphicsPathItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = max(8.0, float(w))
        self._h = max(40.0, float(h))
        if hook_ratio is None:
            hook_ratio = self.DEFAULT_HOOK_RATIO
        self._hook_ratio = self._clamp_ratio(float(hook_ratio))
        self._update_path()
        self.setPos(x, y)
        self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    def width(self) -> float:
        return self._w

    def height(self) -> float:
        return self._h

    def hook_ratio(self) -> float:
        return self._hook_ratio

    def set_hook_ratio(self, ratio: float) -> None:
        clamped = self._clamp_ratio(ratio)
        if not math.isclose(clamped, self._hook_ratio, abs_tol=1e-4):
            self._hook_ratio = clamped
            self._update_path()

    def set_size(self, w: float, h: float, adjust_origin: bool = True) -> None:
        self._w = max(8.0, float(w))
        self._h = max(40.0, float(h))
        self._update_path()
        if adjust_origin:
            self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)

    def _clamp_ratio(self, ratio: float | None = None) -> float:
        value = self._hook_ratio if ratio is None else float(ratio)
        return max(0.08, min(0.45, value))

    def _update_path(self) -> None:
        self.prepareGeometryChange()
        hook = self._hook_ratio * self._h
        path = build_curvy_bracket_path(self._w, self._h, hook)
        self.setPath(path)
        self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)

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


__all__ = ["CurvyBracketItem", "EllipseItem"]
