# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence

from PySide6 import QtCore, QtWidgets

import canvas_view


def _snap_threshold_scene_units(self: canvas_view.CanvasView) -> tuple[float, float]:
    transform = self.transform()
    scale_x = abs(transform.m11())
    scale_y = abs(transform.m22())
    return (
        canvas_view.SNAP_THRESHOLD_PIXELS / scale_x
        if scale_x > 0.0
        else canvas_view.SNAP_THRESHOLD_PIXELS,
        canvas_view.SNAP_THRESHOLD_PIXELS / scale_y
        if scale_y > 0.0
        else canvas_view.SNAP_THRESHOLD_PIXELS,
    )


def _nearest_snap(
    values: tuple[float, ...], candidates: tuple[float, ...], threshold: float
) -> tuple[float, float] | None:
    choices = (
        (abs(candidate - value), candidate - value, candidate)
        for value in values
        for candidate in candidates
        if abs(candidate - value) <= threshold
    )
    try:
        _distance, offset, guide = min(choices, key=lambda choice: choice[0])
    except ValueError:
        return None
    return offset, guide


def _begin_snap_drag(self: canvas_view.CanvasView) -> None:
    self._snap_drag_cache = {}


def _end_snap_drag(self: canvas_view.CanvasView) -> None:
    self._snap_drag_cache = None


def _invalidate_snap_drag(self: canvas_view.CanvasView) -> None:
    if self._snap_drag_cache is not None:
        self._snap_drag_cache.clear()


def _nearest_sorted_snap(
    values: tuple[float, ...], candidates: Sequence[tuple[float, int]], threshold: float
) -> tuple[float, float] | None:
    best = None
    for value_index, value in enumerate(values):
        index = bisect_left(candidates, (value, -1))
        positions = []
        if index < len(candidates):
            positions.append(index)
        if index:
            previous = candidates[index - 1][0]
            positions.append(bisect_left(candidates, (previous, -1)))
        for position in positions:
            candidate, original_index = candidates[position]
            distance = abs(candidate - value)
            if distance <= threshold:
                choice = (
                    distance,
                    value_index,
                    original_index,
                    candidate - value,
                    candidate,
                )
                if best is None or choice[:3] < best[:3]:
                    best = choice
    return None if best is None else (best[3], best[4])


def _snap_to_objects(
    self: canvas_view.CanvasView,
    exclude: tuple[QtWidgets.QGraphicsItem, ...],
    x_values: tuple[float, ...],
    y_values: tuple[float, ...],
    threshold_x: float,
    threshold_y: float,
    snapped_x: tuple[float, float] | None,
    snapped_y: tuple[float, float] | None,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    scene = self.scene()
    if scene is not None:
        excluded = set(exclude)
        key = frozenset(excluded)
        cache = self._snap_drag_cache
        candidates = cache.get(key) if cache is not None else None
        if candidates is None:
            smart_x: list[float] = []
            smart_y: list[float] = []
            for item in canvas_view.scene_root_items(scene.items()):
                if item in excluded or isinstance(item, canvas_view.A4PageItem):
                    continue
                bounds = canvas_view.item_snap_bounds(item, self)
                if bounds is None:
                    continue
                smart_x.extend((bounds.left(), bounds.center().x(), bounds.right()))
                smart_y.extend((bounds.top(), bounds.center().y(), bounds.bottom()))
            if cache is not None:
                candidates = (
                    sorted((value, index) for index, value in enumerate(smart_x)),
                    sorted((value, index) for index, value in enumerate(smart_y)),
                )
                cache[key] = candidates
        if cache is None:
            if snapped_x is None:
                snapped_x = self._nearest_snap(x_values, tuple(smart_x), threshold_x)
            if snapped_y is None:
                snapped_y = self._nearest_snap(y_values, tuple(smart_y), threshold_y)
        else:
            if snapped_x is None:
                snapped_x = self._nearest_sorted_snap(
                    x_values, candidates[0], threshold_x
                )
            if snapped_y is None:
                snapped_y = self._nearest_sorted_snap(
                    y_values, candidates[1], threshold_y
                )

    return snapped_x, snapped_y


def snap_scene_position(
    self: canvas_view.CanvasView,
    position: QtCore.QPointF,
    size: QtCore.QSizeF | None = None,
    *,
    exclude: tuple[QtWidgets.QGraphicsItem, ...] = (),
    grid_spacing: float | None = None,
    grid_anchor: QtCore.QPointF | None = None,
) -> tuple[QtCore.QPointF, dict[str, float]]:
    """Translate by the geometry grid anchor, then report reached alignment.

    With grid snapping disabled, guides and objects may translate freely.
    ``position`` and ``size`` describe the alignment envelope independently
    of the geometry reference supplied by ``grid_anchor``.
    """

    position = QtCore.QPointF(position)
    grid_enabled = getattr(self, "_grid_snap_enabled", True)
    alignment_enabled = getattr(self, "_alignment_snap_enabled", True)
    if grid_enabled:
        anchor = grid_anchor if grid_anchor is not None else position
        spacing = float(
            grid_spacing if grid_spacing is not None else self._grid_size_min
        )
        snapped_anchor = QtCore.QPointF(
            canvas_view.snap_coordinate(anchor.x(), spacing, self._master_origin.x()),
            canvas_view.snap_coordinate(anchor.y(), spacing, self._master_origin.y()),
        )
        position += snapped_anchor - anchor
    if not alignment_enabled:
        return position, {}

    width = max(0.0, float(size.width())) if size is not None else 0.0
    height = max(0.0, float(size.height())) if size is not None else 0.0
    x_values = (position.x(), position.x() + width / 2.0, position.x() + width)
    y_values = (position.y(), position.y() + height / 2.0, position.y() + height)
    threshold_x, threshold_y = self._snap_threshold_scene_units()
    if grid_enabled:
        # Near misses must not be advertised as alignment after grid snap.
        threshold_x = threshold_y = 1e-6
    guide_x = tuple(value for axis, value in self._guides if axis == "vertical")
    guide_y = tuple(value for axis, value in self._guides if axis == "horizontal")
    snapped_x = self._nearest_snap(x_values, guide_x, threshold_x)
    snapped_y = self._nearest_snap(y_values, guide_y, threshold_y)
    snapped_x, snapped_y = _snap_to_objects(
        self,
        exclude,
        x_values,
        y_values,
        threshold_x,
        threshold_y,
        snapped_x,
        snapped_y,
    )

    active: dict[str, float] = {}
    x, y = position.x(), position.y()
    if snapped_x is not None:
        if not grid_enabled:
            x += snapped_x[0]
        active["vertical"] = snapped_x[1]
    if snapped_y is not None:
        if not grid_enabled:
            y += snapped_y[0]
        active["horizontal"] = snapped_y[1]
    return QtCore.QPointF(x, y), active


def _snap_new_item(
    self: canvas_view.CanvasView, item: QtWidgets.QGraphicsItem, *, grid_spacing: float
) -> dict[str, float]:
    """Snap a prospective scene root using its constructed geometry."""
    bounds = canvas_view.item_snap_bounds(item, self)
    anchor = canvas_view.item_grid_anchor(item)
    if bounds is None or anchor is None:
        return {}
    snapped, active = self.snap_scene_position(
        bounds.topLeft(),
        bounds.size(),
        grid_spacing=grid_spacing,
        grid_anchor=anchor,
    )
    delta = snapped - bounds.topLeft()
    # Prospective items are not in the scene, so item-local grid hooks do
    # not interfere with this single central geometry translation.
    item.moveBy(delta.x(), delta.y())
    return active


def _snap_selected_items(self: canvas_view.CanvasView) -> None:
    roots = set(canvas_view.scene_root_items(self.scene().items()))
    selected = [
        item
        for item in self.scene().selectedItems()
        if not isinstance(item, canvas_view.A4PageItem)
        and not item.__class__.__name__.endswith("Handle")
        and item in roots
    ]
    if not selected:
        if self._active_snap_guides:
            self._active_snap_guides.clear()
            self.viewport().update()
        return
    primary = self.scene().mouseGrabberItem()
    while primary is not None and primary.parentItem() is not None:
        primary = primary.parentItem()
    if primary not in selected:
        selected.sort(
            key=lambda item: (
                item.scenePos().x(),
                item.scenePos().y(),
                str(item.data(canvas_view.KEY_ITEM_ID) or ""),
                type(item).__name__,
            )
        )
        primary = selected[0]
    bounds = canvas_view.item_snap_bounds(primary, self)
    anchor = canvas_view.item_grid_anchor(primary)
    if bounds is None or anchor is None:
        self._active_snap_guides.clear()
        self.viewport().update()
        return
    snapped, active_guides = self.snap_scene_position(
        bounds.topLeft(),
        bounds.size(),
        exclude=tuple(selected),
        grid_anchor=anchor,
    )
    delta = snapped - bounds.topLeft()
    self._active_snap_guides = active_guides
    if delta.isNull():
        self.viewport().update()
        return
    original_spacing = self._grid_size_min
    self._grid_size_min = 0
    try:
        for item in selected:
            item.moveBy(delta.x(), delta.y())
    finally:
        self._grid_size_min = original_spacing
    self.viewport().update()


# Public entry points used by CanvasView.
begin_snap_drag = _begin_snap_drag
end_snap_drag = _end_snap_drag
invalidate_snap_drag = _invalidate_snap_drag
nearest_snap = _nearest_snap
nearest_sorted_snap = _nearest_sorted_snap
snap_new_item = _snap_new_item
snap_selected_items = _snap_selected_items
snap_threshold_scene_units = _snap_threshold_scene_units
