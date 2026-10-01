from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from constants import SELECTED_COLOR
from items import LineItem


def _render_item(item: LineItem, rotation: float = 0.0):
    image = QtGui.QImage(480, 480, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.white)
    transform = QtGui.QTransform().translate(160.0, 160.0).rotate(rotation)
    painter = QtGui.QPainter(image)
    painter.setTransform(transform)
    try:
        item.paint(painter, QtWidgets.QStyleOptionGraphicsItem())
    finally:
        painter.end()
    return image, transform


def _has_selection_near(image, transform, point, radius=15):
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            pixel = transform.map(QtCore.QPointF(point[0] + dx, point[1] + dy))
            if image.pixelColor(round(pixel.x()), round(pixel.y())) == SELECTED_COLOR:
                return True
    return False


@pytest.mark.parametrize("rotation", (0.0, 35.0))
@pytest.mark.parametrize(
    "arrow_start, arrow_end", ((False, False), (True, False), (False, True), (True, True))
)
@pytest.mark.parametrize(
    "points, shaft_midpoint, empty_corner",
    (
        ([(40, 40), (200, 180)], (120, 110), (195, 45)),
        ([(40, 180), (40, 40), (200, 40)], (40, 110), (195, 175)),
    ),
    ids=("diagonal", "bent"),
)
def test_selected_line_outline_follows_shaft_instead_of_empty_bounding_area(
    application, rotation, arrow_start, arrow_end, points, shaft_midpoint, empty_corner
):
    item = LineItem(
        0.0, 0.0,
        points=[QtCore.QPointF(x, y) for x, y in points],
        arrow_start=arrow_start, arrow_end=arrow_end,
        arrow_head_length=30.0, arrow_head_width=30.0,
    )
    item.setSelected(True)

    image, transform = _render_item(item, rotation)

    assert _has_selection_near(image, transform, shaft_midpoint)
    assert not _has_selection_near(image, transform, empty_corner)
    assert all(handle.isVisible() for handle in item._handles + item._mid_handles)

    item.setSelected(False)
    image, transform = _render_item(item, rotation)
    assert not _has_selection_near(image, transform, shaft_midpoint)
    assert all(not handle.isVisible() for handle in item._handles + item._mid_handles)


@pytest.mark.parametrize("rotation", (0.0, 35.0))
def test_selected_arrow_outline_includes_wide_arrowhead_edges(application, rotation):
    item = LineItem(
        0.0, 0.0,
        points=[QtCore.QPointF(40, 40), QtCore.QPointF(200, 40)],
        arrow_end=True, arrow_head_length=40.0, arrow_head_width=50.0,
    )
    item.setSelected(True)

    image, transform = _render_item(item, rotation)

    assert _has_selection_near(image, transform, (180, 27.5), radius=7)
    assert _has_selection_near(image, transform, (180, 52.5), radius=7)
    assert not _has_selection_near(image, transform, (100, 15), radius=7)
