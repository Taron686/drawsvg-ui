# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import json
import math
from collections.abc import Mapping
from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QTransform

from constants import PALETTE_MIME, SHAPES, DEFAULTS
from items import (
    BlockArrowItem,
    CurvyBracketItem,
    DiamondItem,
    EllipseItem,
    FolderTreeItem,
    GroupItem,
    LineItem,
    RectItem,
    ResizableItem,
    ResizeHandle,
    RotationHandle,
    ShapeLabelMixin,
    SplitRoundedRectItem,
    TextItem,
    TriangleItem,
)

A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
SCREEN_DPI = 96  # Typical desktop DPI


def _enum_to_int(value: Any) -> int:
    """Return an integer value for Qt enum instances."""
    if hasattr(value, "value"):
        value = value.value
    return int(value)


def mm_to_px(mm: float, dpi: float = SCREEN_DPI) -> float:
    return mm / 25.4 * dpi


def _snap_coordinate(value: float, spacing: float, origin: float) -> float:
    if spacing <= 0.0:
        return value
    return round((value - origin) / spacing) * spacing + origin


def _color_to_data(color: QtGui.QColor) -> dict[str, float | str]:
    return {"name": color.name(), "alpha": float(color.alphaF())}


def _color_from_data(data: Mapping[str, Any] | None) -> QtGui.QColor:
    name = "#000000"
    alpha = 1.0
    if data:
        name = str(data.get("name", name))
        alpha = float(data.get("alpha", alpha))
    color = QtGui.QColor(name)
    color.setAlphaF(alpha)
    return color


def _brush_to_data(brush: QtGui.QBrush) -> dict[str, Any]:
    style = _enum_to_int(brush.style())
    data: dict[str, Any] = {"style": style}
    if style != _enum_to_int(QtCore.Qt.BrushStyle.NoBrush):
        data["color"] = _color_to_data(brush.color())
    return data


def _brush_from_data(data: Mapping[str, Any] | None) -> QtGui.QBrush:
    default_style = _enum_to_int(QtCore.Qt.BrushStyle.NoBrush)
    style_val = int(data.get("style", default_style)) if data else default_style
    brush = QtGui.QBrush(QtCore.Qt.BrushStyle(style_val))
    if style_val != _enum_to_int(QtCore.Qt.BrushStyle.NoBrush) and data is not None:
        color_data = data.get("color")
        if isinstance(color_data, Mapping):
            brush.setColor(_color_from_data(color_data))
    return brush


def _pen_to_data(pen: QtGui.QPen) -> dict[str, Any]:
    data: dict[str, Any] = {
        "color": _color_to_data(pen.color()),
        "width": float(pen.widthF()),
        "style": _enum_to_int(pen.style()),
        "cap": _enum_to_int(pen.capStyle()),
        "join": _enum_to_int(pen.joinStyle()),
        "cosmetic": bool(pen.isCosmetic()),
    }
    pattern = pen.dashPattern()
    if pattern:
        data["dash"] = [float(value) for value in pattern]
    return data


def _pen_from_data(data: Mapping[str, Any] | None) -> QtGui.QPen:
    pen = QtGui.QPen()
    if not data:
        return pen
    color_data = data.get("color")
    if isinstance(color_data, Mapping):
        pen.setColor(_color_from_data(color_data))
    if "width" in data:
        pen.setWidthF(float(data["width"]))
    if "style" in data:
        try:
            pen.setStyle(QtCore.Qt.PenStyle(int(data["style"])))
        except ValueError:
            pass
    if "cap" in data:
        try:
            pen.setCapStyle(QtCore.Qt.PenCapStyle(int(data["cap"])))
        except ValueError:
            pass
    if "join" in data:
        try:
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle(int(data["join"])))
        except ValueError:
            pass
    if "cosmetic" in data:
        pen.setCosmetic(bool(data["cosmetic"]))
    if pen.style() == QtCore.Qt.PenStyle.CustomDashLine and "dash" in data:
        pattern = data.get("dash")
        if isinstance(pattern, (list, tuple)):
            pen.setDashPattern([float(value) for value in pattern])
    return pen


def _describe_font_size(font: QtGui.QFont) -> str | None:
    pixel_size = font.pixelSize()
    if pixel_size and pixel_size > 0:
        return f"{pixel_size:g} px"
    point_size_f = font.pointSizeF()
    if point_size_f and point_size_f > 0:
        if abs(point_size_f - round(point_size_f)) < 0.01:
            return f"{int(round(point_size_f))} pt"
        return f"{point_size_f:.1f} pt"
    point_size = font.pointSize()
    if point_size and point_size > 0:
        return f"{point_size:g} pt"
    return None


def _serialize_shape_label(item: ShapeLabelMixin) -> dict[str, Any] | None:
    if not isinstance(item, ShapeLabelMixin):
        return None
    label = item.label_item()
    data: dict[str, Any] = {
        "text": item.label_text(),
        "alignment": list(item.label_alignment()),
        "font": label.font().toString(),
        "color": _color_to_data(label.defaultTextColor()),
    }
    font_size = _describe_font_size(label.font())
    if font_size:
        data["font_size"] = font_size
    if item.label_has_custom_color():
        data["color_override"] = True
    return data


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


class SceneHistory(QtCore.QObject):
    historyChanged = QtCore.Signal(bool, bool)

    def __init__(self, view: "CanvasView", *, max_states: int = 50) -> None:
        super().__init__(view)
        self._view = view
        self._max_states = max(1, int(max_states))
        self._states: list[str] = []
        self._index = -1
        self._ignore_changes = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._capture_snapshot)
        scene = view.scene()
        if scene is not None:
            scene.changed.connect(self._on_scene_changed)

    def capture_initial_state(self) -> None:
        self._states.clear()
        self._index = -1
        self._capture_snapshot(force=True)
        self._notify()

    def mark_dirty(self) -> None:
        if self._ignore_changes:
            return
        self._timer.start()

    def capture_now(self) -> None:
        self._capture_snapshot()

    def undo(self) -> None:
        if not self.can_undo():
            return
        self._index -= 1
        self._apply_current_state()
        self._notify()

    def redo(self) -> None:
        if not self.can_redo():
            return
        self._index += 1
        self._apply_current_state()
        self._notify()

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return 0 <= self._index < len(self._states) - 1

    def _notify(self) -> None:
        self.historyChanged.emit(self.can_undo(), self.can_redo())

    def _on_scene_changed(self, _region: list[QtCore.QRectF]) -> None:  # type: ignore[override]
        if self._ignore_changes:
            return
        self._timer.start()

    def _serialize_state(self) -> str:
        state = self._view._serialize_scene_state()
        return json.dumps(state, sort_keys=True, separators=(",", ":"))

    def _capture_snapshot(self, force: bool = False) -> None:
        if self._ignore_changes:
            return
        state_str = self._serialize_state()
        if not force and self._index >= 0 and self._states[self._index] == state_str:
            return
        if self._index < len(self._states) - 1:
            self._states = self._states[: self._index + 1]
        self._states.append(state_str)
        if len(self._states) > self._max_states:
            overflow = len(self._states) - self._max_states
            self._states = self._states[overflow:]
            self._index = len(self._states) - 1
        else:
            self._index = len(self._states) - 1
        self._notify()

    def _apply_current_state(self) -> None:
        if not (0 <= self._index < len(self._states)):
            return
        state_str = self._states[self._index]
        state = json.loads(state_str)
        self._ignore_changes = True
        self._timer.stop()
        try:
            self._view._restore_scene_state(state)
        finally:
            self._ignore_changes = False

# Minimum mouse movement (in scene coordinates) required before
# showing duplicates when Ctrl+dragging selected items.
DUPLICATE_DRAG_THRESHOLD = 10.0


class CornerRadiusDialog(QtWidgets.QDialog):
    valueChanged = QtCore.Signal(int)

    def __init__(self, radius: float, parent=None):
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

    def __init__(self, value: float, parent=None):
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._owned_items: set[QtWidgets.QGraphicsItem] = set()

    def addItem(self, item: QtWidgets.QGraphicsItem) -> None:  # type: ignore[override]
        super().addItem(item)
        self._owned_items.add(item)

    def removeItem(self, item: QtWidgets.QGraphicsItem) -> None:  # type: ignore[override]
        super().removeItem(item)
        self._owned_items.discard(item)

    def clear(self) -> None:  # type: ignore[override]
        super().clear()
        self._owned_items.clear()


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
    ):
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

    def set_grid_spacing(self, grid_px: int, subgrid_px: int) -> None:
        self._grid_px = max(1, grid_px)
        self._subgrid_px = max(1, subgrid_px)
        self.update()

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
        widget=None,
    ) -> None:
        super().paint(painter, option, widget)

        page_rect = self.rect()

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
        has_right_neighbor = self._neighbors["right"]
        has_top_neighbor = self._neighbors["top"]
        has_bottom_neighbor = self._neighbors["bottom"]

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

        if not self._grid_visible:
            return

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
            if math.isclose(offset, spacing, abs_tol=1e-6) or math.isclose(offset, 0.0, abs_tol=1e-6):
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


class CanvasView(QtWidgets.QGraphicsView):
    gridVisibilityChanged = QtCore.Signal(bool)
    selectionSnapshotChanged = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.RubberBandDrag)
        # Style the selection rubber band with a blue dashed outline
        self.viewport().setStyleSheet(
            "QRubberBand { border: 1px dashed #14b5ff; }"
        )
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
        scene.changed.connect(self._update_scene_rect)
        self.setScene(scene)
        self.setBackgroundBrush(QtGui.QColor("#f0f0f0"))
        self._grid_size = 50
        self._grid_size_min = 10
        self._show_grid = True
        self._page_width = mm_to_px(A4_WIDTH_MM, SCREEN_DPI)
        self._page_height = mm_to_px(A4_HEIGHT_MM, SCREEN_DPI)
        self._master_index: tuple[int, int] = (0, 0)
        self._pages: dict[tuple[int, int], A4PageItem] = {}
        self._master_origin = self._page_top_left_for_index(self._master_index)
        self._page_item = self._create_page_item(self._master_index)
        self._pages[self._master_index] = self._page_item
        scene.addItem(self._page_item)
        self._update_transition_edges()
        QtCore.QTimer.singleShot(0, self._fit_view_to_page)
        self._update_scene_rect()

        self._panning = False
        self._pan_start = QtCore.QPointF()
        self._prev_drag_mode = self.dragMode()
        self._right_button_pressed = False
        self._suppress_context_menu = False

        self._history = SceneHistory(self)
        self._history.capture_initial_state()

        scene.selectionChanged.connect(self._notify_selection_snapshot)
        scene.changed.connect(self._on_scene_contents_changed)
        self._notify_selection_snapshot()

    def history(self) -> SceneHistory:
        return self._history

    def undo(self) -> None:
        self._history.undo()

    def redo(self) -> None:
        self._history.redo()

    # --- Serialization helpers for undo/redo ---
    def _is_serializable_item(self, item: QtWidgets.QGraphicsItem) -> bool:
        if isinstance(item, A4PageItem):
            return False
        name = item.__class__.__name__
        if name.endswith("Handle"):
            return False
        if isinstance(item, QtWidgets.QGraphicsItemGroup) and name == "QGraphicsItemGroup":
            return False
        return True

    def _item_sort_key(self, item: QtWidgets.QGraphicsItem) -> tuple[float, str, float, float]:
        shape = str(item.data(0)) if item.data(0) else item.__class__.__name__
        pos = item.pos()
        return (
            round(float(item.zValue()), 6),
            shape,
            round(float(pos.x()), 6),
            round(float(pos.y()), 6),
        )

    def _serialize_scene_state(self) -> dict[str, Any]:
        scene = self.scene()
        if scene is None:
            return {"items": [], "grid_visible": bool(self._show_grid)}
        items = [
            item
            for item in scene.items()
            if self._is_serializable_item(item) and item.parentItem() is None
        ]
        items.sort(key=self._item_sort_key)
        return {
            "items": [self._serialize_item(item) for item in items],
            "grid_visible": bool(self._show_grid),
        }

    def _serialize_item(self, item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
        shape_value = item.data(0)
        shape = str(shape_value) if shape_value else item.__class__.__name__
        base: dict[str, Any] = {
            "shape": shape,
            "class": item.__class__.__name__,
            "pos": [float(item.pos().x()), float(item.pos().y())],
            "rotation": float(item.rotation()),
            "scale": float(item.scale()),
            "z": float(item.zValue()),
        }

        if isinstance(item, RectItem):
            rect = item.rect()
            base["size"] = [float(rect.width()), float(rect.height())]
            base["rx"] = float(getattr(item, "rx", 0.0))
            base["ry"] = float(getattr(item, "ry", 0.0))
            base["pen"] = _pen_to_data(item.pen())
            base["brush"] = _brush_to_data(item.brush())
            label = _serialize_shape_label(item)
            if label:
                base["label"] = label
        elif isinstance(item, SplitRoundedRectItem):
            rect = item.rect()
            base["size"] = [float(rect.width()), float(rect.height())]
            base["rx"] = float(getattr(item, "rx", 0.0))
            base["ry"] = float(getattr(item, "ry", 0.0))
            base["divider_ratio"] = float(item.divider_ratio())
            base["pen"] = _pen_to_data(item.pen())
            base["bottom_brush"] = _brush_to_data(item.bottomBrush())
            base["top_brush"] = _brush_to_data(item.topBrush())
        elif isinstance(item, EllipseItem):
            rect = item.rect()
            base["size"] = [float(rect.width()), float(rect.height())]
            base["pen"] = _pen_to_data(item.pen())
            base["brush"] = _brush_to_data(item.brush())
            label = _serialize_shape_label(item)
            if label:
                base["label"] = label
        elif isinstance(item, TriangleItem):
            rect = item.boundingRect()
            base["size"] = [float(rect.width()), float(rect.height())]
            base["pen"] = _pen_to_data(item.pen())
            base["brush"] = _brush_to_data(item.brush())
        elif isinstance(item, DiamondItem):
            rect = item.boundingRect()
            base["size"] = [float(rect.width()), float(rect.height())]
            base["pen"] = _pen_to_data(item.pen())
            base["brush"] = _brush_to_data(item.brush())
            label = _serialize_shape_label(item)
            if label:
                base["label"] = label
        elif isinstance(item, BlockArrowItem):
            rect = item.boundingRect()
            base["size"] = [float(rect.width()), float(rect.height())]
            base["pen"] = _pen_to_data(item.pen())
            base["brush"] = _brush_to_data(item.brush())
            base["head_ratio"] = float(item.head_ratio())
            base["shaft_ratio"] = float(item.shaft_ratio())
        elif isinstance(item, LineItem):
            points = getattr(item, "_points", [])
            base["points"] = [
                [float(point.x()), float(point.y())]
                for point in points
            ]
            base["arrow_start"] = bool(getattr(item, "arrow_start", False))
            base["arrow_end"] = bool(getattr(item, "arrow_end", False))
            length_getter = getattr(item, "arrow_head_length", None)
            width_getter = getattr(item, "arrow_head_width", None)
            if callable(length_getter) and callable(width_getter):
                base["arrow_head"] = {
                    "length": float(length_getter()),
                    "width": float(width_getter()),
                }
            base["pen"] = _pen_to_data(item.pen())
        elif isinstance(item, CurvyBracketItem):
            base["size"] = [float(item.width()), float(item.height())]
            base["hook_ratio"] = float(item.hook_ratio())
            base["pen"] = _pen_to_data(item.pen())
        elif isinstance(item, TextItem):
            rect = item.boundingRect()
            base["size"] = [float(rect.width()), float(rect.height())]
            base["text"] = item.toPlainText()
            base["font"] = item.font().toString()
            font_size = _describe_font_size(item.font())
            if font_size:
                base["font_size"] = font_size
            base["color"] = _color_to_data(item.defaultTextColor())
            doc = item.document()
            if doc is not None:
                base["document_margin"] = float(doc.documentMargin())
            h_align, v_align = item.text_alignment()
            base["alignment"] = [h_align, v_align]
            base["direction"] = item.text_direction()
        elif isinstance(item, FolderTreeItem):
            base["structure"] = item.structure()
        elif isinstance(item, GroupItem):
            children = [
                child
                for child in item.childItems()
                if self._is_serializable_item(child)
            ]
            children.sort(key=self._item_sort_key)
            base["children"] = [self._serialize_item(child) for child in children]
        else:
            width, height = self._item_dimensions(item)
            base["size"] = [width, height]
        return base

    def _format_property_name(self, key: str) -> str:
        if not key:
            return ""
        parts = key.split("_")
        return " ".join(part.capitalize() if part else "" for part in parts)

    def _format_property_value(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.2f}"
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (list, tuple)):
            return ", ".join(self._format_property_value(v) for v in value)
        if isinstance(value, Mapping):
            return "; ".join(
                f"{self._format_property_name(str(k))}: {self._format_property_value(v)}"
                for k, v in value.items()
            )
        return str(value)

    def _build_properties_for_item(
        self, item: QtWidgets.QGraphicsItem
    ) -> tuple[
        str,
        list[tuple[str, str]],
        list[tuple[str, str]] | None,
        dict[str, Any],
        dict[str, Any] | None,
    ]:
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

        object_properties: list[tuple[str, str]] = []
        for key, value in object_data.items():
            if key == "shape":
                continue
            object_properties.append(
                (self._format_property_name(str(key)), self._format_property_value(value))
            )

        text_properties: list[tuple[str, str]] | None = None
        if text_data:
            text_properties = []
            for key, value in text_data.items():
                text_properties.append(
                    (self._format_property_name(str(key)), self._format_property_value(value))
                )

        plain_text_data: dict[str, Any] | None = dict(text_data) if text_data else None

        return title, object_properties, text_properties, object_data, plain_text_data

    def _build_selection_snapshot(self) -> dict[str, Any]:
        scene = self.scene()
        if scene is None:
            return {"selection_type": "none"}
        selected = [
            item
            for item in scene.selectedItems()
            if self._is_serializable_item(item)
        ]
        if len(selected) == 1:
            item = selected[0]
            (
                title,
                object_props,
                text_props,
                object_data,
                text_data,
            ) = self._build_properties_for_item(item)
            return {
                "selection_type": "single",
                "title": title,
                "properties": object_props,
                "text_properties": text_props,
                "item": item,
                "object_data": object_data,
                "text_data": text_data,
            }
        if selected:
            return {"selection_type": "multi", "count": len(selected)}
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
        if isinstance(width_attr, (int, float)) and isinstance(height_attr, (int, float)):
            return float(width_attr), float(height_attr)
        bounds = item.boundingRect()
        return float(bounds.width()), float(bounds.height())

    def _notify_selection_snapshot(self) -> None:
        payload = self._build_selection_snapshot()
        self.selectionSnapshotChanged.emit(payload)

    def _on_scene_contents_changed(self, _changes) -> None:
        scene = self.scene()
        if scene is None:
            return
        if any(self._is_serializable_item(item) for item in scene.selectedItems()):
            self._notify_selection_snapshot()

    def _apply_item_transform(self, item: QtWidgets.QGraphicsItem, data: Mapping[str, Any]) -> None:
        pos = data.get("pos", [0.0, 0.0])
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            item.setPos(float(pos[0]), float(pos[1]))
        rotation = data.get("rotation")
        if rotation is not None:
            item.setRotation(float(rotation))
        scale = data.get("scale")
        if scale is not None:
            item.setScale(float(scale))
        z_val = data.get("z")
        if z_val is not None:
            item.setZValue(float(z_val))

    def _instantiate_item(self, data: Mapping[str, Any]) -> QtWidgets.QGraphicsItem | None:
        shape = str(data.get("shape", ""))
        size = data.get("size")
        width = height = None
        if isinstance(size, (list, tuple)) and len(size) == 2:
            width = float(size[0])
            height = float(size[1])
        pen_data = data.get("pen") if isinstance(data, Mapping) else None
        brush_data = data.get("brush") if isinstance(data, Mapping) else None
        item: QtWidgets.QGraphicsItem | None = None

        if shape in ("Rectangle", "Rounded Rectangle"):
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (160.0, 100.0))
            rx = float(data.get("rx", 0.0))
            ry = float(data.get("ry", rx))
            item = RectItem(0.0, 0.0, width, height, rx, ry)
            item.setPen(_pen_from_data(pen_data))
            item.setBrush(_brush_from_data(brush_data))
            label_data = data.get("label") if isinstance(data, Mapping) else None
            if label_data:
                _apply_shape_label(item, label_data)  # type: ignore[arg-type]
        elif shape == "Split Rounded Rectangle":
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (180.0, 120.0))
            rx = float(data.get("rx", 0.0))
            ry = float(data.get("ry", rx))
            item = SplitRoundedRectItem(0.0, 0.0, width, height, rx, ry)
            item.setPen(_pen_from_data(pen_data))
            bottom_data = data.get("bottom_brush") if isinstance(data, Mapping) else None
            top_data = data.get("top_brush") if isinstance(data, Mapping) else None
            item.setBottomBrush(_brush_from_data(bottom_data))
            item.setTopBrush(_brush_from_data(top_data))
            divider = data.get("divider_ratio")
            if divider is not None:
                item.set_divider_ratio(float(divider))
        elif shape in ("Ellipse", "Circle"):
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (160.0, 100.0))
            item = EllipseItem(0.0, 0.0, width, height)
            item.setPen(_pen_from_data(pen_data))
            item.setBrush(_brush_from_data(brush_data))
        elif shape == "Triangle":
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (160.0, 100.0))
            item = TriangleItem(0.0, 0.0, width, height)
            item.setPen(_pen_from_data(pen_data))
            item.setBrush(_brush_from_data(brush_data))
        elif shape == "Diamond":
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (140.0, 140.0))
            item = DiamondItem(0.0, 0.0, width, height)
            item.setPen(_pen_from_data(pen_data))
            item.setBrush(_brush_from_data(brush_data))
            label_data = data.get("label") if isinstance(data, Mapping) else None
            if label_data:
                _apply_shape_label(item, label_data)
        elif shape == "Block Arrow":
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (200.0, 120.0))
            item = BlockArrowItem(0.0, 0.0, width, height)
            item.setPen(_pen_from_data(pen_data))
            item.setBrush(_brush_from_data(brush_data))
            head_ratio = data.get("head_ratio")
            if head_ratio is not None:
                item.set_head_ratio(float(head_ratio))
            shaft_ratio = data.get("shaft_ratio")
            if shaft_ratio is not None:
                item.set_shaft_ratio(float(shaft_ratio))
        elif shape in ("Line", "Arrow"):
            points_raw = data.get("points")
            points: list[QtCore.QPointF] = []
            if isinstance(points_raw, list):
                for point in points_raw:
                    if isinstance(point, (list, tuple)) and len(point) == 2:
                        points.append(QtCore.QPointF(float(point[0]), float(point[1])))
            arrow_start = bool(data.get("arrow_start", False))
            arrow_end = bool(data.get("arrow_end", False))
            arrow_head_data = data.get("arrow_head")
            arrow_head_length: float | None = None
            arrow_head_width: float | None = None
            if isinstance(arrow_head_data, Mapping):
                length_value = arrow_head_data.get("length")
                width_value = arrow_head_data.get("width")
                if length_value is not None:
                    arrow_head_length = float(length_value)
                if width_value is not None:
                    arrow_head_width = float(width_value)
            item = LineItem(
                0.0,
                0.0,
                points=points or None,
                arrow_start=arrow_start,
                arrow_end=arrow_end,
                arrow_head_length=arrow_head_length,
                arrow_head_width=arrow_head_width,
            )
            item.setPen(_pen_from_data(pen_data))
        elif shape == "Curvy Right Bracket":
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (80.0, 160.0))
            hook_ratio = float(data.get("hook_ratio", CurvyBracketItem.DEFAULT_HOOK_RATIO))
            item = CurvyBracketItem(0.0, 0.0, width, height, hook_ratio)
            item.setPen(_pen_from_data(pen_data))
            item.setBrush(_brush_from_data(brush_data))
        elif shape == "Text":
            if width is None or height is None:
                width, height = DEFAULTS.get(shape, (100.0, 30.0))
            item = TextItem(0.0, 0.0, width, height)
            text_value = data.get("text")
            if isinstance(text_value, str):
                item.setPlainText(text_value)
            font_value = data.get("font")
            if isinstance(font_value, str):
                font = QtGui.QFont()
                font.fromString(font_value)
                item.setFont(font)
            color_value = data.get("color")
            if isinstance(color_value, Mapping):
                item.setDefaultTextColor(_color_from_data(color_value))
            margin_value = data.get("document_margin")
            if margin_value is not None:
                item.set_document_margin(float(margin_value))
            alignment = data.get("alignment")
            if isinstance(alignment, (list, tuple)) and len(alignment) == 2:
                item.set_text_alignment(horizontal=str(alignment[0]), vertical=str(alignment[1]))
            direction = data.get("direction")
            if isinstance(direction, str):
                item.set_text_direction(direction)
        elif shape == "Folder Tree":
            structure = data.get("structure")
            if not isinstance(structure, Mapping):
                structure = None
            item = FolderTreeItem(0.0, 0.0, 0.0, 0.0, structure=structure)  # type: ignore[arg-type]
        elif shape == "Group":
            item = GroupItem()
        else:
            return None

        if shape and shape != "Group" and item is not None:
            item.setData(0, shape)
        return item

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
            self._apply_item_transform(child, child_data)
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

    def _restore_scene_state(self, state: Mapping[str, Any]) -> None:
        scene = self.scene()
        if scene is None:
            return
        self.clear_canvas()
        restored: list[QtWidgets.QGraphicsItem] = []
        items_data = state.get("items") if isinstance(state, Mapping) else None
        if isinstance(items_data, list):
            for data in items_data:
                if not isinstance(data, Mapping):
                    continue
                item = self._instantiate_item(data)
                if item is None:
                    continue
                scene.addItem(item)
                if isinstance(item, GroupItem):
                    children = data.get("children")
                    if isinstance(children, list):
                        self._restore_group_children(item, children)
                self._apply_item_transform(item, data)
                restored.append(item)
        self._ensure_pages_for_items(restored)
        scene.clearSelection()
        grid_visible = bool(state.get("grid_visible", self._show_grid))
        self._show_grid = grid_visible
        for page in self._pages.values():
            page.set_grid_visible(grid_visible)
        self.viewport().update()
        self._update_scene_rect()
        self.gridVisibilityChanged.emit(self._show_grid)

    def _page_top_left_for_index(self, index: tuple[int, int]) -> QtCore.QPointF:
        row, col = index
        base_x = -self._page_width / 2.0
        base_y = -self._page_height / 2.0
        return QtCore.QPointF(
            base_x + col * self._page_width,
            base_y + row * self._page_height,
        )

    def _page_index_for_point(self, point: QtCore.QPointF) -> tuple[int, int]:
        base_x = -self._page_width / 2.0
        base_y = -self._page_height / 2.0
        col = math.floor((point.x() - base_x) / self._page_width)
        row = math.floor((point.y() - base_y) / self._page_height)
        return (row, col)

    def _create_page_item(self, index: tuple[int, int]) -> A4PageItem:
        page = A4PageItem(
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
        self, index: tuple[int, int], *, update_edges: bool = True
    ) -> A4PageItem:
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

    def _ensure_pages_between_master(self, target_index: tuple[int, int]) -> None:
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

    def _update_transition_edges(self) -> None:
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
        self, item: QtWidgets.QGraphicsItem, drop_reference: QtCore.QPointF | None
    ) -> A4PageItem:
        rect = item.sceneBoundingRect()
        page: A4PageItem | None = None
        for existing in self._pages.values():
            page_rect = existing.mapRectToScene(existing.rect())
            if page_rect.contains(rect):
                page = existing
                break

        indices_to_connect: set[tuple[int, int]] = set()

        if page is None:
            reference = drop_reference if drop_reference is not None else rect.center()
            index = self._page_index_for_point(reference)
            page = self._add_page(index)
            indices_to_connect.add(index)
            if not page.mapRectToScene(page.rect()).contains(rect):
                center_index = self._page_index_for_point(rect.center())
                page = self._add_page(center_index)
                indices_to_connect.add(center_index)
        if page is not None:
            indices_to_connect.add(page.index)

        for index in indices_to_connect:
            self._ensure_pages_between_master(index)

        self._prune_empty_pages()
        self._update_scene_rect()
        assert page is not None
        return page

    def _collect_canvas_content_items(self) -> list[QtWidgets.QGraphicsItem]:
        scene = self.scene()
        if scene is None:
            return []
        items: list[QtWidgets.QGraphicsItem] = []
        for item in scene.items():
            if isinstance(item, A4PageItem):
                continue
            if item.__class__.__name__.endswith("Handle"):
                continue
            items.append(item)
        return items

    def _prune_empty_pages(self) -> bool:
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
        self, items: list[QtWidgets.QGraphicsItem]
    ) -> None:
        for item in items:
            if isinstance(item, A4PageItem):
                continue
            if item.__class__.__name__.endswith("Handle"):
                continue
            if item.parentItem() is not None:
                continue
            self._ensure_page_for_item(item, item.sceneBoundingRect().center())

    def _fit_view_to_page(self) -> None:
        if self._page_item is None:
            return
        page_scene_rect = self._page_item.mapRectToScene(self._page_item.rect())
        padded = page_scene_rect.adjusted(-80, -80, 80, 80)
        if padded.isValid() and padded.width() > 0 and padded.height() > 0:
            self.fitInView(padded, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(self._page_item)

    def clear_canvas(self):
        """Remove all items from the scene."""
        scene = self.scene()
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

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        super().drawBackground(painter, rect)

    def set_grid_visible(self, visible: bool):
        self._show_grid = visible
        for page in self._pages.values():
            page.set_grid_visible(visible)
        self.viewport().update()
        if hasattr(self, "_history"):
            self._history.mark_dirty()
        self.gridVisibilityChanged.emit(self._show_grid)

    def _update_scene_rect(self):
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

    def resizeEvent(self, event: QtGui.QResizeEvent):
        """Ensure scene rect grows with the view."""
        super().resizeEvent(event)
        self._update_scene_rect()

    def add_shape(
        self,
        shape: str,
        scene_pos: QtCore.QPointF,
        snap_to_grid: bool = True,
    ) -> QtWidgets.QGraphicsItem | None:
        normalized = shape.strip()
        if normalized not in SHAPES:
            return None

        x = scene_pos.x()
        y = scene_pos.y()
        w, h = DEFAULTS[normalized]

        if snap_to_grid:
            size = self._grid_size
            origin = self._master_origin
            if isinstance(origin, QtCore.QPointF):
                origin_x, origin_y = origin.x(), origin.y()
            else:
                origin_x = float(getattr(origin, "x", 0.0))
                origin_y = float(getattr(origin, "y", 0.0))
            x = _snap_coordinate(x, size, origin_x)
            y = _snap_coordinate(y, size, origin_y)
            if normalized in ("Line", "Arrow"):
                w = round(w / size) * size

        drop_reference = QtCore.QPointF(x + w / 2.0, y + h / 2.0)

        if normalized == "Rectangle":
            item = RectItem(x, y, w, h)
        elif normalized == "Rounded Rectangle":
            item = RectItem(x, y, w, h, 15.0, 15.0)
        elif normalized == "Split Rounded Rectangle":
            item = SplitRoundedRectItem(x, y, w, h, 15.0, 15.0)
        elif normalized in ("Circle", "Ellipse"):
            item = EllipseItem(x, y, w, h)
        elif normalized == "Triangle":
            item = TriangleItem(x, y, w, h)
        elif normalized == "Diamond":
            item = DiamondItem(x, y, w, h)
        elif normalized == "Line":
            item = LineItem(x, y, w)
        elif normalized == "Arrow":
            item = LineItem(x, y, w, arrow_end=True)
        elif normalized == "Block Arrow":
            item = BlockArrowItem(x, y, w, h)
        elif normalized == "Curvy Right Bracket":
            item = CurvyBracketItem(x, y, w, h)
        elif normalized == "Text":
            item = TextItem(x, y, w, h)
        elif normalized == "Folder Tree":
            item = FolderTreeItem(x, y, w, h)
        else:
            return None

        item.setData(0, normalized)
        self.scene().addItem(item)
        item.setSelected(True)
        self._ensure_page_for_item(item, drop_reference)
        self._update_scene_rect()
        return item

    def add_shape_at_view_center(self, shape: str) -> QtWidgets.QGraphicsItem | None:
        normalized = shape.strip()
        if normalized not in SHAPES:
            return None

        center = self.mapToScene(self.viewport().rect().center())
        w, h = DEFAULTS[normalized]
        if normalized in ("Line", "Arrow"):
            pos = QtCore.QPointF(center.x() - w / 2.0, center.y())
        else:
            pos = QtCore.QPointF(center.x() - w / 2.0, center.y() - h / 2.0)
        return self.add_shape(normalized, pos, snap_to_grid=False)

    # --- Drag and drop from the palette ---
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        md = event.mimeData()
        if md.hasFormat(PALETTE_MIME) or md.hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if event.mimeData().hasFormat(PALETTE_MIME) or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent):
        md = event.mimeData()
        text = ""
        if md.hasFormat(PALETTE_MIME):
            text = str(bytes(md.data(PALETTE_MIME)).decode("utf-8"))
        elif md.hasText():
            text = md.text()

        shape = text.strip()
        if shape not in SHAPES:
            super().dropEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        snap = not (
            event.keyboardModifiers() & QtCore.Qt.KeyboardModifier.AltModifier
        )
        item = self.add_shape(shape, scene_pos, snap_to_grid=snap)
        if item is not None:
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # --- Duplicate selected items with Ctrl+drag ---
    def mousePressEvent(self, event: QtGui.QMouseEvent):
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

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        
        item = self.itemAt(event.position().toPoint())
        if item and item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
            self.viewport().setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        else:
            self.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)

        if self._panning or self._right_button_pressed:
            delta = event.position() - self._pan_start
            if (
                self._right_button_pressed
                and not self._panning
                and delta.manhattanLength() > 0
            ):
                self._panning = True
                self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
                self.viewport().setCursor(
                    QtCore.Qt.CursorShape.ClosedHandCursor
                )
            if self._panning:
                self._pan_start = event.position()
                hbar = self.horizontalScrollBar()
                vbar = self.verticalScrollBar()
                hbar.setValue(hbar.value() - int(delta.x()))
                vbar.setValue(vbar.value() - int(delta.y()))
                event.accept()
                return
        if getattr(self, "_dup_source", None):
            pos = self.mapToScene(event.position().toPoint())
            delta = pos - self._dup_start
            if self._dup_items is None:
                # Only create clones after surpassing the threshold.
                if delta.manhattanLength() < DUPLICATE_DRAG_THRESHOLD:
                    event.accept()
                    return
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
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            if self._panning:
                self._panning = False
                self._right_button_pressed = False
                self.setDragMode(self._prev_drag_mode)
                self.viewport().setCursor(
                    QtCore.Qt.CursorShape.ArrowCursor
                )
                self._suppress_context_menu = True
                event.accept()
                return
            if self._right_button_pressed:
                self._right_button_pressed = False
                event.accept()
                return
        if (
            event.button() == QtCore.Qt.MouseButton.MiddleButton and self._panning
        ):
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
                return
            if getattr(self, "_dup_source", None):
                # Ctrl+click without enough movement -> no duplication
                self._dup_source = []
                event.accept()
                return
        super().mouseReleaseEvent(event)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._ensure_pages_for_items(self.scene().selectedItems())

    def _clone_item(self, item: QtWidgets.QGraphicsItem):
        if isinstance(item, RectItem):
            r = item.rect()
            clone = RectItem(item.x(), item.y(), r.width(), r.height(), getattr(item, "rx", 0.0), getattr(item, "ry", 0.0))
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, SplitRoundedRectItem):
            r = item.rect()
            clone = SplitRoundedRectItem(
                item.x(),
                item.y(),
                r.width(),
                r.height(),
                getattr(item, "rx", 0.0),
                getattr(item, "ry", 0.0),
            )
            clone.setTopBrush(item.topBrush())
            clone.setBottomBrush(item.bottomBrush())
            clone.set_divider_ratio(item.divider_ratio())
            clone.setPen(item.pen())
        elif isinstance(item, EllipseItem):
            r = item.rect()
            clone = EllipseItem(item.x(), item.y(), r.width(), r.height())
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, TriangleItem):
            br = item.boundingRect()
            clone = TriangleItem(item.x(), item.y(), br.width(), br.height())
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, DiamondItem):
            br = item.boundingRect()
            clone = DiamondItem(item.x(), item.y(), br.width(), br.height())
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, LineItem):
            clone = LineItem(
                item.x(),
                item.y(),
                points=[QtCore.QPointF(p) for p in item._points],
                arrow_start=getattr(item, "arrow_start", False),
                arrow_end=getattr(item, "arrow_end", False),
                arrow_head_length=getattr(item, "arrow_head_length", lambda: 10.0)(),
                arrow_head_width=getattr(item, "arrow_head_width", lambda: 10.0)(),
            )
            clone.setPen(item.pen())
        elif isinstance(item, TextItem):
            br = item.boundingRect()
            clone = TextItem(item.x(), item.y(), br.width(), br.height())
            clone.setPlainText(item.toPlainText())
            clone.setFont(item.font())
            clone.setDefaultTextColor(item.defaultTextColor())
            doc = item.document()
            if doc is not None:
                clone.set_document_margin(doc.documentMargin())
            h_align, v_align = item.text_alignment()
            clone.set_text_alignment(horizontal=h_align, vertical=v_align)
            clone.set_text_direction(item.text_direction())
            clone.setScale(item.scale())
            br = clone.boundingRect()
            clone.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
        elif isinstance(item, FolderTreeItem):
            clone = FolderTreeItem(item.x(), item.y(), 0.0, 0.0, structure=item.structure())
            clone.setScale(item.scale())
        else:
            return None
        if isinstance(item, ShapeLabelMixin) and isinstance(clone, ShapeLabelMixin):
            clone.copy_label_from(item)
        clone.setRotation(item.rotation())
        clone.setData(0, item.data(0))
        return clone

    # --- Mouse wheel zooming and scrolling ---
    def wheelEvent(self, event: QtGui.QWheelEvent):
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
            self.setTransformationAnchor(anchor)
            self._update_scene_rect()
            event.accept()
            return
        super().wheelEvent(event)

    def _group_selected_items(self):
        selected = self.scene().selectedItems()
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
            it.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False
            )
            it.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False
            )
            if isinstance(it, ResizableItem):
                it.hide_handles()

        group.setTransformOriginPoint(group.boundingRect().center())
        group.setSelected(True)
        group.update_handles()
        self._update_scene_rect()

    def _ungroup_selected_items(self):
        selected = self.scene().selectedItems()
        changed = False
        for it in selected:
            if isinstance(it, GroupItem):
                it.setSelected(False)
                children = [
                    c
                    for c in it.childItems()
                    if not isinstance(c, (ResizeHandle, RotationHandle))
                ]
                for child in children:
                    it.removeFromGroup(child)
                    child.setFlag(
                        QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,
                        True,
                    )
                    child.setFlag(
                        QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                        True,
                    )
                    child.setSelected(False)
                self.scene().removeItem(it)
                changed = True
        if changed:
            self.scene().clearSelection()
            self._prune_empty_pages()
            self._update_scene_rect()

    # --- Keyboard shortcut to delete selected items ---
    def keyPressEvent(self, event: QtGui.QKeyEvent):
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
        if (
            event.key() == QtCore.Qt.Key.Key_G
            and mods
            == (
                QtCore.Qt.KeyboardModifier.ControlModifier
                | QtCore.Qt.KeyboardModifier.ShiftModifier
            )
        ):
            self._ungroup_selected_items()
            event.accept()
            return
        super().keyPressEvent(event)

    # --- Alignment helpers ---
    def _align_items(self, items, mode: str):
        brs = [it.sceneBoundingRect() for it in items]
        if mode == "grid":
            size = self._grid_size
            for it, br in zip(items, brs):
                new_x = round(br.left() / size) * size
                new_y = round(br.top() / size) * size
                it.moveBy(new_x - br.left(), new_y - br.top())
            return
        if mode == "left":
            target = min(br.left() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(target - br.left(), 0)
        elif mode == "hcenter":
            target = sum(br.center().x() for br in brs) / len(brs)
            for it, br in zip(items, brs):
                it.moveBy(target - br.center().x(), 0)
        elif mode == "right":
            target = max(br.right() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(target - br.right(), 0)
        elif mode == "top":
            target = min(br.top() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(0, target - br.top())
        elif mode == "vcenter":
            target = sum(br.center().y() for br in brs) / len(brs)
            for it, br in zip(items, brs):
                it.moveBy(0, target - br.center().y())
        elif mode == "bottom":
            target = max(br.bottom() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(0, target - br.bottom())

    def _create_color_action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        title: str,
        color_getter: Callable[[], QtGui.QColor],
        color_setter: Callable[[QtGui.QColor], None],
    ) -> tuple[QtGui.QAction, Callable[[], None]]:
        action = menu.addAction(text)

        def callback() -> None:
            color = QtWidgets.QColorDialog.getColor(color_getter(), self, title)
            if color.isValid():
                color_setter(color)

        return action, callback

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
        action = menu.addAction(text)

        def callback() -> None:
            value, ok = QtWidgets.QInputDialog.getDouble(
                self,
                dialog_title,
                label,
                value_getter(),
                minimum,
                maximum,
                decimals,
            )
            if ok:
                value_setter(value)

        return action, callback

    def _add_shape_label_actions(
        self, menu: QtWidgets.QMenu, item: ShapeLabelMixin
    ) -> dict[QtGui.QAction, Callable[[], None]]:
        actions: dict[QtGui.QAction, Callable[[], None]] = {}
        label_menu = menu.addMenu("Label")
        edit_action = label_menu.addAction("Edit text")
        actions[edit_action] = lambda item=item: item.edit_label()

        has_label = item.has_label()

        color_action, color_callback = self._create_color_action(
            label_menu,
            "Set font color...",
            "Label font color",
            lambda item=item: item.label_color(),
            lambda color, item=item: item.set_label_color(color),
        )
        color_action.setEnabled(has_label)
        actions[color_action] = color_callback

        font_action = label_menu.addAction("Set font size...")
        font_action.setEnabled(has_label)

        def font_callback(item=item) -> None:
            label_item = item.label_item()
            if label_item is None:
                return
            font = QtGui.QFont(label_item.font())
            pixel_size = float(font.pixelSize())
            if pixel_size <= 0.0:
                point_size = font.pointSizeF()
                if point_size > 0.0:
                    pixel_size = point_size
            if pixel_size <= 0.0:
                pixel_size = QtGui.QFontMetricsF(font).height()
            value, ok = QtWidgets.QInputDialog.getDouble(
                self,
                "Label font size",
                "Font size (px):",
                max(1.0, pixel_size),
                1.0,
                500.0,
                1,
            )
            if ok:
                item.set_label_font_pixel_size(value)

        actions[font_action] = font_callback

        label_menu.addSeparator()
        h_menu = label_menu.addMenu("Horizontal")
        v_menu = label_menu.addMenu("Vertical")
        h_menu.setEnabled(has_label)
        v_menu.setEnabled(has_label)
        h_align, v_align = item.label_alignment()
        for title, key in (("Left", "left"), ("Center", "center"), ("Right", "right")):
            action = h_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(h_align == key)
            actions[action] = lambda item=item, key=key: item.set_label_alignment(horizontal=key)
        for title, key in (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom")):
            action = v_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(v_align == key)
            actions[action] = lambda item=item, key=key: item.set_label_alignment(vertical=key)
        return actions
    def _create_shape_style_actions(
        self, menu: QtWidgets.QMenu, item: QtWidgets.QGraphicsItem
    ) -> dict[QtGui.QAction, Callable[[], None]]:
        actions: dict[QtGui.QAction, Callable[[], None]] = {}

        if isinstance(item, ShapeLabelMixin):
            label_actions = self._add_shape_label_actions(menu, item)
            actions.update(label_actions)
            menu.addSeparator()

        def add_fill_actions() -> None:
            fill_action, fill_callback = self._create_color_action(
                menu,
                "Set fill color…",
                "Fill color",
                lambda item=item: item.brush().color(),
                lambda color, item=item: item.setBrush(color),
            )
            actions[fill_action] = fill_callback

            def opacity_getter(item=item) -> float:
                brush = item.brush()
                if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                    return 1.0
                return brush.color().alphaF()

            def opacity_setter(value: float, item=item) -> None:
                brush = item.brush()
                color = brush.color()
                color.setAlphaF(value)
                item.setBrush(color)

            opacity_action = menu.addAction("Set fill opacity…")

            def opacity_callback(item=item) -> None:
                initial_opacity = opacity_getter()
                dialog = OpacityDialog(initial_opacity, self)

                def handle_value_changed(value: float, item=item) -> None:
                    opacity_setter(value, item)

                dialog.valueChanged.connect(handle_value_changed)
                result = dialog.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    opacity_setter(dialog.value(), item)
                else:
                    opacity_setter(initial_opacity, item)

            actions[opacity_action] = opacity_callback

        def add_stroke_actions() -> None:
            def stroke_color_setter(color: QtGui.QColor, item=item) -> None:
                pen = item.pen()
                pen.setColor(color)
                item.setPen(pen)
                item.update()

            stroke_action, stroke_callback = self._create_color_action(
                menu,
                "Set stroke color…",
                "Stroke color",
                lambda item=item: item.pen().color(),
                stroke_color_setter,
            )
            actions[stroke_action] = stroke_callback

            def width_setter(value: float, item=item) -> None:
                pen = item.pen()
                pen.setWidthF(value)
                item.setPen(pen)
                item.update()

            width_action, width_callback = self._create_double_action(
                menu,
                "Set stroke width…",
                "Stroke width",
                "Width:",
                lambda item=item: item.pen().widthF(),
                width_setter,
                0.1,
                50.0,
                1,
            )
            actions[width_action] = width_callback

        def add_corner_action() -> None:
            corner_action = menu.addAction("Set corner radius…")

            def corner_callback(item=item) -> None:
                initial_rx = item.rx
                initial_ry = item.ry
                dlg = CornerRadiusDialog(item.rx, self)

                def handle_value_changed(value: int, item=item) -> None:
                    radius = min(float(value), 50.0)
                    item.rx = item.ry = radius
                    item.update()

                dlg.valueChanged.connect(handle_value_changed)
                result = dlg.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    handle_value_changed(dlg.value())
                else:
                    item.rx = initial_rx
                    item.ry = initial_ry
                    item.update()

            actions[corner_action] = corner_callback

        def add_arrow_actions() -> None:
            start_action = menu.addAction("Show start arrowhead")
            start_action.setCheckable(True)
            start_action.setChecked(getattr(item, "arrow_start", False))

            def start_callback(action=start_action, item=item) -> None:
                item.set_arrow_start(action.isChecked())

            actions[start_action] = start_callback

            end_action = menu.addAction("Show end arrowhead")
            end_action.setCheckable(True)
            end_action.setChecked(getattr(item, "arrow_end", False))

            def end_callback(action=end_action, item=item) -> None:
                item.set_arrow_end(action.isChecked())

            actions[end_action] = end_callback

            length_getter = getattr(item, "arrow_head_length", None)
            width_getter = getattr(item, "arrow_head_width", None)
            length_setter = getattr(item, "set_arrow_head_length", None)
            width_setter = getattr(item, "set_arrow_head_width", None)
            if all(callable(fn) for fn in (length_getter, width_getter, length_setter, width_setter)):
                style_menu = menu.addMenu("Arrowhead style")
                height_action, height_callback = self._create_double_action(
                    style_menu,
                    "Set arrowhead height...",
                    "Arrowhead height",
                    "Height:",
                    lambda item=item, getter=length_getter: getter(),
                    lambda value, item=item, setter=length_setter: setter(value),
                    1.0,
                    500.0,
                    1,
                )
                actions[height_action] = height_callback

                width_action, width_callback = self._create_double_action(
                    style_menu,
                    "Set arrowhead width...",
                    "Arrowhead width",
                    "Width:",
                    lambda item=item, getter=width_getter: getter(),
                    lambda value, item=item, setter=width_setter: setter(value),
                    1.0,
                    500.0,
                    1,
                )
                actions[width_action] = width_callback

        def add_line_style_actions() -> None:
            style_menu = menu.addMenu("Line style")
            action_group = QtGui.QActionGroup(menu)
            action_group.setExclusive(True)
            current_style = item.pen().style()

            def make_action(text: str, style: QtCore.Qt.PenStyle) -> None:
                act = style_menu.addAction(text)
                act.setCheckable(True)
                act.setChecked(current_style == style)
                action_group.addAction(act)

                def callback(item=item, style=style) -> None:
                    setter = getattr(item, "set_pen_style", None)
                    if callable(setter):
                        setter(style)
                    else:
                        pen = QtGui.QPen(item.pen())
                        pen.setStyle(style)
                        item.setPen(pen)
                        item.update()

                actions[act] = callback

            make_action("Solid", QtCore.Qt.PenStyle.SolidLine)
            make_action("Dashed", QtCore.Qt.PenStyle.DashLine)
            make_action("Dotted", QtCore.Qt.PenStyle.DotLine)

        def add_text_actions() -> None:
            text_color_action, text_color_callback = self._create_color_action(
                menu,
                "Set text color...",
                "Text color",
                lambda item=item: item.defaultTextColor(),
                lambda color, item=item: item.setDefaultTextColor(color),
            )
            actions[text_color_action] = text_color_callback

            def font_size_setter(value: float, item=item) -> None:
                font = item.font()
                font.setPointSizeF(value)
                item.setFont(font)

            font_size_action, font_size_callback = self._create_double_action(
                menu,
                "Set font size...",
                "Font size",
                "Size:",
                lambda item=item: item.font().pointSizeF(),
                font_size_setter,
                1.0,
                500.0,
                1,
            )
            actions[font_size_action] = font_size_callback

            align_menu = menu.addMenu("Alignment")
            h_menu = align_menu.addMenu("Horizontal")
            v_menu = align_menu.addMenu("Vertical")
            h_align, v_align = item.text_alignment()
            for title, key in (("Left", "left"), ("Center", "center"), ("Right", "right")):
                action = h_menu.addAction(title)
                action.setCheckable(True)
                action.setChecked(h_align == key)
                actions[action] = lambda item=item, key=key: item.set_text_alignment(horizontal=key)
            for title, key in (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom")):
                action = v_menu.addAction(title)
                action.setCheckable(True)
                action.setChecked(v_align == key)
                actions[action] = lambda item=item, key=key: item.set_text_alignment(vertical=key)

            dir_menu = align_menu.addMenu("Direction")
            current_dir = item.text_direction()
            for title, key in (("Left to right", "ltr"), ("Right to left", "rtl")):
                action = dir_menu.addAction(title)
                action.setCheckable(True)
                action.setChecked(current_dir == key)
                actions[action] = lambda item=item, key=key: item.set_text_direction(key)

        def add_split_rect_fill_actions() -> None:
            split_item: SplitRoundedRectItem = item  # type: ignore[assignment]

            top_action, top_callback = self._create_color_action(
                menu,
                "Set top fill color…",
                "Top fill color",
                lambda item=split_item: item.topBrush().color(),
                lambda color, item=split_item: item.setTopBrush(color),
            )
            actions[top_action] = top_callback

            def top_opacity_getter(item=split_item) -> float:
                brush = item.topBrush()
                if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                    return 1.0
                return brush.color().alphaF()

            def top_opacity_setter(value: float, item=split_item) -> None:
                brush = item.topBrush()
                color = brush.color()
                color.setAlphaF(value)
                item.setTopBrush(color)

            top_opacity_action = menu.addAction("Set top fill opacity…")

            def top_opacity_callback(item=split_item) -> None:
                initial_opacity = top_opacity_getter()
                dialog = OpacityDialog(initial_opacity, self)

                def handle_value_changed(value: float, item=item) -> None:
                    top_opacity_setter(value, item)

                dialog.valueChanged.connect(handle_value_changed)
                result = dialog.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    top_opacity_setter(dialog.value(), item)
                else:
                    top_opacity_setter(initial_opacity, item)

            actions[top_opacity_action] = top_opacity_callback

            bottom_action, bottom_callback = self._create_color_action(
                menu,
                "Set bottom fill color…",
                "Bottom fill color",
                lambda item=split_item: item.bottomBrush().color(),
                lambda color, item=split_item: item.setBottomBrush(color),
            )
            actions[bottom_action] = bottom_callback

            def bottom_opacity_getter(item=split_item) -> float:
                brush = item.bottomBrush()
                if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                    return 1.0
                return brush.color().alphaF()

            def bottom_opacity_setter(value: float, item=split_item) -> None:
                brush = item.bottomBrush()
                color = brush.color()
                color.setAlphaF(value)
                item.setBottomBrush(color)

            bottom_opacity_action = menu.addAction("Set bottom fill opacity…")

            def bottom_opacity_callback(item=split_item) -> None:
                initial_opacity = bottom_opacity_getter()
                dialog = OpacityDialog(initial_opacity, self)

                def handle_value_changed(value: float, item=item) -> None:
                    bottom_opacity_setter(value, item)

                dialog.valueChanged.connect(handle_value_changed)
                result = dialog.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    bottom_opacity_setter(dialog.value(), item)
                else:
                    bottom_opacity_setter(initial_opacity, item)

            actions[bottom_opacity_action] = bottom_opacity_callback

        if isinstance(item, RectItem):
            add_fill_actions()
            add_corner_action()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, SplitRoundedRectItem):
            add_split_rect_fill_actions()
            add_corner_action()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, (QtWidgets.QGraphicsEllipseItem, TriangleItem, DiamondItem)):
            add_fill_actions()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, LineItem):
            add_arrow_actions()
            add_line_style_actions()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, TextItem):
            add_text_actions()
        else:
            add_stroke_actions()

        return actions

    # --- Context menu for adjusting colors and line width ---
    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if self._suppress_context_menu:
            self._suppress_context_menu = False
            event.accept()
            return
        pos = event.pos()
        item = self.itemAt(pos)
        if isinstance(item, QtWidgets.QGraphicsTextItem):
            parent = item.parentItem()
            if isinstance(parent, ShapeLabelMixin) and getattr(parent, 'label_item', lambda: None)() is item:
                item = parent
        if not item:
            menu = QtWidgets.QMenu(self)
            reset_act = menu.addAction("Reset zoom")
            action = menu.exec(event.globalPos())
            if action is reset_act:
                self.resetTransform()
            else:
                super().contextMenuEvent(event)
            return

        menu = QtWidgets.QMenu(self)

        selected = self.scene().selectedItems()
        group_act = ungroup_act = None
        if len(selected) >= 2:
            group_act = menu.addAction("Group")
        if any(isinstance(it, GroupItem) for it in selected):
            ungroup_act = menu.addAction("Ungroup")
        if group_act or ungroup_act:
            menu.addSeparator()

        align_actions = {}
        if len(selected) >= 2:
            align_menu = menu.addMenu("Align")
            align_actions[align_menu.addAction("Left")] = "left"
            align_actions[align_menu.addAction("Center")] = "hcenter"
            align_actions[align_menu.addAction("Right")] = "right"
            align_menu.addSeparator()
            align_actions[align_menu.addAction("Top")] = "top"
            align_actions[align_menu.addAction("Middle")] = "vcenter"
            align_actions[align_menu.addAction("Bottom")] = "bottom"
            align_menu.addSeparator()
            align_actions[align_menu.addAction("Snap to grid")] = "grid"
            menu.addSeparator()

        style_actions = self._create_shape_style_actions(menu, item)
        if style_actions:
            menu.addSeparator()

        back1_act = menu.addAction("Send backward")
        front1_act = menu.addAction("Bring forward")
        menu.addSeparator()
        back_act = menu.addAction("Send to back")
        front_act = menu.addAction("Bring to front")

        action = menu.exec(event.globalPos())
        if not action:
            super().contextMenuEvent(event)
            return

        if action in align_actions:
            self._align_items(selected, align_actions[action])
        elif action is group_act:
            self._group_selected_items()
        elif action is ungroup_act:
            self._ungroup_selected_items()
        else:
            style_callback = style_actions.get(action)
            if style_callback:
                style_callback()
            elif action in (back1_act, front1_act, back_act, front_act):
                scene = self.scene()
                items = [
                    it
                    for it in scene.items()
                    if it.data(0) in SHAPES or isinstance(it, GroupItem)
                ]
                items.sort(key=lambda it: it.zValue())
                idx = items.index(item)
                if action == back1_act and idx > 0:
                    items[idx - 1], items[idx] = items[idx], items[idx - 1]
                elif action == front1_act and idx < len(items) - 1:
                    items[idx + 1], items[idx] = items[idx], items[idx + 1]
                elif action == back_act:
                    items.insert(0, items.pop(idx))
                elif action == front_act:
                    items.append(items.pop(idx))
                for z, it in enumerate(items):
                    it.setZValue(z)
            else:
                super().contextMenuEvent(event)
