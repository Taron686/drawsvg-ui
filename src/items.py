# items.py
import math
from typing import Any, Mapping
from PySide6 import QtCore, QtGui, QtWidgets
from constants import PEN_NORMAL, PEN_SELECTED, DEFAULT_FILL

HANDLE_COLOR = QtGui.QColor("#14b5ff")
HANDLE_SIZE = 8.0
HANDLE_OFFSET = 10.0
DIVIDER_HANDLE_COLOR = QtGui.QColor("#d28b00")
DIVIDER_HANDLE_DIAMETER = 10.0


def _origin_component(origin: Any, axis: str) -> float:
    attr = getattr(origin, axis, None)
    if callable(attr):
        try:
            return float(attr())
        except TypeError:
            # If attr is a property returning a value without call support
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
    """Unit-Vektoren der lokalen +X und +Y-Achse im SCENE-Raum."""
    T = item.sceneTransform()
    ex = T.map(QtCore.QPointF(1, 0)) - T.map(QtCore.QPointF(0, 0))
    ey = T.map(QtCore.QPointF(0, 1)) - T.map(QtCore.QPointF(0, 0))
    ex_len = math.hypot(ex.x(), ex.y())
    ey_len = math.hypot(ey.x(), ey.y())
    if ex_len == 0 or ey_len == 0:
        return QtCore.QPointF(1, 0), QtCore.QPointF(0, 1)
    return QtCore.QPointF(ex.x() / ex_len, ex.y() / ex_len), QtCore.QPointF(ey.x() / ey_len, ey.y() / ey_len)


def _cursor_for_dir_rotated(direction: str, angle_deg: float) -> QtCore.Qt.CursorShape:
    """Passendes Cursor-Icon je Handle-Richtung + Item-Rotation."""
    a = (angle_deg % 180.0 + 180.0) % 180.0
    swap_hv = 45.0 <= a < 135.0  # ~90°: H/V tauschen

    if direction in ("left", "right"):
        return QtCore.Qt.CursorShape.SizeVerCursor if swap_hv else QtCore.Qt.CursorShape.SizeHorCursor
    if direction in ("top", "bottom"):
        return QtCore.Qt.CursorShape.SizeHorCursor if swap_hv else QtCore.Qt.CursorShape.SizeVerCursor

    # Diagonale tauschen wir bei ~90°
    if direction in ("top_left", "bottom_right"):
        return QtCore.Qt.CursorShape.SizeBDiagCursor if swap_hv else QtCore.Qt.CursorShape.SizeFDiagCursor
    else:  # top_right, bottom_left
        return QtCore.Qt.CursorShape.SizeFDiagCursor if swap_hv else QtCore.Qt.CursorShape.SizeBDiagCursor


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

    c = w * 0.85
    d = hook * 0.55

    path = QtGui.QPainterPath()
    path.moveTo(cx - w * 0.48, top + 2.0)
    path.cubicTo(
        cx - w * 0.48 + d,
        top + 2.0,
        cx - w * 0.12,
        top + hook * 0.25,
        cx + 0.0,
        top + hook,
    )
    path.cubicTo(
        cx + c * 0.12,
        top + hook + (h * 0.20),
        cx + c * 0.18,
        mid - (h * 0.08),
        cx + w * 0.42,
        mid - 2.0,
    )
    path.lineTo(cx + w * 0.50, mid)
    path.lineTo(cx + w * 0.42, mid + 2.0)
    path.cubicTo(
        cx + c * 0.18,
        mid + (h * 0.08),
        cx + c * 0.12,
        bottom - hook - (h * 0.20),
        cx + 0.0,
        bottom - hook,
    )
    path.cubicTo(
        cx - w * 0.12,
        bottom - hook * 0.25,
        cx - w * 0.48 + d,
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
    """Handle zum interaktiven Resizen."""

    def __init__(self, parent: QtWidgets.QGraphicsItem, direction: str):
        super().__init__(-HANDLE_SIZE / 2.0, -HANDLE_SIZE / 2.0, HANDLE_SIZE, HANDLE_SIZE, parent)
        self.setBrush(HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self._direction = direction
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)

        # Startzustand (bei press)
        self._start_pos_scene: QtCore.QPointF | None = None
        self._parent_start_pos: QtCore.QPointF | None = None
        self._parent_was_movable = False
        self._start_rx = 0.0
        self._start_ry = 0.0
        self._w0 = 0.0
        self._h0 = 0.0
        self._ex_u = QtCore.QPointF(1, 0)  # lokale X-Achse in Szene
        self._ey_u = QtCore.QPointF(0, 1)  # lokale Y-Achse in Szene

        # Anfangscursor
        self.setCursor(_cursor_for_dir_rotated(direction, getattr(parent, "rotation", lambda: 0.0)()))

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        self._start_pos_scene = event.scenePos()
        self._parent_start_pos = QtCore.QPointF(parent.pos())
        self._ex_u, self._ey_u = _local_axis_units(parent)

        # Startbreite/-höhe pro Typ
        if isinstance(parent, (QtWidgets.QGraphicsRectItem, QtWidgets.QGraphicsEllipseItem)):
            r = parent.rect()
            self._w0, self._h0 = r.width(), r.height()
            self._start_rx = getattr(parent, "rx", 0.0)
            self._start_ry = getattr(parent, "ry", 0.0)
        elif isinstance(parent, (TriangleItem, DiamondItem)):
            # TriangleItem hält w/h intern
            self._w0, self._h0 = parent._w, parent._h
        else:
            br = parent.boundingRect()
            self._w0, self._h0 = br.width(), br.height()

        # Parent während Drag nicht verschiebbar
        flags = parent.flags()
        self._parent_was_movable = bool(flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
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

        # Szene-Delta -> Projektion entlang lokaler Achsen
        dS = scene_pos - self._start_pos_scene
        dx_local = dS.x() * self._ex_u.x() + dS.y() * self._ex_u.y()
        dy_local = dS.x() * self._ey_u.x() + dS.y() * self._ey_u.y()

        MIN_W, MIN_H = 10.0, 10.0

        # Zielbreite/-höhe aus Startwerten + projizierter Bewegung
        new_w, new_h = self._w0, self._h0
        shift_x = 0.0
        shift_y = 0.0

        # Nur die relevanten Kanten bewegen und ggf. die Position entlang lokaler Achse schieben
        if self._direction == "right":
            new_w = max(MIN_W, self._w0 + dx_local)
            # pos bleibt

        elif self._direction == "left":
            new_w_raw = self._w0 - dx_local
            new_w = max(MIN_W, new_w_raw)
            # effektive Verschiebung (falls durch clamp geringer als dx_local)
            dx_eff = self._w0 - new_w
            shift_x = dx_eff  # lokale +X Richtung

        elif self._direction == "bottom":
            new_h = max(MIN_H, self._h0 + dy_local)

        elif self._direction == "top":
            new_h_raw = self._h0 - dy_local
            new_h = max(MIN_H, new_h_raw)
            dy_eff = self._h0 - new_h
            shift_y = dy_eff  # lokale +Y Richtung

        elif self._direction == "top_left":
            # X
            new_w_raw = self._w0 - dx_local
            new_w = max(MIN_W, new_w_raw)
            dx_eff = self._w0 - new_w
            shift_x = dx_eff
            # Y
            new_h_raw = self._h0 - dy_local
            new_h = max(MIN_H, new_h_raw)
            dy_eff = self._h0 - new_h
            shift_y = dy_eff

        elif self._direction == "top_right":
            new_w = max(MIN_W, self._w0 + dx_local)  # rechts ohne pos-shift
            new_h_raw = self._h0 - dy_local
            new_h = max(MIN_H, new_h_raw)
            dy_eff = self._h0 - new_h
            shift_y = dy_eff

        elif self._direction == "bottom_left":
            new_w_raw = self._w0 - dx_local
            new_w = max(MIN_W, new_w_raw)
            dx_eff = self._w0 - new_w
            shift_x = dx_eff
            new_h = max(MIN_H, self._h0 + dy_local)

        elif self._direction == "bottom_right":
            new_w = max(MIN_W, self._w0 + dx_local)
            new_h = max(MIN_H, self._h0 + dy_local)

        # Optional: lokales Rastern NACH der Geometrie (nur veränderte Dimensionen runden)
        if snap_scene:
            grid = 10
            sc = parent.scene()
            if sc and sc.views():
                grid = getattr(sc.views()[0], "_grid_size_min", 10)

            def s(v): return round(v / grid) * grid
            # Nur die Dimensionen snappen, die wir verändert haben
            if "left" in self._direction or "right" in self._direction:
                new_w = max(MIN_W, s(new_w))
                # shift_x bleibt konsistent zur effektiven Breitenänderung
                if self._direction in ("left", "top_left", "bottom_left"):
                    shift_x = self._w0 - new_w
            if "top" in self._direction or "bottom" in self._direction:
                new_h = max(MIN_H, s(new_h))
                if self._direction in ("top", "top_left", "top_right"):
                    shift_y = self._h0 - new_h

        # Geometrie setzen + Positionsverschiebung entlang lokaler Achsen
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
            parent.set_size(new_w, new_h, adjust_origin=False)

        else:
            # generischer Fallback: skalieren
            br = parent.boundingRect()
            sx = new_w / (br.width() or 1.0)
            sy = new_h / (br.height() or 1.0)
            parent.setScale(max(sx, sy))

        # Positions-Shift (lokale Achsen -> Szene)
        if shift_x or shift_y:
            # shift_x entlang +X_local, shift_y entlang +Y_local
            delta_scene = QtCore.QPointF(
                shift_x * self._ex_u.x() + shift_y * self._ey_u.x(),
                shift_x * self._ex_u.y() + shift_y * self._ey_u.y(),
            )
            parent.setPos(self._parent_start_pos + delta_scene)
        else:
            # rechts/bottom/BR: pos unverändert
            parent.setPos(self._parent_start_pos)

        if hasattr(parent, "update_handles"):
            parent.update_handles()
        event.accept()

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        # Origin zurück in die Mitte (optisch angenehmer)
        # Dabei die aktuelle Position in der Szene beibehalten, da eine
        # Veränderung des Transform-Origins bei rotierten Items sonst zu
        # einem sichtbaren "Springen" führt.
        br = parent.boundingRect()
        # Szene-Position der aktuellen linken oberen Ecke merken
        old_tl = parent.mapToScene(QtCore.QPointF(0, 0))
        # Origin auf die neue Mitte setzen
        parent.setTransformOriginPoint(br.center())
        # Nach dem Ändern des Transform-Origins hat sich die Szene-Position
        # der linken oberen Ecke verändert. Wir verschieben das Item um den
        # Unterschied, sodass es visuell an Ort und Stelle bleibt.
        new_tl = parent.mapToScene(QtCore.QPointF(0, 0))
        parent.setPos(parent.pos() + (old_tl - new_tl))

        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._parent_was_movable = False

        self._start_pos_scene = None
        event.accept()


class SplitDividerHandle(QtWidgets.QGraphicsEllipseItem):
    """Drag-Handle für den horizontalen Trenner im SplitRoundedRectItem."""

    def __init__(self, parent: "SplitRoundedRectItem"):
        radius = DIVIDER_HANDLE_DIAMETER / 2.0
        super().__init__(-radius, -radius, DIVIDER_HANDLE_DIAMETER, DIVIDER_HANDLE_DIAMETER, parent)
        self.setBrush(DIVIDER_HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._parent_was_movable = False

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None:
            flags = parent.flags()
            self._parent_was_movable = bool(
                flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            )
            if self._parent_was_movable:
                parent.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                    False,
                )
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None:
            parent._set_divider_from_scene_pos(event.scenePos())  # type: ignore[attr-defined]
        event.accept()

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None and self._parent_was_movable:
            parent.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                True,
            )
        self._parent_was_movable = False
        event.accept()


class BlockArrowHandle(QtWidgets.QGraphicsEllipseItem):
    """Orangefarbene Spezial-Handles für das BlockArrowItem."""

    def __init__(self, parent: "BlockArrowItem", role: str):
        radius = DIVIDER_HANDLE_DIAMETER / 2.0
        super().__init__(-radius, -radius, DIVIDER_HANDLE_DIAMETER, DIVIDER_HANDLE_DIAMETER, parent)
        self._role = role
        self.setBrush(DIVIDER_HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        if role == "head":
            self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        self._parent_was_movable = False

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None:
            flags = parent.flags()
            self._parent_was_movable = bool(
                flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            )
            if self._parent_was_movable:
                parent.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                    False,
                )
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent: "BlockArrowItem" = self.parentItem()  # type: ignore[assignment]
        if parent is not None:
            parent._handle_special_drag(self._role, event)
        event.accept()

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent = self.parentItem()
        if parent is not None and self._parent_was_movable:
            parent.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                True,
            )
            self._parent_was_movable = False
        event.accept()


class RotationHandle(QtWidgets.QGraphicsPixmapItem):
    """Handle zum Rotieren."""

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
        path.moveTo(15, 8); path.lineTo(11, 8); path.lineTo(13, 4); path.closeSubpath()
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
        self._center = parent.mapToScene(parent.boundingRect().center())
        pos = event.scenePos()
        self._start_angle = math.degrees(math.atan2(pos.y() - self._center.y(), pos.x() - self._center.x()))
        self._start_rotation = parent.rotation()
        flags = parent.flags()
        self._parent_was_movable = bool(flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        if parent.scene():
            scene = parent.scene()
            if self._angle_label is None:
                self._angle_label = QtWidgets.QGraphicsSimpleTextItem(); self._angle_label.setZValue(1001); scene.addItem(self._angle_label)
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
            event.ignore(); return
        pos = event.scenePos()
        angle = math.degrees(math.atan2(pos.y() - self._center.y(), pos.x() - self._center.x()))
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
            if self._angle_label: scene.removeItem(self._angle_label)
            if self._angle_label_bg: scene.removeItem(self._angle_label_bg)
        self._angle_label = None
        self._angle_label_bg = None
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        event.accept()

    def _update_label(self, angle: float) -> None:
        if not self._angle_label: return
        self._angle_label.setText(f"{angle:.1f}\N{DEGREE SIGN}")
        parent = self.parentItem()
        scene_rect = parent.mapToScene(parent.boundingRect()).boundingRect()
        pos = QtCore.QPointF(scene_rect.center().x(), scene_rect.bottom() + 25)
        br = self._angle_label.boundingRect()
        self._angle_label.setPos(pos.x() - br.width() / 2.0, pos.y())
        if self._angle_label_bg:
            padding = 2.0
            rect = QtCore.QRectF(self._angle_label.pos().x() - padding,
                                 self._angle_label.pos().y() - padding,
                                 br.width() + 2 * padding, br.height() + 2 * padding)
            self._angle_label_bg.setRect(rect)


class ResizableItem(HandleAwareItemMixin):
    """Mixin mit 8 Resize-Handles + Rotation-Handle."""

    def __init__(self):
        self._handles: list[ResizeHandle] = []
        self._rotation_handle: RotationHandle | None = None

    def _handle_rect(self) -> QtCore.QRectF:
        """Bezugsrechteck für die Platzierung der Handles."""
        return self.boundingRect()

    def _ensure_handles(self):
        if self._handles:
            return
        directions = ["top_left", "top", "top_right", "right", "bottom_right", "bottom", "bottom_left", "left"]
        for d in directions:
            h = ResizeHandle(self, d)
            h.hide()
            self._handles.append(h)
        self._rotation_handle = RotationHandle(self)
        self._rotation_handle.hide()

    def update_handles(self):
        self._ensure_handles()
        rect = self._handle_rect()
        if rect.isNull():
            rect = self.boundingRect()
        scale = self.scale() or 1.0
        o = HANDLE_OFFSET / scale
        points = [
            rect.topLeft() - QtCore.QPointF(o, o),
            QtCore.QPointF(rect.center().x(), rect.top() - o),
            rect.topRight() + QtCore.QPointF(o, -o),
            QtCore.QPointF(rect.right() + o, rect.center().y()),
            rect.bottomRight() + QtCore.QPointF(o, o),
            QtCore.QPointF(rect.center().x(), rect.bottom() + o),
            rect.bottomLeft() + QtCore.QPointF(-o, o),
            QtCore.QPointF(rect.left() - o, rect.center().y()),
        ]
        for pt, h in zip(points, self._handles):
            h.setPos(pt)
            # Cursor passend zur aktuellen Rotation
            h.setCursor(_cursor_for_dir_rotated(h._direction, getattr(self, "rotation", lambda: 0.0)()))
        if self._rotation_handle:
            rot_o = (HANDLE_OFFSET + 15.0) / scale
            rot_offset = QtCore.QPointF(rot_o, -rot_o)
            self._rotation_handle.setPos(rect.topRight() + rot_offset)

    def show_handles(self):
        self.update_handles()
        for h in self._handles:
            h.show()
        if self._rotation_handle:
            self._rotation_handle.show()

    def hide_handles(self):
        for h in self._handles:
            h.hide()
        if self._rotation_handle:
            self._rotation_handle.hide()

class LineHandle(QtWidgets.QGraphicsEllipseItem):
    """Handle für Polyline-Punkte und Midpoints."""
    def __init__(self, parent: "LineItem", index: int, is_mid: bool = False):
        super().__init__(-HANDLE_SIZE / 2.0, -HANDLE_SIZE / 2.0, HANDLE_SIZE, HANDLE_SIZE, parent)
        self.setBrush(HANDLE_COLOR)
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.index = index
        self.is_mid = is_mid
        self._parent_was_movable = False

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent: "LineItem" = self.parentItem()  # type: ignore[assignment]
        if self.is_mid:
            parent.insert_point(self.index + 1, self.pos())
            parent._mid_handles.pop(self.index)
            self.is_mid = False
            parent._handles.insert(self.index + 1, self)
            parent.update_handles()
        flags = parent.flags()
        self._parent_was_movable = bool(flags & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        parent._moving_index = self.index
        event.accept()

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent: "LineItem" = self.parentItem()  # type: ignore[assignment]
        parent._handle_move(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        parent: "LineItem" = self.parentItem()  # type: ignore[assignment]
        if self._parent_was_movable:
            parent.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._parent_was_movable = False
        parent._moving_index = None
        event.accept()


class RectItem(ResizableItem, QtWidgets.QGraphicsRectItem):
    def __init__(self, x, y, w, h, rx: float = 0.0, ry: float = 0.0):
        QtWidgets.QGraphicsRectItem.__init__(self, 0, 0, w, h)
        ResizableItem.__init__(self)
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)
        self.rx = rx
        self.ry = ry

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        if self.rx or self.ry:
            painter.setPen(self.pen())
            painter.setBrush(self.brush())
            painter.drawRoundedRect(self.rect(), self.rx, self.ry)
        else:
            super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            if self.rx or self.ry:
                painter.drawRoundedRect(self.rect(), self.rx, self.ry)
            else:
                painter.drawRect(self.rect())
            painter.restore()


class SplitRoundedRectItem(ResizableItem, QtWidgets.QGraphicsRectItem):
    def __init__(self, x: float, y: float, w: float, h: float, rx: float = 15.0, ry: float | None = None):
        QtWidgets.QGraphicsRectItem.__init__(self, 0, 0, w, h)
        ResizableItem.__init__(self)
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )

        self.rx = rx
        self.ry = ry if ry is not None else rx
        self._split_ratio = 1.0 / 3.0
        self._top_brush = QtGui.QBrush(QtGui.QColor("#f6e3b0"))
        self._bottom_brush = QtGui.QBrush(DEFAULT_FILL)
        self._divider_pen = QtGui.QPen(QtGui.QColor("#777"), 1.5)
        self._divider_pen.setCosmetic(True)

        self.setPen(PEN_NORMAL)

        self._divider_handle = SplitDividerHandle(self)
        self._divider_handle.setZValue(1.0)
        self._divider_handle.hide()
        self._update_divider_handle()

    def _handle_margin(self) -> float:
        bounds = self._divider_handle.boundingRect()
        return max(bounds.width(), bounds.height()) / 2.0

    def _line_y(self) -> float:
        rect = self.rect()
        return rect.top() + rect.height() * self._split_ratio

    def divider_ratio(self) -> float:
        return self._split_ratio

    def set_divider_ratio(self, ratio: float) -> None:
        rect = self.rect()
        if rect.height() <= 0:
            self._split_ratio = 0.5
        else:
            clamped = max(0.0, min(1.0, ratio))
            target = rect.top() + rect.height() * clamped
            self.set_divider_y(target)

    def set_divider_y(self, y: float) -> None:
        rect = self.rect()
        if rect.height() <= 0:
            self._split_ratio = 0.5
        else:
            margin = self._handle_margin()
            min_y = rect.top() + margin
            max_y = rect.bottom() - margin
            if max_y < min_y:
                y = rect.center().y()
            else:
                y = min(max(y, min_y), max_y)
            self._split_ratio = (y - rect.top()) / rect.height()
        self.update()
        self._update_divider_handle()

    def _update_divider_handle(self) -> None:
        rect = self.rect()
        self._divider_handle.setPos(rect.center().x(), self._line_y())

    def _set_divider_from_scene_pos(self, scene_pos: QtCore.QPointF) -> None:
        local = self.mapFromScene(scene_pos)
        self.set_divider_y(local.y())

    def topBrush(self) -> QtGui.QBrush:
        return QtGui.QBrush(self._top_brush)

    def bottomBrush(self) -> QtGui.QBrush:
        return QtGui.QBrush(self._bottom_brush)

    def setTopBrush(self, brush: QtGui.QBrush | QtGui.QColor) -> None:
        self._top_brush = QtGui.QBrush(brush)
        self.update()

    def setBottomBrush(self, brush: QtGui.QBrush | QtGui.QColor) -> None:
        self._bottom_brush = QtGui.QBrush(brush)
        self.update()

    def brush(self) -> QtGui.QBrush:  # type: ignore[override]
        return self.bottomBrush()

    def setBrush(self, brush: QtGui.QBrush | QtGui.QColor) -> None:  # type: ignore[override]
        self.setBottomBrush(brush)

    def setPen(self, pen: QtGui.QPen | QtGui.QColor) -> None:  # type: ignore[override]
        qpen = QtGui.QPen(pen)
        QtWidgets.QGraphicsRectItem.setPen(self, qpen)
        divider_width = max(1.0, qpen.widthF() * 0.75)
        self._divider_pen = QtGui.QPen(qpen.color(), divider_width)
        self._divider_pen.setCosmetic(True)
        self.update()

    def show_handles(self):  # type: ignore[override]
        super().show_handles()
        self._divider_handle.show()
        self._update_divider_handle()

    def hide_handles(self):  # type: ignore[override]
        super().hide_handles()
        self._divider_handle.hide()

    def update_handles(self):  # type: ignore[override]
        super().update_handles()
        self._update_divider_handle()

    def setRect(self, x: float, y: float, w: float, h: float) -> None:  # type: ignore[override]
        QtWidgets.QGraphicsRectItem.setRect(self, x, y, w, h)
        self._update_divider_handle()

    def paint(self, painter, option, widget=None):  # type: ignore[override]
        rect = self.rect()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rx = max(0.0, min(self.rx, rect.width() / 2.0, 50.0))
        ry = max(0.0, min(self.ry, rect.height() / 2.0, 50.0))

        base_path = QtGui.QPainterPath()
        if rx > 0.0 or ry > 0.0:
            base_path.addRoundedRect(rect, rx, ry)
        else:
            base_path.addRect(rect)

        line_y = self._line_y()

        top_clip = QtGui.QPainterPath()
        top_clip.addRect(rect.left(), rect.top(), rect.width(), max(0.0, line_y - rect.top()))
        top_path = base_path.intersected(top_clip)
        if not top_path.isEmpty():
            painter.fillPath(top_path, self._top_brush)

        bottom_clip = QtGui.QPainterPath()
        bottom_clip.addRect(rect.left(), line_y, rect.width(), max(0.0, rect.bottom() - line_y))
        bottom_path = base_path.intersected(bottom_clip)
        if not bottom_path.isEmpty():
            painter.fillPath(bottom_path, self._bottom_brush)

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen())
        if rx > 0.0 or ry > 0.0:
            painter.drawRoundedRect(rect, rx, ry)
        else:
            painter.drawRect(rect)

        painter.setPen(self._divider_pen)
        painter.drawLine(rect.left(), line_y, rect.right(), line_y)
        painter.restore()

        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            if rx > 0.0 or ry > 0.0:
                painter.drawRoundedRect(rect, rx, ry)
            else:
                painter.drawRect(rect)
            painter.restore()

    def shape(self) -> QtGui.QPainterPath:  # type: ignore[override]
        rect = self.rect()
        path = QtGui.QPainterPath()
        rx = max(0.0, min(self.rx, rect.width() / 2.0, 50.0))
        ry = max(0.0, min(self.ry, rect.height() / 2.0, 50.0))
        if rx > 0.0 or ry > 0.0:
            path.addRoundedRect(rect, rx, ry)
        else:
            path.addRect(rect)
        return path


class EllipseItem(ResizableItem, QtWidgets.QGraphicsEllipseItem):
    def __init__(self, x, y, w, h):
        QtWidgets.QGraphicsEllipseItem.__init__(self, 0, 0, w, h)
        ResizableItem.__init__(self)
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect())
            painter.restore()


class TriangleItem(ResizableItem, QtWidgets.QGraphicsPolygonItem):
    def __init__(self, x, y, w, h):
        QtWidgets.QGraphicsPolygonItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = w
        self._h = h
        self._update_polygon()
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

    def _update_polygon(self):
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(self._w / 2.0, 0.0),
                QtCore.QPointF(0.0, self._h),
                QtCore.QPointF(self._w, self._h),
            ]
        )
        self.setPolygon(poly)

    def set_size(self, w, h, adjust_origin: bool = True):
        self._w = w
        self._h = h
        self._update_polygon()
        if adjust_origin:
            self.setTransformOriginPoint(w / 2.0, h / 2.0)

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            rect = self.polygon().boundingRect()
            painter.drawRect(rect)
            painter.restore()


class DiamondItem(ResizableItem, QtWidgets.QGraphicsPolygonItem):
    def __init__(self, x: float, y: float, w: float, h: float):
        QtWidgets.QGraphicsPolygonItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = w
        self._h = h
        self._update_polygon()
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2.0, h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

    def _update_polygon(self) -> None:
        half_w = self._w / 2.0
        half_h = self._h / 2.0
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(half_w, 0.0),
                QtCore.QPointF(self._w, half_h),
                QtCore.QPointF(half_w, self._h),
                QtCore.QPointF(0.0, half_h),
            ]
        )
        self.setPolygon(poly)

    def set_size(self, w: float, h: float, adjust_origin: bool = True) -> None:
        self._w = w
        self._h = h
        self._update_polygon()
        if adjust_origin:
            self.setTransformOriginPoint(w / 2.0, h / 2.0)

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            rect = self.polygon().boundingRect()
            painter.drawRect(rect)
            painter.restore()


class BlockArrowItem(ResizableItem, QtWidgets.QGraphicsPolygonItem):
    """Rechts gerichteter Blockpfeil mit zwei spezialisierten Orange-Handles."""

    def __init__(self, x: float, y: float, w: float, h: float):
        QtWidgets.QGraphicsPolygonItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = max(1.0, w)
        self._h = max(1.0, h)
        self._head_ratio = 0.3
        self._shaft_ratio = 0.45
        self._head_handle: BlockArrowHandle | None = None
        self._body_handle: BlockArrowHandle | None = None
        self._update_polygon()
        self.setPos(x, y)
        self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(DEFAULT_FILL)

        self._head_handle = BlockArrowHandle(self, "head")
        self._body_handle = BlockArrowHandle(self, "body")
        self._head_handle.setZValue(1.0)
        self._body_handle.setZValue(1.0)
        self._head_handle.hide()
        self._body_handle.hide()
        self._update_custom_handles()

    def width(self) -> float:
        return self._w

    def height(self) -> float:
        return self._h

    def head_ratio(self) -> float:
        return self._head_ratio

    def shaft_ratio(self) -> float:
        return self._shaft_ratio

    def set_head_ratio(self, ratio: float, *, update_handles: bool = True) -> None:
        clamped = self._clamp_head_ratio(ratio)
        if not math.isclose(self._head_ratio, clamped, abs_tol=1e-4):
            self._head_ratio = clamped
            self._update_polygon()
            if update_handles:
                self.update_handles()
        elif update_handles:
            self._update_custom_handles()

    def set_shaft_ratio(self, ratio: float, *, update_handles: bool = True) -> None:
        clamped = self._clamp_shaft_ratio(ratio)
        if not math.isclose(self._shaft_ratio, clamped, abs_tol=1e-4):
            self._shaft_ratio = clamped
            self._update_polygon()
            if update_handles:
                self.update_handles()
        elif update_handles:
            self._update_custom_handles()

    def set_size(self, w: float, h: float, adjust_origin: bool = True) -> None:
        self._w = max(1.0, w)
        self._h = max(1.0, h)
        self._head_ratio = self._clamp_head_ratio(self._head_ratio)
        self._shaft_ratio = self._clamp_shaft_ratio(self._shaft_ratio)
        self._update_polygon()
        if adjust_origin:
            self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)
        self.update_handles()

    def _clamp_head_ratio(self, ratio: float | None = None) -> float:
        w = max(self._w, 1.0)
        min_head_px = min(w - 1.0, max(12.0, w * 0.1))
        min_tail_px = max(12.0, w * 0.1)
        min_ratio = min(0.95, max(0.05, min_head_px / w))
        max_ratio = max(0.05, min(0.95, 1.0 - (min_tail_px / w)))
        if min_ratio > max_ratio:
            mid = 0.5
            min_ratio = max_ratio = mid
        value = self._head_ratio if ratio is None else ratio
        return max(min_ratio, min(max_ratio, value))

    def _clamp_shaft_ratio(self, ratio: float | None = None) -> float:
        h = max(self._h, 1.0)
        min_shaft_px = max(12.0, h * 0.15)
        min_ratio = min(1.0, max(0.1, min_shaft_px / h))
        value = self._shaft_ratio if ratio is None else ratio
        return max(min_ratio, min(1.0, value))

    def _head_width(self) -> float:
        return self._w * self._clamp_head_ratio(self._head_ratio)

    def _shaft_bounds(self) -> tuple[float, float]:
        shaft_h = self._h * self._clamp_shaft_ratio(self._shaft_ratio)
        top = (self._h - shaft_h) / 2.0
        return top, top + shaft_h

    def _update_polygon(self) -> None:
        self.prepareGeometryChange()
        w = self._w
        h = self._h
        head_w = self._head_width()
        shaft_top, shaft_bottom = self._shaft_bounds()
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(0.0, shaft_top),
                QtCore.QPointF(w - head_w, shaft_top),
                QtCore.QPointF(w - head_w, 0.0),
                QtCore.QPointF(w, h / 2.0),
                QtCore.QPointF(w - head_w, h),
                QtCore.QPointF(w - head_w, shaft_bottom),
                QtCore.QPointF(0.0, shaft_bottom),
            ]
        )
        self.setPolygon(poly)
        self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)
        self._update_custom_handles()

    def _update_custom_handles(self) -> None:
        if not (self._head_handle and self._body_handle):
            return
        head_w = self._head_width()
        shaft_top, shaft_bottom = self._shaft_bounds()
        tail_width = self._w - head_w
        margin = DIVIDER_HANDLE_DIAMETER / 2.0
        head_pos = QtCore.QPointF(self._w - head_w, shaft_top - margin)
        body_pos = QtCore.QPointF(
            max(0.0, tail_width / 2.0), shaft_bottom + margin
        )
        self._head_handle.setPos(head_pos)
        self._body_handle.setPos(body_pos)

    def _handle_special_drag(self, role: str, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        scene_pos = event.scenePos()
        if not (event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier):
            scene_pos = snap_to_grid(self, scene_pos)
        local = self.mapFromScene(scene_pos)
        if role == "head":
            self._apply_head_drag(local.x())
        else:
            self._apply_body_drag(local.y())

    def _apply_head_drag(self, local_x: float) -> None:
        w = self._w
        if w <= 0:
            return
        min_tail = max(8.0, min(w - 8.0, w * 0.1))
        min_head = max(8.0, w * 0.1)
        max_x = max(min_tail, w - min_head)
        min_x = min_tail
        if max_x < min_x:
            min_x = max_x = w / 2.0
        clamped_x = max(min_x, min(local_x, max_x))
        ratio = (w - clamped_x) / w
        self.set_head_ratio(ratio)

    def _apply_body_drag(self, local_y: float) -> None:
        h = self._h
        if h <= 0:
            return
        center = h / 2.0
        min_shaft = max(8.0, h * 0.15)
        min_bottom = center + min_shaft / 2.0
        clamped_y = max(min_bottom, min(local_y, h))
        shaft_height = (clamped_y - center) * 2.0
        ratio = shaft_height / h
        self.set_shaft_ratio(ratio)

    def update_handles(self):  # type: ignore[override]
        super().update_handles()
        self._update_custom_handles()

    def show_handles(self):  # type: ignore[override]
        super().show_handles()
        if self._head_handle:
            self._head_handle.show()
        if self._body_handle:
            self._body_handle.show()

    def hide_handles(self):  # type: ignore[override]
        super().hide_handles()
        if self._head_handle:
            self._head_handle.hide()
        if self._body_handle:
            self._body_handle.hide()

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPolygon(self.polygon())
            painter.restore()


class FolderTreeNode:
    __slots__ = ("name", "is_folder", "children", "parent")

    def __init__(
        self,
        name: str,
        is_folder: bool = True,
        parent: "FolderTreeNode | None" = None,
    ) -> None:
        self.name = name
        self.is_folder = is_folder
        self.parent = parent
        self.children: list["FolderTreeNode"] = []

    def add_child(self, child: "FolderTreeNode") -> "FolderTreeNode":
        child.parent = self
        self.children.append(child)
        return child

    def remove_child(self, child: "FolderTreeNode") -> None:
        try:
            self.children.remove(child)
            child.parent = None
        except ValueError:
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "folder": self.is_folder,
            "children": [child.to_dict() for child in self.children],
        }

    @staticmethod
    def from_dict(
        data: Mapping[str, Any],
        parent: "FolderTreeNode | None" = None,
    ) -> "FolderTreeNode":
        name = str(data.get("name", "node"))
        is_folder = bool(data.get("folder", True))
        node = FolderTreeNode(name, is_folder, parent)
        for child_data in data.get("children", []):
            if isinstance(child_data, Mapping):
                node.add_child(FolderTreeNode.from_dict(child_data, node))
        return node


class FolderTreeBranchDot(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, tree: "FolderTreeItem", node: FolderTreeNode, radius: float):
        super().__init__(-radius, -radius, radius * 2.0, radius * 2.0, tree)
        self._tree = tree
        self._node = node
        self.setBrush(QtGui.QColor("#f28c28"))
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(
            QtCore.Qt.MouseButton.LeftButton | QtCore.Qt.MouseButton.RightButton
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
            True,
        )
        self.setZValue(1.0)

    def node(self) -> FolderTreeNode:
        return self._node

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() in (
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.RightButton,
        ):
            self._tree.open_branch_menu(self._node, event.screenPos())
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QtWidgets.QGraphicsSceneContextMenuEvent) -> None:
        self._tree.open_branch_menu(self._node, event.screenPos())
        event.accept()


class FolderTreeItem(HandleAwareItemMixin, QtWidgets.QGraphicsItem):
    LINE_COLOR = QtGui.QColor("#7a7a7a")
    FOLDER_COLOR = QtGui.QColor("#9bd97c")
    FILE_COLOR = QtGui.QColor("#f58db2")
    TEXT_COLOR = QtGui.QColor("#e7e7e7")

    def __init__(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        structure: Mapping[str, Any] | None = None,
    ) -> None:
        QtWidgets.QGraphicsItem.__init__(self)
        self.setPos(x, y)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)

        self._padding = 18.0
        self._indent = 54.0
        self._line_height = 28.0
        self._dot_radius = 6.0
        self._text_gap = 12.0
        self._font = QtGui.QFont("Cascadia Code", 11)

        self._line_pen = QtGui.QPen(self.LINE_COLOR, 1.6)
        self._line_pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        self._folder_pen = QtGui.QPen(self.FOLDER_COLOR)
        self._file_pen = QtGui.QPen(self.FILE_COLOR)

        if structure:
            self._root = FolderTreeNode.from_dict(structure)
        else:
            self._root = self._build_default_structure()

        self._node_info: dict[FolderTreeNode, dict[str, Any]] = {}
        self._order: list[FolderTreeNode] = []
        self._dot_items: dict[FolderTreeNode, FolderTreeBranchDot] = {}
        self._bounding_rect = QtCore.QRectF()

        self._rebuild_layout()
        self.setTransformOriginPoint(self.boundingRect().center())

    def update_handles(self) -> None:
        """Folder trees don't expose resize handles."""

        return

    def show_handles(self):
        return

    def hide_handles(self):
        return

    def boundingRect(self) -> QtCore.QRectF:  # type: ignore[override]
        return QtCore.QRectF(self._bounding_rect)

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            highlight = self._bounding_rect.adjusted(2.0, 2.0, -2.0, -2.0)
            painter.drawRoundedRect(highlight, 8.0, 8.0)
            painter.restore()

        painter.setPen(self._line_pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        for node in self._order:
            parent = node.parent
            if parent is None:
                continue
            info = self._node_info[node]
            parent_info = self._node_info[parent]
            parent_center: QtCore.QPointF = parent_info["dot_center"]
            child_center: QtCore.QPointF = info["dot_center"]
            offset = self._dot_radius - 1.0
            start = QtCore.QPointF(parent_center.x(), parent_center.y() + offset)
            end = QtCore.QPointF(parent_center.x(), child_center.y())
            painter.drawLine(start, end)
            start_horizontal = QtCore.QPointF(parent_center.x(), child_center.y())
            end_horizontal = QtCore.QPointF(
                child_center.x() - (self._dot_radius - 1.0), child_center.y()
            )
            painter.drawLine(start_horizontal, end_horizontal)

        painter.setFont(self._font)
        for node in self._order:
            info = self._node_info[node]
            text_rect: QtCore.QRectF = info["text_rect"]
            label = self._node_label(node)
            painter.setPen(self._folder_pen if node.is_folder else self._file_pen)
            painter.drawText(
                text_rect,
                QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
                label,
            )

    def _node_label(self, node: FolderTreeNode) -> str:
        return f"{node.name}/" if node.is_folder else node.name

    def _build_default_structure(self) -> FolderTreeNode:
        root = FolderTreeNode("projekt", True)
        docs = root.add_child(FolderTreeNode("docs", True))
        api = docs.add_child(FolderTreeNode("api", True))
        api.add_child(FolderTreeNode("index.md", False))
        src = root.add_child(FolderTreeNode("src", True))
        src.add_child(FolderTreeNode("app", True))
        src.add_child(FolderTreeNode("main.py", False))
        tests = root.add_child(FolderTreeNode("tests", True))
        tests.add_child(FolderTreeNode("test_main.py", False))
        return root

    def _rebuild_layout(self) -> None:
        fm = QtGui.QFontMetricsF(self._font)
        self._line_height = max(self._line_height, fm.height() + 8.0)

        self._node_info.clear()
        self._order.clear()

        def traverse(node: FolderTreeNode, depth: int) -> None:
            info = {"depth": depth, "row": len(self._order)}
            self._node_info[node] = info
            self._order.append(node)
            for child in node.children:
                traverse(child, depth + 1)

        traverse(self._root, 0)

        max_text_right = self._padding
        for node in self._order:
            info = self._node_info[node]
            depth = info["depth"]
            row = info["row"]
            y = self._padding + row * self._line_height
            x = self._padding + depth * self._indent
            text_x = x + self._dot_radius * 2.0 + self._text_gap
            label = self._node_label(node)
            text_width = fm.horizontalAdvance(label)
            max_text_right = max(max_text_right, text_x + text_width)
            info["dot_center"] = QtCore.QPointF(x, y + self._line_height / 2.0)
            info["text_x"] = text_x
            info["y"] = y

        width = max_text_right + self._padding
        min_width = self._padding * 2.0 + self._indent
        width = max(width, min_width)
        height = self._padding * 2.0 + max(1, len(self._order)) * self._line_height

        self.prepareGeometryChange()
        self._bounding_rect = QtCore.QRectF(0.0, 0.0, width, height)

        for node in self._order:
            info = self._node_info[node]
            text_rect = QtCore.QRectF(
                info["text_x"],
                info["y"],
                width - info["text_x"] - self._padding,
                self._line_height,
            )
            info["text_rect"] = text_rect

        self._update_branch_dots()
        self.setTransformOriginPoint(self._bounding_rect.center())
        self.update()

    def _update_branch_dots(self) -> None:
        current_nodes = set(self._order)
        for node in list(self._dot_items.keys()):
            if node not in current_nodes:
                dot = self._dot_items.pop(node)
                dot.setParentItem(None)
                if dot.scene() is not None:
                    dot.scene().removeItem(dot)
        for node in self._order:
            info = self._node_info[node]
            dot = self._dot_items.get(node)
            if dot is None:
                dot = FolderTreeBranchDot(self, node, self._dot_radius)
                self._dot_items[node] = dot
            dot.setPos(info["dot_center"])

    def open_branch_menu(
        self,
        node: FolderTreeNode,
        global_pos: QtCore.QPointF | QtCore.QPoint,
    ) -> None:
        menu = QtWidgets.QMenu()
        add_folder_action = None
        add_file_action = None
        delete_action = None

        if node.is_folder:
            add_folder_action = menu.addAction("Neuen Ordner hinzufügen")
            add_file_action = menu.addAction("Neue Datei hinzufügen")
        if node.parent is not None:
            if menu.actions():
                menu.addSeparator()
            delete_action = menu.addAction("Eintrag entfernen")

        if isinstance(global_pos, QtCore.QPointF):
            global_point = QtCore.QPoint(round(global_pos.x()), round(global_pos.y()))
        else:
            global_point = global_pos

        selected = menu.exec(global_point)
        if not selected:
            return
        if selected is add_folder_action:
            self._create_child(node, True)
        elif selected is add_file_action:
            self._create_child(node, False)
        elif selected is delete_action:
            self._delete_node(node)

    def _view_widget(self) -> QtWidgets.QWidget | None:
        scene = self.scene()
        if scene and scene.views():
            return scene.views()[0]
        return None

    def _prompt_name(
        self,
        title: str,
        label: str,
        default: str = "",
    ) -> str | None:
        parent = self._view_widget()
        text, ok = QtWidgets.QInputDialog.getText(
            parent,
            title,
            label,
            QtWidgets.QLineEdit.EchoMode.Normal,
            default,
        )
        if not ok:
            return None
        name = text.strip()
        return name or None

    def _create_child(self, parent: FolderTreeNode, is_folder: bool) -> None:
        title = "Neuen Ordner hinzufügen" if is_folder else "Neue Datei hinzufügen"
        prompt = "Ordnername:" if is_folder else "Dateiname:"
        name = self._prompt_name(title, prompt)
        if not name:
            return
        parent.add_child(FolderTreeNode(name, is_folder))
        self._rebuild_layout()

    def _delete_node(self, node: FolderTreeNode) -> None:
        if node.parent is None:
            return
        parent_widget = self._view_widget()
        reply = QtWidgets.QMessageBox.question(
            parent_widget,
            "Eintrag entfernen",
            f"Soll '{self._node_label(node)}' wirklich entfernt werden?",
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        node.parent.remove_child(node)
        self._rebuild_layout()

    def _rename_node(self, node: FolderTreeNode) -> None:
        current = node.name
        title = "Eintrag umbenennen"
        prompt = "Neuer Name:"
        name = self._prompt_name(title, prompt, current)
        if not name or name == current:
            return
        node.name = name
        self._rebuild_layout()

    def structure(self) -> dict[str, Any]:
        return self._root.to_dict()

    def set_structure(self, structure: Mapping[str, Any]) -> None:
        self._root = FolderTreeNode.from_dict(structure)
        self._rebuild_layout()

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        super().mousePressEvent(event)
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return

        local_pos = event.pos()
        for node in self._order:
            if self._node_info[node]["text_rect"].contains(local_pos):
                event.accept()
                return

    def mouseDoubleClickEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        local_pos = event.pos()
        for node in self._order:
            text_rect: QtCore.QRectF = self._node_info[node]["text_rect"]
            if text_rect.contains(local_pos):
                self._rename_node(node)
                event.accept()
                return

        super().mouseDoubleClickEvent(event)


class CurvyBracketItem(ResizableItem, QtWidgets.QGraphicsPathItem):
    """Resizable right-facing curly bracket."""

    DEFAULT_HOOK_RATIO = 0.3

    def __init__(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        hook_ratio: float | None = None,
    ) -> None:
        QtWidgets.QGraphicsPathItem.__init__(self)
        ResizableItem.__init__(self)
        self._w = max(8.0, float(w))
        self._h = max(40.0, float(h))
        if hook_ratio is None:
            hook_ratio = self.DEFAULT_HOOK_RATIO
        self._hook_ratio = self._clamp_ratio(float(hook_ratio))
        self._update_path()
        self.setPos(x, y)
        self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(PEN_NORMAL)
        self.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    def width(self) -> float:
        return self._w

    def height(self) -> float:
        return self._h

    def hook_ratio(self) -> float:
        return self._hook_ratio

    def set_hook_ratio(self, ratio: float) -> None:
        clamped = self._clamp_ratio(ratio)
        if not math.isclose(clamped, self._hook_ratio, abs_tol=1e-4):
            self._hook_ratio = clamped
            self._update_path()

    def set_size(self, w: float, h: float, adjust_origin: bool = True) -> None:
        self._w = max(8.0, float(w))
        self._h = max(40.0, float(h))
        self._update_path()
        if adjust_origin:
            self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)

    def _clamp_ratio(self, ratio: float | None = None) -> float:
        value = self._hook_ratio if ratio is None else float(ratio)
        return max(0.08, min(0.45, value))

    def _update_path(self) -> None:
        self.prepareGeometryChange()
        hook = self._hook_ratio * self._h
        path = build_curvy_bracket_path(self._w, self._h, hook)
        self.setPath(path)
        self.setTransformOriginPoint(self._w / 2.0, self._h / 2.0)

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()


class LineItem(HandleAwareItemMixin, QtWidgets.QGraphicsPathItem):
    def __init__(
        self,
        x: float,
        y: float,
        length: float | None = None,
        arrow_start: bool = False,
        arrow_end: bool = False,
        points: list[QtCore.QPointF] | None = None,
    ):
        super().__init__()
        self.setPos(x, y)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(QtGui.QPen(PEN_NORMAL))
        self.arrow_start = arrow_start
        self.arrow_end = arrow_end
        self._arrow_size = 10.0
        if points is not None:
            self._points = [QtCore.QPointF(p) for p in points]
        else:
            self._points = [QtCore.QPointF(0.0, 0.0), QtCore.QPointF(length or 0.0, 0.0)]
        self._moving_index: int | None = None
        self._handles: list[LineHandle] = []
        self._mid_handles: list[LineHandle] = []
        self._update_path()
        self.update_handles()
        self.hide_handles()

    def _update_length(self) -> None:
        total = 0.0
        for i in range(len(self._points) - 1):
            total += QtCore.QLineF(self._points[i], self._points[i + 1]).length()
        self._length = total

    def _compute_center(self) -> QtCore.QPointF:
        br = self.path().boundingRect()
        return br.center()

    def _update_path(self) -> None:
        path = QtGui.QPainterPath(self._points[0])
        for p in self._points[1:]:
            path.lineTo(p)
        self.setPath(path)
        self._update_length()
        self.setTransformOriginPoint(self._compute_center())

    def insert_point(self, index: int, pos: QtCore.QPointF) -> None:
        self._points.insert(index, QtCore.QPointF(pos))
        self._update_path()

    def _handle_move(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._moving_index is None:
            return
        new_pos = event.scenePos()
        if not (event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier):
            new_pos = snap_to_grid(self, new_pos)
        self._points[self._moving_index] = self.mapFromScene(new_pos)
        self._update_path()
        self.update_handles()
        event.accept()

    def set_arrow_start(self, val: bool) -> None:
        if self.arrow_start != val:
            self.prepareGeometryChange()
            self.arrow_start = val
            self.update()

    def set_arrow_end(self, val: bool) -> None:
        if self.arrow_end != val:
            self.prepareGeometryChange()
            self.arrow_end = val
            self.update()

    def set_pen_style(self, style: QtCore.Qt.PenStyle) -> None:
        pen = QtGui.QPen(self.pen())
        if pen.style() != style:
            pen.setStyle(style)
        if style == QtCore.Qt.PenStyle.DotLine:
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        elif pen.capStyle() == QtCore.Qt.PenCapStyle.RoundCap:
            pen.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
        self.setPen(pen)
        self.update()

    def boundingRect(self):  # type: ignore[override]
        br = super().boundingRect()
        if self.arrow_start or self.arrow_end:
            extra = self._arrow_size
            return br.adjusted(-extra, -extra, extra, extra)
        return br

    def update_handles(self) -> None:
        # Vertex-Handles
        while len(self._handles) < len(self._points):
            h = LineHandle(self, len(self._handles))
            self._handles.append(h)
        while len(self._handles) > len(self._points):
            h = self._handles.pop()
            h.setParentItem(None)
        for i, p in enumerate(self._points):
            h = self._handles[i]
            h.index = i
            h.is_mid = False
            h.setPos(p)
        # Mid-Handles
        segs = len(self._points) - 1
        while len(self._mid_handles) < segs:
            h = LineHandle(self, len(self._mid_handles), is_mid=True)
            self._mid_handles.append(h)
        while len(self._mid_handles) > segs:
            h = self._mid_handles.pop()
            h.setParentItem(None)
        for i in range(segs):
            p1, p2 = self._points[i], self._points[i + 1]
            mid = QtCore.QPointF((p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0)
            h = self._mid_handles[i]
            h.index = i
            h.is_mid = True
            h.setPos(mid)

    def show_handles(self) -> None:
        self.update_handles()
        for h in self._handles + self._mid_handles:
            h.show()

    def hide_handles(self) -> None:
        for h in self._handles + self._mid_handles:
            h.hide()

    def _arrow_head_clip_path(
        self, tip: QtCore.QPointF, direction: QtCore.QPointF
    ) -> QtGui.QPainterPath:
        clip = QtGui.QPainterPath()
        dx = direction.x()
        dy = direction.y()
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            clip.moveTo(tip)
            return clip
        nx = -dy / length
        ny = dx / length
        half_span = max(self._arrow_size * 2.0, self.pen().widthF() * 4.0)
        back_extent = max(self._arrow_size * 3.0, self.pen().widthF() * 8.0)
        clip.moveTo(tip.x() - nx * half_span, tip.y() - ny * half_span)
        clip.lineTo(tip.x() + nx * half_span, tip.y() + ny * half_span)
        clip.lineTo(
            tip.x() + nx * half_span - (dx / length) * back_extent,
            tip.y() + ny * half_span - (dy / length) * back_extent,
        )
        clip.lineTo(
            tip.x() - nx * half_span - (dx / length) * back_extent,
            tip.y() - ny * half_span - (dy / length) * back_extent,
        )
        clip.closeSubpath()
        return clip

    def _arrow_head_geometry(
        self, start: QtCore.QPointF, end: QtCore.QPointF
    ) -> tuple[QtGui.QPolygonF, QtCore.QPointF, QtGui.QPainterPath]:
        line = QtCore.QLineF(start, end)
        size = self._arrow_size
        tip = QtCore.QPointF(end)
        if line.length() <= 1e-6:
            polygon = QtGui.QPolygonF([tip, tip, tip])
            clip = QtGui.QPainterPath()
            clip.moveTo(tip)
            return polygon, tip, clip

        angle = math.atan2(-line.dy(), line.dx())
        left_point = tip + QtCore.QPointF(
            math.sin(angle - math.pi / 3.0) * size,
            math.cos(angle - math.pi / 3.0) * size,
        )
        right_point = tip + QtCore.QPointF(
            math.sin(angle - math.pi + math.pi / 3.0) * size,
            math.cos(angle - math.pi + math.pi / 3.0) * size,
        )
        base_center = QtCore.QPointF(
            (left_point.x() + right_point.x()) / 2.0,
            (left_point.y() + right_point.y()) / 2.0,
        )
        polygon = QtGui.QPolygonF([tip, left_point, right_point])
        clip = self._arrow_head_clip_path(tip, QtCore.QPointF(line.dx(), line.dy()))
        return polygon, base_center, clip

    def _draw_arrow_head(
        self, painter: QtGui.QPainter, start: QtCore.QPointF, end: QtCore.QPointF
    ) -> None:
        polygon, _, clip = self._arrow_head_geometry(start, end)
        painter.save()
        if not clip.isEmpty():
            painter.setClipPath(clip, QtCore.Qt.ClipOperation.IntersectClip)
        painter.drawPolygon(polygon)
        painter.restore()

    def paint(self, painter, option, widget=None):
        pts = self._points

        arrow_polygons: list[tuple[QtGui.QPolygonF, QtGui.QPainterPath]] = []
        if self.arrow_start or self.arrow_end:
            shaft_points = [QtCore.QPointF(p) for p in pts]
            if len(shaft_points) >= 2:
                if self.arrow_start:
                    start_poly, start_base, start_clip = self._arrow_head_geometry(
                        pts[1], pts[0]
                    )
                    arrow_polygons.append((start_poly, start_clip))
                    shaft_points[0] = start_base
                if self.arrow_end:
                    end_poly, end_base, end_clip = self._arrow_head_geometry(
                        pts[-2], pts[-1]
                    )
                    arrow_polygons.append((end_poly, end_clip))
                    shaft_points[-1] = end_base
                shaft_path = QtGui.QPainterPath(shaft_points[0])
                for point in shaft_points[1:]:
                    shaft_path.lineTo(point)
            else:
                shaft_path = QtGui.QPainterPath(self.path())
        else:
            shaft_path = QtGui.QPainterPath(self.path())

        painter.save()
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawPath(shaft_path)
        painter.restore()

        if arrow_polygons:
            painter.save()
            arrow_pen = QtGui.QPen(self.pen())
            if arrow_pen.style() != QtCore.Qt.PenStyle.SolidLine:
                arrow_pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
            arrow_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
            painter.setPen(arrow_pen)
            painter.setBrush(self.pen().color())
            for poly, clip in arrow_polygons:
                painter.save()
                if not clip.isEmpty():
                    painter.setClipPath(clip, QtCore.Qt.ClipOperation.IntersectClip)
                painter.drawPolygon(poly)
                painter.restore()
            painter.restore()

        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(shaft_path)
            for poly, clip in arrow_polygons:
                painter.save()
                if not clip.isEmpty():
                    painter.setClipPath(clip, QtCore.Qt.ClipOperation.IntersectClip)
                painter.drawPolygon(poly)
                painter.restore()
            painter.restore()


class TextItem(ResizableItem, QtWidgets.QGraphicsTextItem):
    def __init__(self, x, y, w, h):
        QtWidgets.QGraphicsTextItem.__init__(self, "Text")
        ResizableItem.__init__(self)
        self.setPos(x, y)
        font = QtGui.QFont("Arial")
        font.setPointSizeF(24.0)
        self.setFont(font)
        self.setDefaultTextColor(QtGui.QColor("#222"))
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable,
        )
        br = self.boundingRect()
        self.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)

    def setPlainText(self, text: str) -> None:  # type: ignore[override]
        super().setPlainText(text)
        br = self.boundingRect()
        self.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
        if _should_draw_selection(self):
            self.update_handles()

    def paint(self, painter, option, widget=None):
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus()
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self.setPlainText(self.toPlainText())


class GroupItem(ResizableItem, QtWidgets.QGraphicsItemGroup):
    """Gruppe mehrerer Items, gemeinsam beweg-/skalier-/rotierbar."""

    def __init__(self):
        QtWidgets.QGraphicsItemGroup.__init__(self)
        ResizableItem.__init__(self)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setData(0, "Group")
        # Wichtig: Handles dürfen Maus-Events bekommen
        self.setHandlesChildEvents(False)

    def _handle_rect(self) -> QtCore.QRectF:  # type: ignore[override]
        tight = self._contentRect()
        if not tight.isNull():
            return tight
        return QtWidgets.QGraphicsItemGroup.boundingRect(self)

    def _contentRect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF()
        first = True
        for c in self.childItems():
            if isinstance(c, (ResizeHandle, RotationHandle)):
                continue
            r = c.mapToParent(c.boundingRect()).boundingRect()
            rect = r if first else rect.united(r)
            first = False
        return rect if not first else QtCore.QRectF()

    def update_handles(self):  # type: ignore[override]
        rect = self._handle_rect()
        if not rect.isNull():
            self.setTransformOriginPoint(rect.center())
        else:
            self.setTransformOriginPoint(QtCore.QPointF())
        super().update_handles()

    def paint(self, painter, option, widget=None):
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            tight = self._contentRect()
            if not tight.isNull():
                half = PEN_SELECTED.widthF() * 0.5
                painter.drawRect(tight.adjusted(half, half, -half, -half))
            else:
                painter.drawRect(self.boundingRect())
            painter.restore()
