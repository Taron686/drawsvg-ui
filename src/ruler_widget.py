"""Viewport-aligned rulers that create and edit canvas guides."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from canvas_view import CanvasView


class RulerWidget(QtWidgets.QWidget):
    """A millimetre ruler bound to one axis of a :class:`CanvasView`."""

    _THICKNESS = 22

    def __init__(
        self,
        orientation: QtCore.Qt.Orientation,
        canvas: CanvasView,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._orientation = orientation
        self._canvas = canvas
        self._dragging: tuple[str, float] | None = None
        self.setMouseTracking(True)
        if orientation == QtCore.Qt.Orientation.Horizontal:
            self.setFixedHeight(self._THICKNESS)
        else:
            self.setFixedWidth(self._THICKNESS)
        canvas.viewChanged.connect(self.update)
        canvas.guidesVisibilityChanged.connect(self.setVisible)

    @property
    def guide_orientation(self) -> str:
        return (
            "vertical"
            if self._orientation == QtCore.Qt.Orientation.Horizontal
            else "horizontal"
        )

    def _scene_position(self, point: QtCore.QPointF) -> float:
        viewport_point = (
            QtCore.QPoint(int(point.x()), 0)
            if self._orientation == QtCore.Qt.Orientation.Horizontal
            else QtCore.QPoint(0, int(point.y()))
        )
        scene_point = self._canvas.mapToScene(viewport_point)
        return (
            scene_point.x() if self.guide_orientation == "vertical" else scene_point.y()
        )

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        position = self._scene_position(event.position())
        orientation = self.guide_orientation
        nearest = self._canvas.guide_near(orientation, position)
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            if nearest is not None:
                self._canvas.history().begin_transaction()
                self._canvas.remove_guide(*nearest)
                self._canvas.history().end_transaction()
            event.accept()
            return
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._canvas.history().begin_transaction()
        if nearest is None:
            self._canvas.add_guide(orientation, position)
            nearest = (orientation, position)
        self._dragging = nearest
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging is None or not (
            event.buttons() & QtCore.Qt.MouseButton.LeftButton
        ):
            super().mouseMoveEvent(event)
            return
        orientation, old_position = self._dragging
        new_position = self._scene_position(event.position())
        if self._canvas.move_guide(orientation, old_position, new_position):
            self._dragging = (orientation, new_position)
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self._dragging is not None
        ):
            self._dragging = None
            self._canvas.history().end_transaction()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(event.rect(), QtGui.QColor("#e5e7eb"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#667085")))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        scene_start, scene_end = self._scene_range()
        for scene_position, millimetres in self._canvas.ruler_ticks(
            scene_start, scene_end
        ):
            pixel = self._canvas.mapFromScene(self._point_for(scene_position))
            axis_pixel = (
                pixel.x()
                if self._orientation == QtCore.Qt.Orientation.Horizontal
                else pixel.y()
            )
            self._paint_tick(painter, axis_pixel, millimetres)

    def _scene_range(self) -> tuple[float, float]:
        viewport = self._canvas.viewport().rect()
        if self._orientation == QtCore.Qt.Orientation.Horizontal:
            start = self._canvas.mapToScene(viewport.topLeft()).x()
            end = self._canvas.mapToScene(viewport.topRight()).x()
        else:
            start = self._canvas.mapToScene(viewport.topLeft()).y()
            end = self._canvas.mapToScene(viewport.bottomLeft()).y()
        return min(start, end), max(start, end)

    def _point_for(self, position: float) -> QtCore.QPointF:
        return (
            QtCore.QPointF(position, 0.0)
            if self._orientation == QtCore.Qt.Orientation.Horizontal
            else QtCore.QPointF(0.0, position)
        )

    def _paint_tick(
        self, painter: QtGui.QPainter, pixel: int, millimetres: float
    ) -> None:
        label = f"{millimetres:g} mm"
        if self._orientation == QtCore.Qt.Orientation.Horizontal:
            painter.drawLine(pixel, self.height() - 7, pixel, self.height() - 1)
            painter.drawText(pixel + 2, 12, label)
        else:
            painter.drawLine(self.width() - 7, pixel, self.width() - 1, pixel)
            painter.save()
            painter.translate(11, pixel - 2)
            painter.rotate(-90)
            painter.drawText(0, 0, label)
            painter.restore()
