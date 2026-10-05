# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Scene-space snap envelopes, separate from enlarged Qt hit regions."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from items import GroupItem, LineItem, TextItem
from items.shapes.paths import FreePathItem
from scene_codec import KEY_TRANSIENT


def scene_root_items(
    items: Iterable[QtWidgets.QGraphicsItem],
) -> tuple[QtWidgets.QGraphicsItem, ...]:
    """Find roots through child links without transferring Qt ownership."""
    items = tuple(items)
    children = {child for item in items for child in item.childItems()}
    return tuple(item for item in items if item not in children)


def _stroke_in_scene(
    path: QtGui.QPainterPath,
    pen: QtGui.QPen,
    item: QtWidgets.QGraphicsItem,
    view: QtWidgets.QGraphicsView,
) -> QtGui.QPainterPath:
    stroker = QtGui.QPainterPathStroker(pen)
    # Alignment uses a stable envelope, independently of the dash phase.
    stroker.setDashPattern(QtCore.Qt.PenStyle.SolidLine)
    if not pen.isCosmetic():
        return item.sceneTransform().map(stroker.createStroke(path))

    # A cosmetic pen is measured in physical device pixels, including width 0.
    dpr = view.viewport().devicePixelRatioF()
    physical = QtGui.QTransform.fromScale(dpr, dpr)
    item_to_device = item.deviceTransform(view.viewportTransform()) * physical
    scene_to_device = view.viewportTransform() * physical
    device_to_scene, invertible = scene_to_device.inverted()
    if not invertible:
        return QtGui.QPainterPath()
    stroker.setWidth(pen.widthF() or 1.0)
    return device_to_scene.map(stroker.createStroke(item_to_device.map(path)))


def _path_bounds(
    path: QtGui.QPainterPath,
    pen: QtGui.QPen,
    brush: QtGui.QBrush,
    item: QtWidgets.QGraphicsItem,
    view: QtWidgets.QGraphicsView,
) -> QtCore.QRectF | None:
    painted = QtGui.QPainterPath()
    if brush.style() != QtCore.Qt.BrushStyle.NoBrush:
        painted = item.sceneTransform().map(path)
    if pen.style() != QtCore.Qt.PenStyle.NoPen:
        stroke = _stroke_in_scene(path, pen, item, view)
        painted = painted.united(stroke) if not painted.isEmpty() else stroke
    return None if painted.isEmpty() else painted.boundingRect()


def _union_bounds(
    rectangles: Iterable[QtCore.QRectF | None],
) -> QtCore.QRectF | None:
    result = None
    for rect in rectangles:
        if rect is not None:
            result = rect if result is None else result.united(rect)
    return result


def item_snap_bounds(
    item: QtWidgets.QGraphicsItem,
    view: QtWidgets.QGraphicsView,
) -> QtCore.QRectF | None:
    """Return the current body envelope, or None for an ineligible item."""
    if (
        not item.isVisible()
        or item.effectiveOpacity() <= 0.0
        or item.data(KEY_TRANSIENT)
        or item.__class__.__name__.endswith("Handle")
    ):
        return None

    if isinstance(item, GroupItem):
        return _union_bounds(item_snap_bounds(child, view) for child in item.childItems())

    if isinstance(item, LineItem):
        shaft, heads = item._paint_geometry()
        rectangles = [_path_bounds(shaft, item.pen(), item.brush(), item, view)]
        arrow_pen = QtGui.QPen(item.pen())
        arrow_pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
        arrow_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
        for polygon in heads:
            outline = QtGui.QPainterPath()
            outline.addPolygon(polygon)
            outline.closeSubpath()
            rectangles.append(
                _path_bounds(outline, arrow_pen, QtGui.QBrush(item.pen().color()), item, view)
            )
        return _union_bounds(rectangles)

    if isinstance(item, FreePathItem):
        return _path_bounds(item.path(), item.pen(), item.brush(), item, view)

    # Text fields and assets align by their editable/display rectangles.
    return item.sceneBoundingRect()


def _item_grid_bounds(item: QtWidgets.QGraphicsItem) -> QtCore.QRectF | None:
    """Scene frame of editable geometry, excluding pens and interaction handles."""
    if (
        not item.isVisible()
        or item.effectiveOpacity() <= 0.0
        or item.data(KEY_TRANSIENT)
        or item.__class__.__name__.endswith("Handle")
    ):
        return None
    if isinstance(item, GroupItem):
        return _union_bounds(_item_grid_bounds(child) for child in item.childItems())
    if isinstance(item, QtWidgets.QGraphicsPathItem):
        return item.sceneTransform().map(item.path()).boundingRect()
    if isinstance(item, QtWidgets.QGraphicsPolygonItem):
        return item.mapToScene(item.polygon()).boundingRect()
    rect = item.rect() if hasattr(item, "rect") else item.boundingRect()
    return item.mapRectToScene(rect)


def item_grid_anchor(item: QtWidgets.QGraphicsItem) -> QtCore.QPointF | None:
    """Return a stroke-independent scene reference for translating an item to grid.

    Text uses its editable local corner. Paths use their geometric frame; arrows
    retain their tip reference, choosing the nearest grid correction for two tips
    (the start tip wins ties). Group frames use current eligible child geometry.
    """
    bounds = _item_grid_bounds(item)
    if bounds is None:
        return None
    if isinstance(item, TextItem):
        return item.mapToScene(QtCore.QPointF())
    if isinstance(item, LineItem) and (item.arrow_start or item.arrow_end):
        tips = []
        if item.arrow_start:
            tips.append(item.mapToScene(item.path().pointAtPercent(0)))
        if item.arrow_end:
            tips.append(item.mapToScene(item.path().pointAtPercent(1)))
        scene = item.scene()
        views = scene.views() if scene is not None else []
        if len(tips) > 1 and views:
            view = views[0]
            spacing = float(getattr(view, "_grid_size_min", 10.0))
            origin = getattr(view, "_master_origin", QtCore.QPointF())
            if spacing > 0:
                return min(tips, key=lambda tip: (
                    (round((tip.x() - origin.x()) / spacing) * spacing + origin.x() - tip.x()) ** 2
                    + (round((tip.y() - origin.y()) / spacing) * spacing + origin.y() - tip.y()) ** 2
                ))
        return tips[0]
    return bounds.topLeft()
