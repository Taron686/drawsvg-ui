"""Polyline items and their interactive handles."""

from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets

from constants import PEN_NORMAL, PEN_SELECTED
from ..base import (
    HANDLE_COLOR,
    HANDLE_SIZE,
    HandleAwareItemMixin,
    _should_draw_selection,
    snap_to_grid,
)


class LineHandle(QtWidgets.QGraphicsEllipseItem):
    """Handle for line vertices and midpoints."""

    def __init__(self, parent: "LineItem", index: int, is_mid: bool = False):
        super().__init__(
            -HANDLE_SIZE / 2.0,
            -HANDLE_SIZE / 2.0,
            HANDLE_SIZE,
            HANDLE_SIZE,
            parent,
        )
        self.setBrush(HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.index = index
        self.is_mid = is_mid
        self._parent_was_movable = False

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent: "LineItem" = self.parentItem()  # type: ignore[assignment]
        if self.is_mid:
            parent.insert_point(self.index + 1, self.pos())
            parent._mid_handles.pop(self.index)
            self.is_mid = False
            parent._handles.insert(self.index + 1, self)
            parent.update_handles()
        flags = parent.flags()
        self._parent_was_movable = bool(
            flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        parent._moving_index = self.index
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent: "LineItem" = self.parentItem()  # type: ignore[assignment]
        parent._handle_move(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent: "LineItem" = self.parentItem()  # type: ignore[assignment]
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._parent_was_movable = False
        parent._moving_index = None
        event.accept()


class LineItem(HandleAwareItemMixin, QtWidgets.QGraphicsPathItem):
    def __init__(
        self,
        x: float,
        y: float,
        length: float | None = None,
        arrow_start: bool = False,
        arrow_end: bool = False,
        points: list[QtCore.QPointF] | None = None,
        arrow_head_length: float | None = None,
        arrow_head_width: float | None = None,
    ):
        super().__init__()
        self.setPos(x, y)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(QtGui.QPen(PEN_NORMAL))
        self.arrow_start = arrow_start
        self.arrow_end = arrow_end
        default_arrow_size = 10.0
        if arrow_head_length is None:
            self._arrow_head_length = default_arrow_size
        else:
            self._arrow_head_length = max(0.1, float(arrow_head_length))
        if arrow_head_width is None:
            self._arrow_head_width = default_arrow_size
        else:
            self._arrow_head_width = max(0.1, float(arrow_head_width))
        self._selection_padding = 10.0
        if points is not None:
            self._points = [QtCore.QPointF(p) for p in points]
        else:
            self._points = [
                QtCore.QPointF(0.0, 0.0),
                QtCore.QPointF(length or 0.0, 0.0),
            ]
        self._moving_index: int | None = None
        self._handles: list[LineHandle] = []
        self._mid_handles: list[LineHandle] = []
        self._update_path()
        self.update_handles()
        self.hide_handles()

    def _update_length(self) -> None:
        total = 0.0
        for i in range(len(self._points) - 1):
            total += QtCore.QLineF(self._points[i], self._points[i + 1]).length()
        self._length = total

    def _compute_center(self) -> QtCore.QPointF:
        br = self.path().boundingRect()
        return br.center()

    def _update_path(self) -> None:
        path = QtGui.QPainterPath(self._points[0])
        for point in self._points[1:]:
            path.lineTo(point)
        self.setPath(path)
        self._update_length()
        self.setTransformOriginPoint(self._compute_center())

    def insert_point(self, index: int, pos: QtCore.QPointF) -> None:
        self._points.insert(index, QtCore.QPointF(pos))
        self._update_path()

    def _snap_position_value(self, value):  # type: ignore[override]
        if not isinstance(value, QtCore.QPointF):
            return value

        mods = QtWidgets.QApplication.keyboardModifiers()
        if mods & QtCore.Qt.KeyboardModifier.AltModifier:
            return value

        if not (self.arrow_start or self.arrow_end):
            return super()._snap_position_value(value)

        tip_deltas: list[QtCore.QPointF] = []
        current_scene_pos = self.scenePos()

        if self.arrow_start and self._points:
            start_scene = self.mapToScene(self._points[0])
            tip_deltas.append(start_scene - current_scene_pos)

        if self.arrow_end and self._points:
            end_scene = self.mapToScene(self._points[-1])
            tip_deltas.append(end_scene - current_scene_pos)

        if not tip_deltas:
            return super()._snap_position_value(value)

        best_value: QtCore.QPointF | None = None
        best_distance: float | None = None

        for delta in tip_deltas:
            new_tip_scene = value + delta
            snapped_tip = snap_to_grid(self, new_tip_scene)
            adjusted_value = snapped_tip - delta
            distance = math.hypot(
                adjusted_value.x() - value.x(),
                adjusted_value.y() - value.y(),
            )
            if best_distance is None or distance < best_distance - 1e-6:
                best_distance = distance
                best_value = adjusted_value

        if best_value is None:
            return super()._snap_position_value(value)

        return best_value

    def _handle_move(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._moving_index is None:
            return
        new_pos = event.scenePos()
        if not (event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier):
            new_pos = snap_to_grid(self, new_pos)
        self._points[self._moving_index] = self.mapFromScene(new_pos)
        self._update_path()
        self.update_handles()
        event.accept()

    def set_arrow_start(self, value: bool) -> None:
        if self.arrow_start != value:
            self.prepareGeometryChange()
            self.arrow_start = value
            self.update()

    def set_arrow_end(self, value: bool) -> None:
        if self.arrow_end != value:
            self.prepareGeometryChange()
            self.arrow_end = value
            self.update()

    def arrow_head_length(self) -> float:
        return self._arrow_head_length

    def arrow_head_width(self) -> float:
        return self._arrow_head_width

    def set_arrow_head_length(self, value: float) -> None:
        new_value = max(0.1, float(value))
        if not math.isclose(self._arrow_head_length, new_value, rel_tol=1e-6, abs_tol=1e-6):
            self.prepareGeometryChange()
            self._arrow_head_length = new_value
            self.update()

    def set_arrow_head_width(self, value: float) -> None:
        new_value = max(0.1, float(value))
        if not math.isclose(self._arrow_head_width, new_value, rel_tol=1e-6, abs_tol=1e-6):
            self.prepareGeometryChange()
            self._arrow_head_width = new_value
            self.update()

    def set_pen_style(self, style: QtCore.Qt.PenStyle) -> None:
        pen = QtGui.QPen(self.pen())
        if pen.style() != style:
            pen.setStyle(style)
        if style == QtCore.Qt.PenStyle.DotLine:
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        elif pen.capStyle() == QtCore.Qt.PenCapStyle.RoundCap:
            pen.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
        self.setPen(pen)
        self.update()

    def boundingRect(self):  # type: ignore[override]
        rect = super().boundingRect()
        padding = self._selection_padding
        if self.arrow_start or self.arrow_end:
            arrow_padding = max(self._arrow_head_length, self._arrow_head_width / 2.0)
            padding += arrow_padding
        if padding <= 0.0:
            return rect
        return rect.adjusted(-padding, -padding, padding, padding)

    def shape(self) -> QtGui.QPainterPath:  # type: ignore[override]
        points = self._points

        pen = self.pen()
        pen_width = max(pen.widthF(), 0.1)
        half_width = pen_width / 2.0 + self._selection_padding

        base_path = QtGui.QPainterPath(self.path())

        selection_path = QtGui.QPainterPath()
        selection_path.setFillRule(QtCore.Qt.FillRule.WindingFill)

        if half_width > 0.0 and len(points) >= 2:
            for start_point, end_point in zip(points, points[1:]):
                direction = end_point - start_point
                length = math.hypot(direction.x(), direction.y())
                if length <= 1e-6:
                    continue

                unit_dir = QtCore.QPointF(direction.x() / length, direction.y() / length)
                perp = QtCore.QPointF(-unit_dir.y(), unit_dir.x())

                extension = QtCore.QPointF(unit_dir.x() * half_width, unit_dir.y() * half_width)
                offset = QtCore.QPointF(perp.x() * half_width, perp.y() * half_width)

                rect_path = QtGui.QPainterPath()
                rect_path.moveTo(start_point - extension + offset)
                rect_path.lineTo(start_point - extension - offset)
                rect_path.lineTo(end_point + extension - offset)
                rect_path.lineTo(end_point + extension + offset)
                rect_path.closeSubpath()
                selection_path.addPath(rect_path)

        if self.arrow_start or self.arrow_end:
            if len(points) >= 2:
                arrow_path = QtGui.QPainterPath()
                if self.arrow_start:
                    start_poly, _ = self._arrow_head_geometry(points[1], points[0])
                    arrow_path.addPolygon(start_poly)
                if self.arrow_end:
                    end_poly, _ = self._arrow_head_geometry(points[-2], points[-1])
                    arrow_path.addPolygon(end_poly)

                if not arrow_path.isEmpty():
                    selection_path.addPath(arrow_path)
                    if self._selection_padding > 0.0:
                        arrow_stroke = QtGui.QPainterPathStroker()
                        arrow_stroke.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
                        arrow_stroke.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
                        arrow_stroke.setMiterLimit(4.0)
                        arrow_stroke.setWidth(self._selection_padding * 2.0)
                        selection_path.addPath(arrow_stroke.createStroke(arrow_path))

        return selection_path

    def update_handles(self) -> None:
        while len(self._handles) < len(self._points):
            handle = LineHandle(self, len(self._handles))
            self._handles.append(handle)
        while len(self._handles) > len(self._points):
            handle = self._handles.pop()
            handle.setParentItem(None)
        for index, point in enumerate(self._points):
            handle = self._handles[index]
            handle.index = index
            handle.is_mid = False
            handle.setPos(point)

        segments = len(self._points) - 1
        while len(self._mid_handles) < segments:
            handle = LineHandle(self, len(self._mid_handles), is_mid=True)
            self._mid_handles.append(handle)
        while len(self._mid_handles) > segments:
            handle = self._mid_handles.pop()
            handle.setParentItem(None)
        for index in range(segments):
            p1, p2 = self._points[index], self._points[index + 1]
            mid = QtCore.QPointF((p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0)
            handle = self._mid_handles[index]
            handle.index = index
            handle.is_mid = True
            handle.setPos(mid)

    def show_handles(self) -> None:
        self.update_handles()
        for handle in self._handles + self._mid_handles:
            handle.show()

    def hide_handles(self) -> None:
        for handle in self._handles + self._mid_handles:
            handle.hide()

    def _arrow_head_geometry(
        self, start: QtCore.QPointF, end: QtCore.QPointF
    ) -> tuple[QtGui.QPolygonF, QtCore.QPointF]:
        line = QtCore.QLineF(start, end)
        tip = QtCore.QPointF(end)
        length = line.length()
        if length <= 1e-6:
            polygon = QtGui.QPolygonF([tip, tip, tip])
            return polygon, tip
        arrow_length = self._arrow_head_length
        arrow_width = self._arrow_head_width
        direction = QtCore.QPointF(end - start)
        unit_dir = QtCore.QPointF(direction.x() / length, direction.y() / length)
        perp = QtCore.QPointF(-unit_dir.y(), unit_dir.x())
        base_center = QtCore.QPointF(
            tip.x() - unit_dir.x() * arrow_length,
            tip.y() - unit_dir.y() * arrow_length,
        )
        half_width = arrow_width / 2.0
        left_point = QtCore.QPointF(
            base_center.x() + perp.x() * half_width,
            base_center.y() + perp.y() * half_width,
        )
        right_point = QtCore.QPointF(
            base_center.x() - perp.x() * half_width,
            base_center.y() - perp.y() * half_width,
        )
        polygon = QtGui.QPolygonF([tip, left_point, right_point])
        return polygon, base_center

    def paint(self, painter, option, widget=None):
        points = self._points

        arrow_polygons: list[QtGui.QPolygonF] = []
        if self.arrow_start or self.arrow_end:
            shaft_points = [QtCore.QPointF(p) for p in points]
            if len(shaft_points) >= 2:
                if self.arrow_start:
                    start_poly, start_base = self._arrow_head_geometry(
                        points[1], points[0]
                    )
                    arrow_polygons.append(start_poly)
                    shaft_points[0] = start_base
                if self.arrow_end:
                    end_poly, end_base = self._arrow_head_geometry(
                        points[-2], points[-1]
                    )
                    arrow_polygons.append(end_poly)
                    shaft_points[-1] = end_base
                shaft_path = QtGui.QPainterPath(shaft_points[0])
                for point in shaft_points[1:]:
                    shaft_path.lineTo(point)
            else:
                shaft_path = QtGui.QPainterPath(self.path())
        else:
            shaft_path = QtGui.QPainterPath(self.path())

        painter.save()
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawPath(shaft_path)
        painter.restore()

        if arrow_polygons:
            painter.save()
            arrow_pen = QtGui.QPen(self.pen())
            if arrow_pen.style() != QtCore.Qt.PenStyle.SolidLine:
                arrow_pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
            arrow_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
            painter.setPen(arrow_pen)
            painter.setBrush(self.pen().color())
            for polygon in arrow_polygons:
                painter.drawPolygon(polygon)
            painter.restore()

        if _should_draw_selection(self):
            highlight_path = self.shape()
            if not highlight_path.isEmpty():
                painter.save()
                highlight_color = QtGui.QColor(255, 235, 59)
                highlight_color.setAlpha(80)
                painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                painter.setBrush(highlight_color)
                painter.drawPath(highlight_path)
                painter.restore()

            painter.save()
            selection_pen = QtGui.QPen(PEN_SELECTED)
            selection_pen.setCapStyle(self.pen().capStyle())
            selection_pen.setJoinStyle(self.pen().joinStyle())
            selection_pen.setWidthF(max(selection_pen.widthF(), self.pen().widthF()))
            selection_pen.setCosmetic(True)
            painter.setPen(selection_pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(shaft_path)
            for polygon in arrow_polygons:
                painter.drawPolygon(polygon)
            painter.restore()


__all__ = ["LineHandle", "LineItem"]
