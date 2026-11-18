# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtGui, QtWidgets

import canvas_view
from bitmap_item import BitmapItem
from connectors import ConnectorItem
from items import (
    DiamondItem,
    GroupItem,
    LineItem,
    RectItem,
    ShapeLabelMixin,
    SplitRoundedRectItem,
    TextItem,
    TriangleItem,
)
from constants import LINE_STYLE_CHOICES
from shape_registry import SHAPE_REGISTRY


def _create_color_action(
    self: canvas_view.CanvasView,
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
    self: canvas_view.CanvasView,
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
    self: canvas_view.CanvasView, menu: QtWidgets.QMenu, item: ShapeLabelMixin
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

    def font_callback(item: ShapeLabelMixin = item) -> None:
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
        actions[action] = lambda item=item, key=key: item.set_label_alignment(
            horizontal=key
        )
    for title, key in (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom")):
        action = v_menu.addAction(title)
        action.setCheckable(True)
        action.setChecked(v_align == key)
        actions[action] = lambda item=item, key=key: item.set_label_alignment(
            vertical=key
        )
    return actions


def add_fill_actions(
    self: canvas_view.CanvasView,
    menu: QtWidgets.QMenu,
    item: QtWidgets.QAbstractGraphicsShapeItem,
    actions: dict[QtGui.QAction, Callable[[], None]],
) -> None:
    fill_action, fill_callback = self._create_color_action(
        menu,
        "Set fill color…",
        "Fill color",
        lambda item=item: item.brush().color(),
        lambda color, item=item: item.setBrush(color),
    )
    actions[fill_action] = fill_callback

    def opacity_getter(item: QtWidgets.QAbstractGraphicsShapeItem = item) -> float:
        brush = item.brush()
        if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
            return 1.0
        return brush.color().alphaF()

    def opacity_setter(
        value: float, item: QtWidgets.QAbstractGraphicsShapeItem = item
    ) -> None:
        brush = item.brush()
        color = brush.color()
        color.setAlphaF(value)
        item.setBrush(color)

    opacity_action = menu.addAction("Set fill opacity…")

    def opacity_callback(item: QtWidgets.QAbstractGraphicsShapeItem = item) -> None:
        initial_opacity = opacity_getter()
        dialog = canvas_view.OpacityDialog(initial_opacity, self)

        def handle_value_changed(
            value: float, item: QtWidgets.QAbstractGraphicsShapeItem = item
        ) -> None:
            opacity_setter(value, item)

        dialog.valueChanged.connect(handle_value_changed)
        result = dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            opacity_setter(dialog.value(), item)
        else:
            opacity_setter(initial_opacity, item)

    actions[opacity_action] = opacity_callback


def add_stroke_actions(
    self: canvas_view.CanvasView,
    menu: QtWidgets.QMenu,
    item: QtWidgets.QAbstractGraphicsShapeItem,
    actions: dict[QtGui.QAction, Callable[[], None]],
) -> None:
    def stroke_color_setter(
        color: QtGui.QColor, item: QtWidgets.QAbstractGraphicsShapeItem = item
    ) -> None:
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

    def width_setter(
        value: float, item: QtWidgets.QAbstractGraphicsShapeItem = item
    ) -> None:
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
    # Connector data stores only pen color and width, so a line style would
    # be lost on save.
    if not isinstance(item, ConnectorItem):
        add_line_style_actions(self, menu, item, actions)


def add_corner_action(
    self: canvas_view.CanvasView,
    menu: QtWidgets.QMenu,
    item: RectItem | SplitRoundedRectItem,
    actions: dict[QtGui.QAction, Callable[[], None]],
) -> None:
    corner_action = menu.addAction("Set corner radius…")

    def corner_callback(item: RectItem | SplitRoundedRectItem = item) -> None:
        initial_rx = item.rx
        initial_ry = item.ry
        dlg = canvas_view.CornerRadiusDialog(item.rx, self)

        def handle_value_changed(
            value: int, item: RectItem | SplitRoundedRectItem = item
        ) -> None:
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


def add_arrow_actions(
    self: canvas_view.CanvasView,
    menu: QtWidgets.QMenu,
    item: LineItem,
    actions: dict[QtGui.QAction, Callable[[], None]],
) -> None:
    start_action = menu.addAction("Show start arrowhead")
    start_action.setCheckable(True)
    start_action.setChecked(item.arrow_start)

    def start_callback(
        action: QtGui.QAction = start_action, item: LineItem = item
    ) -> None:
        item.set_arrow_start(action.isChecked())

    actions[start_action] = start_callback

    end_action = menu.addAction("Show end arrowhead")
    end_action.setCheckable(True)
    end_action.setChecked(item.arrow_end)

    def end_callback(action: QtGui.QAction = end_action, item: LineItem = item) -> None:
        item.set_arrow_end(action.isChecked())

    actions[end_action] = end_callback

    length_getter = item.arrow_head_length
    width_getter = item.arrow_head_width
    length_setter = item.set_arrow_head_length
    width_setter = item.set_arrow_head_width
    if all(
        callable(fn)
        for fn in (length_getter, width_getter, length_setter, width_setter)
    ):
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


def add_line_style_actions(
    self: canvas_view.CanvasView,
    menu: QtWidgets.QMenu,
    item: QtWidgets.QAbstractGraphicsShapeItem,
    actions: dict[QtGui.QAction, Callable[[], None]],
) -> None:
    style_menu = menu.addMenu("Line style")
    action_group = QtGui.QActionGroup(menu)
    action_group.setExclusive(True)
    current_style = item.pen().style()

    def make_action(text: str, style: QtCore.Qt.PenStyle) -> None:
        act = style_menu.addAction(text)
        act.setCheckable(True)
        act.setChecked(current_style == style)
        action_group.addAction(act)

        def callback(
            item: QtWidgets.QAbstractGraphicsShapeItem = item,
            style: QtCore.Qt.PenStyle = style,
        ) -> None:
            setter = getattr(item, "set_pen_style", None)
            if callable(setter):
                setter(style)
            else:
                pen = QtGui.QPen(item.pen())
                pen.setStyle(style)
                item.setPen(pen)
                item.update()

        actions[act] = callback

    for text, style in LINE_STYLE_CHOICES:
        make_action(text, style)


def add_text_actions(
    self: canvas_view.CanvasView,
    menu: QtWidgets.QMenu,
    item: TextItem,
    actions: dict[QtGui.QAction, Callable[[], None]],
) -> None:
    fit_action = menu.addAction("Fit to text")
    actions[fit_action] = lambda item=item: item.fit_to_text()
    text_color_action, text_color_callback = self._create_color_action(
        menu,
        "Set text color...",
        "Text color",
        lambda item=item: item.defaultTextColor(),
        lambda color, item=item: item.setDefaultTextColor(color),
    )
    actions[text_color_action] = text_color_callback

    def font_size_setter(value: float, item: TextItem = item) -> None:
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
    for title, key in (
        ("Left", "left"),
        ("Center", "center"),
        ("Right", "right"),
    ):
        action = h_menu.addAction(title)
        action.setCheckable(True)
        action.setChecked(h_align == key)
        actions[action] = lambda item=item, key=key: item.set_text_alignment(
            horizontal=key
        )
    for title, key in (
        ("Top", "top"),
        ("Middle", "middle"),
        ("Bottom", "bottom"),
    ):
        action = v_menu.addAction(title)
        action.setCheckable(True)
        action.setChecked(v_align == key)
        actions[action] = lambda item=item, key=key: item.set_text_alignment(
            vertical=key
        )

    dir_menu = align_menu.addMenu("Direction")
    current_dir = item.text_direction()
    for title, key in (("Left to right", "ltr"), ("Right to left", "rtl")):
        action = dir_menu.addAction(title)
        action.setCheckable(True)
        action.setChecked(current_dir == key)
        actions[action] = lambda item=item, key=key: item.set_text_direction(key)


def add_split_rect_fill_actions(
    self: canvas_view.CanvasView,
    menu: QtWidgets.QMenu,
    item: SplitRoundedRectItem,
    actions: dict[QtGui.QAction, Callable[[], None]],
) -> None:
    split_item: SplitRoundedRectItem = item  # type: ignore[assignment]

    top_action, top_callback = self._create_color_action(
        menu,
        "Set top fill color…",
        "Top fill color",
        lambda item=split_item: item.topBrush().color(),
        lambda color, item=split_item: item.setTopBrush(color),
    )
    actions[top_action] = top_callback

    def top_opacity_getter(item: SplitRoundedRectItem = split_item) -> float:
        brush = item.topBrush()
        if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
            return 1.0
        return brush.color().alphaF()

    def top_opacity_setter(
        value: float, item: SplitRoundedRectItem = split_item
    ) -> None:
        brush = item.topBrush()
        color = brush.color()
        color.setAlphaF(value)
        item.setTopBrush(color)

    top_opacity_action = menu.addAction("Set top fill opacity…")

    def top_opacity_callback(item: SplitRoundedRectItem = split_item) -> None:
        initial_opacity = top_opacity_getter()
        dialog = canvas_view.OpacityDialog(initial_opacity, self)

        def handle_value_changed(
            value: float, item: SplitRoundedRectItem = item
        ) -> None:
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

    def bottom_opacity_getter(item: SplitRoundedRectItem = split_item) -> float:
        brush = item.bottomBrush()
        if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
            return 1.0
        return brush.color().alphaF()

    def bottom_opacity_setter(
        value: float, item: SplitRoundedRectItem = split_item
    ) -> None:
        brush = item.bottomBrush()
        color = brush.color()
        color.setAlphaF(value)
        item.setBottomBrush(color)

    bottom_opacity_action = menu.addAction("Set bottom fill opacity…")

    def bottom_opacity_callback(item: SplitRoundedRectItem = split_item) -> None:
        initial_opacity = bottom_opacity_getter()
        dialog = canvas_view.OpacityDialog(initial_opacity, self)

        def handle_value_changed(
            value: float, item: SplitRoundedRectItem = item
        ) -> None:
            bottom_opacity_setter(value, item)

        dialog.valueChanged.connect(handle_value_changed)
        result = dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            bottom_opacity_setter(dialog.value(), item)
        else:
            bottom_opacity_setter(initial_opacity, item)

    actions[bottom_opacity_action] = bottom_opacity_callback


def _create_shape_style_actions(
    self: canvas_view.CanvasView, menu: QtWidgets.QMenu, item: QtWidgets.QGraphicsItem
) -> dict[QtGui.QAction, Callable[[], None]]:
    actions: dict[QtGui.QAction, Callable[[], None]] = {}

    if isinstance(item, ShapeLabelMixin):
        label_actions = self._add_shape_label_actions(menu, item)
        actions.update(label_actions)
        menu.addSeparator()

    if isinstance(item, RectItem):
        add_fill_actions(self, menu, item, actions)
        add_corner_action(self, menu, item, actions)
        menu.addSeparator()
        add_stroke_actions(self, menu, item, actions)
    elif isinstance(item, SplitRoundedRectItem):
        add_split_rect_fill_actions(self, menu, item, actions)
        add_corner_action(self, menu, item, actions)
        menu.addSeparator()
        add_stroke_actions(self, menu, item, actions)
    elif isinstance(item, (QtWidgets.QGraphicsEllipseItem, TriangleItem, DiamondItem)):
        add_fill_actions(self, menu, item, actions)
        menu.addSeparator()
        add_stroke_actions(self, menu, item, actions)
    elif isinstance(item, LineItem):
        add_arrow_actions(self, menu, item, actions)
        menu.addSeparator()
        add_stroke_actions(self, menu, item, actions)
    elif isinstance(item, TextItem):
        add_text_actions(self, menu, item, actions)
    else:
        add_stroke_actions(self, menu, item, actions)

    return actions


def contextMenuEvent(
    self: canvas_view.CanvasView, event: QtGui.QContextMenuEvent
) -> None:
    if self._suppress_context_menu:
        self._suppress_context_menu = False
        event.accept()
        return
    pos = event.pos()
    item = self.itemAt(pos)
    if isinstance(item, QtWidgets.QGraphicsTextItem):
        parent = item.parentItem()
        if isinstance(parent, ShapeLabelMixin) and parent.label_item() is item:
            item = parent
    if not item:
        menu = QtWidgets.QMenu(self)
        reset_act = menu.addAction("Reset zoom")
        action = menu.exec(event.globalPos())
        if action is reset_act:
            self.resetTransform()
        else:
            QtWidgets.QGraphicsView.contextMenuEvent(self, event)
        return

    menu = QtWidgets.QMenu(self)

    # Qt also reports children of selected groups as selected.
    selected = [
        item for item in self.scene().selectedItems() if item.parentItem() is None
    ]
    group_act, ungroup_act, align_actions = _add_selection_actions(menu, selected)

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
        QtWidgets.QGraphicsView.contextMenuEvent(self, event)
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
            _reorder_items(
                self, item, action, back1_act, front1_act, back_act, front_act
            )
        else:
            QtWidgets.QGraphicsView.contextMenuEvent(self, event)


def _reorder_items(
    self: canvas_view.CanvasView,
    item: QtWidgets.QGraphicsItem,
    action: QtGui.QAction,
    back1_act: QtGui.QAction,
    front1_act: QtGui.QAction,
    back_act: QtGui.QAction,
    front_act: QtGui.QAction,
) -> None:
    scene = self.scene()
    items = [
        it
        for it in scene.items()
        if (
            SHAPE_REGISTRY.definition_for_item(it) is not None
            or isinstance(it, GroupItem)
            or isinstance(it, ConnectorItem)
            or isinstance(it, BitmapItem)
        )
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


def _add_selection_actions(
    menu: QtWidgets.QMenu, selected: list[QtWidgets.QGraphicsItem]
) -> tuple[QtGui.QAction | None, QtGui.QAction | None, dict[QtGui.QAction, str]]:
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

    return group_act, ungroup_act, align_actions


# Public entry points used by CanvasView.
add_shape_label_actions = _add_shape_label_actions
create_color_action = _create_color_action
create_double_action = _create_double_action
create_shape_style_actions = _create_shape_style_actions
