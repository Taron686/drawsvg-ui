from PySide6 import QtCore, QtGui, QtWidgets

from constants import PALETTE_MIME, SHAPES, DEFAULTS
from items import (
    RectItem,
    EllipseItem,
    LineItem,
    TextItem,
    TriangleItem,
    GroupItem,
    ResizableItem,
    ResizeHandle,
    RotationHandle,
)

# Minimum mouse movement (in scene coordinates) required before
# showing duplicates when Ctrl+dragging selected items.
DUPLICATE_DRAG_THRESHOLD = 10.0


class CornerRadiusDialog(QtWidgets.QDialog):
    def __init__(self, radius: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Corner radius")

        layout = QtWidgets.QFormLayout(self)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 50)
        self.slider.setValue(int(radius))
        self.label = QtWidgets.QLabel(str(int(radius)))
        self.label.setFixedWidth(40)
        self.slider.valueChanged.connect(lambda v: self.label.setText(str(v)))
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

    def value(self) -> int:
        return self.slider.value()


class CanvasView(QtWidgets.QGraphicsView):
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
        self.setViewportUpdateMode(
            QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )

        scene = QtWidgets.QGraphicsScene(self)
        self._scene_padding = 200
        scene.setSceneRect(
            -self._scene_padding,
            -self._scene_padding,
            self._scene_padding * 2,
            self._scene_padding * 2,
        )
        scene.changed.connect(self._update_scene_rect)
        self.setScene(scene)
        self.setBackgroundBrush(QtGui.QColor("#fafafa"))
        self._grid_size = 20
        self._show_grid = True

        self._panning = False
        self._pan_start = QtCore.QPointF()
        self._prev_drag_mode = self.dragMode()
        self._right_button_pressed = False
        self._suppress_context_menu = False

    def clear_canvas(self):
        """Remove all items from the scene."""
        self.scene().clear()
        self._update_scene_rect()

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        super().drawBackground(painter, rect)
        if not self._show_grid:
            return
        left = int(rect.left()) - int(rect.left()) % self._grid_size
        top = int(rect.top()) - int(rect.top()) % self._grid_size
        lines = []
        x = left
        while x < rect.right():
            lines.append(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
            x += self._grid_size
        y = top
        while y < rect.bottom():
            lines.append(QtCore.QLineF(rect.left(), y, rect.right(), y))
            y += self._grid_size
        pen = QtGui.QPen(QtGui.QColor("#D0D0D0"))
        painter.setPen(pen)
        painter.drawLines(lines)

    def set_grid_visible(self, visible: bool):
        self._show_grid = visible
        self.viewport().update()

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
        x = scene_pos.x()
        y = scene_pos.y()

        w, h = DEFAULTS[shape]
        mods = event.keyboardModifiers()
        if not mods & QtCore.Qt.KeyboardModifier.AltModifier:
            size = self._grid_size
            x = round(x / size) * size
            y = round(y / size) * size
            if shape in ("Line", "Arrow"):
                w = round(w / size) * size

        if shape == "Rectangle":
            item = RectItem(x, y, w, h)
        elif shape in ("Circle", "Ellipse"):
            item = EllipseItem(x, y, w, h)
        elif shape == "Triangle":
            item = TriangleItem(x, y, w, h)
        elif shape == "Line":
            item = LineItem(x, y, w)
        elif shape == "Arrow":
            item = LineItem(x, y, w, arrow_end=True)
        else:  # "Text"
            item = TextItem(x, y, w, h)

        item.setData(0, shape)  # for export
        self.scene().addItem(item)
        item.setSelected(True)
        self._update_scene_rect()
        event.acceptProposedAction()

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
                event.accept()
                return
            if getattr(self, "_dup_source", None):
                # Ctrl+click without enough movement -> no duplication
                self._dup_source = []
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _clone_item(self, item: QtWidgets.QGraphicsItem):
        if isinstance(item, RectItem):
            r = item.rect()
            clone = RectItem(item.x(), item.y(), r.width(), r.height(), getattr(item, "rx", 0.0), getattr(item, "ry", 0.0))
            clone.setBrush(item.brush())
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
        elif isinstance(item, LineItem):
            clone = LineItem(
                item.x(),
                item.y(),
                points=[QtCore.QPointF(p) for p in item._points],
                arrow_start=getattr(item, "arrow_start", False),
                arrow_end=getattr(item, "arrow_end", False),
            )
            clone.setPen(item.pen())
        elif isinstance(item, TextItem):
            br = item.boundingRect()
            clone = TextItem(item.x(), item.y(), br.width(), br.height())
            clone.setPlainText(item.toPlainText())
            clone.setFont(item.font())
            clone.setDefaultTextColor(item.defaultTextColor())
            br = clone.boundingRect()
            clone.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
            clone.setScale(item.scale())
        else:
            return None
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
            self._update_scene_rect()

    # --- Keyboard shortcut to delete selected items ---
    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key.Key_Delete:
            selected = self.scene().selectedItems()
            if selected:
                for it in selected:
                    self.scene().removeItem(it)
                event.accept()
                return
        mods = event.modifiers()
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

    # --- Context menu for adjusting colors and line width ---
    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if self._suppress_context_menu:
            self._suppress_context_menu = False
            event.accept()
            return
        pos = event.pos()
        item = self.itemAt(pos)
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
        fill_act = opacity_act = stroke_act = width_act = None
        color_act = size_act = corner_act = None
        start_arrow_act = end_arrow_act = None

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
        if isinstance(item, RectItem):
            fill_act = menu.addAction("Set fill color…")
            opacity_act = menu.addAction("Set fill opacity…")
            corner_act = menu.addAction("Set corner radius…")
            menu.addSeparator()
            stroke_act = menu.addAction("Set stroke color…")
            width_act = menu.addAction("Set stroke width…")
        elif isinstance(item, QtWidgets.QGraphicsEllipseItem):
            fill_act = menu.addAction("Set fill color…")
            opacity_act = menu.addAction("Set fill opacity…")
            menu.addSeparator()
            stroke_act = menu.addAction("Set stroke color…")
            width_act = menu.addAction("Set stroke width…")
        elif isinstance(item, TriangleItem):
            fill_act = menu.addAction("Set fill color…")
            opacity_act = menu.addAction("Set fill opacity…")
            menu.addSeparator()
            stroke_act = menu.addAction("Set stroke color…")
            width_act = menu.addAction("Set stroke width…")
        elif isinstance(item, LineItem):
            start_arrow_act = menu.addAction("Show start arrowhead")
            start_arrow_act.setCheckable(True)
            start_arrow_act.setChecked(getattr(item, "arrow_start", False))
            end_arrow_act = menu.addAction("Show end arrowhead")
            end_arrow_act.setCheckable(True)
            end_arrow_act.setChecked(getattr(item, "arrow_end", False))
            menu.addSeparator()
            stroke_act = menu.addAction("Set stroke color…")
            width_act = menu.addAction("Set stroke width…")
        elif isinstance(item, TextItem):
            color_act = menu.addAction("Set text color…")
            size_act = menu.addAction("Set font size…")
        else:
            stroke_act = menu.addAction("Set stroke color…")
            width_act = menu.addAction("Set stroke width…")
        menu.addSeparator()
        back1_act = menu.addAction("Send backward")
        front1_act = menu.addAction("Bring forward")
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
        elif action is fill_act:
            brush = item.brush()
            color = QtWidgets.QColorDialog.getColor(brush.color(), self, "Fill color")
            if color.isValid():
                item.setBrush(color)
        elif action is opacity_act:
            brush = item.brush()
            start = brush.color().alphaF() if brush.style() != QtCore.Qt.BrushStyle.NoBrush else 1.0
            val, ok = QtWidgets.QInputDialog.getDouble(self, "Fill opacity", "Opacity:", start, 0.0, 1.0, 2)
            if ok:
                color = brush.color()
                color.setAlphaF(val)
                item.setBrush(color)
        elif action is stroke_act:
            pen = item.pen()
            color = QtWidgets.QColorDialog.getColor(pen.color(), self, "Stroke color")
            if color.isValid():
                pen.setColor(color)
                item.setPen(pen)
                item.update()
        elif action is width_act:
            pen = item.pen()
            val, ok = QtWidgets.QInputDialog.getDouble(self, "Stroke width", "Width:", pen.widthF(), 0.1, 50.0, 1)
            if ok:
                pen.setWidthF(val)
                item.setPen(pen)
                item.update()
        elif action is start_arrow_act and isinstance(item, LineItem):
            item.set_arrow_start(start_arrow_act.isChecked())
        elif action is end_arrow_act and isinstance(item, LineItem):
            item.set_arrow_end(end_arrow_act.isChecked())
        elif action is corner_act and isinstance(item, RectItem):
            dlg = CornerRadiusDialog(item.rx, self)
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                val = dlg.value()
                item.rx = item.ry = min(float(val), 50.0)
                item.update()
        elif action is color_act:
            color = QtWidgets.QColorDialog.getColor(item.defaultTextColor(), self, "Text color")
            if color.isValid():
                item.setDefaultTextColor(color)
        elif action is size_act:
            font = item.font()
            val, ok = QtWidgets.QInputDialog.getDouble(self, "Font size", "Size:", font.pointSizeF(), 1.0, 500.0, 1)
            if ok:
                font.setPointSizeF(val)
                item.setFont(font)
                br = item.boundingRect()
                item.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
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
