"""Parametric diagram shape items."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from constants import DEFAULT_FILL, PEN_NORMAL, PEN_SELECTED
from ..base import ResizableItem, _should_draw_selection
from ..labels import ShapeLabelMixin


class DiagramItem(ShapeLabelMixin, ResizableItem, QtWidgets.QGraphicsPathItem):
    """A labelled, resizable diagram shape with serializable parameters."""

    def __init__(self, x: float, y: float, w: float, h: float, kind: str):
        QtWidgets.QGraphicsPathItem.__init__(self)
        ResizableItem.__init__(self)
        self.kind = kind
        self._w = w
        self._h = h
        self._rows = 3
        self._columns = 3
        self._lanes = 3
        self.setPos(x, y)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self._init_shape_label()
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)
        self._update_path()

    def _label_base_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(0.0, 0.0, self._w, self._h)

    def setPen(self, pen: QtGui.QPen | QtGui.QColor) -> None:  # type: ignore[override]
        super().setPen(pen)
        self._update_label_color()

    def set_size(self, w: float, h: float, adjust_origin: bool = True) -> None:
        self._w = max(1.0, w)
        self._h = max(1.0, h)
        self._update_path()
        if adjust_origin:
            self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)
        self._update_label_geometry()

    def set_table_dimensions(self, rows: int, columns: int) -> None:
        self._rows = max(1, int(rows))
        self._columns = max(1, int(columns))
        self._update_path()

    def set_swimlane_count(self, lanes: int) -> None:
        self._lanes = max(1, int(lanes))
        self._update_path()

    def parameters(self) -> dict[str, int]:
        if self.kind == "table":
            return {"rows": self._rows, "columns": self._columns}
        if self.kind == "swimlane":
            return {"lanes": self._lanes}
        return {}

    def apply_parameters(self, data: dict[str, object]) -> None:
        if self.kind == "table":
            self.set_table_dimensions(
                int(data.get("rows", self._rows)),
                int(data.get("columns", self._columns)),
            )
        elif self.kind == "swimlane":
            self.set_swimlane_count(int(data.get("lanes", self._lanes)))

    def _update_path(self) -> None:
        self.prepareGeometryChange()
        w, h = self._w, self._h
        path = QtGui.QPainterPath()
        if self.kind == "hexagon":
            inset = min(w * 0.25, h * 0.5)
            path.moveTo(inset, 0.0)
            path.lineTo(w - inset, 0.0)
            path.lineTo(w, h / 2.0)
            path.lineTo(w - inset, h)
            path.lineTo(inset, h)
            path.lineTo(0.0, h / 2.0)
            path.closeSubpath()
        elif self.kind == "parallelogram":
            inset = min(w * 0.2, h * 0.5)
            path.moveTo(inset, 0.0)
            path.lineTo(w, 0.0)
            path.lineTo(w - inset, h)
            path.lineTo(0.0, h)
            path.closeSubpath()
        elif self.kind in {"document", "multiple_document"}:

            def document_outline(offset: float) -> None:
                bottom = h - offset
                path.moveTo(offset, offset)
                path.lineTo(w - offset, offset)
                path.lineTo(w - offset, bottom)
                path.cubicTo(
                    w * 0.75,
                    bottom - h * 0.12,
                    w * 0.25,
                    bottom + h * 0.12,
                    offset,
                    bottom,
                )
                path.closeSubpath()

            if self.kind == "multiple_document":
                document_outline(min(12.0, w * 0.1, h * 0.1))
            document_outline(0.0)
        elif self.kind == "cloud":
            path.moveTo(w * 0.18, h * 0.78)
            path.cubicTo(-w * 0.06, h * 0.78, -w * 0.06, h * 0.48, w * 0.15, h * 0.47)
            path.cubicTo(w * 0.08, h * 0.12, w * 0.45, -h * 0.05, w * 0.53, h * 0.22)
            path.cubicTo(w * 0.82, -h * 0.03, w * 1.12, h * 0.25, w * 0.89, h * 0.48)
            path.cubicTo(w * 1.12, h * 0.75, w * 0.8, h * 0.98, w * 0.6, h * 0.78)
            path.closeSubpath()
        elif self.kind == "callout":
            body = QtCore.QRectF(0.0, 0.0, w, h * 0.78)
            path.addRoundedRect(body, min(16.0, h * 0.18), min(16.0, h * 0.18))
            path.moveTo(w * 0.3, body.bottom())
            path.lineTo(w * 0.2, h)
            path.lineTo(w * 0.48, body.bottom())
        elif self.kind == "database":
            ellipse_h = min(h * 0.28, 28.0)
            top = QtCore.QRectF(0.0, 0.0, w, ellipse_h)
            bottom = QtCore.QRectF(0.0, h - ellipse_h, w, ellipse_h)
            path.addEllipse(top)
            path.moveTo(0.0, ellipse_h / 2.0)
            path.lineTo(0.0, h - ellipse_h / 2.0)
            path.moveTo(w, ellipse_h / 2.0)
            path.lineTo(w, h - ellipse_h / 2.0)
            path.arcMoveTo(bottom, 180.0)
            path.arcTo(bottom, 180.0, -180.0)
        else:
            path.addRect(0.0, 0.0, w, h)
            if self.kind == "table":
                for row in range(1, self._rows):
                    y = h * row / self._rows
                    path.moveTo(0.0, y)
                    path.lineTo(w, y)
                for column in range(1, self._columns):
                    x = w * column / self._columns
                    path.moveTo(x, 0.0)
                    path.lineTo(x, h)
            elif self.kind == "swimlane":
                header = min(h * 0.2, 32.0)
                path.moveTo(0.0, header)
                path.lineTo(w, header)
                for lane in range(1, self._lanes):
                    x = w * lane / self._lanes
                    path.moveTo(x, header)
                    path.lineTo(x, h)
        self.setPath(path)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        if hasattr(self, "_label"):
            self._update_label_geometry()

    def mouseDoubleClickEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:  # type: ignore[override]
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_label_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paint(self, painter, option, widget=None):  # type: ignore[override]
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()


__all__ = ["DiagramItem"]
