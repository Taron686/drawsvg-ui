# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Interactive properties panel that allows editing item attributes."""

from __future__ import annotations

import math
import weakref
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtUiTools import QUiLoader

from items import (
    BlockArrowItem,
    CurvyBracketItem,
    DiamondItem,
    EllipseItem,
    LineItem,
    RectItem,
    ShapeLabelMixin,
    SplitRoundedRectItem,
    TextItem,
    TriangleItem,
)

if TYPE_CHECKING:  # pragma: no cover - only for typing
    from canvas_view import CanvasView


Number = float

_UI_PATH = Path(__file__).resolve().parent / "ui" / "properties_panel.ui"

class ColorButton(QtWidgets.QToolButton):
    """Tool button that displays and edits a QColor."""

    colorChanged = QtCore.Signal(QtGui.QColor)

    def __init__(self, color: QtGui.QColor | str | None = None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QtGui.QColor()
        self.setAutoRaise(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setMinimumHeight(26)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.clicked.connect(self._choose_color)
        self.setColor(color or QtGui.QColor("#000000"))

    def color(self) -> QtGui.QColor:
        return QtGui.QColor(self._color)

    def setColor(self, value: QtGui.QColor | str | None) -> None:
        if isinstance(value, QtGui.QColor):
            color = QtGui.QColor(value)
        elif isinstance(value, str):
            color = QtGui.QColor(value)
        else:
            color = QtGui.QColor("#00000000")
        if not color.isValid():
            color = QtGui.QColor("#00000000")
        if self._color == color:
            return
        self._color = color
        self._update_visuals()

    def _choose_color(self) -> None:
        dialog = QtWidgets.QColorDialog(self._color, self)
        dialog.setOption(QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
        if dialog.exec():
            new_color = dialog.currentColor()
            if new_color.isValid():
                if self._color != new_color:
                    self._color = QtGui.QColor(new_color)
                    self._update_visuals()
                    self.colorChanged.emit(QtGui.QColor(self._color))

    def _update_visuals(self) -> None:
        rgba = self._color.name(QtGui.QColor.HexArgb)
        text = self._color.name(QtGui.QColor.HexRgb) if self._color.alphaF() >= 0.99 else rgba
        self.setText(text.upper())
        luminance = 0.2126 * self._color.redF() + 0.7152 * self._color.greenF() + 0.0722 * self._color.blueF()
        foreground = "#000000" if luminance > 0.6 or self._color.alphaF() < 0.5 else "#ffffff"
        self.setStyleSheet(
            "QToolButton {"
            f"background-color: {rgba};"
            "border: 1px solid #666;"
            f"color: {foreground};"
            "padding: 3px 8px;"
            "}"
        )


class PlainTextEditor(QtWidgets.QPlainTextEdit):
    """Plain text editor that emits editingFinished on focus loss or Ctrl+Enter."""

    editingFinished = QtCore.Signal()

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:  # type: ignore[override]
        super().focusOutEvent(event)
        self.editingFinished.emit()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # type: ignore[override]
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter) and (
            event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
        ):
            self.editingFinished.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _PropertiesUiLoader(QUiLoader):
    """QUiLoader that embeds the .ui file into an existing QWidget instance."""

    def __init__(self, baseinstance: QtWidgets.QWidget) -> None:
        super().__init__(baseinstance)
        self._baseinstance = baseinstance
        self.registerCustomWidget(ColorButton)
        self.registerCustomWidget(PlainTextEditor)

    def createWidget(
        self,
        class_name: str,
        parent: QtWidgets.QWidget | None = None,
        name: str = "",
    ) -> QtWidgets.QWidget:
        if parent is None and self._baseinstance is not None:
            return self._baseinstance
        widget = super().createWidget(class_name, parent, name)
        if self._baseinstance is not None and name:
            setattr(self._baseinstance, name, widget)
        return widget


class PropertyBinding(QtCore.QObject):
    """Connects a UI widget with getter/setter callables."""

    def __init__(
        self,
        widget: QtWidgets.QWidget,
        getter: Callable[[], Any],
        setter: Callable[[Any], bool | None],
        change_signal: QtCore.SignalInstance,
        read_from_widget: Callable[[QtWidgets.QWidget], Any],
        write_to_widget: Callable[[QtWidgets.QWidget, Any], None],
        change_callback: Callable[[], None],
    ) -> None:
        super().__init__(widget)
        self.widget = widget
        self._getter = getter
        self._setter = setter
        self._read = read_from_widget
        self._write = write_to_widget
        self._change_callback = change_callback
        self._guard = False
        change_signal.connect(self._on_widget_changed)

    def refresh(self) -> None:
        if self.widget is None:
            return
        value = self._getter()
        self._guard = True
        try:
            blocker = QtCore.QSignalBlocker(self.widget)
            self._write(self.widget, value)
        finally:
            self._guard = False

    def _on_widget_changed(self, *args: Any) -> None:
        if self._guard or self.widget is None:
            return
        self._guard = True
        try:
            value = self._read(self.widget)
            changed = self._setter(value)
        finally:
            self._guard = False
        if changed is not False:
            self._change_callback()


class PropertiesPanel(QtWidgets.QWidget):
    """Interactive properties panel that keeps the canvas in sync with edits."""

    def __init__(
        self,
        canvas: CanvasView | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumWidth(260)
        self._canvas = canvas
        self._current_item: QtWidgets.QGraphicsItem | None = None
        self._object_bindings: list[PropertyBinding] = []
        self._text_bindings: list[PropertyBinding] = []
        self._latest_object_data: dict[str, Any] = {}
        self._latest_text_data: dict[str, Any] = {}
        self._half_width_widgets: list[weakref.ReferenceType[QtWidgets.QWidget]] = []
        self._spacer_visible = False

        self._load_ui()
        self.setMinimumWidth(260)  # loader resets widget properties
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._layout = self.layout()
        if self._layout is None:
            self._layout = QtWidgets.QVBoxLayout(self)
            self.setLayout(self._layout)

        self._empty_spacer = QtWidgets.QSpacerItem(
            0,
            0,
            QtWidgets.QSizePolicy.Policy.Minimum,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        self._title_label = self._require_widget(QtWidgets.QLabel, "titleLabel")
        title_font = self._title_label.font()
        title_font.setBold(True)
        self._title_label.setFont(title_font)

        self._info_label = self._require_widget(QtWidgets.QLabel, "infoLabel")

        self._tab_widget = self._require_widget(QtWidgets.QTabWidget, "tabWidget")
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setMovable(False)
        self._tab_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        if self._layout is not None:
            index = self._layout.indexOf(self._tab_widget)
            if index >= 0:
                self._layout.setStretch(index, 1)

        self._cache_object_widgets()
        self._cache_text_widgets()
        self._initialize_combobox_options()
        self._initialize_half_width_tracking()
        self._reset_object_sections()
        self._reset_text_sections()
        self._set_tab_widget_active(False)
        self._set_empty_spacer_visible(True)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_half_width_widgets()

    def _load_ui(self) -> None:
        loader = _PropertiesUiLoader(self)
        ui_file = QtCore.QFile(str(_UI_PATH))
        if not ui_file.open(QtCore.QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Could not open UI file: {_UI_PATH}")
        try:
            if loader.load(ui_file) is None:
                raise RuntimeError(f"Failed to load UI from {_UI_PATH}")
        finally:
            ui_file.close()

    def _require_widget(
        self,
        widget_type: type[QtWidgets.QWidget],
        object_name: str,
    ) -> QtWidgets.QWidget:
        widget = self.findChild(widget_type, object_name)
        if widget is None:
            raise RuntimeError(f"Missing widget '{object_name}' in properties panel UI")
        return widget

    def _cache_object_widgets(self) -> None:
        self._group_transform = self._require_widget(QtWidgets.QGroupBox, "groupTransform")
        self._group_size = self._require_widget(QtWidgets.QGroupBox, "groupSize")
        self._group_rounded = self._require_widget(QtWidgets.QGroupBox, "groupRoundedCorners")
        self._group_sections = self._require_widget(QtWidgets.QGroupBox, "groupSections")
        self._group_stroke = self._require_widget(QtWidgets.QGroupBox, "groupStroke")
        self._group_fill = self._require_widget(QtWidgets.QGroupBox, "groupFill")
        self._group_arrow_shape = self._require_widget(QtWidgets.QGroupBox, "groupArrowShape")
        self._group_bracket = self._require_widget(QtWidgets.QGroupBox, "groupBracket")
        self._group_line_arrows = self._require_widget(QtWidgets.QGroupBox, "groupLineArrows")

        self._spin_pos_x = self._require_widget(QtWidgets.QDoubleSpinBox, "spinPosX")
        self._spin_pos_y = self._require_widget(QtWidgets.QDoubleSpinBox, "spinPosY")
        self._spin_rotation = self._require_widget(QtWidgets.QDoubleSpinBox, "spinRotation")
        self._spin_scale = self._require_widget(QtWidgets.QDoubleSpinBox, "spinScale")
        self._spin_z_value = self._require_widget(QtWidgets.QDoubleSpinBox, "spinZValue")
        self._spin_width = self._require_widget(QtWidgets.QDoubleSpinBox, "spinWidth")
        self._spin_height = self._require_widget(QtWidgets.QDoubleSpinBox, "spinHeight")
        self._spin_radius_x = self._require_widget(QtWidgets.QDoubleSpinBox, "spinRadiusX")
        self._spin_radius_y = self._require_widget(QtWidgets.QDoubleSpinBox, "spinRadiusY")
        self._color_top_fill = self._require_widget(ColorButton, "colorTopFill")
        self._color_bottom_fill = self._require_widget(ColorButton, "colorBottomFill")
        self._spin_divider_ratio = self._require_widget(QtWidgets.QDoubleSpinBox, "spinDividerRatio")
        self._color_stroke = self._require_widget(ColorButton, "colorStroke")
        self._spin_stroke_width = self._require_widget(QtWidgets.QDoubleSpinBox, "spinStrokeWidth")
        self._color_fill = self._require_widget(ColorButton, "colorFill")
        self._spin_head_ratio = self._require_widget(QtWidgets.QDoubleSpinBox, "spinHeadRatio")
        self._spin_shaft_ratio = self._require_widget(QtWidgets.QDoubleSpinBox, "spinShaftRatio")
        self._spin_hook_depth = self._require_widget(QtWidgets.QDoubleSpinBox, "spinHookDepth")
        self._check_arrow_start = self._require_widget(QtWidgets.QCheckBox, "checkArrowStart")
        self._check_arrow_end = self._require_widget(QtWidgets.QCheckBox, "checkArrowEnd")
        self._spin_arrow_length = self._require_widget(QtWidgets.QDoubleSpinBox, "spinArrowLength")
        self._spin_arrow_width = self._require_widget(QtWidgets.QDoubleSpinBox, "spinArrowWidth")

        self._object_groups = [
            self._group_transform,
            self._group_size,
            self._group_rounded,
            self._group_sections,
            self._group_stroke,
            self._group_fill,
            self._group_arrow_shape,
            self._group_bracket,
            self._group_line_arrows,
        ]

    def _cache_text_widgets(self) -> None:
        self._group_label = self._require_widget(QtWidgets.QGroupBox, "groupLabel")
        self._group_text_content = self._require_widget(QtWidgets.QGroupBox, "groupTextContent")
        self._group_text_format = self._require_widget(QtWidgets.QGroupBox, "groupTextFormat")

        self._line_label_text = self._require_widget(QtWidgets.QLineEdit, "lineLabelText")
        self._combo_label_font = self._require_widget(QtWidgets.QFontComboBox, "comboLabelFont")
        self._spin_label_font_size = self._require_widget(QtWidgets.QDoubleSpinBox, "spinLabelFontSize")
        self._color_label_font = self._require_widget(ColorButton, "colorLabelFont")
        self._button_label_color_default = self._require_widget(QtWidgets.QToolButton, "buttonLabelColorDefault")
        self._combo_label_horizontal = self._require_widget(QtWidgets.QComboBox, "comboLabelHorizontal")
        self._combo_label_vertical = self._require_widget(QtWidgets.QComboBox, "comboLabelVertical")

        self._plain_text_content = self._require_widget(PlainTextEditor, "plainTextContent")
        self._combo_text_font = self._require_widget(QtWidgets.QFontComboBox, "comboTextFont")
        self._spin_text_font_size = self._require_widget(QtWidgets.QDoubleSpinBox, "spinTextFontSize")
        self._color_text_font = self._require_widget(ColorButton, "colorTextFont")
        self._spin_text_padding = self._require_widget(QtWidgets.QDoubleSpinBox, "spinTextPadding")
        self._combo_text_horizontal = self._require_widget(QtWidgets.QComboBox, "comboTextHorizontal")
        self._combo_text_vertical = self._require_widget(QtWidgets.QComboBox, "comboTextVertical")
        self._combo_text_direction = self._require_widget(QtWidgets.QComboBox, "comboTextDirection")

        self._text_groups = [self._group_label, self._group_text_content, self._group_text_format]

    def _initialize_combobox_options(self) -> None:
        alignment_options = [("Left", "left"), ("Centered", "center"), ("Right", "right")]
        vertical_options = [("Top", "top"), ("Center", "middle"), ("Bottom", "bottom")]
        self._configure_combobox(self._combo_label_horizontal, alignment_options)
        self._configure_combobox(self._combo_label_vertical, vertical_options)
        self._configure_combobox(self._combo_text_horizontal, alignment_options)
        self._configure_combobox(self._combo_text_vertical, vertical_options)
        self._configure_combobox(
            self._combo_text_direction,
            [("Left to Right", "ltr"), ("Right to Left", "rtl")],
        )

    def _configure_combobox(
        self,
        combo: QtWidgets.QComboBox,
        options: list[tuple[str, Any]],
    ) -> None:
        combo.clear()
        combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.setMinimumContentsLength(1)
        combo.setMaxVisibleItems(16)
        combo.setEditable(False)
        for text, value in options:
            combo.addItem(text, value)

    def _initialize_half_width_tracking(self) -> None:
        widgets = [
            self._line_label_text,
            self._combo_label_font,
            self._combo_label_horizontal,
            self._combo_label_vertical,
            self._combo_text_font,
            self._combo_text_horizontal,
            self._combo_text_vertical,
            self._combo_text_direction,
        ]
        for widget in widgets:
            self._track_half_width_widget(widget)

    def _reset_object_sections(self) -> None:
        for group in self._object_groups:
            group.hide()

    def _reset_text_sections(self) -> None:
        for group in self._text_groups:
            group.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def _half_width_limit(self) -> int:
        base = self.width()
        if base <= 0:
            base = self.minimumWidth()
        if base <= 0:
            base = 200
        return max(40,80)

    def _track_half_width_widget(self, widget: QtWidgets.QWidget) -> None:
        if widget is None:
            return
        for ref in self._half_width_widgets:
            if ref() is widget:
                break
        else:
            self._half_width_widgets.append(weakref.ref(widget))
        self._set_widget_half_width(widget)

    def _set_widget_half_width(self, widget: QtWidgets.QWidget | None) -> None:
        if widget is None:
            return
        widget.setMaximumWidth(self._half_width_limit())

    def _update_half_width_widgets(self) -> None:
        limit = self._half_width_limit()
        alive_refs: list[weakref.ReferenceType[QtWidgets.QWidget]] = []
        for ref in self._half_width_widgets:
            widget = ref()
            if widget is None:
                continue
            widget.setMaximumWidth(limit)
            alive_refs.append(ref)
        self._half_width_widgets = alive_refs

    def clear(self) -> None:
        self._title_label.setText("Properties")
        self._info_label.setText("No object selected.")
        self._info_label.show()
        self._current_item = None
        self._latest_object_data = {}
        self._latest_text_data = {}
        self._clear_bindings()
        self._reset_object_sections()
        self._reset_text_sections()
        self._set_tab_widget_active(False)
        self._set_empty_spacer_visible(True)

    def show_multi_selection(self, count: int) -> None:
        self._title_label.setText("Properties")
        self._info_label.setText(f"{count} objects selected.")
        self._info_label.show()
        self._current_item = None
        self._latest_object_data = {}
        self._latest_text_data = {}
        self._clear_bindings()
        self._reset_object_sections()
        self._reset_text_sections()
        self._set_tab_widget_active(False)
        self._set_empty_spacer_visible(True)

    def update_snapshot(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self.clear()
            return

        selection_type = payload.get("selection_type")
        if selection_type == "single":
            item = payload.get("item")
            if not isinstance(item, QtWidgets.QGraphicsItem):
                self.clear()
                return
            title = str(payload.get("title", "Object"))
            object_data = payload.get("object_data")
            if not isinstance(object_data, dict):
                object_data = {}
            text_data = payload.get("text_data")
            if not isinstance(text_data, dict):
                text_data = {}
            self._show_single(item, title, object_data, text_data)
        elif selection_type == "multi":
            count = int(payload.get("count", 0))
            self.show_multi_selection(count)
        else:
            self.clear()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _show_single(
        self,
        item: QtWidgets.QGraphicsItem,
        title: str,
        object_data: dict[str, Any],
        text_data: dict[str, Any],
    ) -> None:
        self._title_label.setText(f"Properties – {title}")
        self._info_label.hide()

        if item is not self._current_item:
            self._current_item = item
            self._rebuild_for_item(item, object_data, text_data)
        else:
            self._latest_object_data = dict(object_data)
            self._latest_text_data = dict(text_data)
            self._refresh_active_bindings()

        if hasattr(self._tab_widget, "setCurrentIndex") and self._tab_widget.currentIndex() == -1:
            self._tab_widget.setCurrentIndex(0)
        self._set_tab_widget_active(True)
        self._set_empty_spacer_visible(False)

    def _rebuild_for_item(
        self,
        item: QtWidgets.QGraphicsItem,
        object_data: dict[str, Any],
        text_data: dict[str, Any],
    ) -> None:
        self._latest_object_data = dict(object_data)
        self._latest_text_data = dict(text_data)
        self._clear_bindings()
        self._reset_object_sections()
        self._reset_text_sections()
        self._build_object_section(item, object_data)
        self._build_text_section(item)
        self._update_text_tab_visibility()
        self._refresh_active_bindings()

    def _clear_bindings(self) -> None:
        for binding in self._object_bindings:
            binding.deleteLater()
        for binding in self._text_bindings:
            binding.deleteLater()
        self._object_bindings.clear()
        self._text_bindings.clear()

    def _bindings_for(self, group: str) -> list[PropertyBinding]:
        return self._object_bindings if group == "object" else self._text_bindings

    def _refresh_active_bindings(self) -> None:
        for binding in self._object_bindings:
            binding.refresh()
        for binding in self._text_bindings:
            binding.refresh()

    def _set_tab_widget_active(self, active: bool) -> None:
        if self._layout is None:
            return
        tab_index = self._layout.indexOf(self._tab_widget)
        self._tab_widget.show()
        self._tab_widget.setEnabled(active)
        if not active:
            self._tab_widget.setCurrentIndex(0)
        if tab_index >= 0:
            self._layout.setStretch(tab_index, 1)
        self._layout.invalidate()

    def _set_empty_spacer_visible(self, visible: bool) -> None:
        if self._layout is None or self._empty_spacer is None:
            return
        if visible and not self._spacer_visible:
            self._layout.addItem(self._empty_spacer)
            self._spacer_visible = True
        elif not visible and self._spacer_visible:
            self._layout.removeItem(self._empty_spacer)
            self._spacer_visible = False

    def _after_property_change(self) -> None:
        if self._canvas is not None:
            self._canvas.history().mark_dirty()
        self._refresh_active_bindings()

    @staticmethod
    def _set_double_spin_value(spin: QtWidgets.QDoubleSpinBox, value: Any) -> None:
        try:
            target = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(target):
            return
        precision = 10 ** (-spin.decimals())
        if abs(spin.value() - target) > precision / 2.0:
            spin.setValue(target)

    def _set_check_state(self, box: QtWidgets.QCheckBox, value: Any) -> None:
        target = bool(value)
        if box.isChecked() != target:
            box.setChecked(target)

    @staticmethod
    def _set_combo_value(combo: QtWidgets.QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index < 0:
            return
        if combo.currentIndex() != index:
            combo.setCurrentIndex(index)
    @staticmethod
    def _set_line_edit_text(edit: QtWidgets.QLineEdit, value: Any) -> None:
        text = "" if value is None else str(value)
        if edit.text() != text:
            edit.setText(text)

    @staticmethod
    def _set_plain_text(editor: PlainTextEditor, value: Any) -> None:
        text = "" if value is None else str(value)
        if editor.toPlainText() != text:
            cursor = editor.textCursor()
            position = cursor.position()
            editor.blockSignals(True)
            editor.setPlainText(text)
            cursor = editor.textCursor()
            cursor.setPosition(min(position, len(text)))
            editor.setTextCursor(cursor)
            editor.blockSignals(False)

    def _bind_double_spin(
        self,
        spin: QtWidgets.QDoubleSpinBox,
        getter: Callable[[], Number],
        setter: Callable[[Number], bool | None],
        *,
        group: str = "object",
    ) -> None:
        binding = PropertyBinding(
            spin,
            getter,
            setter,
            spin.valueChanged,
            lambda w: float(w.value()),
            self._set_double_spin_value,
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)

    def _bind_checkbox(
        self,
        box: QtWidgets.QCheckBox,
        getter: Callable[[], bool],
        setter: Callable[[bool], bool | None],
        *,
        group: str = "object",
    ) -> None:
        binding = PropertyBinding(
            box,
            getter,
            setter,
            box.toggled,
            lambda w: bool(w.isChecked()),
            self._set_check_state,
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)

    def _bind_combobox(
        self,
        combo: QtWidgets.QComboBox,
        getter: Callable[[], Any],
        setter: Callable[[Any], bool | None],
        *,
        group: str = "object",
    ) -> None:
        binding = PropertyBinding(
            combo,
            getter,
            setter,
            combo.currentIndexChanged,
            lambda w: w.currentData(),
            self._set_combo_value,
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)

    def _bind_line_edit(
        self,
        edit: QtWidgets.QLineEdit,
        getter: Callable[[], str],
        setter: Callable[[str], bool | None],
        *,
        group: str = "object",
    ) -> None:
        binding = PropertyBinding(
            edit,
            getter,
            setter,
            edit.editingFinished,
            lambda w: w.text(),
            self._set_line_edit_text,
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)

    def _bind_plain_text(
        self,
        editor: PlainTextEditor,
        getter: Callable[[], str],
        setter: Callable[[str], bool | None],
        *,
        group: str = "object",
    ) -> None:
        binding = PropertyBinding(
            editor,
            getter,
            setter,
            editor.editingFinished,
            lambda w: w.toPlainText(),
            self._set_plain_text,
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)

    def _bind_font_combobox(
        self,
        combo: QtWidgets.QFontComboBox,
        getter: Callable[[], QtGui.QFont],
        setter: Callable[[QtGui.QFont], bool | None],
        *,
        group: str = "object",
    ) -> None:
        binding = PropertyBinding(
            combo,
            getter,
            setter,
            combo.currentFontChanged,
            lambda w: w.currentFont(),
            lambda w, value: w.setCurrentFont(value),
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)

    def _bind_color_field(
        self,
        color_button: ColorButton,
        getter: Callable[[], QtGui.QColor],
        setter: Callable[[QtGui.QColor], bool | None],
        *,
        group: str = "object",
        reset_button: QtWidgets.QAbstractButton | None = None,
        resetter: Callable[[], bool | None] | None = None,
    ) -> None:
        binding = PropertyBinding(
            color_button,
            getter,
            setter,
            color_button.colorChanged,
            lambda w: w.color(),
            lambda w, value: w.setColor(value),
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)

        if reset_button is not None and resetter is not None:
            def on_reset() -> None:
                changed = resetter()
                if changed is False:
                    binding.refresh()
                else:
                    self._after_property_change()

            previous = getattr(reset_button, "_properties_panel_reset_callback", None)
            if previous is not None:
                try:
                    reset_button.clicked.disconnect(previous)
                except (TypeError, RuntimeError):
                    pass
            reset_button._properties_panel_reset_callback = on_reset  # type: ignore[attr-defined]
            reset_button.clicked.connect(on_reset)

    # ------------------------------------------------------------------ #
    # Object section                                                     #
    # ------------------------------------------------------------------ #

    def _build_object_section(self, item: QtWidgets.QGraphicsItem, object_data: dict[str, Any]) -> None:
        self._group_transform.show()
        self._bind_double_spin(
            self._spin_pos_x,
            lambda: float(item.pos().x()),
            lambda value: self._set_item_pos(item, x=value),
        )
        self._bind_double_spin(
            self._spin_pos_y,
            lambda: float(item.pos().y()),
            lambda value: self._set_item_pos(item, y=value),
        )
        self._bind_double_spin(
            self._spin_rotation,
            lambda: float(item.rotation()),
            lambda value: self._set_item_rotation(item, value),
        )
        self._bind_double_spin(
            self._spin_scale,
            lambda: float(item.scale()),
            lambda value: self._set_item_scale(item, value),
        )
        self._bind_double_spin(
            self._spin_z_value,
            lambda: float(item.zValue()),
            lambda value: self._set_item_z(item, value),
        )

        size_value = object_data.get("size")
        if isinstance(size_value, (list, tuple)) and len(size_value) == 2:
            self._group_size.show()
            self._bind_double_spin(
                self._spin_width,
                lambda item=item: float(self._item_dimensions(item)[0]),
                lambda value: self._set_item_size(item, width=value),
            )
            self._bind_double_spin(
                self._spin_height,
                lambda item=item: float(self._item_dimensions(item)[1]),
                lambda value: self._set_item_size(item, height=value),
            )

        if isinstance(item, (RectItem, SplitRoundedRectItem)) or hasattr(item, "rx"):
            self._group_rounded.show()
            self._bind_double_spin(
                self._spin_radius_x,
                lambda: float(getattr(item, "rx", 0.0)),
                lambda value: self._set_corner_radius(item, "rx", value),
            )
            self._bind_double_spin(
                self._spin_radius_y,
                lambda: float(getattr(item, "ry", getattr(item, "rx", 0.0))),
                lambda value: self._set_corner_radius(item, "ry", value),
            )

        if isinstance(item, SplitRoundedRectItem):
            self._group_sections.show()
            self._bind_color_field(
                self._color_top_fill,
                lambda: item.topBrush().color(),
                lambda color: self._set_split_brush_color(item, "top", color),
            )
            self._bind_color_field(
                self._color_bottom_fill,
                lambda: item.bottomBrush().color(),
                lambda color: self._set_split_brush_color(item, "bottom", color),
            )
            self._bind_double_spin(
                self._spin_divider_ratio,
                lambda: float(item.divider_ratio()),
                lambda value: self._set_split_ratio(item, value),
            )

        if hasattr(item, "pen") and not isinstance(item, TextItem):
            self._group_stroke.show()
            self._bind_color_field(
                self._color_stroke,
                lambda: item.pen().color(),
                lambda color: self._set_pen_color(item, color),
            )
            self._bind_double_spin(
                self._spin_stroke_width,
                lambda: float(item.pen().widthF()),
                lambda value: self._set_pen_width(item, value),
            )

        if hasattr(item, "brush") and not isinstance(item, LineItem):
            self._group_fill.show()
            self._bind_color_field(
                self._color_fill,
                lambda: item.brush().color(),
                lambda color: self._set_brush_color(item, color),
            )

        if isinstance(item, BlockArrowItem):
            self._group_arrow_shape.show()
            self._bind_double_spin(
                self._spin_head_ratio,
                item.head_ratio,
                lambda value: self._set_block_arrow_ratio(item, "head", value),
            )
            self._bind_double_spin(
                self._spin_shaft_ratio,
                item.shaft_ratio,
                lambda value: self._set_block_arrow_ratio(item, "shaft", value),
            )

        if isinstance(item, CurvyBracketItem):
            self._group_bracket.show()
            self._bind_double_spin(
                self._spin_hook_depth,
                item.hook_ratio,
                lambda value: self._set_bracket_hook_ratio(item, value),
            )

        if isinstance(item, LineItem):
            self._group_line_arrows.show()
            self._bind_checkbox(
                self._check_arrow_start,
                lambda: bool(item.arrow_start),
                lambda value: self._toggle_line_arrow(item, "start", value),
            )
            self._bind_checkbox(
                self._check_arrow_end,
                lambda: bool(item.arrow_end),
                lambda value: self._toggle_line_arrow(item, "end", value),
            )
            self._bind_double_spin(
                self._spin_arrow_length,
                item.arrow_head_length,
                lambda value: self._set_line_arrow_metric(item, "length", value),
            )
            self._bind_double_spin(
                self._spin_arrow_width,
                item.arrow_head_width,
                lambda value: self._set_line_arrow_metric(item, "width", value),
            )

    # ------------------------------------------------------------------ #
    # Text section                                                       #
    # ------------------------------------------------------------------ #

    def _build_text_section(self, item: QtWidgets.QGraphicsItem) -> None:
        if isinstance(item, TextItem):
            self._build_text_item_section(item)
        elif isinstance(item, ShapeLabelMixin):
            self._build_label_section(item)

    def _build_label_section(self, item: ShapeLabelMixin) -> None:
        self._group_label.show()
        self._bind_line_edit(
            self._line_label_text,
            item.label_text,
            lambda value: self._set_label_text(item, value),
            group="text",
        )
        self._combo_label_font.setCurrentFont(item.label_item().font())
        self._bind_font_combobox(
            self._combo_label_font,
            lambda: item.label_item().font(),
            lambda font: self._set_label_font_family(item, font),
            group="text",
        )
        self._bind_double_spin(
            self._spin_label_font_size,
            lambda: float(self._label_font_size(item)),
            lambda value: self._set_label_font_size(item, value),
            group="text",
        )
        self._bind_color_field(
            self._color_label_font,
            item.label_color,
            lambda color: self._set_label_color(item, color),
            group="text",
            reset_button=self._button_label_color_default,
            resetter=lambda: self._reset_label_color(item),
        )
        self._bind_combobox(
            self._combo_label_horizontal,
            lambda: item.label_alignment()[0],
            lambda value: self._set_label_alignment(item, horizontal=value),
            group="text",
        )
        self._bind_combobox(
            self._combo_label_vertical,
            lambda: item.label_alignment()[1],
            lambda value: self._set_label_alignment(item, vertical=value),
            group="text",
        )

    def _build_text_item_section(self, item: TextItem) -> None:
        self._group_text_content.show()
        self._bind_plain_text(
            self._plain_text_content,
            item.toPlainText,
            lambda value: self._set_text_item_content(item, value),
            group="text",
        )

        self._group_text_format.show()
        self._combo_text_font.setCurrentFont(item.font())
        self._bind_font_combobox(
            self._combo_text_font,
            lambda: item.font(),
            lambda font: self._set_text_item_font_family(item, font),
            group="text",
        )
        self._bind_double_spin(
            self._spin_text_font_size,
            lambda: float(self._text_point_size(item)),
            lambda value: self._set_text_point_size(item, value),
            group="text",
        )
        self._bind_color_field(
            self._color_text_font,
            item.defaultTextColor,
            lambda color: self._set_text_color(item, color),
            group="text",
        )
        self._bind_double_spin(
            self._spin_text_padding,
            lambda: float(item.document().documentMargin()) if item.document() else 0.0,
            lambda value: self._set_text_margin(item, value),
            group="text",
        )
        self._bind_combobox(
            self._combo_text_horizontal,
            lambda: item.text_alignment()[0],
            lambda value: self._set_text_alignment(item, horizontal=value),
            group="text",
        )
        self._bind_combobox(
            self._combo_text_vertical,
            lambda: item.text_alignment()[1],
            lambda value: self._set_text_alignment(item, vertical=value),
            group="text",
        )
        self._bind_combobox(
            self._combo_text_direction,
            item.text_direction,
            lambda value: self._set_text_direction(item, value),
            group="text",
        )

    def _update_text_tab_visibility(self) -> None:
        has_text = bool(self._text_bindings)
        if hasattr(self._tab_widget, "setTabVisible"):
            self._tab_widget.setTabVisible(1, has_text)
        else:
            self._tab_widget.setTabEnabled(1, has_text)
            if not has_text and self._tab_widget.currentIndex() == 1:
                self._tab_widget.setCurrentIndex(0)

    # ------------------------------------------------------------------ #
    # Setter helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _set_item_pos(item: QtWidgets.QGraphicsItem, *, x: Number | None = None, y: Number | None = None) -> bool:
        pos = item.pos()
        target_x = float(x) if x is not None else float(pos.x())
        target_y = float(y) if y is not None else float(pos.y())
        if math.isclose(pos.x(), target_x, abs_tol=0.1) and math.isclose(pos.y(), target_y, abs_tol=0.1):
            return False
        item.setPos(target_x, target_y)
        return True

    @staticmethod
    def _set_item_rotation(item: QtWidgets.QGraphicsItem, angle: Number) -> bool:
        target = float(angle)
        if math.isclose(item.rotation(), target, abs_tol=0.1):
            return False
        item.setRotation(target)
        return True

    @staticmethod
    def _set_item_scale(item: QtWidgets.QGraphicsItem, scale: Number) -> bool:
        target = max(0.01, float(scale))
        if math.isclose(item.scale(), target, rel_tol=1e-3, abs_tol=1e-3):
            return False
        item.setScale(target)
        return True

    @staticmethod
    def _set_item_z(item: QtWidgets.QGraphicsItem, z_value: Number) -> bool:
        target = float(z_value)
        if math.isclose(item.zValue(), target, abs_tol=0.01):
            return False
        item.setZValue(target)
        return True

    def _set_item_size(
        self,
        item: QtWidgets.QGraphicsItem,
        *,
        width: Number | None = None,
        height: Number | None = None,
    ) -> bool:
        current_w, current_h = self._item_dimensions(item)
        target_w = float(width) if width is not None else current_w
        target_h = float(height) if height is not None else current_h
        target_w = max(1.0, target_w)
        target_h = max(1.0, target_h)
        if (
            math.isclose(current_w, target_w, rel_tol=1e-3, abs_tol=0.2)
            and math.isclose(current_h, target_h, rel_tol=1e-3, abs_tol=0.2)
        ):
            return False
        old_top_left = item.mapToScene(QtCore.QPointF(0.0, 0.0))

        if isinstance(item, QtWidgets.QGraphicsRectItem):
            rect = item.rect()
            item.setRect(rect.x(), rect.y(), target_w, target_h)
        elif isinstance(item, QtWidgets.QGraphicsEllipseItem):
            rect = item.rect()
            item.setRect(rect.x(), rect.y(), target_w, target_h)
        elif isinstance(item, BlockArrowItem):
            item._w = target_w  # type: ignore[assignment]
            item._h = target_h  # type: ignore[assignment]
            item._update_polygon()  # type: ignore[attr-defined]
            item.setTransformOriginPoint(target_w / 2.0, target_h / 2.0)
        elif hasattr(item, "set_size") and callable(getattr(item, "set_size")):
            try:
                item.set_size(target_w, target_h)  # type: ignore[misc]
            except TypeError:
                item.set_size(target_w, target_h, adjust_origin=True)  # type: ignore[misc]
        else:
            base_bounds = item.boundingRect()
            scale_x = target_w / (base_bounds.width() or 1.0)
            scale_y = target_h / (base_bounds.height() or 1.0)
            item.setScale(max(scale_x, scale_y))

        new_bounds = item.boundingRect()
        item.setTransformOriginPoint(new_bounds.center())
        new_top_left = item.mapToScene(QtCore.QPointF(0.0, 0.0))
        item.setPos(item.pos() + (old_top_left - new_top_left))
        if hasattr(item, "update_handles"):
            item.update_handles()
        return True

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

    @staticmethod
    def _set_corner_radius(item: Any, attr: str, value: Number) -> bool:
        target = max(0.0, float(value))
        current = float(getattr(item, attr, 0.0))
        if math.isclose(current, target, abs_tol=0.1):
            return False
        setattr(item, attr, target)
        if hasattr(item, "update"):
            item.update()
        return True

    @staticmethod
    def _set_pen_color(item: Any, color: QtGui.QColor) -> bool:
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return False
        pen = QtGui.QPen(item.pen())
        if pen.color() == qcolor:
            return False
        pen.setColor(qcolor)
        item.setPen(pen)
        return True

    @staticmethod
    def _set_pen_width(item: Any, width: Number) -> bool:
        target = max(0.05, float(width))
        pen = QtGui.QPen(item.pen())
        if math.isclose(pen.widthF(), target, abs_tol=0.05):
            return False
        pen.setWidthF(target)
        item.setPen(pen)
        return True

    @staticmethod
    def _set_brush_color(item: Any, color: QtGui.QColor) -> bool:
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return False
        brush = QtGui.QBrush(item.brush())
        if brush.style() == QtCore.Qt.BrushStyle.NoBrush or brush.color() != qcolor:
            brush.setStyle(QtCore.Qt.BrushStyle.SolidPattern)
            brush.setColor(qcolor)
            item.setBrush(brush)
            return True
        return False

    @staticmethod
    def _set_split_brush_color(item: SplitRoundedRectItem, which: str, color: QtGui.QColor) -> bool:
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return False
        if which == "top":
            current = item.topBrush().color()
            if current == qcolor:
                return False
            item.setTopBrush(qcolor)
        else:
            current = item.bottomBrush().color()
            if current == qcolor:
                return False
            item.setBottomBrush(qcolor)
        item.update()
        return True

    @staticmethod
    def _set_split_ratio(item: SplitRoundedRectItem, value: Number) -> bool:
        target = float(value)
        current = float(item.divider_ratio())
        if math.isclose(current, target, abs_tol=1e-3):
            return False
        item.set_divider_ratio(target)
        return True

    @staticmethod
    def _set_block_arrow_ratio(item: BlockArrowItem, which: str, value: Number) -> bool:
        target = float(value)
        if which == "head":
            current = float(item.head_ratio())
            if math.isclose(current, target, abs_tol=1e-3):
                return False
            item.set_head_ratio(target)
        else:
            current = float(item.shaft_ratio())
            if math.isclose(current, target, abs_tol=1e-3):
                return False
            item.set_shaft_ratio(target)
        return True

    @staticmethod
    def _set_bracket_hook_ratio(item: CurvyBracketItem, value: Number) -> bool:
        target = float(value)
        current = float(item.hook_ratio())
        if math.isclose(current, target, abs_tol=1e-3):
            return False
        item.set_hook_ratio(target)
        return True

    @staticmethod
    def _toggle_line_arrow(item: LineItem, which: str, value: bool) -> bool:
        desired = bool(value)
        if which == "start":
            before = bool(item.arrow_start)
            if before == desired:
                return False
            item.set_arrow_start(desired)
        else:
            before = bool(item.arrow_end)
            if before == desired:
                return False
            item.set_arrow_end(desired)
        return True

    @staticmethod
    def _set_line_arrow_metric(item: LineItem, which: str, value: Number) -> bool:
        target = max(0.1, float(value))
        if which == "length":
            before = float(item.arrow_head_length())
            if math.isclose(before, target, abs_tol=0.1):
                return False
            item.set_arrow_head_length(target)
        else:
            before = float(item.arrow_head_width())
            if math.isclose(before, target, abs_tol=0.1):
                return False
            item.set_arrow_head_width(target)
        return True

    @staticmethod
    def _set_label_text(item: ShapeLabelMixin, value: str) -> bool:
        text = str(value)
        if item.label_text() == text:
            return False
        item.set_label_text(text)
        return True

    @staticmethod
    def _set_label_font_family(item: ShapeLabelMixin, font: QtGui.QFont) -> bool:
        current_font = item.label_item().font()
        if current_font.family() == font.family():
            return False
        new_font = QtGui.QFont(current_font)
        new_font.setFamily(font.family())
        item.label_item().setFont(new_font)
        return True

    @staticmethod
    def _label_font_size(item: ShapeLabelMixin) -> float:
        font = item.label_item().font()
        size = font.pixelSize()
        if size and size > 0:
            return float(size)
        point_size = font.pointSizeF()
        if point_size and point_size > 0:
            return float(point_size)
        return 16.0

    @staticmethod
    def _set_label_font_size(item: ShapeLabelMixin, value: Number) -> bool:
        size = max(4.0, float(value))
        current = PropertiesPanel._label_font_size(item)
        if math.isclose(current, size, abs_tol=0.5):
            return False
        item.set_label_font_pixel_size(int(round(size)))
        return True

    @staticmethod
    def _set_label_color(item: ShapeLabelMixin, color: QtGui.QColor) -> bool:
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return False
        has_override = item.label_has_custom_color()
        current = item.label_color()
        if has_override and current == qcolor:
            return False
        item.set_label_color(qcolor)
        return True

    @staticmethod
    def _reset_label_color(item: ShapeLabelMixin) -> bool:
        if not item.label_has_custom_color():
            return False
        item.reset_label_color()
        return True

    @staticmethod
    def _set_label_alignment(
        item: ShapeLabelMixin,
        *,
        horizontal: str | None = None,
        vertical: str | None = None,
    ) -> bool:
        before_h, before_v = item.label_alignment()
        item.set_label_alignment(horizontal=horizontal, vertical=vertical)
        after_h, after_v = item.label_alignment()
        return before_h != after_h or before_v != after_v

    @staticmethod
    def _set_text_item_content(item: TextItem, value: str) -> bool:
        text = str(value)
        if item.toPlainText() == text:
            return False
        item.setPlainText(text)
        return True

    @staticmethod
    def _set_text_item_font_family(item: TextItem, font: QtGui.QFont) -> bool:
        current = item.font()
        if current.family() == font.family():
            return False
        new_font = QtGui.QFont(current)
        new_font.setFamily(font.family())
        item.setFont(new_font)
        return True

    @staticmethod
    def _text_point_size(item: TextItem) -> float:
        font = item.font()
        size = font.pointSizeF()
        if size and size > 0:
            return float(size)
        pixel = font.pixelSize()
        if pixel and pixel > 0:
            return float(pixel)
        return 12.0

    @staticmethod
    def _set_text_point_size(item: TextItem, value: Number) -> bool:
        size = max(1.0, float(value))
        current = PropertiesPanel._text_point_size(item)
        if math.isclose(current, size, abs_tol=0.4):
            return False
        font = QtGui.QFont(item.font())
        font.setPointSizeF(size)
        if font.pointSizeF() <= 0.0:
            font.setPixelSize(int(round(size)))
        item.setFont(font)
        return True

    @staticmethod
    def _set_text_color(item: TextItem, color: QtGui.QColor) -> bool:
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return False
        current = item.defaultTextColor()
        if current == qcolor:
            return False
        item.setDefaultTextColor(qcolor)
        return True

    @staticmethod
    def _set_text_margin(item: TextItem, value: Number) -> bool:
        margin = max(0.0, float(value))
        doc = item.document()
        if doc is None:
            return False
        current = float(doc.documentMargin())
        if math.isclose(current, margin, abs_tol=0.2):
            return False
        item.set_document_margin(margin)
        return True

    @staticmethod
    def _set_text_alignment(
        item: TextItem,
        *,
        horizontal: str | None = None,
        vertical: str | None = None,
    ) -> bool:
        before = item.text_alignment()
        item.set_text_alignment(horizontal=horizontal, vertical=vertical)
        after = item.text_alignment()
        return before != after

    @staticmethod
    def _set_text_direction(item: TextItem, direction: str) -> bool:
        if item.text_direction() == direction:
            return False
        item.set_text_direction(direction)
        return True
