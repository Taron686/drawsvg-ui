"""Paint the public editor's hover overlay without changing scene items."""

from PySide6 import QtCore, QtGui, QtWidgets

HOVER_PREVIEW_STRENGTH = 0.8
HOVER_PREVIEW_X_COUNT = 16
HOVER_PREVIEW_COLOR = "#14b5ff"


def _marker_points(polygon: QtGui.QPolygonF) -> list[QtCore.QPointF]:
    outline = QtGui.QPainterPath()
    outline.addPolygon(polygon)
    outline.closeSubpath()
    perimeter = outline.length()
    return [
        outline.pointAtPercent(outline.percentAtLength(perimeter * index / HOVER_PREVIEW_X_COUNT))
        for index in range(HOVER_PREVIEW_X_COUNT)
    ]


def _overlay_pen(alpha: int, width: float) -> QtGui.QPen:
    color = QtGui.QColor(HOVER_PREVIEW_COLOR)
    color.setAlpha(round(alpha * HOVER_PREVIEW_STRENGTH))
    pen = QtGui.QPen(color, width)
    pen.setCosmetic(True)
    return pen


def _draw_markers(painter: QtGui.QPainter, polygon: QtGui.QPolygonF) -> None:
    transform = painter.worldTransform()
    scale = (QtCore.QLineF(transform.map(QtCore.QPointF()), transform.map(QtCore.QPointF(1, 0))).length())
    half_size = 3.0 * HOVER_PREVIEW_STRENGTH / max(scale, 1e-6)
    painter.setPen(_overlay_pen(220, 1.3 * HOVER_PREVIEW_STRENGTH))
    for point in _marker_points(polygon):
        painter.drawLine(point + QtCore.QPointF(-half_size, -half_size), point + QtCore.QPointF(half_size, half_size))
        painter.drawLine(point + QtCore.QPointF(-half_size, half_size), point + QtCore.QPointF(half_size, -half_size))


def draw_hover_preview(painter: QtGui.QPainter, item: QtWidgets.QGraphicsItem) -> None:
    """Draw an outline and X markers for a live item; preserve painter state.

    The caller supplies a scene-coordinate painter and an unselected item.
    Only the view is painted; scene serialization and exports are unaffected.
    """
    polygon = item.mapToScene(item.boundingRect())
    painter.save()
    try:
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(_overlay_pen(125, HOVER_PREVIEW_STRENGTH))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPolygon(polygon)
        _draw_markers(painter, polygon)
    finally:
        painter.restore()
