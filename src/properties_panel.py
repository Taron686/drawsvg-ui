"""Interactive properties panel that allows editing item attributes."""

from __future__ import annotations

import math
from typing import Any, Callable, TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

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

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title_label = QtWidgets.QLabel("Eigenschaften")
        title_font = self._title_label.font()
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        layout.addWidget(self._title_label)

        self._info_label = QtWidgets.QLabel("Kein Objekt ausgewählt.")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        self._tab_widget = QtWidgets.QTabWidget(self)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setMovable(False)

        self._object_scroll = QtWidgets.QScrollArea(self)
        self._object_scroll.setWidgetResizable(True)
        self._object_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._object_container: QtWidgets.QWidget | None = None
        self._object_form: QtWidgets.QFormLayout | None = None
        self._reset_object_form()
        self._tab_widget.addTab(self._object_scroll, "Objekt")

        self._text_scroll = QtWidgets.QScrollArea(self)
        self._text_scroll.setWidgetResizable(True)
        self._text_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._text_container: QtWidgets.QWidget | None = None
        self._text_form: QtWidgets.QFormLayout | None = None
        self._reset_text_form()
        self._tab_widget.addTab(self._text_scroll, "Text")
        self._tab_widget.hide()

        layout.addWidget(self._tab_widget, 1)

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def _reset_object_form(self) -> None:
        previous = self._object_scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        self._object_container = QtWidgets.QWidget(self)
        self._object_form = QtWidgets.QFormLayout(self._object_container)
        self._object_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._object_form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.DontWrapRows)
        self._object_form.setContentsMargins(0, 0, 0, 0)
        self._object_form.setSpacing(6)
        self._object_scroll.setWidget(self._object_container)

    def _reset_text_form(self) -> None:
        previous = self._text_scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        self._text_container = QtWidgets.QWidget(self)
        self._text_form = QtWidgets.QFormLayout(self._text_container)
        self._text_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._text_form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.DontWrapRows)
        self._text_form.setContentsMargins(0, 0, 0, 0)
        self._text_form.setSpacing(6)
        self._text_scroll.setWidget(self._text_container)

    def clear(self) -> None:
        self._title_label.setText("Eigenschaften")
        self._info_label.setText("Kein Objekt ausgewählt.")
        self._info_label.show()
        self._tab_widget.hide()
        self._current_item = None
        self._latest_object_data = {}
        self._latest_text_data = {}
        self._clear_bindings()
        self._reset_object_form()
        self._reset_text_form()

    def show_multi_selection(self, count: int) -> None:
        self._title_label.setText("Eigenschaften")
        self._info_label.setText(f"{count} Objekte ausgewählt.")
        self._info_label.show()
        self._tab_widget.hide()
        self._current_item = None
        self._latest_object_data = {}
        self._latest_text_data = {}
        self._clear_bindings()
        self._reset_object_form()
        self._reset_text_form()

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
            title = str(payload.get("title", "Objekt"))
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
        self._title_label.setText(f"Eigenschaften – {title}")
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
        self._tab_widget.show()

    def _rebuild_for_item(
        self,
        item: QtWidgets.QGraphicsItem,
        object_data: dict[str, Any],
        text_data: dict[str, Any],
    ) -> None:
        self._latest_object_data = dict(object_data)
        self._latest_text_data = dict(text_data)
        self._clear_bindings()
        self._reset_object_form()
        self._reset_text_form()
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

    def _after_property_change(self) -> None:
        if self._canvas is not None:
            self._canvas.history().mark_dirty()
        self._refresh_active_bindings()

    @staticmethod
    def _add_section_header(layout: QtWidgets.QFormLayout, text: str) -> None:
        label = QtWidgets.QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setStyleSheet("QLabel { margin-top: 8px; }")
        layout.addRow(label)

    # ------------------------------------------------------------------ #
    # Widget factory helpers                                             #
    # ------------------------------------------------------------------ #

    def _set_double_spin_value(self, spin: QtWidgets.QDoubleSpinBox, value: Any) -> None:
        try:
            target = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(target):
            return
        precision = 10 ** (-spin.decimals())
        if abs(spin.value() - target) > precision / 2.0:
            spin.setValue(target)

    def _add_double_spin(
        self,
        layout: QtWidgets.QFormLayout,
        label: str,
        getter: Callable[[], Number],
        setter: Callable[[Number], bool | None],
        *,
        decimals: int = 1,
        step: float = 1.0,
        minimum: float = -10_000.0,
        maximum: float = 10_000.0,
        suffix: str = "",
        group: str = "object",
    ) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        if suffix:
            spin.setSuffix(suffix)
        spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(label, spin)
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
        return spin

    def _set_spin_value(self, spin: QtWidgets.QSpinBox, value: Any) -> None:
        try:
            target = int(round(float(value)))
        except (TypeError, ValueError):
            return
        if spin.value() != target:
            spin.setValue(target)

    def _add_int_spin(
        self,
        layout: QtWidgets.QFormLayout,
        label: str,
        getter: Callable[[], int],
        setter: Callable[[int], bool | None],
        *,
        minimum: int = -1_000_000,
        maximum: int = 1_000_000,
        step: int = 1,
        group: str = "object",
    ) -> QtWidgets.QSpinBox:
        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(label, spin)
        binding = PropertyBinding(
            spin,
            getter,
            setter,
            spin.valueChanged,
            lambda w: int(w.value()),
            self._set_spin_value,
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for(group).append(binding)
        return spin

    def _set_check_state(self, box: QtWidgets.QCheckBox, value: Any) -> None:
        target = bool(value)
        if box.isChecked() != target:
            box.setChecked(target)

    def _add_checkbox(
        self,
        layout: QtWidgets.QFormLayout,
        label: str,
        getter: Callable[[], bool],
        setter: Callable[[bool], bool | None],
        *,
        group: str = "object",
    ) -> QtWidgets.QCheckBox:
        box = QtWidgets.QCheckBox()
        layout.addRow(label, box)
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
        return box

    @staticmethod
    def _set_combo_value(combo: QtWidgets.QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index < 0:
            return
        if combo.currentIndex() != index:
            combo.setCurrentIndex(index)

    def _add_combobox(
        self,
        layout: QtWidgets.QFormLayout,
        label: str,
        options: list[tuple[str, Any]],
        getter: Callable[[], Any],
        setter: Callable[[Any], bool | None],
        *,
        group: str = "object",
    ) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        for text, value in options:
            combo.addItem(text, value)
        combo.setEditable(False)
        layout.addRow(label, combo)
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
        return combo

    @staticmethod
    def _set_line_edit_text(edit: QtWidgets.QLineEdit, value: Any) -> None:
        text = "" if value is None else str(value)
        if edit.text() != text:
            edit.setText(text)

    def _add_line_edit(
        self,
        layout: QtWidgets.QFormLayout,
        label: str,
        getter: Callable[[], str],
        setter: Callable[[str], bool | None],
        *,
        placeholder: str = "",
        group: str = "object",
    ) -> QtWidgets.QLineEdit:
        edit = QtWidgets.QLineEdit()
        if placeholder:
            edit.setPlaceholderText(placeholder)
        layout.addRow(label, edit)
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
        return edit

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

    def _add_plain_text(
        self,
        layout: QtWidgets.QFormLayout,
        label: str,
        getter: Callable[[], str],
        setter: Callable[[str], bool | None],
        *,
        group: str = "object",
    ) -> PlainTextEditor:
        editor = PlainTextEditor()
        editor.setMinimumHeight(140)
        layout.addRow(label, editor)
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
        return editor

    def _add_color_field(
        self,
        layout: QtWidgets.QFormLayout,
        label: str,
        getter: Callable[[], QtGui.QColor],
        setter: Callable[[QtGui.QColor], bool | None],
        *,
        group: str = "object",
        resetter: Callable[[], bool | None] | None = None,
    ) -> ColorButton:
        color_button = ColorButton()
        field_widget: QtWidgets.QWidget = color_button
        reset_button: QtWidgets.QToolButton | None = None

        if resetter is not None:
            container = QtWidgets.QWidget()
            h_layout = QtWidgets.QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)
            h_layout.setSpacing(6)
            color_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            h_layout.addWidget(color_button)
            reset_button = QtWidgets.QToolButton(container)
            reset_button.setText("Standard")
            reset_button.setAutoRaise(True)
            reset_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            h_layout.addWidget(reset_button)
            field_widget = container

        layout.addRow(label, field_widget)
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

            reset_button.clicked.connect(on_reset)

        return color_button

    # ------------------------------------------------------------------ #
    # Object section                                                     #
    # ------------------------------------------------------------------ #

    def _build_object_section(self, item: QtWidgets.QGraphicsItem, object_data: dict[str, Any]) -> None:
        if self._object_form is None:
            return
        form = self._object_form
        self._add_section_header(form, "Transformieren")
        self._add_double_spin(
            form,
            "Position X",
            lambda: float(item.pos().x()),
            lambda value: self._set_item_pos(item, x=value),
            decimals=1,
            step=1.0,
            minimum=-5000.0,
            maximum=5000.0,
        )
        self._add_double_spin(
            form,
            "Position Y",
            lambda: float(item.pos().y()),
            lambda value: self._set_item_pos(item, y=value),
            decimals=1,
            step=1.0,
            minimum=-5000.0,
            maximum=5000.0,
        )
        self._add_double_spin(
            form,
            "Rotation",
            lambda: float(item.rotation()),
            lambda value: self._set_item_rotation(item, value),
            decimals=1,
            step=1.0,
            minimum=-720.0,
            maximum=720.0,
            suffix="°",
        )
        self._add_double_spin(
            form,
            "Skalierung",
            lambda: float(item.scale()),
            lambda value: self._set_item_scale(item, value),
            decimals=2,
            step=0.05,
            minimum=0.05,
            maximum=20.0,
        )
        self._add_double_spin(
            form,
            "Z-Wert",
            lambda: float(item.zValue()),
            lambda value: self._set_item_z(item, value),
            decimals=1,
            step=0.5,
            minimum=-1000.0,
            maximum=1000.0,
        )

        size_value = object_data.get("size")
        if isinstance(size_value, (list, tuple)) and len(size_value) == 2:
            self._add_section_header(form, "Größe")
            self._add_double_spin(
                form,
                "Breite",
                lambda: float(item.boundingRect().width()),
                lambda value: self._set_item_size(item, width=value),
                decimals=1,
                step=1.0,
                minimum=1.0,
                maximum=5000.0,
                suffix=" px",
            )
            self._add_double_spin(
                form,
                "Höhe",
                lambda: float(item.boundingRect().height()),
                lambda value: self._set_item_size(item, height=value),
                decimals=1,
                step=1.0,
                minimum=1.0,
                maximum=5000.0,
                suffix=" px",
            )

        if isinstance(item, (RectItem, SplitRoundedRectItem)) or hasattr(item, "rx"):
            self._add_section_header(form, "Abgerundete Ecken")
            self._add_double_spin(
                form,
                "Radius X",
                lambda: float(getattr(item, "rx", 0.0)),
                lambda value: self._set_corner_radius(item, "rx", value),
                decimals=1,
                step=1.0,
                minimum=0.0,
                maximum=200.0,
            )
            self._add_double_spin(
                form,
                "Radius Y",
                lambda: float(getattr(item, "ry", getattr(item, "rx", 0.0))),
                lambda value: self._set_corner_radius(item, "ry", value),
                decimals=1,
                step=1.0,
                minimum=0.0,
                maximum=200.0,
            )

        if isinstance(item, SplitRoundedRectItem):
            self._add_section_header(form, "Bereiche")
            self._add_color_field(
                form,
                "Füllung oben",
                lambda: item.topBrush().color(),
                lambda color: self._set_split_brush_color(item, "top", color),
            )
            self._add_color_field(
                form,
                "Füllung unten",
                lambda: item.bottomBrush().color(),
                lambda color: self._set_split_brush_color(item, "bottom", color),
            )
            self._add_double_spin(
                form,
                "Trennverhältnis",
                lambda: float(item.divider_ratio()),
                lambda value: self._set_split_ratio(item, value),
                decimals=2,
                step=0.01,
                minimum=0.05,
                maximum=0.95,
            )

        if hasattr(item, "pen") and not isinstance(item, TextItem):
            self._add_section_header(form, "Linie")
            self._add_color_field(
                form,
                "Linienfarbe",
                lambda: item.pen().color(),
                lambda color: self._set_pen_color(item, color),
            )
            self._add_double_spin(
                form,
                "Linienstärke",
                lambda: float(item.pen().widthF()),
                lambda value: self._set_pen_width(item, value),
                decimals=2,
                step=0.1,
                minimum=0.1,
                maximum=64.0,
                suffix=" px",
            )

        if hasattr(item, "brush") and not isinstance(item, LineItem):
            self._add_section_header(form, "Füllung")
            self._add_color_field(
                form,
                "Füllfarbe",
                lambda: item.brush().color(),
                lambda color: self._set_brush_color(item, color),
            )

        if isinstance(item, BlockArrowItem):
            self._add_section_header(form, "Pfeilform")
            self._add_double_spin(
                form,
                "Kopfanteil",
                item.head_ratio,
                lambda value: self._set_block_arrow_ratio(item, "head", value),
                decimals=3,
                step=0.01,
                minimum=0.05,
                maximum=0.8,
            )
            self._add_double_spin(
                form,
                "Schaftanteil",
                item.shaft_ratio,
                lambda value: self._set_block_arrow_ratio(item, "shaft", value),
                decimals=3,
                step=0.01,
                minimum=0.1,
                maximum=0.9,
            )

        if isinstance(item, CurvyBracketItem):
            self._add_section_header(form, "Klammer")
            self._add_double_spin(
                form,
                "Hakentiefe",
                item.hook_ratio,
                lambda value: self._set_bracket_hook_ratio(item, value),
                decimals=3,
                step=0.01,
                minimum=0.08,
                maximum=0.45,
            )

        if isinstance(item, LineItem):
            self._add_section_header(form, "Pfeile")
            self._add_checkbox(
                form,
                "Pfeil am Anfang",
                lambda: bool(item.arrow_start),
                lambda value: self._toggle_line_arrow(item, "start", value),
            )
            self._add_checkbox(
                form,
                "Pfeil am Ende",
                lambda: bool(item.arrow_end),
                lambda value: self._toggle_line_arrow(item, "end", value),
            )
            self._add_double_spin(
                form,
                "Pfeillänge",
                item.arrow_head_length,
                lambda value: self._set_line_arrow_metric(item, "length", value),
                decimals=1,
                step=1.0,
                minimum=1.0,
                maximum=200.0,
                suffix=" px",
            )
            self._add_double_spin(
                form,
                "Pfeilbreite",
                item.arrow_head_width,
                lambda value: self._set_line_arrow_metric(item, "width", value),
                decimals=1,
                step=1.0,
                minimum=1.0,
                maximum=200.0,
                suffix=" px",
            )

    # ------------------------------------------------------------------ #
    # Text section                                                       #
    # ------------------------------------------------------------------ #

    def _build_text_section(self, item: QtWidgets.QGraphicsItem) -> None:
        if self._text_form is None:
            return
        if isinstance(item, TextItem):
            self._build_text_item_section(item)
        elif isinstance(item, ShapeLabelMixin):
            self._build_label_section(item)

    def _build_label_section(self, item: ShapeLabelMixin) -> None:
        form = self._text_form
        if form is None:
            return
        self._add_section_header(form, "Beschriftung")
        self._add_line_edit(
            form,
            "Text",
            item.label_text,
            lambda value: self._set_label_text(item, value),
            group="text",
        )
        self._add_double_spin(
            form,
            "Schriftgröße",
            lambda: float(self._label_font_size(item)),
            lambda value: self._set_label_font_size(item, value),
            decimals=0,
            step=1.0,
            minimum=6.0,
            maximum=200.0,
            suffix=" px",
            group="text",
        )
        self._add_color_field(
            form,
            "Schriftfarbe",
            item.label_color,
            lambda color: self._set_label_color(item, color),
            group="text",
            resetter=lambda: self._reset_label_color(item),
        )
        self._add_combobox(
            form,
            "Horizontal",
            [("Links", "left"), ("Zentriert", "center"), ("Rechts", "right")],
            lambda: item.label_alignment()[0],
            lambda value: self._set_label_alignment(item, horizontal=value),
            group="text",
        )
        self._add_combobox(
            form,
            "Vertikal",
            [("Oben", "top"), ("Mittig", "middle"), ("Unten", "bottom")],
            lambda: item.label_alignment()[1],
            lambda value: self._set_label_alignment(item, vertical=value),
            group="text",
        )

    def _build_text_item_section(self, item: TextItem) -> None:
        form = self._text_form
        if form is None:
            return
        self._add_section_header(form, "Text")
        self._add_plain_text(
            form,
            "Inhalt",
            item.toPlainText,
            lambda value: self._set_text_item_content(item, value),
            group="text",
        )

        self._add_section_header(form, "Format")
        font_combo = QtWidgets.QFontComboBox()
        font_combo.setCurrentFont(item.font())
        form.addRow("Schriftart", font_combo)
        binding = PropertyBinding(
            font_combo,
            lambda: item.font(),
            lambda font: self._set_text_item_font_family(item, font),
            font_combo.currentFontChanged,
            lambda w: w.currentFont(),
            lambda w, value: w.setCurrentFont(value),
            self._after_property_change,
        )
        binding.refresh()
        self._bindings_for("text").append(binding)

        self._add_double_spin(
            form,
            "Schriftgröße",
            lambda: float(self._text_point_size(item)),
            lambda value: self._set_text_point_size(item, value),
            decimals=1,
            step=0.5,
            minimum=4.0,
            maximum=400.0,
            suffix=" pt",
            group="text",
        )
        self._add_color_field(
            form,
            "Schriftfarbe",
            item.defaultTextColor,
            lambda color: self._set_text_color(item, color),
            group="text",
        )
        self._add_double_spin(
            form,
            "Innenabstand",
            lambda: float(item.document().documentMargin()) if item.document() else 0.0,
            lambda value: self._set_text_margin(item, value),
            decimals=1,
            step=1.0,
            minimum=0.0,
            maximum=200.0,
            suffix=" px",
            group="text",
        )
        self._add_combobox(
            form,
            "Horizontal",
            [("Links", "left"), ("Zentriert", "center"), ("Rechts", "right")],
            lambda: item.text_alignment()[0],
            lambda value: self._set_text_alignment(item, horizontal=value),
            group="text",
        )
        self._add_combobox(
            form,
            "Vertikal",
            [("Oben", "top"), ("Mittig", "middle"), ("Unten", "bottom")],
            lambda: item.text_alignment()[1],
            lambda value: self._set_text_alignment(item, vertical=value),
            group="text",
        )
        self._add_combobox(
            form,
            "Textrichtung",
            [("Links nach rechts", "ltr"), ("Rechts nach links", "rtl")],
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
        bounds = item.boundingRect()
        current_w = float(bounds.width())
        current_h = float(bounds.height())
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
