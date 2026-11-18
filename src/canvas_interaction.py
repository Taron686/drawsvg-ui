# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

import canvas_view


def _connector_move(self: canvas_view.CanvasView, event: QtGui.QMouseEvent) -> bool:
    if self._connector_creation_enabled and not event.buttons() & (
        QtCore.Qt.MouseButton.MiddleButton | QtCore.Qt.MouseButton.RightButton
    ):
        if self._connector_start is not None:
            self._connector_preview_position = self.mapToScene(
                event.position().toPoint()
            )
            self.viewport().update()
        self.viewport().setCursor(QtCore.Qt.CursorShape.CrossCursor)
        event.accept()
        return True

    return False


def _update_cursor(self: canvas_view.CanvasView, event: QtGui.QMouseEvent) -> None:
    item = self.itemAt(event.position().toPoint())
    if item and item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
        self.viewport().setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
    else:
        self.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)


def _pan_move(self: canvas_view.CanvasView, event: QtGui.QMouseEvent) -> bool:
    if self._panning or self._right_button_pressed:
        delta = event.position() - self._pan_start
        if (
            self._right_button_pressed
            and not self._panning
            and delta.manhattanLength() > 0
        ):
            self._panning = True
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        if self._panning:
            self._pan_start = event.position()
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - int(delta.x()))
            vbar.setValue(vbar.value() - int(delta.y()))
            event.accept()
            return True
    return False


def _duplicate_move(self: canvas_view.CanvasView, event: QtGui.QMouseEvent) -> bool:
    if getattr(self, "_dup_source", None):
        pos = self.mapToScene(event.position().toPoint())
        delta = pos - self._dup_start
        if self._dup_items is None:
            # Only create clones after surpassing the threshold.
            if delta.manhattanLength() < canvas_view.DUPLICATE_DRAG_THRESHOLD:
                event.accept()
                return True
            self._dup_items = []
            self._dup_orig = []
            for it in self._dup_source:
                clone = self._clone_item(it)
                if clone:
                    self.scene().addItem(clone)
                    self._dup_items.append(clone)
                    self._dup_orig.append(clone.pos())
            self.scene().clearSelection()
            for it in self._dup_items:
                it.setSelected(True)
        for it, start in zip(self._dup_items, self._dup_orig):
            it.setPos(start + delta)
        event.accept()
        return True
    return False


def mouse_move_event(self: canvas_view.CanvasView, event: QtGui.QMouseEvent) -> None:
    if _connector_move(self, event):
        return
    _update_cursor(self, event)
    if _pan_move(self, event) or _duplicate_move(self, event):
        return
    grabber = self.scene().mouseGrabberItem()
    moving_selection = (
        event.buttons() & QtCore.Qt.MouseButton.LeftButton
        and grabber is not None
        and not grabber.__class__.__name__.endswith("Handle")
    )
    original_spacing = self._grid_size_min
    if moving_selection:
        # Item-local position snapping cannot know the geometry reference.
        # Let Qt translate freely, then snap the dragged root as a whole.
        self._grid_size_min = 0
    try:
        QtWidgets.QGraphicsView.mouseMoveEvent(self, event)
    finally:
        self._grid_size_min = original_spacing
    if event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier:
        self._active_snap_guides.clear()
        self.viewport().update()
        return
    if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
        grabber = self.scene().mouseGrabberItem()
        if grabber is None or grabber.__class__.__name__.endswith("Handle"):
            if self._active_snap_guides:
                self._active_snap_guides.clear()
                self.viewport().update()
            return
        self._snap_selected_items()
