"""Core utilities, mixins, and shared handles for interactive items."""

from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

HANDLE_COLOR = QtGui.QColor("#14b5ff")
HANDLE_SIZE = 8.0
HANDLE_OFFSET = 10.0
DIVIDER_HANDLE_COLOR = QtGui.QColor("#d28b00")
DIVIDER_HANDLE_DIAMETER = 10.0


if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from .shapes.polygons import DiamondItem, TriangleItem


def _origin_component(origin: Any, axis: str) -> float:
    attr = getattr(origin, axis, None)
    if callable(attr):
        try:
            return float(attr())
        except TypeError:
            pass
    if attr is not None:
        return float(attr)
    return 0.0


def _grid_origin(view: QtWidgets.QGraphicsView) -> tuple[float, float]:
    origin = getattr(view, "_master_origin", None)
    if isinstance(origin, QtCore.QPointF):
        return origin.x(), origin.y()
    if origin is None:
        return 0.0, 0.0
    return _origin_component(origin, "x"), _origin_component(origin, "y")


def _snap_component(value: float, spacing: float, origin: float) -> float:
    if spacing <= 0.0:
        return value
    return round((value - origin) / spacing) * spacing + origin


def snap_to_grid(item: QtWidgets.QGraphicsItem, pos: QtCore.QPointF) -> QtCore.QPointF:
    scene = item.scene()
    if scene:
        views = scene.views()
        if views:
            view = views[0]
            spacing = float(getattr(view, "_grid_size_min", 10.0))
            ox, oy = _grid_origin(view)
            x = _snap_component(pos.x(), spacing, ox)
            y = _snap_component(pos.y(), spacing, oy)
            return QtCore.QPointF(x, y)
    return pos


def _local_axis_units(item: QtWidgets.QGraphicsItem) -> tuple[QtCore.QPointF, QtCore.QPointF]:
    """Unit vectors for the local +X and +Y axes in scene space."""

    transform = item.sceneTransform()
    ex = transform.map(QtCore.QPointF(1, 0)) - transform.map(QtCore.QPointF(0, 0))
    ey = transform.map(QtCore.QPointF(0, 1)) - transform.map(QtCore.QPointF(0, 0))
    ex_len = math.hypot(ex.x(), ex.y())
    ey_len = math.hypot(ey.x(), ey.y())
    if ex_len == 0 or ey_len == 0:
        return QtCore.QPointF(1, 0), QtCore.QPointF(0, 1)
    return (
        QtCore.QPointF(ex.x() / ex_len, ex.y() / ex_len),
        QtCore.QPointF(ey.x() / ey_len, ey.y() / ey_len),
    )


def _cursor_for_dir_rotated(direction: str, angle_deg: float) -> QtCore.Qt.CursorShape:
    """Return the correct resize cursor for a rotated item."""

    angle = (angle_deg % 180.0 + 180.0) % 180.0
    swap_hv = 45.0 <= angle < 135.0

    if direction in ("left", "right"):
        return (
            QtCore.Qt.CursorShape.SizeVerCursor
            if swap_hv
            else QtCore.Qt.CursorShape.SizeHorCursor
        )
    if direction in ("top", "bottom"):
        return (
            QtCore.Qt.CursorShape.SizeHorCursor
            if swap_hv
            else QtCore.Qt.CursorShape.SizeVerCursor
        )

    if direction in ("top_left", "bottom_right"):
        return (
            QtCore.Qt.CursorShape.SizeBDiagCursor
            if swap_hv
            else QtCore.Qt.CursorShape.SizeFDiagCursor
        )
    return (
        QtCore.Qt.CursorShape.SizeFDiagCursor
        if swap_hv
        else QtCore.Qt.CursorShape.SizeBDiagCursor
    )


def _has_selected_group_parent(item: QtWidgets.QGraphicsItem) -> bool:
    parent = item.parentItem()
    while parent is not None:
        if (
            isinstance(parent, QtWidgets.QGraphicsItemGroup)
            and parent.data(0) == "Group"
            and parent.isSelected()
        ):
            return True
        parent = parent.parentItem()
    return False


def _should_draw_selection(item: QtWidgets.QGraphicsItem) -> bool:
    return item.isSelected() and not _has_selected_group_parent(item)


def build_curvy_bracket_path(w: float, h: float, hook: float) -> QtGui.QPainterPath:
    """Return a right-facing curly bracket path translated to the origin."""

    w = max(8.0, float(w))
    h = max(40.0, float(h))
    hook = max(6.0, min(float(hook), h * 0.45))

    rect = QtCore.QRectF(-w / 2.0, -h / 2.0, w, h)
    cx = rect.center().x()
    top = rect.top()
    bottom = rect.bottom()
    mid = rect.center().y()

    curvature = w * 0.85
    depth = hook * 0.55

    path = QtGui.QPainterPath()
    path.moveTo(cx - w * 0.48, top + 2.0)
    path.cubicTo(
        cx - w * 0.48 + depth,
        top + 2.0,
        cx - w * 0.12,
        top + hook * 0.25,
        cx + 0.0,
        top + hook,
    )
    path.cubicTo(
        cx + curvature * 0.12,
        top + hook + (h * 0.20),
        cx + curvature * 0.18,
        mid - (h * 0.08),
        cx + w * 0.42,
        mid - 2.0,
    )
    path.lineTo(cx + w * 0.50, mid)
    path.lineTo(cx + w * 0.42, mid + 2.0)
    path.cubicTo(
        cx + curvature * 0.18,
        mid + (h * 0.08),
        cx + curvature * 0.12,
        bottom - hook - (h * 0.20),
        cx + 0.0,
        bottom - hook,
    )
    path.cubicTo(
        cx - w * 0.12,
        bottom - hook * 0.25,
        cx - w * 0.48 + depth,
        bottom - 2.0,
        cx - w * 0.48,
        bottom - 2.0,
    )

    path.translate(w / 2.0, h / 2.0)
    return path


class HandleAwareItemMixin:
    """Shared ``itemChange`` implementation for items with interactive handles."""

    def _snap_position_value(self, value):
        if isinstance(value, QtCore.QPointF):
            mods = QtWidgets.QApplication.keyboardModifiers()
            if not mods & QtCore.Qt.KeyboardModifier.AltModifier:
                return snap_to_grid(self, value)
        return value

    def _handle_selection_changed(self, selected: bool) -> None:
        if selected and not _has_selected_group_parent(self):
            self.show_handles()
        else:
            self.hide_handles()

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            value = self._snap_position_value(value)
        elif change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._handle_selection_changed(bool(value))
        elif change in (
            QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged,
            QtWidgets.QGraphicsItem.GraphicsItemChange.ItemTransformHasChanged,
        ):
            if _should_draw_selection(self):
                self.update_handles()
        return super().itemChange(change, value)  # type: ignore[misc]


class ResizeHandle(QtWidgets.QGraphicsEllipseItem):
    """Interactive resize handle."""

    def __init__(self, parent: QtWidgets.QGraphicsItem, direction: str):
        super().__init__(
            -HANDLE_SIZE / 2.0,
            -HANDLE_SIZE / 2.0,
            HANDLE_SIZE,
            HANDLE_SIZE,
            parent,
        )
        self.setBrush(HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self._direction = direction
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)

        self._start_pos_scene: QtCore.QPointF | None = None
        self._parent_start_pos: QtCore.QPointF | None = None
        self._parent_was_movable = False
        self._start_rx = 0.0
        self._start_ry = 0.0
        self._w0 = 0.0
        self._h0 = 0.0
        self._ex_u = QtCore.QPointF(1, 0)
        self._ey_u = QtCore.QPointF(0, 1)

        rotation = getattr(parent, "rotation", lambda: 0.0)()
        self.setCursor(_cursor_for_dir_rotated(direction, rotation))

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        self._start_pos_scene = event.scenePos()
        self._parent_start_pos = QtCore.QPointF(parent.pos())
        self._ex_u, self._ey_u = _local_axis_units(parent)

        if isinstance(parent, (QtWidgets.QGraphicsRectItem, QtWidgets.QGraphicsEllipseItem)):
            rect = parent.rect()
            self._w0, self._h0 = rect.width(), rect.height()
            self._start_rx = getattr(parent, "rx", 0.0)
            self._start_ry = getattr(parent, "ry", 0.0)
        else:
            from .shapes.polygons import DiamondItem, TriangleItem  # local import to avoid cycles

            if isinstance(parent, (TriangleItem, DiamondItem)):
                self._w0, self._h0 = parent._w, parent._h  # type: ignore[attr-defined]
            else:
                bounds = parent.boundingRect()
                self._w0, self._h0 = bounds.width(), bounds.height()

        flags = parent.flags()
        self._parent_was_movable = bool(
            flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if self._start_pos_scene is None:
            event.ignore()
            return

        parent = self.parentItem()
        scene_pos = event.scenePos()
        snap_scene = not (event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier)
        if snap_scene:
            scene_pos = snap_to_grid(self, scene_pos)

        delta_scene = scene_pos - self._start_pos_scene
        dx_local = delta_scene.x() * self._ex_u.x() + delta_scene.y() * self._ex_u.y()
        dy_local = delta_scene.x() * self._ey_u.x() + delta_scene.y() * self._ey_u.y()

        min_w, min_h = 10.0, 10.0

        new_w, new_h = self._w0, self._h0
        shift_x = 0.0
        shift_y = 0.0

        if self._direction == "right":
            new_w = max(min_w, self._w0 + dx_local)
        elif self._direction == "left":
            new_w_raw = self._w0 - dx_local
            new_w = max(min_w, new_w_raw)
            dx_eff = self._w0 - new_w
            shift_x = dx_eff
        elif self._direction == "bottom":
            new_h = max(min_h, self._h0 + dy_local)
        elif self._direction == "top":
            new_h_raw = self._h0 - dy_local
            new_h = max(min_h, new_h_raw)
            dy_eff = self._h0 - new_h
            shift_y = dy_eff
        elif self._direction == "top_left":
            new_w_raw = self._w0 - dx_local
            new_w = max(min_w, new_w_raw)
            dx_eff = self._w0 - new_w
            shift_x = dx_eff
            new_h_raw = self._h0 - dy_local
            new_h = max(min_h, new_h_raw)
            dy_eff = self._h0 - new_h
            shift_y = dy_eff
        elif self._direction == "top_right":
            new_w = max(min_w, self._w0 + dx_local)
            new_h_raw = self._h0 - dy_local
            new_h = max(min_h, new_h_raw)
            dy_eff = self._h0 - new_h
            shift_y = dy_eff
        elif self._direction == "bottom_left":
            new_w_raw = self._w0 - dx_local
            new_w = max(min_w, new_w_raw)
            dx_eff = self._w0 - new_w
            shift_x = dx_eff
            new_h = max(min_h, self._h0 + dy_local)
        elif self._direction == "bottom_right":
            new_w = max(min_w, self._w0 + dx_local)
            new_h = max(min_h, self._h0 + dy_local)

        if snap_scene:
            grid = 10
            scene = parent.scene()
            if scene and scene.views():
                grid = getattr(scene.views()[0], "_grid_size_min", 10)

            def snap(value: float) -> float:
                return round(value / grid) * grid

            if "left" in self._direction or "right" in self._direction:
                new_w = max(min_w, snap(new_w))
                if self._direction in ("left", "top_left", "bottom_left"):
                    shift_x = self._w0 - new_w
            if "top" in self._direction or "bottom" in self._direction:
                new_h = max(min_h, snap(new_h))
                if self._direction in ("top", "top_left", "top_right"):
                    shift_y = self._h0 - new_h

        if isinstance(parent, QtWidgets.QGraphicsRectItem):
            parent.setRect(0, 0, new_w, new_h)
            if hasattr(parent, "rx") and hasattr(parent, "ry"):
                sx = new_w / (self._w0 or 1.0)
                sy = new_h / (self._h0 or 1.0)
                scale = min(sx, sy)
                max_r = min(new_w, new_h) / 2.0
                new_r = min(self._start_rx, self._start_ry) * scale
                parent.rx = parent.ry = min(new_r, max_r, 50.0)
        elif isinstance(parent, QtWidgets.QGraphicsEllipseItem):
            parent.setRect(0, 0, new_w, new_h)
        elif hasattr(parent, "set_size") and callable(getattr(parent, "set_size", None)):
            parent.set_size(new_w, new_h, adjust_origin=False)  # type: ignore[attr-defined]
        else:
            bounds = parent.boundingRect()
            sx = new_w / (bounds.width() or 1.0)
            sy = new_h / (bounds.height() or 1.0)
            parent.setScale(max(sx, sy))

        if shift_x or shift_y:
            delta_scene = QtCore.QPointF(
                shift_x * self._ex_u.x() + shift_y * self._ey_u.x(),
                shift_x * self._ex_u.y() + shift_y * self._ey_u.y(),
            )
            parent.setPos(self._parent_start_pos + delta_scene)
        else:
            parent.setPos(self._parent_start_pos)

        if hasattr(parent, "update_handles"):
            parent.update_handles()
        event.accept()

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        bounds = parent.boundingRect()
        old_top_left = parent.mapToScene(QtCore.QPointF(0, 0))
        parent.setTransformOriginPoint(bounds.center())
        new_top_left = parent.mapToScene(QtCore.QPointF(0, 0))
        parent.setPos(parent.pos() + (old_top_left - new_top_left))

        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._parent_was_movable = False

        self._start_pos_scene = None
        event.accept()


class RotationHandle(QtWidgets.QGraphicsPixmapItem):
    """Handle for rotating an item."""

    def __init__(self, parent: QtWidgets.QGraphicsItem):
        pix = QtGui.QPixmap(20, 20)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(HANDLE_COLOR)
        pen.setWidth(2)
        painter.setPen(pen)
        rect = QtCore.QRectF(5, 5, 10, 10)
        painter.drawArc(rect, 30 * 16, 300 * 16)
        path = QtGui.QPainterPath()
        path.moveTo(15, 8)
        path.lineTo(11, 8)
        path.lineTo(13, 4)
        path.closeSubpath()
        painter.fillPath(path, HANDLE_COLOR)
        painter.end()

        super().__init__(pix, parent)
        self.setOffset(-pix.width() / 2.0, -pix.height() / 2.0)
        self.setShapeMode(QtWidgets.QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._start_angle = None
        self._start_rotation = 0.0
        self._center = QtCore.QPointF()
        self._parent_was_movable = False
        self._angle_label: QtWidgets.QGraphicsSimpleTextItem | None = None
        self._angle_label_bg: QtWidgets.QGraphicsRectItem | None = None

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        pos = event.scenePos()
        self._center = parent.sceneBoundingRect().center()
        self._start_angle = math.degrees(
            math.atan2(pos.y() - self._center.y(), pos.x() - self._center.x())
        )
        self._start_rotation = parent.rotation()
        flags = parent.flags()
        self._parent_was_movable = bool(
            flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        if parent.scene():
            scene = parent.scene()
            if self._angle_label is None:
                self._angle_label = QtWidgets.QGraphicsSimpleTextItem()
                self._angle_label.setZValue(1001)
                scene.addItem(self._angle_label)
            if self._angle_label_bg is None:
                self._angle_label_bg = QtWidgets.QGraphicsRectItem()
                self._angle_label_bg.setBrush(QtGui.QColor(220, 220, 220))
                self._angle_label_bg.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                self._angle_label_bg.setZValue(1000)
                scene.addItem(self._angle_label_bg)
        self._update_label(parent.rotation())
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if self._start_angle is None:
            event.ignore()
            return
        pos = event.scenePos()
        angle = math.degrees(
            math.atan2(pos.y() - self._center.y(), pos.x() - self._center.x())
        )
        delta = angle - self._start_angle
        parent = self.parentItem()
        new_angle = self._start_rotation + delta
        mods = QtWidgets.QApplication.keyboardModifiers()
        if not mods & QtCore.Qt.KeyboardModifier.AltModifier:
            new_angle = round(new_angle / 5.0) * 5.0
        parent.setRotation(new_angle)
        self._update_label(parent.rotation())
        if hasattr(parent, "update_handles"):
            parent.update_handles()
        event.accept()

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._parent_was_movable = False
        self._start_angle = None
        if parent.scene():
            scene = parent.scene()
            if self._angle_label:
                scene.removeItem(self._angle_label)
            if self._angle_label_bg:
                scene.removeItem(self._angle_label_bg)
        self._angle_label = None
        self._angle_label_bg = None
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        event.accept()

    def _update_label(self, angle: float) -> None:
        if not self._angle_label:
            return
        self._angle_label.setText(f"{angle:.1f}\N{DEGREE SIGN}")
        parent = self.parentItem()
        scene_rect = parent.mapToScene(parent.boundingRect()).boundingRect()
        pos = QtCore.QPointF(scene_rect.center().x(), scene_rect.bottom() + 25)
        br = self._angle_label.boundingRect()
        self._angle_label.setPos(pos.x() - br.width() / 2.0, pos.y())
        if self._angle_label_bg:
            padding = 2.0
            rect = QtCore.QRectF(
                self._angle_label.pos().x() - padding,
                self._angle_label.pos().y() - padding,
                br.width() + 2 * padding,
                br.height() + 2 * padding,
            )
            self._angle_label_bg.setRect(rect)


class ResizableItem(HandleAwareItemMixin):
    """Mixin that adds eight resize handles and a rotation handle."""

    def __init__(self):
        self._handles: list[ResizeHandle] = []
        self._rotation_handle: RotationHandle | None = None

    def _handle_rect(self) -> QtCore.QRectF:
        return self.boundingRect()

    def _ensure_handles(self):
        if self._handles:
            return
        directions = [
            "top_left",
            "top",
            "top_right",
            "right",
            "bottom_right",
            "bottom",
            "bottom_left",
            "left",
        ]
        for direction in directions:
            handle = ResizeHandle(self, direction)
            handle.hide()
            self._handles.append(handle)
        self._rotation_handle = RotationHandle(self)
        self._rotation_handle.hide()

    def update_handles(self):
        self._ensure_handles()
        rect = self._handle_rect()
        if rect.isNull():
            rect = self.boundingRect()
        scale = self.scale() or 1.0
        offset = HANDLE_OFFSET / scale
        points = [
            rect.topLeft() - QtCore.QPointF(offset, offset),
            QtCore.QPointF(rect.center().x(), rect.top() - offset),
            rect.topRight() + QtCore.QPointF(offset, -offset),
            QtCore.QPointF(rect.right() + offset, rect.center().y()),
            rect.bottomRight() + QtCore.QPointF(offset, offset),
            QtCore.QPointF(rect.center().x(), rect.bottom() + offset),
            rect.bottomLeft() + QtCore.QPointF(-offset, offset),
            QtCore.QPointF(rect.left() - offset, rect.center().y()),
        ]
        for point, handle in zip(points, self._handles):
            handle.setPos(point)
            handle.setCursor(
                _cursor_for_dir_rotated(
                    handle._direction,
                    getattr(self, "rotation", lambda: 0.0)(),
                )
            )
        if self._rotation_handle:
            rot_offset = (HANDLE_OFFSET + 15.0) / scale
            rotation_vector = QtCore.QPointF(rot_offset, -rot_offset)
            self._rotation_handle.setPos(rect.topRight() + rotation_vector)

    def show_handles(self):
        self.update_handles()
        for handle in self._handles:
            handle.show()
        if self._rotation_handle:
            self._rotation_handle.show()

    def hide_handles(self):
        for handle in self._handles:
            handle.hide()
        if self._rotation_handle:
            self._rotation_handle.hide()


__all__ = [
    "DIVIDER_HANDLE_COLOR",
    "DIVIDER_HANDLE_DIAMETER",
    "HANDLE_COLOR",
    "HANDLE_OFFSET",
    "HANDLE_SIZE",
    "HandleAwareItemMixin",
    "ResizableItem",
    "ResizeHandle",
    "RotationHandle",
    "build_curvy_bracket_path",
    "_should_draw_selection",
    "snap_to_grid",
]
