# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

import logging
import math
from bisect import bisect_left as bisect_left
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from functools import wraps
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

import canvas_alignment
import canvas_context_menu
import canvas_interaction
import canvas_pages
import canvas_snapping
from canvas_history import (
    SceneHistory as SceneHistory,
    UndoTransactionManager as UndoTransactionManager,
)
from canvas_page import A4PageItem as A4PageItem, mm_to_px as mm_to_px
from connectors import (
    AnchorName,
    ConnectorItem,
    ConnectorManager,
    is_connector_data,
)
from asset_service import BitmapAssetService
from bitmap_item import (
    BitmapItem,
    bitmap_assets_for_items,
    restore_bitmap_item,
    serialize_bitmap_item,
)
from clipboard_service import CLIPBOARD_MIME_TYPE, ClipboardService
from constants import PALETTE_MIME
from hover_preview import draw_hover_preview
from document_format import ProjectAsset
from items import (
    DiamondItem as DiamondItem,
    GroupItem,
    HandleAwareItemMixin,
    LineItem as LineItem,
    RectItem as RectItem,
    ResizableItem,
    ResizeHandle,
    RotationHandle,
    ShapeLabelMixin,
    SplitRoundedRectItem as SplitRoundedRectItem,
    TextItem,
    TriangleItem as TriangleItem,
)
from layer_manager import LayerManager
from scene_codec import KEY_ITEM_ID, KEY_LAYER_ID, SceneCodec
from shape_registry import SHAPE_REGISTRY, _color_from_data
from snap_geometry import item_grid_anchor as item_grid_anchor
from snap_geometry import item_snap_bounds, scene_root_items as scene_root_items

A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
SCREEN_DPI = 96  # Typical desktop DPI
KEY_OWNER_PAGE = 1006
SNAP_THRESHOLD_PIXELS = 6.0


def _snap_coordinate(value: float, spacing: float, origin: float) -> float:
    if spacing <= 0.0:
        return value
    return round((value - origin) / spacing) * spacing + origin


def snap_coordinate(value: float, spacing: float, origin: float) -> float:
    return _snap_coordinate(value, spacing, origin)


def _apply_shape_label(item: ShapeLabelMixin, data: Mapping[str, Any] | None) -> None:
    if not data:
        return
    text = data.get("text")
    if isinstance(text, str):
        item.set_label_text(text)
    alignment = data.get("alignment")
    if isinstance(alignment, (list, tuple)) and len(alignment) == 2:
        horizontal, vertical = alignment
        item.set_label_alignment(horizontal=str(horizontal), vertical=str(vertical))
    font_data = data.get("font")
    if isinstance(font_data, str):
        font = QtGui.QFont()
        font.fromString(font_data)
        item.label_item().setFont(font)
    color_data = data.get("color")
    color_override = bool(data.get("color_override", False))
    if isinstance(color_data, Mapping):
        color = _color_from_data(color_data)
        if color_override:
            item.set_label_color(color)
        else:
            item.reset_label_color(update=True, base_color=color)


# Minimum mouse movement (in scene coordinates) required before
# showing duplicates when Ctrl+dragging selected items.
DUPLICATE_DRAG_THRESHOLD = 10.0


class CornerRadiusDialog(QtWidgets.QDialog):
    valueChanged = QtCore.Signal(int)

    def __init__(self, radius: float, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Corner radius")

        layout = QtWidgets.QFormLayout(self)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 50)
        self.slider.setValue(int(radius))
        self.slider.setTracking(True)
        self.label = QtWidgets.QLabel(str(int(radius)))
        self.label.setFixedWidth(40)
        radius_layout = QtWidgets.QHBoxLayout()
        radius_layout.addWidget(self.slider)
        radius_layout.addWidget(self.label)
        layout.addRow("radius", radius_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.slider.valueChanged.connect(self._on_slider_value_changed)

    def value(self) -> int:
        return self.slider.value()

    def _on_slider_value_changed(self, value: int) -> None:
        self.label.setText(str(value))
        self.valueChanged.emit(value)


class OpacityDialog(QtWidgets.QDialog):
    valueChanged = QtCore.Signal(float)

    def __init__(self, value: float, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fill opacity")

        self._value = value

        layout = QtWidgets.QVBoxLayout(self)

        slider_layout = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(round(value * 100))
        self.slider.setTracking(True)
        slider_layout.addWidget(self.slider, stretch=1)

        self.display = QtWidgets.QLineEdit(f"{value:.2f}")
        self.display.setReadOnly(True)
        self.display.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.display.setFixedWidth(60)
        slider_layout.addWidget(self.display)

        layout.addLayout(slider_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.slider.valueChanged.connect(self._on_slider_value_changed)

    def _on_slider_value_changed(self, slider_value: int) -> None:
        self._value = slider_value / 100.0
        self.display.setText(f"{self._value:.2f}")
        self.valueChanged.emit(self._value)

    def value(self) -> float:
        return self._value


class TrackingScene(QtWidgets.QGraphicsScene):
    """QGraphicsScene that keeps strong refs to added items."""

    itemRemoved = QtCore.Signal(object)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._owned_items: set[QtWidgets.QGraphicsItem] = set()

    def addItem(self, item: QtWidgets.QGraphicsItem) -> None:  # type: ignore[override]
        super().addItem(item)
        self._owned_items.add(item)

    def removeItem(self, item: QtWidgets.QGraphicsItem) -> None:  # type: ignore[override]
        self.itemRemoved.emit(item)
        super().removeItem(item)
        self._owned_items.discard(item)

    def clear(self) -> None:  # type: ignore[override]
        super().clear()
        self._owned_items.clear()


def _undo_transaction(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def wrapped(view: "CanvasView", *args: Any, **kwargs: Any) -> Any:
        with view.history().transaction():
            return method(view, *args, **kwargs)

    return wrapped


class CanvasView(QtWidgets.QGraphicsView):
    gridVisibilityChanged = QtCore.Signal(bool)
    guidesVisibilityChanged = QtCore.Signal(bool)
    connectorCreationChanged = QtCore.Signal(bool)
    connectorCreationStartChanged = QtCore.Signal(bool)
    viewChanged = QtCore.Signal()
    selectionSnapshotChanged = QtCore.Signal(dict)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover_preview_item: QtWidgets.QGraphicsItem | None = None
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.RubberBandDrag)
        # Style the selection rubber band with a blue dashed outline
        self.viewport().setStyleSheet("QRubberBand { border: 1px dashed #14b5ff; }")
        self.setAcceptDrops(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        # Keep the view centered when splitter widths change so the canvas does not drift.
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(
            QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )

        scene = TrackingScene(self)
        self._scene_padding = 200
        scene.setSceneRect(
            -self._scene_padding,
            -self._scene_padding,
            self._scene_padding * 2,
            self._scene_padding * 2,
        )
        # Growth is applied at once; shrinking waits for a pause in the edits.
        self._scene_rect_timer = QtCore.QTimer(self)
        self._scene_rect_timer.setSingleShot(True)
        self._scene_rect_timer.setInterval(250)
        self._scene_rect_timer.timeout.connect(lambda: self._update_scene_rect())
        scene.changed.connect(self._on_scene_rect_changed)
        self.setScene(scene)
        self.setBackgroundBrush(QtGui.QColor("#f0f0f0"))
        self._grid_size = 50
        self._grid_size_min = 10
        self._grid_snap_enabled = True
        self._alignment_snap_enabled = True
        self._show_grid = True
        self._page_width = mm_to_px(A4_WIDTH_MM, SCREEN_DPI)
        self._page_height = mm_to_px(A4_HEIGHT_MM, SCREEN_DPI)
        self._master_index: tuple[int, int] = (0, 0)
        self._pages: dict[tuple[int, int], A4PageItem] = {}
        self._guides: list[tuple[str, float]] = []
        self._guides_visible = True
        self._active_snap_guides: dict[str, float] = {}
        self._snap_drag_cache = None
        self._master_origin = self._page_top_left_for_index(self._master_index)
        self._page_item = self._create_page_item(self._master_index)
        self._pages[self._master_index] = self._page_item
        scene.addItem(self._page_item)
        self._update_transition_edges()
        self._initial_fit_pending = True
        self._update_scene_rect()

        self._panning = False
        self._pan_start = QtCore.QPointF()
        self._prev_drag_mode = self.dragMode()
        self._right_button_pressed = False
        self._suppress_context_menu = False
        self._connector_creation_enabled = False
        self._connector_start: QtCore.QPointF | QtWidgets.QGraphicsItem | None = None
        self._connector_preview_position: QtCore.QPointF | None = None

        self._layer_manager = LayerManager(self)
        self._layer_manager.changed.connect(self._invalidate_snap_drag)
        self._connector_manager = ConnectorManager(scene, self)
        # A rerouted connector is a snap candidate whose cached bounds are stale.
        self._connector_manager.routeChanged.connect(self._invalidate_snap_drag)
        self._layer_manager.changed.connect(self._connector_manager.refresh_visibility)
        # Project archives own the binary data. History snapshots retain only
        # item-to-asset references and resolve them through this service.
        self._bitmap_assets = BitmapAssetService()
        self._history = SceneHistory(self)
        self._history.capture_initial_state()

        scene.selectionChanged.connect(self._notify_selection_snapshot)
        scene.changed.connect(self._on_scene_contents_changed)
        self.horizontalScrollBar().valueChanged.connect(self.viewChanged)
        self.verticalScrollBar().valueChanged.connect(self.viewChanged)
        self._notify_selection_snapshot()

    def history(self) -> SceneHistory:
        return self._history

    def layer_manager(self) -> LayerManager:
        return self._layer_manager

    def connector_manager(self) -> ConnectorManager:
        return self._connector_manager

    # Public entry points for collaborators (window, controller, panels, export).
    def page_items(self) -> tuple[A4PageItem, ...]:
        return tuple(self._pages.values())

    def is_serializable_item(self, item: QtWidgets.QGraphicsItem) -> bool:
        return self._is_serializable_item(item)

    def serialize_scene_state(self) -> dict[str, Any]:
        return self._serialize_scene_state()

    def restore_scene_state(self, state: Mapping[str, Any]) -> None:
        self._restore_scene_state(state)

    def validate_scene_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        return self._validate_scene_state(state)

    def notify_selection_snapshot(self) -> None:
        self._notify_selection_snapshot()

    def bitmap_assets(self) -> tuple[ProjectAsset, ...]:
        """Return the project asset source used by bitmap scene items."""

        return self._bitmap_assets.assets()

    def set_bitmap_assets(self, assets: Iterable[ProjectAsset]) -> None:
        """Install validated project assets before restoring bitmap scene items."""

        self._bitmap_assets = BitmapAssetService(assets)

    def undo(self) -> None:
        self._history.undo()

    def redo(self) -> None:
        self._history.redo()

    def connector_creation_enabled(self) -> bool:
        return self._connector_creation_enabled

    def set_connector_creation_enabled(self, enabled: bool) -> None:
        """Toggle the two-click connector creation mode."""

        enabled = bool(enabled)
        if self._connector_creation_enabled == enabled:
            return
        self._connector_creation_enabled = enabled
        self._connector_start = None
        self._connector_preview_position = None
        if enabled:
            self.viewport().setCursor(QtCore.Qt.CursorShape.CrossCursor)
        else:
            self.viewport().unsetCursor()
        self.connectorCreationChanged.emit(enabled)
        self.connectorCreationStartChanged.emit(False)
        self.viewport().update()

    def _connector_preview_start(self) -> QtCore.QPointF | None:
        start = self._connector_start
        if start is None:
            return None
        if isinstance(start, QtWidgets.QGraphicsItem):
            return start.sceneBoundingRect().center()
        return QtCore.QPointF(start)

    def _connector_target_at(
        self, position: QtCore.QPoint
    ) -> QtCore.QPointF | QtWidgets.QGraphicsItem:
        """Return a bindable item at *position*, or its free scene position."""

        item = self.itemAt(position)
        while (
            item is not None
            and item.parentItem() is not None
            and (
                item.__class__.__name__.endswith("Handle")
                or item.data(KEY_ITEM_ID) is None
            )
        ):
            item = item.parentItem()
        if (
            item is None
            or isinstance(item, (A4PageItem, ConnectorItem))
            or SceneCodec.is_transient(item)
        ):
            return self.mapToScene(position)
        return item

    def _handle_connector_click(self, position: QtCore.QPoint) -> None:
        endpoint = self._connector_target_at(position)
        if self._connector_start is None:
            self._connector_start = endpoint
            self._connector_preview_position = self.mapToScene(position)
            self.connectorCreationStartChanged.emit(True)
            self.viewport().update()
            return
        self.add_connector(self._connector_start, endpoint)
        self.set_connector_creation_enabled(False)

    @_undo_transaction
    def add_connector(
        self,
        start: QtCore.QPointF | QtWidgets.QGraphicsItem,
        end: QtCore.QPointF | QtWidgets.QGraphicsItem,
        *,
        start_anchor: AnchorName = "auto",
        end_anchor: AnchorName = "auto",
    ) -> ConnectorItem:
        """Add a connector with free or item-bound endpoints."""
        start_endpoint = self._connector_manager.endpoint_for(
            start, anchor=start_anchor
        )
        end_endpoint = self._connector_manager.endpoint_for(end, anchor=end_anchor)
        connector = self._connector_manager.create_connector(
            start_endpoint, end_endpoint
        )
        self._layer_manager.register_item(connector)
        connector.setSelected(True)
        self._ensure_page_for_item(connector, connector.sceneBoundingRect().center())
        self._update_scene_rect()
        return connector

    # --- Serialization helpers for undo/redo ---
    def _is_serializable_item(self, item: QtWidgets.QGraphicsItem) -> bool:
        if isinstance(item, A4PageItem):
            return False
        name = item.__class__.__name__
        if name.endswith("Handle"):
            return False
        if (
            isinstance(item, QtWidgets.QGraphicsItemGroup)
            and name == "QGraphicsItemGroup"
        ):
            return False
        return isinstance(item, (BitmapItem, ConnectorItem, GroupItem)) or (
            SHAPE_REGISTRY.definition_for_item(item) is not None
        )

    def _serialize_scene_state(self) -> dict[str, Any]:
        scene = self.scene()
        if scene is None:
            state = SceneCodec.serialize_state(
                [], self._serialize_item, grid_visible=bool(self._show_grid)
            )
            state["layers"] = self._layer_manager.serialize_state()
            state["guides"] = self._serialize_guides()
            return state
        items = [
            item
            for item in scene.items(QtCore.Qt.SortOrder.AscendingOrder)
            if (
                item.parentItem() is None
                and self._is_serializable_item(item)
                and not SceneCodec.is_transient(item)
            )
        ]
        state = SceneCodec.serialize_state(
            items, self._serialize_item, grid_visible=bool(self._show_grid)
        )
        state["layers"] = self._layer_manager.serialize_state()
        state["guides"] = self._serialize_guides()
        return state

    def _serialize_item(self, item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
        if isinstance(item, ConnectorItem):
            self._connector_manager.update_connector(item)
            connector_data = item.to_data()
            owner_page = self._owner_page_index(item)
            if owner_page is not None:
                connector_data["owner_page"] = [owner_page[0], owner_page[1]]
            connector_data.update(self._layer_manager.item_metadata(item))
            return connector_data
        base: dict[str, Any] = {
            "shape": str(item.data(0) or item.__class__.__name__),
            "class": item.__class__.__name__,
            "pos": [float(item.pos().x()), float(item.pos().y())],
            "rotation": float(item.rotation()),
            "scale": float(item.scale()),
            "transform": [
                float(item.transform().m11()),
                float(item.transform().m12()),
                float(item.transform().m13()),
                float(item.transform().m21()),
                float(item.transform().m22()),
                float(item.transform().m23()),
                float(item.transform().m31()),
                float(item.transform().m32()),
                float(item.transform().m33()),
            ],
            "z": float(item.zValue()),
        }
        owner_page = self._owner_page_index(item)
        if owner_page is not None:
            base["owner_page"] = [owner_page[0], owner_page[1]]

        if isinstance(item, BitmapItem):
            self._bitmap_assets.ensure(item.asset)
            base.update(serialize_bitmap_item(item))
        elif isinstance(item, GroupItem):
            origin = item.transformOriginPoint()
            base["transform_origin"] = [float(origin.x()), float(origin.y())]
            children = [
                child
                for child in item.childItems()
                if self._is_serializable_item(child)
            ]
            base["children"] = SceneCodec.serialize_items(
                children, self._serialize_item
            )
        else:
            registry_data = SHAPE_REGISTRY.serialize(item)
            if registry_data is not None:
                base.update(registry_data)
        base.update(self._layer_manager.item_metadata(item))
        return base

    def _build_properties_for_item(
        self, item: QtWidgets.QGraphicsItem
    ) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        data = self._serialize_item(item)
        title = str(data.get("shape", item.__class__.__name__))

        object_data = dict(data)
        text_data: Mapping[str, Any] | dict[str, Any] | None = None

        if isinstance(item, ShapeLabelMixin):
            label_data = object_data.pop("label", None)
            if isinstance(label_data, Mapping):
                text_data = dict(label_data)
        elif isinstance(item, TextItem):
            text_keys = (
                "text",
                "font",
                "font_size",
                "color",
                "document_margin",
                "alignment",
                "direction",
            )
            text_section: dict[str, Any] = {}
            for key in text_keys:
                if key in object_data:
                    text_section[key] = object_data.pop(key)
            if text_section:
                text_data = text_section

        plain_text_data: dict[str, Any] | None = dict(text_data) if text_data else None

        return title, object_data, plain_text_data

    def _build_selection_snapshot(self) -> dict[str, Any]:
        scene = self.scene()
        if scene is None:
            return {"selection_type": "none"}
        selected = [
            item for item in scene.selectedItems() if self._is_serializable_item(item)
        ]
        if len(selected) == 1:
            item = selected[0]
            title, object_data, text_data = self._build_properties_for_item(item)
            return {
                "selection_type": "single",
                "title": title,
                "item": item,
                "object_data": object_data,
                "text_data": text_data,
            }
        if selected:
            return {
                "selection_type": "multi",
                "count": len(selected),
                "items": selected,
            }
        return {"selection_type": "none"}

    @staticmethod
    def _item_dimensions(item: QtWidgets.QGraphicsItem) -> tuple[float, float]:
        if isinstance(item, QtWidgets.QGraphicsRectItem):
            rect = item.rect()
            return float(rect.width()), float(rect.height())
        if isinstance(item, QtWidgets.QGraphicsEllipseItem):
            rect = item.rect()
            return float(rect.width()), float(rect.height())
        width_attr = getattr(item, "_w", None)
        height_attr = getattr(item, "_h", None)
        if isinstance(width_attr, (int, float)) and isinstance(
            height_attr, (int, float)
        ):
            return float(width_attr), float(height_attr)
        bounds = item.boundingRect()
        return float(bounds.width()), float(bounds.height())

    def _hover_preview_target_at(self, view_pos: QtCore.QPoint) -> QtWidgets.QGraphicsItem | None:
        candidate = self.itemAt(view_pos)
        selectable = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        while candidate is not None and not (candidate.flags() & selectable):
            candidate = candidate.parentItem()
        if candidate is not None and (
            candidate.isSelected() or isinstance(candidate, LineItem)
            or not self._is_serializable_item(candidate)
        ):
            candidate = None
        return candidate

    def _set_hover_preview_item(self, item: QtWidgets.QGraphicsItem | None) -> None:
        if item is not self._hover_preview_item:
            self._hover_preview_item = item
            self.viewport().update()

    def _clear_hover_preview(self) -> None:
        self._set_hover_preview_item(None)

    def _valid_hover_preview(self) -> QtWidgets.QGraphicsItem | None:
        item = self._hover_preview_item
        if item is not None:
            try:
                if item.scene() is not self.scene() or item.isSelected() or not item.isVisible():
                    item = None
            except RuntimeError:
                item = None  # Qt may have deleted the item during undo or document restore.
        self._hover_preview_item = item
        return item

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        """Clear the visual hover overlay when the pointer leaves the view."""
        self._clear_hover_preview()
        super().leaveEvent(event)

    def _notify_selection_snapshot(self) -> None:
        self._clear_hover_preview()
        payload = self._build_selection_snapshot()
        self.selectionSnapshotChanged.emit(payload)

    def _on_scene_contents_changed(self, _changes: list[QtCore.QRectF]) -> None:
        scene = self.scene()
        if scene is None:
            return
        if any(self._is_serializable_item(item) for item in scene.selectedItems()):
            self._notify_selection_snapshot()

    def _apply_item_transform(
        self, item: QtWidgets.QGraphicsItem, data: Mapping[str, Any]
    ) -> None:
        if isinstance(item, GroupItem):
            origin = data.get("transform_origin")
            if isinstance(origin, (list, tuple)) and len(origin) == 2:
                item.setTransformOriginPoint(float(origin[0]), float(origin[1]))
            else:
                item.setTransformOriginPoint(item._contentRect().center())
        transform = data.get("transform")
        if isinstance(transform, (list, tuple)) and len(transform) == 9:
            item.setTransform(QtGui.QTransform(*(float(value) for value in transform)))
        pos = data.get("pos", [0.0, 0.0])
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            original_spacing = self._grid_size_min
            self._grid_size_min = 0
            try:
                item.setPos(float(pos[0]), float(pos[1]))
            finally:
                self._grid_size_min = original_spacing
        rotation = data.get("rotation")
        if rotation is not None:
            item.setRotation(float(rotation))
        scale = data.get("scale")
        if scale is not None:
            item.setScale(float(scale))
        z_val = data.get("z")
        if z_val is not None:
            item.setZValue(float(z_val))

    def _instantiate_item(
        self, data: Mapping[str, Any]
    ) -> QtWidgets.QGraphicsItem | None:
        shape = str(data.get("shape", ""))
        if data.get("type_id") == "Bitmap" or shape == "Bitmap":
            return restore_bitmap_item(data, self._bitmap_assets.assets())
        if shape == "Group":
            return GroupItem()
        return SHAPE_REGISTRY.restore(data)

    def _restore_group_children(
        self,
        group: GroupItem,
        children_data: list[Mapping[str, Any]],
    ) -> None:
        scene = self.scene()
        if scene is None:
            return
        for child_data in children_data:
            if not isinstance(child_data, Mapping):
                continue
            child = self._instantiate_item(child_data)
            if child is None:
                continue
            scene.addItem(child)
            group.addToGroup(child)
            if not isinstance(child, GroupItem):
                self._apply_item_transform(child, child_data)
            SceneCodec.restore_item_metadata(child, child_data)
            # Without this the restored scene serializes differently from its
            # snapshot and every undo records a new, identical-looking state.
            self._restore_owner_page(child, child_data.get("owner_page"))
            self._layer_manager.restore_item_state(child, child_data)
            child.setSelected(False)
            child.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,
                False,
            )
            child.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                False,
            )
            if isinstance(child, ResizableItem):
                child.hide_handles()
            if isinstance(child, GroupItem):
                sub_children = child_data.get("children")
                if isinstance(sub_children, list):
                    self._restore_group_children(child, sub_children)
                self._apply_item_transform(child, child_data)

    @staticmethod
    def _validate_scene_state(state: Mapping[str, Any]) -> dict[str, Any]:
        """Check shape support before touching the current scene or selection."""
        state = SceneCodec.normalize_state(state)
        items_data = state.get("items")

        def validate_items(items: list[Any]) -> None:
            for data in items:
                if not isinstance(data, Mapping):
                    continue
                shape = str(data.get("shape", ""))
                if (
                    is_connector_data(data)
                    or data.get("type_id") == "Bitmap"
                    or shape == "Bitmap"
                ):
                    continue
                if shape == "Group":
                    children = data.get("children")
                    if isinstance(children, list):
                        validate_items(children)
                    continue
                if SHAPE_REGISTRY.type_id_from_payload(data) is None:
                    raise ValueError(f"Unknown shape: {shape}")

        if isinstance(items_data, list):
            validate_items(items_data)
        return state

    def _restore_scene_state(self, state: Mapping[str, Any]) -> None:
        scene = self.scene()
        if scene is None:
            return
        state = self._validate_scene_state(state)
        items_data = state.get("items")
        self.clear_canvas()
        self._guides = self._guides_from_state(state.get("guides"))
        self._active_snap_guides.clear()
        self._layer_manager.restore_state(state.get("layers"))
        restored: list[QtWidgets.QGraphicsItem] = []
        connector_data: list[Mapping[str, Any]] = []
        if isinstance(items_data, list):
            for data in items_data:
                if not isinstance(data, Mapping):
                    continue
                if is_connector_data(data):
                    connector_data.append(data)
                    continue
                item = self._instantiate_item(data)
                if item is None:
                    continue
                scene.addItem(item)
                SceneCodec.restore_item_metadata(item, data)
                self._restore_owner_page(item, data.get("owner_page"))
                self._layer_manager.restore_item_state(item, data)
                if isinstance(item, GroupItem):
                    children = data.get("children")
                    if isinstance(children, list):
                        self._restore_group_children(item, children)
                self._apply_item_transform(item, data)
                restored.append(item)
        self._connector_manager.rebuild_item_index()
        for data in connector_data:
            connector = ConnectorItem.from_data(data)
            scene.addItem(connector)
            SceneCodec.restore_item_metadata(connector, data)
            self._restore_owner_page(connector, data.get("owner_page"))
            self._layer_manager.restore_item_state(connector, data)
            self._connector_manager.register_connector(connector)
            restored.append(connector)
        self._connector_manager.resolve_bindings()
        for item in restored:
            self._ensure_page_for_item(item, None)
        self._layer_manager.sync_items()
        scene.clearSelection()
        grid_visible = bool(state.get("grid_visible", self._show_grid))
        self._show_grid = grid_visible
        for page in self._pages.values():
            page.set_grid_visible(grid_visible)
        self.viewport().update()
        self._update_scene_rect()
        self.gridVisibilityChanged.emit(self._show_grid)

    def _page_top_left_for_index(self, index: tuple[int, int]) -> QtCore.QPointF:
        return canvas_pages.page_top_left_for_index(self, index)

    @staticmethod
    def _normalized_page_index(value: Any) -> tuple[int, int] | None:
        return canvas_pages.normalized_page_index(value)

    def _owner_page_index(
        self, item: QtWidgets.QGraphicsItem
    ) -> tuple[int, int] | None:
        return canvas_pages.owner_page_index(self, item)

    @staticmethod
    def _set_owner_page(item: QtWidgets.QGraphicsItem, index: tuple[int, int]) -> None:
        canvas_pages.set_owner_page(item, index)

    def _restore_owner_page(self, item: QtWidgets.QGraphicsItem, value: Any) -> None:
        canvas_pages.restore_owner_page(self, item, value)

    def _page_index_for_point(self, point: QtCore.QPointF) -> tuple[int, int]:
        return canvas_pages.page_index_for_point(self, point)

    def _create_page_item(self, index: tuple[int, int]) -> A4PageItem:
        return canvas_pages.create_page_item(self, index)

    def _add_page(
        self, index: tuple[int, int], *, update_edges: bool = True
    ) -> A4PageItem:
        return canvas_pages.add_page(self, index, update_edges=update_edges)

    def _ensure_pages_between_master(self, target_index: tuple[int, int]) -> None:
        canvas_pages.ensure_pages_between_master(self, target_index)

    def _update_transition_edges(self) -> None:
        canvas_pages.update_transition_edges(self)

    def _ensure_page_for_item(
        self, item: QtWidgets.QGraphicsItem, drop_reference: QtCore.QPointF | None
    ) -> A4PageItem:
        return canvas_pages.ensure_page_for_item(self, item, drop_reference)

    def _page_indices_for_rect(self, rect: QtCore.QRectF) -> set[tuple[int, int]]:
        return canvas_pages.page_indices_for_rect(self, rect)

    def _collect_canvas_content_items(self) -> list[QtWidgets.QGraphicsItem]:
        return canvas_pages.collect_canvas_content_items(self)

    def _prune_empty_pages(self) -> bool:
        return canvas_pages.prune_empty_pages(self)

    def _ensure_pages_for_items(self, items: list[QtWidgets.QGraphicsItem]) -> None:
        canvas_pages.ensure_pages_for_items(self, items)

    def fit_to_page(self) -> None:
        """Fit the master page after switching documents in an existing view."""
        self._fit_view_to_page()

    def _fit_view_to_page(self) -> None:
        if self._page_item is None:
            return
        page_scene_rect = self._page_item.mapRectToScene(self._page_item.rect())
        padded = page_scene_rect.adjusted(-80, -80, 80, 80)
        if padded.isValid() and padded.width() > 0 and padded.height() > 0:
            self.fitInView(padded, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(self._page_item)

    @_undo_transaction
    def clear_canvas(self) -> None:
        """Remove all items from the scene."""
        self._clear_hover_preview()
        scene = self.scene()
        self.set_connector_creation_enabled(False)
        self._connector_manager.reset()
        for item in list(scene.items()):
            if isinstance(item, A4PageItem):
                continue
            if item.__class__.__name__.endswith("Handle"):
                continue
            if item.parentItem() is not None:
                continue
            scene.removeItem(item)
        self._prune_empty_pages()
        self._update_scene_rect()

    def ensure_pages_for_scene_items(self) -> None:
        """Ensure every top-level scene item has an A4 page beneath it."""
        scene = self.scene()
        if scene is None:
            return
        self._ensure_pages_for_items(scene.items())

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        super().drawBackground(painter, rect)

    def drawForeground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        super().drawForeground(painter, rect)
        hover_item = self._valid_hover_preview()
        if hover_item is not None:
            draw_hover_preview(painter, hover_item)
        preview_start = self._connector_preview_start()
        preview_end = self._connector_preview_position
        draw_guides = self._guides_visible and bool(
            self._guides or self._active_snap_guides
        )
        if not draw_guides and (preview_start is None or preview_end is None):
            return
        painter.save()
        if draw_guides:
            guide_pen = QtGui.QPen(QtGui.QColor("#28c7d9"))
            guide_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            guide_pen.setCosmetic(True)
            painter.setPen(guide_pen)
            for orientation, position in self._guides:
                self._draw_guide_line(painter, rect, orientation, position)
            active_pen = QtGui.QPen(QtGui.QColor("#00cfe8"))
            active_pen.setCosmetic(True)
            active_pen.setWidth(2)
            painter.setPen(active_pen)
            for orientation, position in self._active_snap_guides.items():
                self._draw_guide_line(painter, rect, orientation, position)
        if preview_start is not None and preview_end is not None:
            preview_pen = QtGui.QPen(QtGui.QColor("#0b9ec9"))
            preview_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            preview_pen.setCosmetic(True)
            preview_pen.setWidth(2)
            painter.setPen(preview_pen)
            painter.drawLine(preview_start, preview_end)
        painter.restore()

    @staticmethod
    def _draw_guide_line(
        painter: QtGui.QPainter,
        rect: QtCore.QRectF,
        orientation: str,
        position: float,
    ) -> None:
        if orientation == "vertical":
            painter.drawLine(position, rect.top(), position, rect.bottom())
        elif orientation == "horizontal":
            painter.drawLine(rect.left(), position, rect.right(), position)

    def add_guide(self, orientation: str, position: float) -> None:
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("Guide orientation must be 'vertical' or 'horizontal'")
        guide = (orientation, float(position))
        if guide not in self._guides:
            self._guides.append(guide)
            self._guides.sort(key=lambda entry: (entry[0], entry[1]))
            self.viewport().update()
            self._history.mark_dirty()

    def move_guide(
        self, orientation: str, old_position: float, new_position: float
    ) -> bool:
        old_guide = (orientation, float(old_position))
        try:
            index = self._guides.index(old_guide)
        except ValueError:
            return False
        self._guides[index] = (orientation, float(new_position))
        self._guides.sort(key=lambda entry: (entry[0], entry[1]))
        self.viewport().update()
        self._history.mark_dirty()
        return True

    def remove_guide(self, orientation: str, position: float) -> bool:
        guide = (orientation, float(position))
        try:
            self._guides.remove(guide)
        except ValueError:
            return False
        self.viewport().update()
        self._history.mark_dirty()
        return True

    def guides(self) -> tuple[tuple[str, float], ...]:
        return tuple(self._guides)

    def guides_visible(self) -> bool:
        return self._guides_visible

    def set_guides_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._guides_visible:
            return
        self._guides_visible = visible
        self.viewport().update()
        self.guidesVisibilityChanged.emit(visible)

    def guide_near(self, orientation: str, position: float) -> tuple[str, float] | None:
        if orientation not in ("vertical", "horizontal"):
            return None
        threshold_x, threshold_y = self._snap_threshold_scene_units()
        threshold = threshold_x if orientation == "vertical" else threshold_y
        candidates = [
            guide
            for guide in self._guides
            if guide[0] == orientation and abs(guide[1] - position) <= threshold
        ]
        return min(candidates, key=lambda guide: abs(guide[1] - position), default=None)

    def ruler_ticks(
        self, scene_start: float, scene_end: float, *, major_mm: float = 10.0
    ) -> tuple[tuple[float, float], ...]:
        """Return scene positions and millimetre labels for a ruler axis."""

        if major_mm <= 0.0:
            raise ValueError("major_mm must be greater than zero")
        spacing = mm_to_px(major_mm)
        first = math.ceil(scene_start / spacing)
        last = math.floor(scene_end / spacing)
        return tuple(
            (step * spacing, step * major_mm) for step in range(first, last + 1)
        )

    def _serialize_guides(self) -> list[dict[str, float | str]]:
        return [
            {"orientation": orientation, "position": position}
            for orientation, position in self._guides
        ]

    @staticmethod
    def _guides_from_state(value: Any) -> list[tuple[str, float]]:
        if not isinstance(value, list):
            return []
        guides: list[tuple[str, float]] = []
        for entry in value:
            if not isinstance(entry, Mapping):
                continue
            orientation = entry.get("orientation")
            position = entry.get("position")
            if orientation not in ("vertical", "horizontal"):
                continue
            if isinstance(position, bool) or not isinstance(position, (int, float)):
                continue
            guides.append((orientation, float(position)))
        return sorted(set(guides), key=lambda entry: (entry[0], entry[1]))

    def _snap_threshold_scene_units(self) -> tuple[float, float]:
        return canvas_snapping.snap_threshold_scene_units(self)

    @staticmethod
    def _nearest_snap(
        values: tuple[float, ...], candidates: tuple[float, ...], threshold: float
    ) -> tuple[float, float] | None:
        return canvas_snapping.nearest_snap(values, candidates, threshold)

    def _begin_snap_drag(self) -> None:
        canvas_snapping.begin_snap_drag(self)

    def _end_snap_drag(self) -> None:
        canvas_snapping.end_snap_drag(self)

    def _invalidate_snap_drag(self) -> None:
        canvas_snapping.invalidate_snap_drag(self)

    @staticmethod
    def _nearest_sorted_snap(
        values: tuple[float, ...],
        candidates: Sequence[tuple[float, int]],
        threshold: float,
    ) -> tuple[float, float] | None:
        return canvas_snapping.nearest_sorted_snap(values, candidates, threshold)

    def snap_scene_position(
        self,
        position: QtCore.QPointF,
        size: QtCore.QSizeF | None = None,
        *,
        exclude: tuple[QtWidgets.QGraphicsItem, ...] = (),
        grid_spacing: float | None = None,
        grid_anchor: QtCore.QPointF | None = None,
    ) -> tuple[QtCore.QPointF, dict[str, float]]:
        return canvas_snapping.snap_scene_position(
            self,
            position,
            size,
            exclude=exclude,
            grid_spacing=grid_spacing,
            grid_anchor=grid_anchor,
        )

    def set_grid_snap_enabled(self, enabled: bool) -> None:
        self._grid_snap_enabled = bool(enabled)
        self._active_snap_guides.clear()
        self.viewport().update()

    def set_alignment_snap_enabled(self, enabled: bool) -> None:
        self._alignment_snap_enabled = bool(enabled)
        self._active_snap_guides.clear()
        self.viewport().update()

    def grid_snap_enabled(self) -> bool:
        return self._grid_snap_enabled

    def alignment_snap_enabled(self) -> bool:
        return self._alignment_snap_enabled

    def set_grid_visible(self, visible: bool) -> None:
        self._show_grid = visible
        for page in self._pages.values():
            page.set_grid_visible(visible)
        self.viewport().update()
        if hasattr(self, "_history"):
            self._history.mark_dirty()
        self.gridVisibilityChanged.emit(self._show_grid)

    def _on_scene_rect_changed(self, regions: list[QtCore.QRectF]) -> None:
        scene = self.scene()
        if not regions or any(
            not scene.sceneRect().contains(region) for region in regions
        ):
            self._scene_rect_timer.stop()
            self._update_scene_rect()
        else:
            # Contained edits can still shrink the content, e.g. a resized item.
            self._scene_rect_timer.start()

    def _update_scene_rect(self) -> None:
        scene = self.scene()
        padding = self._scene_padding
        items_rect = scene.itemsBoundingRect()
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        if items_rect.isNull():
            combined = viewport_rect
        else:
            combined = items_rect.united(viewport_rect)
        if combined.isNull():
            new_rect = QtCore.QRectF(
                -padding,
                -padding,
                padding * 2,
                padding * 2,
            )
        else:
            new_rect = combined.adjusted(-padding, -padding, padding, padding)
        if new_rect != scene.sceneRect():
            scene.setSceneRect(new_rect)
            # ensure newly exposed areas are repainted so drag handles don't leave trails
            self.viewport().update()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self._initial_fit_pending:
            self._initial_fit_pending = False
            # File dialogs can process timers before a new window is laid out.
            QtCore.QTimer.singleShot(0, self, self._fit_view_to_page)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """Ensure scene rect grows with the view."""
        super().resizeEvent(event)
        self._update_scene_rect()
        self.viewChanged.emit()

    def _snap_new_item(
        self, item: QtWidgets.QGraphicsItem, *, grid_spacing: float
    ) -> dict[str, float]:
        return canvas_snapping.snap_new_item(self, item, grid_spacing=grid_spacing)

    @_undo_transaction
    def add_shape(
        self,
        shape: str,
        scene_pos: QtCore.QPointF,
        snap_to_grid: bool = True,
    ) -> QtWidgets.QGraphicsItem | None:
        normalized = shape.strip()
        definition = SHAPE_REGISTRY.get(normalized)
        if definition is None:
            return None

        x = scene_pos.x()
        y = scene_pos.y()
        w, h = definition.default_size

        if snap_to_grid:
            size = self._grid_size
            if (
                normalized in ("Line", "Arrow")
                and getattr(self, "_grid_snap_enabled", True)
                and size > 0
            ):
                w = round(w / size) * size
        item = SHAPE_REGISTRY.create(normalized, x, y, w, h)
        if item is None:
            return None
        if snap_to_grid:
            self._active_snap_guides = self._snap_new_item(item, grid_spacing=size)
            x, y = item.pos().x(), item.pos().y()
        drop_reference = QtCore.QPointF(x + w / 2.0, y + h / 2.0)

        self.scene().clearSelection()
        self.scene().addItem(item)
        self._layer_manager.register_item(item)
        item.setSelected(True)
        self._ensure_page_for_item(item, drop_reference)
        self._update_scene_rect()
        return item

    @_undo_transaction
    def add_bitmap_item(
        self,
        asset: ProjectAsset,
        scene_pos: QtCore.QPointF,
        width: float | None = None,
        height: float | None = None,
    ) -> BitmapItem:
        """Add a bitmap whose bytes were already validated into this project."""

        stored = self._bitmap_assets.resolve(asset.name)
        item = BitmapItem(
            stored,
            scene_pos.x(),
            scene_pos.y(),
            width=width,
            height=height,
        )
        self.scene().addItem(item)
        self._layer_manager.register_item(item)
        item.setSelected(True)
        self._ensure_page_for_item(item, scene_pos)
        self._update_scene_rect()
        return item

    def add_shape_at_view_center(self, shape: str) -> QtWidgets.QGraphicsItem | None:
        normalized = shape.strip()
        definition = SHAPE_REGISTRY.get(normalized)
        if definition is None:
            return None

        snap = not (
            QtWidgets.QApplication.keyboardModifiers()
            & QtCore.Qt.KeyboardModifier.AltModifier
        )
        if not snap:
            self._active_snap_guides.clear()
        center = self.mapToScene(self.viewport().rect().center())
        w, h = definition.default_size
        if normalized in ("Line", "Arrow"):
            pos = QtCore.QPointF(center.x() - w / 2.0, center.y())
        else:
            pos = QtCore.QPointF(center.x() - w / 2.0, center.y() - h / 2.0)
        if (
            snap
            and normalized in ("Line", "Arrow")
            and getattr(self, "_grid_snap_enabled", True)
            and self._grid_size > 0
        ):
            w = round(w / self._grid_size) * self._grid_size
        preview = SHAPE_REGISTRY.create(normalized, pos.x(), pos.y(), w, h)
        assert preview is not None
        while True:
            preview.setPos(pos)
            if snap:
                self._snap_new_item(preview, grid_spacing=self._grid_size)
            candidate = preview.sceneBoundingRect()
            if not any(
                self._is_serializable_item(item)
                and item.sceneBoundingRect().intersects(candidate)
                for item in self.scene().items()
            ):
                break
            pos += QtCore.QPointF(self._grid_size, self._grid_size)
        return self.add_shape(normalized, pos, snap_to_grid=snap)

    # --- Drag and drop from the palette ---
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        md = event.mimeData()
        if md.hasFormat(PALETTE_MIME) or md.hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(PALETTE_MIME) or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        md = event.mimeData()
        text = ""
        if md.hasFormat(PALETTE_MIME):
            text = str(bytes(md.data(PALETTE_MIME)).decode("utf-8"))
        elif md.hasText():
            text = md.text()

        shape = text.strip()
        if SHAPE_REGISTRY.get(shape) is None:
            super().dropEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        snap = not (event.keyboardModifiers() & QtCore.Qt.KeyboardModifier.AltModifier)
        item = self.add_shape(shape, scene_pos, snap_to_grid=snap)
        if item is not None:
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # --- Duplicate selected items with Ctrl+drag ---
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if (
            self._connector_creation_enabled
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            self._handle_connector_click(event.position().toPoint())
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_snap_drag()
            self._history.begin_transaction()
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self._prev_drag_mode = self.dragMode()
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self._right_button_pressed = True
            self._pan_start = event.position()
            self._prev_drag_mode = self.dragMode()
            self._suppress_context_menu = False
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            mods = event.modifiers()
            if mods & (
                QtCore.Qt.KeyboardModifier.ControlModifier
                | QtCore.Qt.KeyboardModifier.ShiftModifier
            ):
                item = self.itemAt(event.pos())
                if item:
                    if (
                        mods & QtCore.Qt.KeyboardModifier.ControlModifier
                        and item.isSelected()
                    ):
                        selected = self.scene().selectedItems()
                        if selected:
                            # Store initial state but postpone cloning until the mouse
                            # has moved far enough to avoid duplicates appearing in place.
                            self._dup_source = list(selected)
                            self._dup_items = None
                            self._dup_orig = None
                            self._dup_start = self.mapToScene(
                                event.position().toPoint()
                            )
                        event.accept()
                        return
                    else:
                        item.setSelected(True)
                        event.accept()
                        return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        hover_item = None
        if not event.buttons() and not self._connector_creation_enabled:
            hover_item = self._hover_preview_target_at(event.position().toPoint())
        self._set_hover_preview_item(hover_item)
        canvas_interaction.mouse_move_event(self, event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._end_snap_drag()
            self._active_snap_guides.clear()
            self.viewport().update()
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            if self._panning:
                self._panning = False
                self._right_button_pressed = False
                self.setDragMode(self._prev_drag_mode)
                self.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
                self._suppress_context_menu = True
                event.accept()
                return
            if self._right_button_pressed:
                self._right_button_pressed = False
                event.accept()
                return
        if event.button() == QtCore.Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setDragMode(self._prev_drag_mode)
            self.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if getattr(self, "_dup_items", None):
                self._dup_items = []
                self._dup_orig = []
                self._dup_source = []
                self._ensure_pages_for_items(self.scene().selectedItems())
                event.accept()
                if self._history.transaction_active:
                    self._history.end_transaction()
                return
            if getattr(self, "_dup_source", None):
                # Ctrl+click without enough movement -> no duplication
                self._dup_source = []
                event.accept()
                if self._history.transaction_active:
                    self._history.end_transaction()
                return
        super().mouseReleaseEvent(event)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._ensure_pages_for_items(self.scene().selectedItems())
            if self._history.transaction_active:
                self._history.end_transaction()

    def _snap_selected_items(self) -> None:
        canvas_snapping.snap_selected_items(self)

    def _clone_item(
        self, item: QtWidgets.QGraphicsItem
    ) -> QtWidgets.QGraphicsItem | None:
        registry_data = SHAPE_REGISTRY.serialize(item)
        if registry_data is not None:
            clone = SHAPE_REGISTRY.restore(registry_data)
            if clone is None:
                return None
        elif isinstance(item, BitmapItem):
            size = item.item_size()
            clone = BitmapItem(
                self._bitmap_assets.ensure(item.asset),
                item.x(),
                item.y(),
                size.width(),
                size.height(),
            )
        else:
            return None
        if isinstance(item, ShapeLabelMixin) and isinstance(clone, ShapeLabelMixin):
            clone.copy_label_from(item)
        clone.setPos(item.pos())
        clone.setTransform(item.transform())
        clone.setRotation(item.rotation())
        clone.setScale(item.scale())
        clone.setZValue(item.zValue())
        clone.setData(0, item.data(0))
        clone.setData(KEY_LAYER_ID, self._layer_manager.layer_for_item(item).id)
        SceneCodec._item_id(clone)
        self._layer_manager.register_item(clone)
        return clone

    # --- Mouse wheel zooming and scrolling ---
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        mods = event.modifiers()
        if mods & (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
        ):
            anchor = self.transformationAnchor()
            self.setTransformationAnchor(
                QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse
            )
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.angleDelta().x()
            factor = 1.2 if delta > 0 else 1 / 1.2
            self.scale(factor, factor)
            # Cosmetic pens are measured in device pixels, so cached snap
            # envelopes are stale once the view transform changes mid-drag.
            self._invalidate_snap_drag()
            self.setTransformationAnchor(anchor)
            self._update_scene_rect()
            self.viewChanged.emit()
            event.accept()
            return
        super().wheelEvent(event)

    @_undo_transaction
    def _group_selected_items(self) -> None:
        selected = [
            item
            for item in self.scene().selectedItems()
            if item.parentItem() is None and not isinstance(item, ConnectorItem)
        ]
        if len(selected) < 2:
            return

        br = QtCore.QRectF()
        for it in selected:
            br = br.united(it.sceneBoundingRect())

        group = GroupItem()
        group.setPos(br.topLeft())
        self.scene().addItem(group)

        for it in selected:
            group.addToGroup(it)
            it.setSelected(False)
            it.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            it.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            if isinstance(it, HandleAwareItemMixin):
                it.hide_handles()

        group.setTransformOriginPoint(group.boundingRect().center())
        group.setSelected(True)
        group.update_handles()
        # Restoring a snapshot assigns a page to every item; assign it here too
        # so the snapshot taken right after grouping matches its restored scene.
        self._ensure_page_for_item(group, group.sceneBoundingRect().center())
        self._update_scene_rect()

    @_undo_transaction
    def _ungroup_selected_items(self) -> None:
        groups = [
            item
            for item in self.scene().selectedItems()
            if item.parentItem() is None and isinstance(item, GroupItem)
        ]
        changed = bool(groups)
        while groups:
            group = groups.pop()
            group.setSelected(False)
            children = [
                child
                for child in group.childItems()
                if not isinstance(child, (ResizeHandle, RotationHandle))
            ]
            for child in children:
                # removeFromGroup preserves the complete scene transform.
                group.removeFromGroup(child)
                if isinstance(child, GroupItem):
                    groups.append(child)
                    continue
                locked = bool(getattr(child, "locked", False))
                child.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,
                    not locked,
                )
                child.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                    not locked,
                )
                child.setSelected(False)
            self.scene().removeItem(group)
        if changed:
            self.scene().clearSelection()
            self._prune_empty_pages()
            self._update_scene_rect()

    def _copy_selected_items(self) -> bool:
        items = [
            item
            for item in self.scene().items(QtCore.Qt.SortOrder.AscendingOrder)
            if item.isSelected()
            and item.parentItem() is None
            and self._is_serializable_item(item)
            and not SceneCodec.is_transient(item)
        ]
        if not items:
            return False
        try:
            records = SceneCodec.serialize_items(items, self._serialize_item)
            encoded = ClipboardService.encode(
                records, assets=bitmap_assets_for_items(items, self.bitmap_assets())
            )
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            logging.getLogger(__name__).warning(
                "Cannot copy scene items (%s)", type(error).__name__
            )
            return False
        mime = QtCore.QMimeData()
        mime.setData(CLIPBOARD_MIME_TYPE, encoded)
        QtWidgets.QApplication.clipboard().setMimeData(mime)
        return True

    @_undo_transaction
    def _paste_clipboard_items(self, scene_position: QtCore.QPointF) -> bool:
        mime = QtWidgets.QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(CLIPBOARD_MIME_TYPE):
            return False

        # Restore into a detached canvas first, so invalid shapes/assets cannot
        # partially change the destination. Reuse the document's restore rules.
        staging = CanvasView()
        try:
            try:
                paste = ClipboardService.prepare_paste(
                    bytes(mime.data(CLIPBOARD_MIME_TYPE)),
                    existing_item_ids=(
                        item.data(KEY_ITEM_ID)
                        for item in self.scene().items()
                        if item.data(KEY_ITEM_ID) is not None
                    ),
                    existing_assets=self.bitmap_assets(),
                )
                if not paste.items:
                    return False
                staging.set_bitmap_assets((*self.bitmap_assets(), *paste.assets_to_add))
                staging._restore_scene_state(
                    {
                        "items": list(paste.items),
                        "layers": self._layer_manager.serialize_state(),
                        "grid_visible": self._show_grid,
                    }
                )
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                logging.getLogger(__name__).warning(
                    "Cannot paste scene items (%s)", type(error).__name__
                )
                return False

            items = [
                item
                for item in staging.scene().items(QtCore.Qt.SortOrder.AscendingOrder)
                if item.parentItem() is None and staging._is_serializable_item(item)
            ]
            if not items:
                return False
            bounds = QtCore.QRectF()
            for item in items:
                item_bounds = item_snap_bounds(item, self)
                if item_bounds is not None:
                    bounds = bounds.united(item_bounds)
            if bounds.isNull():
                bounds = items[0].sceneBoundingRect()
            delta = scene_position - bounds.topLeft()
            staging._connector_manager.reset()
            staging._grid_size_min = 0
            for item in items:
                if isinstance(item, ConnectorItem):
                    item.start_endpoint = replace(
                        item.start_endpoint,
                        position=item.start_endpoint.position + delta,
                    )
                    item.end_endpoint = replace(
                        item.end_endpoint, position=item.end_endpoint.position + delta
                    )
                else:
                    item.moveBy(delta.x(), delta.y())

            self._bitmap_assets = staging._bitmap_assets
            self.scene().clearSelection()
            for item in items:
                staging.scene().removeItem(item)
                self.scene().addItem(item)
                self._layer_manager.register_item(item)
                self._ensure_page_for_item(item, item.sceneBoundingRect().center())
            self._connector_manager.rebuild_item_index()
            for item in items:
                if isinstance(item, ConnectorItem):
                    self._connector_manager.register_connector(item)
                item.setSelected(True)
            self._connector_manager.resolve_bindings()
            self._history.mark_dirty()
            self._update_scene_rect()
            return True
        finally:
            staging.close()
            staging.deleteLater()

    # --- Canvas keyboard commands; active text editors keep Qt copy/paste. ---
    @_undo_transaction
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        copy = event.matches(QtGui.QKeySequence.StandardKey.Copy)
        paste = event.matches(QtGui.QKeySequence.StandardKey.Paste)
        if copy or paste:
            focus = self.scene().focusItem()
            if isinstance(focus, QtWidgets.QGraphicsTextItem) and (
                focus.textInteractionFlags()
                & QtCore.Qt.TextInteractionFlag.TextEditable
            ):
                super().keyPressEvent(event)
                return
            if copy:
                self._copy_selected_items()
            else:
                position = self.viewport().mapFromGlobal(QtGui.QCursor.pos())
                if self.viewport().rect().contains(position):
                    self._paste_clipboard_items(self.mapToScene(position))
            event.accept()
            return
        if self._connector_creation_enabled and event.key() == QtCore.Qt.Key.Key_Escape:
            self.set_connector_creation_enabled(False)
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Delete:
            selected = self.scene().selectedItems()
            if selected:
                for it in selected:
                    self.scene().removeItem(it)
                self._prune_empty_pages()
                self._update_scene_rect()
                event.accept()
                return
        mods = event.modifiers()
        if mods & QtCore.Qt.KeyboardModifier.ControlModifier:
            if event.key() == QtCore.Qt.Key.Key_Z:
                if mods & QtCore.Qt.KeyboardModifier.ShiftModifier:
                    self.redo()
                else:
                    self.undo()
                event.accept()
                return
            if event.key() == QtCore.Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return
        if (
            event.key() == QtCore.Qt.Key.Key_G
            and mods == QtCore.Qt.KeyboardModifier.ControlModifier
        ):
            self._group_selected_items()
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_G and mods == (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.ShiftModifier
        ):
            self._ungroup_selected_items()
            event.accept()
            return
        super().keyPressEvent(event)

    # --- Alignment helpers ---
    @_undo_transaction
    def _align_items(self, items: Iterable[QtWidgets.QGraphicsItem], mode: str) -> None:
        canvas_alignment.align_items(items, mode, self._grid_size)

    def _create_color_action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        title: str,
        color_getter: Callable[[], QtGui.QColor],
        color_setter: Callable[[QtGui.QColor], None],
    ) -> tuple[QtGui.QAction, Callable[[], None]]:
        return canvas_context_menu.create_color_action(
            self, menu, text, title, color_getter, color_setter
        )

    def _create_double_action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        dialog_title: str,
        label: str,
        value_getter: Callable[[], float],
        value_setter: Callable[[float], None],
        minimum: float,
        maximum: float,
        decimals: int,
    ) -> tuple[QtGui.QAction, Callable[[], None]]:
        return canvas_context_menu.create_double_action(
            self,
            menu,
            text,
            dialog_title,
            label,
            value_getter,
            value_setter,
            minimum,
            maximum,
            decimals,
        )

    def _add_shape_label_actions(
        self, menu: QtWidgets.QMenu, item: ShapeLabelMixin
    ) -> dict[QtGui.QAction, Callable[[], None]]:
        return canvas_context_menu.add_shape_label_actions(self, menu, item)

    def _create_shape_style_actions(
        self, menu: QtWidgets.QMenu, item: QtWidgets.QGraphicsItem
    ) -> dict[QtGui.QAction, Callable[[], None]]:
        return canvas_context_menu.create_shape_style_actions(self, menu, item)

    # --- Context menu for adjusting colors and line width ---
    @_undo_transaction
    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        canvas_context_menu.contextMenuEvent(self, event)
