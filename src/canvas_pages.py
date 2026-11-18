# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import math
from typing import Any

from PySide6 import QtCore, QtWidgets

import canvas_view


def _page_top_left_for_index(
    self: canvas_view.CanvasView, index: tuple[int, int]
) -> QtCore.QPointF:
    row, col = index
    base_x = -self._page_width / 2.0
    base_y = -self._page_height / 2.0
    return QtCore.QPointF(
        base_x + col * self._page_width,
        base_y + row * self._page_height,
    )


def _normalized_page_index(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    row, col = value
    if isinstance(row, bool) or isinstance(col, bool):
        return None
    if not isinstance(row, int) or not isinstance(col, int):
        return None
    return row, col


def _owner_page_index(
    self: canvas_view.CanvasView, item: QtWidgets.QGraphicsItem
) -> tuple[int, int] | None:
    return self._normalized_page_index(item.data(canvas_view.KEY_OWNER_PAGE))


def _set_owner_page(item: QtWidgets.QGraphicsItem, index: tuple[int, int]) -> None:
    item.setData(canvas_view.KEY_OWNER_PAGE, [index[0], index[1]])


def _restore_owner_page(
    self: canvas_view.CanvasView, item: QtWidgets.QGraphicsItem, value: Any
) -> None:
    index = self._normalized_page_index(value)
    if index is not None:
        self._set_owner_page(item, index)


def _page_index_for_point(
    self: canvas_view.CanvasView, point: QtCore.QPointF
) -> tuple[int, int]:
    base_x = -self._page_width / 2.0
    base_y = -self._page_height / 2.0
    col = math.floor((point.x() - base_x) / self._page_width)
    row = math.floor((point.y() - base_y) / self._page_height)
    return (row, col)


def _create_page_item(
    self: canvas_view.CanvasView, index: tuple[int, int]
) -> canvas_view.A4PageItem:
    page = canvas_view.A4PageItem(
        self._page_width,
        self._page_height,
        margin_mm=12.0,
        grid_px=self._grid_size,
        subgrid_px=self._grid_size_min,
        index=index,
        master_origin=self._master_origin,
    )
    top_left = self._page_top_left_for_index(index)
    page.setPos(top_left)
    page.set_grid_visible(self._show_grid)
    return page


def _add_page(
    self: canvas_view.CanvasView, index: tuple[int, int], *, update_edges: bool = True
) -> canvas_view.A4PageItem:
    existing = self._pages.get(index)
    if existing is not None:
        existing.set_master_origin(self._master_origin)
        return existing
    page = self._create_page_item(index)
    self.scene().addItem(page)
    self._pages[index] = page
    if update_edges:
        self._update_transition_edges()
    return page


def _ensure_pages_between_master(
    self: canvas_view.CanvasView, target_index: tuple[int, int]
) -> None:
    master_row, master_col = self._master_index
    target_row, target_col = target_index
    min_row = min(master_row, target_row)
    max_row = max(master_row, target_row)
    min_col = min(master_col, target_col)
    max_col = max(master_col, target_col)

    added_any = False
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            index = (row, col)
            if index not in self._pages:
                added_any = True
            self._add_page(index, update_edges=False)
    if added_any:
        self._update_transition_edges()


def _update_transition_edges(self: canvas_view.CanvasView) -> None:
    master_page = self._pages.get(self._master_index)
    if master_page is None:
        return
    for (row, col), page in self._pages.items():
        page.set_outline_neighbors(
            left=(row, col - 1) in self._pages,
            right=(row, col + 1) in self._pages,
            top=(row - 1, col) in self._pages,
            bottom=(row + 1, col) in self._pages,
        )
    master_edges: set[str] = set()
    master_row, master_col = self._master_index
    for (row, col), page in self._pages.items():
        if (row, col) == self._master_index:
            continue
        edges: set[str] = set()
        if row == master_row:
            if col == master_col + 1:
                edges.add("left")
                master_edges.add("right")
            elif col == master_col - 1:
                edges.add("right")
                master_edges.add("left")
        if col == master_col:
            if row == master_row + 1:
                edges.add("top")
                master_edges.add("bottom")
            elif row == master_row - 1:
                edges.add("bottom")
                master_edges.add("top")
        page.set_transition_edges(edges)
    master_page.set_transition_edges(master_edges)


def _ensure_page_for_item(
    self: canvas_view.CanvasView,
    item: QtWidgets.QGraphicsItem,
    drop_reference: QtCore.QPointF | None,
) -> canvas_view.A4PageItem:
    rect = item.sceneBoundingRect()
    owner_index = self._owner_page_index(item)
    if drop_reference is not None or owner_index is None:
        reference = drop_reference if drop_reference is not None else rect.center()
        owner_index = self._page_index_for_point(reference)
        self._set_owner_page(item, owner_index)

    assert owner_index is not None
    page = self._add_page(owner_index, update_edges=False)
    for index in self._page_indices_for_rect(rect):
        self._add_page(index, update_edges=False)
    self._ensure_pages_between_master(owner_index)
    self._update_transition_edges()
    self._prune_empty_pages()
    if owner_index not in self._pages:
        page = self._add_page(owner_index, update_edges=False)
        self._ensure_pages_between_master(owner_index)
        self._update_transition_edges()
    self._update_scene_rect()
    return page


def _page_indices_for_rect(
    self: canvas_view.CanvasView, rect: QtCore.QRectF
) -> set[tuple[int, int]]:
    """Return every page touched by ``rect``, including oversized items."""

    if rect.isNull() or not rect.isValid():
        return {self._page_index_for_point(rect.center())}
    right = math.nextafter(rect.right(), -math.inf)
    bottom = math.nextafter(rect.bottom(), -math.inf)
    first = self._page_index_for_point(rect.topLeft())
    last = self._page_index_for_point(QtCore.QPointF(right, bottom))
    return {
        (row, col)
        for row in range(first[0], last[0] + 1)
        for col in range(first[1], last[1] + 1)
    }


def _collect_canvas_content_items(
    self: canvas_view.CanvasView,
) -> list[QtWidgets.QGraphicsItem]:
    scene = self.scene()
    if scene is None:
        return []
    items: list[QtWidgets.QGraphicsItem] = []
    for item in scene.items():
        if isinstance(item, canvas_view.A4PageItem):
            continue
        if item.__class__.__name__.endswith("Handle"):
            continue
        items.append(item)
    return items


def _prune_empty_pages(self: canvas_view.CanvasView) -> bool:
    scene = self.scene()
    if scene is None:
        return False
    content_items = self._collect_canvas_content_items()
    master_row, master_col = self._master_index

    content_indices: set[tuple[int, int]] = set()
    for index, page in self._pages.items():
        page_rect = page.mapRectToScene(page.rect())
        has_item = any(
            item.sceneBoundingRect().intersects(page_rect)
            for item in content_items
            if item.scene() is scene
        )
        if has_item:
            content_indices.add(index)

    required_indices: set[tuple[int, int]] = {self._master_index}
    for row, col in content_indices:
        min_row = min(master_row, row)
        max_row = max(master_row, row)
        min_col = min(master_col, col)
        max_col = max(master_col, col)
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                required_indices.add((r, c))

    removed = False
    for index, page in list(self._pages.items()):
        if index in required_indices:
            continue
        self._pages.pop(index, None)
        scene.removeItem(page)
        removed = True
    if removed:
        self._update_transition_edges()
    return removed


def _ensure_pages_for_items(
    self: canvas_view.CanvasView, items: list[QtWidgets.QGraphicsItem]
) -> None:
    for item in items:
        if isinstance(item, canvas_view.A4PageItem):
            continue
        if item.__class__.__name__.endswith("Handle"):
            continue
        if item.parentItem() is not None:
            continue
        self._ensure_page_for_item(item, item.sceneBoundingRect().center())


# Public entry points used by CanvasView.
add_page = _add_page
collect_canvas_content_items = _collect_canvas_content_items
create_page_item = _create_page_item
ensure_page_for_item = _ensure_page_for_item
ensure_pages_between_master = _ensure_pages_between_master
ensure_pages_for_items = _ensure_pages_for_items
normalized_page_index = _normalized_page_index
owner_page_index = _owner_page_index
page_index_for_point = _page_index_for_point
page_indices_for_rect = _page_indices_for_rect
page_top_left_for_index = _page_top_left_for_index
prune_empty_pages = _prune_empty_pages
restore_owner_page = _restore_owner_page
set_owner_page = _set_owner_page
update_transition_edges = _update_transition_edges
