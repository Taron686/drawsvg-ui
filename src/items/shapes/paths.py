"""Editable free-form polyline, polygon and cubic Bezier path items."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from constants import PEN_NORMAL, PEN_SELECTED
from ..base import (
    HANDLE_COLOR,
    HANDLE_SIZE,
    HandleAwareItemMixin,
    _should_draw_selection,
    snap_to_grid,
)


def _point(value: Sequence[float] | QtCore.QPointF) -> QtCore.QPointF:
    if isinstance(value, QtCore.QPointF):
        return QtCore.QPointF(value)
    if len(value) != 2:
        raise ValueError("A path point must contain exactly two coordinates")
    return QtCore.QPointF(float(value[0]), float(value[1]))


class PathHandle(QtWidgets.QGraphicsEllipseItem):
    """A movable endpoint or Bezier control point belonging to a free path."""

    def __init__(self, parent: "FreePathItem", segment: int, role: str) -> None:
        super().__init__(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE, parent)
        self.segment = segment
        self.role = role
        self.setBrush(HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._parent_was_movable = False

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        parent: FreePathItem = self.parentItem()  # type: ignore[assignment]
        self._parent_was_movable = bool(
            parent.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        parent: FreePathItem = self.parentItem()  # type: ignore[assignment]
        point = event.scenePos()
        if not event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier:
            point = snap_to_grid(parent, point)
        parent.move_handle(self.segment, self.role, parent.mapFromScene(point))
        event.accept()

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        parent: FreePathItem = self.parentItem()  # type: ignore[assignment]
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._parent_was_movable = False
        event.accept()


class FreePathItem(HandleAwareItemMixin, QtWidgets.QGraphicsPathItem):
    """A path whose endpoints and cubic controls can be edited in-place.

    ``segments`` is deliberately JSON-shaped so the registry can store it without
    relying on Qt's opaque ``QPainterPath`` element representation.
    """

    def __init__(
        self,
        x: float,
        y: float,
        width: float = 150.0,
        height: float = 100.0,
        *,
        closed: bool = False,
        segments: Iterable[Mapping[str, Any]] | None = None,
        start: Sequence[float] | QtCore.QPointF | None = None,
        path_kind: str = "polyline",
    ) -> None:
        super().__init__()
        self.setPos(float(x), float(y))
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(QtGui.QPen(PEN_NORMAL))
        self.setBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
        self.path_kind = path_kind
        self.closed = bool(closed)
        self._start = _point(start or (0.0, 0.0))
        self._segments = self._normalise_segments(
            segments
            if segments is not None
            else [{"kind": "line", "end": [float(width), float(height)]}]
        )
        self._handles: list[PathHandle] = []
        self._update_path()
        self.update_handles()
        self.hide_handles()

    @staticmethod
    def _normalise_segments(
        segments: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in segments:
            kind = str(raw.get("kind", "line"))
            if kind not in {"line", "cubic"}:
                raise ValueError(f"Unsupported path segment kind: {kind}")
            end = _point(raw.get("end", (0.0, 0.0)))
            segment: dict[str, Any] = {"kind": kind, "end": end}
            if kind == "cubic":
                segment["control1"] = _point(raw.get("control1", end))
                segment["control2"] = _point(raw.get("control2", end))
            result.append(segment)
        if not result:
            raise ValueError("A free path requires at least one segment")
        return result

    def _update_path(self) -> None:
        path = QtGui.QPainterPath(self._start)
        for segment in self._segments:
            end: QtCore.QPointF = segment["end"]
            if segment["kind"] == "cubic":
                path.cubicTo(segment["control1"], segment["control2"], end)
            else:
                path.lineTo(end)
        if self.closed:
            path.closeSubpath()
        self.setPath(path)
        self.setTransformOriginPoint(path.boundingRect().center())
        self.update()

    def path_payload(self) -> dict[str, Any]:
        def data(point: QtCore.QPointF) -> list[float]:
            return [float(point.x()), float(point.y())]

        segments: list[dict[str, Any]] = []
        for segment in self._segments:
            entry = {"kind": segment["kind"], "end": data(segment["end"])}
            if segment["kind"] == "cubic":
                entry["control1"] = data(segment["control1"])
                entry["control2"] = data(segment["control2"])
            segments.append(entry)
        return {"start": data(self._start), "segments": segments, "closed": self.closed}

    def move_handle(self, segment: int, role: str, point: QtCore.QPointF) -> None:
        if segment == -1 and role == "start":
            self._start = QtCore.QPointF(point)
        else:
            current = self._segments[segment]
            if role not in current:
                raise ValueError(f"Path segment has no {role} handle")
            current[role] = QtCore.QPointF(point)
        self.prepareGeometryChange()
        self._update_path()
        self.update_handles()

    def _handle_specs(self) -> list[tuple[int, str, QtCore.QPointF]]:
        result = [(-1, "start", self._start)]
        for index, segment in enumerate(self._segments):
            result.append((index, "end", segment["end"]))
            if segment["kind"] == "cubic":
                result.append((index, "control1", segment["control1"]))
                result.append((index, "control2", segment["control2"]))
        return result

    def update_handles(self) -> None:
        specs = self._handle_specs()
        while len(self._handles) < len(specs):
            self._handles.append(PathHandle(self, -1, "start"))
        while len(self._handles) > len(specs):
            handle = self._handles.pop()
            handle.setParentItem(None)
        for handle, (segment, role, point) in zip(self._handles, specs):
            handle.segment = segment
            handle.role = role
            handle.setPos(point)

    def show_handles(self) -> None:
        self.update_handles()
        for handle in self._handles:
            handle.show()

    def hide_handles(self) -> None:
        for handle in self._handles:
            handle.hide()

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

    def shape(self) -> QtGui.QPainterPath:  # type: ignore[override]
        path = QtGui.QPainterPath(self.path())
        if self.closed and self.brush().style() != QtCore.Qt.BrushStyle.NoBrush:
            return path
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(max(8.0, self.pen().widthF() + 6.0))
        return stroker.createStroke(path)


class BezierPathItem(FreePathItem):
    """A free path with one cubic segment as its initial geometry."""

    def __init__(self, x: float, y: float, width: float = 150.0, height: float = 100.0, **kwargs: Any) -> None:
        if "segments" not in kwargs:
            kwargs["segments"] = [
                {
                    "kind": "cubic",
                    "control1": [width / 3.0, 0.0],
                    "control2": [width * 2.0 / 3.0, height],
                    "end": [width, height],
                }
            ]
        kwargs.setdefault("path_kind", "bezier")
        super().__init__(x, y, width, height, **kwargs)


__all__ = ["BezierPathItem", "FreePathItem", "PathHandle"]
