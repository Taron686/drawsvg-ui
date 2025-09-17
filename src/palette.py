from PySide6 import QtCore, QtGui, QtWidgets

from constants import DEFAULTS, DEFAULT_FILL, PALETTE_MIME, PEN_NORMAL, SHAPES


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


def _build_shape_icon(name: str, size: QtCore.QSize) -> QtGui.QPixmap:
    screen = QtGui.QGuiApplication.primaryScreen()
    device_pixel_ratio = float(screen.devicePixelRatio() if screen else 1.0)
    pixel_size = QtCore.QSize(
        max(1, int(size.width() * device_pixel_ratio)),
        max(1, int(size.height() * device_pixel_ratio)),
    )
    pixmap = QtGui.QPixmap(pixel_size)
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(PEN_NORMAL)
    painter.setBrush(DEFAULT_FILL)

    padding = 6 * device_pixel_ratio
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        icon_size = QtCore.QSize(64, 64)
        self.setIconSize(icon_size)
        self.setSpacing(8)
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)

        for name in SHAPES:
            icon = QtGui.QIcon(_build_shape_icon(name, icon_size))
            QtWidgets.QListWidgetItem(icon, name, self)

    def startDrag(self, supportedActions: QtCore.Qt.DropActions):
        item = self.currentItem()
        if not item:
            return
        drag = QtGui.QDrag(self)
        md = QtCore.QMimeData()
        md.setData(PALETTE_MIME, item.text().encode("utf-8"))
        md.setText(item.text())
        drag.setMimeData(md)

        icon = item.icon()
        if not icon.isNull():
            size = self.iconSize()
            pix = icon.pixmap(size)
            if not pix.isNull():
                drag.setPixmap(pix)
                drag.setHotSpot(QtCore.QPoint(pix.width() // 2, pix.height() // 2))
        drag.exec(QtCore.Qt.DropAction.CopyAction)
