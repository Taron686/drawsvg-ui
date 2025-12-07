# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from PySide6 import QtCore, QtGui, QtWidgets
import math

from constants import DEFAULTS, DEFAULT_FILL, PALETTE_MIME, PEN_NORMAL, SHAPES
from items import CurvyBracketItem, build_curvy_bracket_path

def _fit_rect_to_ratio(rect: QtCore.QRectF, aspect_ratio: float) -> QtCore.QRectF:
    """Return a copy of *rect* scaled to match the requested aspect ratio."""

    if aspect_ratio <= 0:
        return QtCore.QRectF(rect)

    width = rect.width()
    height = rect.height()
    if width <= 0 or height <= 0:
        return QtCore.QRectF(rect)

    current_ratio = width / height
    new_width = width
    new_height = height
    if current_ratio > aspect_ratio:
        new_width = height * aspect_ratio
    else:
        new_height = width / aspect_ratio

    fitted = QtCore.QRectF(
        rect.center().x() - new_width / 2,
        rect.center().y() - new_height / 2,
        new_width,
        new_height,
    )
    return fitted

def _build_shape_icon(
    name: str,
    size: QtCore.QSize,
    *,
    device_pixel_ratio: float = 1.0,
) -> QtGui.QPixmap:
    device_pixel_ratio = max(1.0, float(device_pixel_ratio))
    pixel_size = QtCore.QSize(
        max(1, int(math.ceil(size.width() * device_pixel_ratio))),
        max(1, int(math.ceil(size.height() * device_pixel_ratio))),
    )
    pixmap = QtGui.QPixmap(pixel_size)
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(PEN_NORMAL)
    painter.setBrush(DEFAULT_FILL)

    padding = 4 * device_pixel_ratio
    rect = QtCore.QRectF(
        padding,
        padding,
        pixel_size.width() - 2 * padding,
        pixel_size.height() - 2 * padding,
    )

    lower_name = name.lower()
    if lower_name == "rectangle":
        dims = DEFAULTS.get(name)
        draw_rect = rect
        if dims and dims[1]:
            draw_rect = _fit_rect_to_ratio(rect, dims[0] / dims[1])
        painter.drawRect(draw_rect)
    elif lower_name == "rounded rectangle":
        dims = DEFAULTS.get(name)
        draw_rect = rect
        if dims and dims[1]:
            draw_rect = _fit_rect_to_ratio(rect, dims[0] / dims[1])
        radius = 8.0 * device_pixel_ratio
        painter.drawRoundedRect(draw_rect, radius, radius)
    elif lower_name == "split rounded rectangle":
        dims = DEFAULTS.get(name)
        draw_rect = rect
        if dims and dims[1]:
            draw_rect = _fit_rect_to_ratio(rect, dims[0] / dims[1])
        radius = 8.0 * device_pixel_ratio

        base_path = QtGui.QPainterPath()
        base_path.addRoundedRect(draw_rect, radius, radius)
        painter.fillPath(base_path, DEFAULT_FILL)

        header_height = draw_rect.height() / 3.0
        top_clip = QtGui.QPainterPath()
        top_clip.addRect(
            draw_rect.left(),
            draw_rect.top(),
            draw_rect.width(),
            header_height,
        )
        header_color = QtGui.QColor("#f6e3b0")
        painter.fillPath(base_path.intersected(top_clip), header_color)

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(PEN_NORMAL)
        painter.drawRoundedRect(draw_rect, radius, radius)

        line_y = draw_rect.top() + header_height
        divider_pen = QtGui.QPen(QtGui.QColor("#777"))
        divider_pen.setWidthF(max(1.0, PEN_NORMAL.widthF() * device_pixel_ratio * 0.9))
        painter.setPen(divider_pen)
        painter.drawLine(draw_rect.left(), line_y, draw_rect.right(), line_y)

        handle_radius = 3.0 * device_pixel_ratio
        painter.setBrush(QtGui.QColor("#d28b00"))
        painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        painter.drawEllipse(QtCore.QPointF(draw_rect.center().x(), line_y), handle_radius, handle_radius)

        painter.setPen(PEN_NORMAL)
        painter.setBrush(DEFAULT_FILL)
    elif lower_name == "ellipse":
        dims = DEFAULTS.get(name)
        ellipse_rect = rect
        if dims and dims[1]:
            ellipse_rect = _fit_rect_to_ratio(rect, dims[0] / dims[1])
        painter.drawEllipse(ellipse_rect)
    elif lower_name == "circle":
        diameter = min(rect.width(), rect.height())
        circle_rect = QtCore.QRectF(
            rect.center().x() - diameter / 2,
            rect.center().y() - diameter / 2,
            diameter,
            diameter,
        )
        painter.drawEllipse(circle_rect)
    elif lower_name == "triangle":
        points = QtGui.QPolygonF(
            [
                QtCore.QPointF(rect.center().x(), rect.top()),
                QtCore.QPointF(rect.left(), rect.bottom()),
                QtCore.QPointF(rect.right(), rect.bottom()),
            ]
        )
        painter.drawPolygon(points)
    elif lower_name == "diamond":
        points = QtGui.QPolygonF(
            [
                QtCore.QPointF(rect.center().x(), rect.top()),
                QtCore.QPointF(rect.right(), rect.center().y()),
                QtCore.QPointF(rect.center().x(), rect.bottom()),
                QtCore.QPointF(rect.left(), rect.center().y()),
            ]
        )
        painter.drawPolygon(points)
    elif lower_name == "line":
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        y = rect.center().y()
        painter.drawLine(rect.left(), y, rect.right(), y)
    elif lower_name == "arrow":
        shaft_end_x = rect.right() - rect.width() * 0.25
        center_y = rect.center().y()
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawLine(rect.left(), center_y, shaft_end_x, center_y)

        arrow_height = rect.height() * 0.4
        painter.setBrush(DEFAULT_FILL)
        arrow_head = QtGui.QPolygonF(
            [
                QtCore.QPointF(rect.right(), center_y),
                QtCore.QPointF(shaft_end_x, center_y - arrow_height / 2),
                QtCore.QPointF(shaft_end_x, center_y + arrow_height / 2),
            ]
        )
        painter.drawPolygon(arrow_head)
    elif lower_name == "block arrow":
        dims = DEFAULTS.get(name)
        draw_rect = rect
        if dims and dims[1]:
            draw_rect = _fit_rect_to_ratio(rect, dims[0] / dims[1])

        head_frac = 0.32
        head_width = draw_rect.width() * head_frac
        shaft_frac = 0.45
        shaft_height = draw_rect.height() * shaft_frac
        shaft_top = draw_rect.center().y() - shaft_height / 2.0
        shaft_bottom = draw_rect.center().y() + shaft_height / 2.0
        head_base_x = draw_rect.right() - head_width

        polygon = QtGui.QPolygonF(
            [
                QtCore.QPointF(draw_rect.left(), shaft_top),
                QtCore.QPointF(head_base_x, shaft_top),
                QtCore.QPointF(head_base_x, draw_rect.top()),
                QtCore.QPointF(draw_rect.right(), draw_rect.center().y()),
                QtCore.QPointF(head_base_x, draw_rect.bottom()),
                QtCore.QPointF(head_base_x, shaft_bottom),
                QtCore.QPointF(draw_rect.left(), shaft_bottom),
            ]
        )
        painter.drawPolygon(polygon)

        painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        painter.setBrush(QtGui.QColor("#d28b00"))
        handle_radius = 3.0 * device_pixel_ratio
        painter.drawEllipse(
            QtCore.QPointF(head_base_x, shaft_top), handle_radius, handle_radius
        )
        tail_mid_x = draw_rect.left() + (head_base_x - draw_rect.left()) / 2.0
        painter.drawEllipse(
            QtCore.QPointF(tail_mid_x, shaft_bottom), handle_radius, handle_radius
        )
        painter.setBrush(DEFAULT_FILL)
        painter.setPen(PEN_NORMAL)
    elif lower_name == "folder tree":
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        branch_pen = QtGui.QPen(QtGui.QColor("#7a7a7a"))
        branch_pen.setWidthF(max(1.0, PEN_NORMAL.widthF() * device_pixel_ratio * 0.7))
        branch_pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(branch_pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        padding_x = rect.width() * 0.12
        padding_y = rect.height() * 0.18
        indent = rect.width() * 0.28
        line_gap = rect.height() * 0.26

        base_x = rect.left() + padding_x
        level1_x = base_x + indent
        level2_x = level1_x + indent

        y0 = rect.top() + padding_y
        y1 = y0 + line_gap
        y2 = y1 + line_gap

        painter.drawLine(QtCore.QPointF(base_x, y0), QtCore.QPointF(base_x, y2))
        painter.drawLine(QtCore.QPointF(base_x, y0), QtCore.QPointF(level1_x, y0))
        painter.drawLine(QtCore.QPointF(base_x, y1), QtCore.QPointF(level1_x, y1))
        painter.drawLine(QtCore.QPointF(level1_x, y1), QtCore.QPointF(level2_x, y1))
        painter.drawLine(QtCore.QPointF(base_x, y2), QtCore.QPointF(level1_x, y2))
        painter.drawLine(QtCore.QPointF(level1_x, y2), QtCore.QPointF(level2_x, y2))

        dot_radius = 3.0 * device_pixel_ratio
        dot_color = QtGui.QColor("#f28c28")
        painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        painter.setBrush(dot_color)
        dot_centers = [
            QtCore.QPointF(base_x, y0),
            QtCore.QPointF(base_x, y1),
            QtCore.QPointF(base_x, y2),
            QtCore.QPointF(level1_x, y1),
            QtCore.QPointF(level1_x, y2),
            QtCore.QPointF(level2_x, y1),
            QtCore.QPointF(level2_x, y2),
        ]
        for center in dot_centers:
            painter.drawEllipse(center, dot_radius, dot_radius)

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        label_pen = QtGui.QPen(QtGui.QColor("#d7d7d7"))
        label_pen.setWidthF(max(1.0, PEN_NORMAL.widthF() * device_pixel_ratio * 0.6))
        painter.setPen(label_pen)

        label_len = rect.width() * 0.32
        text_offsets = [
            (level1_x + dot_radius * 2.0 + 3.0, y0),
            (level2_x + dot_radius * 2.0 + 3.0, y1),
            (level2_x + dot_radius * 2.0 + 3.0, y2),
        ]
        for tx, ty in text_offsets:
            painter.drawLine(QtCore.QPointF(tx, ty), QtCore.QPointF(tx + label_len, ty))

        painter.setPen(PEN_NORMAL)
        painter.setBrush(DEFAULT_FILL)
    elif lower_name == "curvy right bracket":
        dims = DEFAULTS.get(name)
        draw_rect = rect
        if dims and dims[1]:
            draw_rect = _fit_rect_to_ratio(rect, dims[0] / dims[1])
        path = build_curvy_bracket_path(
            draw_rect.width(),
            draw_rect.height(),
            draw_rect.height() * CurvyBracketItem.DEFAULT_HOOK_RATIO,
        )
        path.translate(draw_rect.left(), draw_rect.top())
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setBrush(DEFAULT_FILL)
    elif lower_name == "text":
        radius = 6 * device_pixel_ratio
        painter.drawRoundedRect(rect, radius, radius)

        inner_rect = rect.adjusted(
            rect.width() * 0.18,
            rect.height() * 0.18,
            -rect.width() * 0.18,
            -rect.height() * 0.18,
        )
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawLine(inner_rect.left(), inner_rect.top(), inner_rect.right(), inner_rect.top())
        painter.drawLine(
            inner_rect.center().x(),
            inner_rect.top(),
            inner_rect.center().x(),
            inner_rect.bottom(),
        )
    else:
        painter.drawRoundedRect(rect, 6 * device_pixel_ratio, 6 * device_pixel_ratio)

    painter.end()
    return pixmap

class PaletteList(QtWidgets.QListWidget):
    shapeClicked = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(False)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)

        self._base_icon_size = QtCore.QSize(56, 56)
        self._base_cell_padding = 4
        self._base_spacing = 6
        self._last_device_pixel_ratio: float | None = None
        self._current_screen: QtGui.QScreen | None = None
        self._window_handle_connected = False

        self._update_metrics()

        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        self._pressed_item: QtWidgets.QListWidgetItem | None = None
        self._press_pos = QtCore.QPointF()
        self._hovered_item: QtWidgets.QListWidgetItem | None = None
        self._hover_brush = QtGui.QBrush(QtGui.QColor("#d2e7ff"))

        for name in SHAPES:
            item = QtWidgets.QListWidgetItem("")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            self.addItem(item)

        self._refresh_icons(force=True)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self._bind_to_current_screen()
        self._refresh_icons()

    def event(self, event: QtCore.QEvent) -> bool:
        if event.type() in (
            QtCore.QEvent.Type.DevicePixelRatioChange,
            QtCore.QEvent.Type.ScreenChangeInternal,
        ):
            self._bind_to_current_screen()
            self._refresh_icons(force=True)
        return super().event(event)

    def _update_metrics(self) -> None:
        icon_size = QtCore.QSize(self._base_icon_size)
        self.setIconSize(icon_size)
        padding = int(self._base_cell_padding)
        self.setGridSize(
            QtCore.QSize(
                icon_size.width() + padding * 2,
                icon_size.height() + padding * 2,
            )
        )
        self.setSpacing(int(self._base_spacing))

    def _effective_device_pixel_ratio(self) -> float:
        dpr = float(self.devicePixelRatioF())
        if not math.isfinite(dpr) or dpr <= 0.0:
            handle = self.windowHandle()
            if handle is not None:
                try:
                    dpr = float(handle.devicePixelRatio())
                except AttributeError:
                    dpr = 1.0
        if not math.isfinite(dpr) or dpr <= 0.0:
            screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
            if screen is not None:
                dpr = float(screen.devicePixelRatio())
        return dpr if math.isfinite(dpr) and dpr > 0.0 else 1.0

    def _refresh_icons(self, *, force: bool = False) -> None:
        if self.count() == 0:
            return
        dpr = self._effective_device_pixel_ratio()
        if (
            not force
            and self._last_device_pixel_ratio is not None
            and abs(self._last_device_pixel_ratio - dpr) < 1e-3
        ):
            return
        self._last_device_pixel_ratio = dpr
        self._update_metrics()
        icon_size = self.iconSize()
        for index in range(self.count()):
            item = self.item(index)
            shape = self._shape_from_item(item)
            if not shape:
                continue
            pixmap = _build_shape_icon(
                shape,
                icon_size,
                device_pixel_ratio=dpr,
            )
            item.setIcon(QtGui.QIcon(pixmap))

    def _ensure_window_handle_connection(self) -> None:
        if self._window_handle_connected:
            return
        window = self.window().windowHandle() if self.window() is not None else None
        if window is None:
            window = self.windowHandle()
        if window is None:
            return
        window.screenChanged.connect(self._on_window_screen_changed)
        self._window_handle_connected = True

    def _bind_to_current_screen(self) -> None:
        self._ensure_window_handle_connection()
        screen = self.screen()
        if screen is None:
            window = self.window().windowHandle() if self.window() is not None else None
            if window is None:
                window = self.windowHandle()
            if window is not None:
                screen = window.screen()
        self._connect_to_screen(screen)

    def _connect_to_screen(self, screen: QtGui.QScreen | None) -> None:
        current = self._current_screen
        if current is screen:
            return
        if current is not None:
            try:
                current.logicalDotsPerInchChanged.disconnect(self._on_screen_metrics_changed)
            except (TypeError, RuntimeError):
                pass
            if hasattr(current, "devicePixelRatioChanged"):
                try:
                    getattr(current, "devicePixelRatioChanged").disconnect(self._on_screen_metrics_changed)
                except (TypeError, RuntimeError):
                    pass
        self._current_screen = screen
        if screen is None:
            return
        screen.logicalDotsPerInchChanged.connect(self._on_screen_metrics_changed)
        if hasattr(screen, "devicePixelRatioChanged"):
            getattr(screen, "devicePixelRatioChanged").connect(self._on_screen_metrics_changed)

    def _on_window_screen_changed(self, screen: QtGui.QScreen | None) -> None:
        self._connect_to_screen(screen)
        self._refresh_icons(force=True)

    def _on_screen_metrics_changed(self, *args) -> None:
        self._refresh_icons(force=True)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._update_hover_from_pos(event.position())
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                self._pressed_item = item
                self._press_pos = event.position()
                event.accept()
                return
        self._pressed_item = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._update_hover_from_pos(event.position())
        if (
            self._pressed_item is not None
            and event.buttons() & QtCore.Qt.MouseButton.LeftButton
        ):
            delta = event.position() - self._press_pos
            distance = QtCore.QLineF(QtCore.QPointF(), delta).length()
            if distance >= QtWidgets.QApplication.startDragDistance():
                item = self._pressed_item
                self._pressed_item = None
                if item is not None:
                    self._start_drag_from_item(item)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._update_hover_from_pos(event.position())
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._pressed_item:
            item = self.itemAt(event.position().toPoint())
            if item is self._pressed_item:
                shape = self._shape_from_item(item)
                if shape:
                    self.shapeClicked.emit(shape)
            self._pressed_item = None
            event.accept()
            return
        self._pressed_item = None
        super().mouseReleaseEvent(event)

    def _shape_from_item(self, item: QtWidgets.QListWidgetItem | None) -> str | None:
        if item is None:
            return None
        data = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return data if isinstance(data, str) else None

    def _start_drag_from_item(self, item: QtWidgets.QListWidgetItem) -> None:
        shape = self._shape_from_item(item)
        if not shape:
            return

        drag = QtGui.QDrag(self)
        md = QtCore.QMimeData()
        md.setData(PALETTE_MIME, shape.encode("utf-8"))
        md.setText(shape)
        drag.setMimeData(md)

        self._set_hover_item(None)

        icon = item.icon()
        if not icon.isNull():
            size = self.iconSize()
            pix = icon.pixmap(size)
            if not pix.isNull():
                drag.setPixmap(pix)
                drag.setHotSpot(QtCore.QPoint(pix.width() // 2, pix.height() // 2))
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._set_hover_item(None)
        super().leaveEvent(event)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        cursor_pos = self.viewport().mapFromGlobal(QtGui.QCursor.pos())
        self._update_hover_from_pos(QtCore.QPointF(cursor_pos))
        super().enterEvent(event)

    def _update_hover_from_pos(self, pos: QtCore.QPointF) -> None:
        item = self.itemAt(pos.toPoint())
        if item is not self._hovered_item:
            self._set_hover_item(item)

    def _set_hover_item(self, item: QtWidgets.QListWidgetItem | None) -> None:
        if item is self._hovered_item:
            return

        if self._hovered_item is not None:
            self._hovered_item.setData(QtCore.Qt.ItemDataRole.BackgroundRole, None)

        self._hovered_item = item

        if self._hovered_item is not None:
            self._hovered_item.setData(
                QtCore.Qt.ItemDataRole.BackgroundRole, self._hover_brush
            )

