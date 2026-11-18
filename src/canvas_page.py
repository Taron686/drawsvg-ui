# SPDX-License-Identifier: GPL-2.0-or-later

import math

from PySide6 import QtCore, QtGui, QtWidgets

SCREEN_DPI = 96


def mm_to_px(mm: float, dpi: float = SCREEN_DPI) -> float:
    return mm / 25.4 * dpi


class A4PageItem(QtWidgets.QGraphicsRectItem):
    """QGraphicsRectItem representing a single A4 page with a grid."""

    def __init__(
        self,
        width: float,
        height: float,
        *,
        margin_mm: float = 12.0,
        grid_px: int = 50,
        subgrid_px: int = 10,
        index: tuple[int, int] = (0, 0),
        master_origin: QtCore.QPointF = QtCore.QPointF(),
    ) -> None:
        super().__init__(0.0, 0.0, width, height)
        self.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.white))
        self.setPen(QtCore.Qt.PenStyle.NoPen)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setZValue(-100)

        margin_px = mm_to_px(margin_mm)
        self._margins = QtCore.QMarginsF(margin_px, margin_px, margin_px, margin_px)
        self._grid_visible = True
        self._grid_px = max(1, grid_px)
        self._subgrid_px = max(1, subgrid_px)
        self.index: tuple[int, int] = index
        self._master_origin = QtCore.QPointF(master_origin)
        self._transition_edges: set[str] = set()
        self._neighbors: dict[str, bool] = {
            "left": False,
            "right": False,
            "top": False,
            "bottom": False,
        }
        self._outline_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 120))
        self._outline_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        self._outline_pen.setWidthF(0)
        self._outline_pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        self._outline_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = visible
        self.update()

    def set_master_origin(self, origin: QtCore.QPointF) -> None:
        if self._master_origin == origin:
            return
        self._master_origin = QtCore.QPointF(origin)
        self.update()

    def set_transition_edges(self, edges: set[str]) -> None:
        if self._transition_edges == edges:
            return
        self._transition_edges = set(edges)
        self.update()

    def set_outline_neighbors(
        self, *, left: bool, right: bool, top: bool, bottom: bool
    ) -> None:
        if (
            self._neighbors["left"] == left
            and self._neighbors["right"] == right
            and self._neighbors["top"] == top
            and self._neighbors["bottom"] == bottom
        ):
            return
        self._neighbors["left"] = left
        self._neighbors["right"] = right
        self._neighbors["top"] = top
        self._neighbors["bottom"] = bottom
        self.update()

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        super().paint(painter, option, widget)

        page_rect = self.rect()

        self._paint_outline(painter, page_rect)

        if not self._grid_visible:
            return

        self._paint_grid(painter, page_rect)

    def _paint_outline(self, painter: QtGui.QPainter, page_rect: QtCore.QRectF) -> None:
        painter.save()
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        outline_vertical = QtGui.QPen(self._outline_pen)
        outline_horizontal = QtGui.QPen(self._outline_pen)

        dash_pattern = outline_vertical.dashPattern()
        dash_period = sum(dash_pattern) if dash_pattern else 0.0
        scene_pos = self.scenePos()

        if dash_period > 0.0:
            vertical_offset = math.fmod(
                scene_pos.y() - self._master_origin.y(), dash_period
            )
            horizontal_offset = math.fmod(
                scene_pos.x() - self._master_origin.x(), dash_period
            )
            if vertical_offset < 0.0:
                vertical_offset += dash_period
            if horizontal_offset < 0.0:
                horizontal_offset += dash_period
            outline_vertical.setDashOffset(vertical_offset)
            outline_horizontal.setDashOffset(horizontal_offset)

        transition_vertical = QtGui.QPen(outline_vertical)
        transition_horizontal = QtGui.QPen(outline_horizontal)
        transition_vertical.setColor(QtGui.QColor(0, 0, 0, 160))
        transition_horizontal.setColor(QtGui.QColor(0, 0, 0, 160))

        has_left_neighbor = self._neighbors["left"]
        has_top_neighbor = self._neighbors["top"]

        edge_segments: list[tuple[str, QtCore.QPointF, QtCore.QPointF]] = []
        if not has_left_neighbor:
            edge_segments.append(
                (
                    "left",
                    QtCore.QPointF(page_rect.left(), page_rect.top()),
                    QtCore.QPointF(page_rect.left(), page_rect.bottom()),
                )
            )
        edge_segments.append(
            (
                "right",
                QtCore.QPointF(page_rect.right(), page_rect.top()),
                QtCore.QPointF(page_rect.right(), page_rect.bottom()),
            )
        )
        if not has_top_neighbor:
            edge_segments.append(
                (
                    "top",
                    QtCore.QPointF(page_rect.left(), page_rect.top()),
                    QtCore.QPointF(page_rect.right(), page_rect.top()),
                )
            )
        edge_segments.append(
            (
                "bottom",
                QtCore.QPointF(page_rect.left(), page_rect.bottom()),
                QtCore.QPointF(page_rect.right(), page_rect.bottom()),
            )
        )

        for edge, start, end in edge_segments:
            if edge in ("left", "right"):
                pen = (
                    transition_vertical
                    if edge in self._transition_edges
                    else outline_vertical
                )
            else:
                pen = (
                    transition_horizontal
                    if edge in self._transition_edges
                    else outline_horizontal
                )
            painter.setPen(pen)
            painter.drawLine(start, end)

        painter.restore()

    def _paint_grid(self, painter: QtGui.QPainter, page_rect: QtCore.QRectF) -> None:
        painter.save()
        painter.setClipRect(page_rect)

        origin_scene = self.scenePos()
        master_origin = self._master_origin

        def _first_position(
            spacing: float,
            orientation: str,
        ) -> float:
            if spacing <= 0:
                return 0.0
            if orientation == "vertical":
                start = page_rect.left()
                offset = (origin_scene.x() - master_origin.x()) % spacing
            else:
                start = page_rect.top()
                offset = (origin_scene.y() - master_origin.y()) % spacing
            if math.isclose(offset, spacing, abs_tol=1e-6) or math.isclose(
                offset, 0.0, abs_tol=1e-6
            ):
                offset = 0.0
            return start + (spacing - offset) % spacing

        def _draw_lines(spacing: float, orientation: str, skip_main: bool) -> None:
            if spacing <= 0:
                return
            if orientation == "vertical":
                start = page_rect.left()
                end = page_rect.right()
                origin_value = origin_scene.x()
                first = _first_position(spacing, orientation)
                pos = first
                while pos <= end + 0.5:
                    if skip_main:
                        scene_value = origin_value + (pos - start)
                        distance = scene_value - master_origin.x()
                        nearest = round(distance / self._grid_px) * self._grid_px
                        if math.isclose(distance, nearest, abs_tol=0.3):
                            pos += spacing
                            continue
                    painter.drawLine(pos, page_rect.top(), pos, page_rect.bottom())
                    pos += spacing
            else:
                start = page_rect.top()
                end = page_rect.bottom()
                origin_value = origin_scene.y()
                first = _first_position(spacing, orientation)
                pos = first
                while pos <= end + 0.5:
                    if skip_main:
                        scene_value = origin_value + (pos - start)
                        distance = scene_value - master_origin.y()
                        nearest = round(distance / self._grid_px) * self._grid_px
                        if math.isclose(distance, nearest, abs_tol=0.3):
                            pos += spacing
                            continue
                    painter.drawLine(page_rect.left(), pos, page_rect.right(), pos)
                    pos += spacing

        subgrid_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 30))
        subgrid_pen.setWidthF(0)
        painter.setPen(subgrid_pen)

        _draw_lines(self._subgrid_px, "vertical", True)
        _draw_lines(self._subgrid_px, "horizontal", True)

        grid_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 80))
        grid_pen.setWidthF(0)
        painter.setPen(grid_pen)

        _draw_lines(self._grid_px, "vertical", False)
        _draw_lines(self._grid_px, "horizontal", False)

        painter.restore()
