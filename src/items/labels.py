"""Label mixins and helpers shared by shape items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from constants import DEFAULT_TEXT_COLOR, DEFAULT_FONT_FAMILY
if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from .shapes.rects import RectItem


class _ShapeLabelItem(QtWidgets.QGraphicsTextItem):
    def __init__(self, parent: "RectItem") -> None:
        super().__init__("", parent)
        self.setFont(QtGui.QFont(DEFAULT_FONT_FAMILY))
        self.setDefaultTextColor(DEFAULT_TEXT_COLOR)
        self.setVisible(False)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, False)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setZValue(1.0)
        doc = self.document()
        doc.setDocumentMargin(0.0)
        text_option = doc.defaultTextOption()
        text_option.setWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(text_option)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:  # type: ignore[override]
        super().focusOutEvent(event)
        parent = self.parentItem()
        if isinstance(parent, ShapeLabelMixin):
            parent._finish_label_edit()


class ShapeLabelMixin:
    def _init_shape_label(self) -> None:
        self._label_color_override: QtGui.QColor | None = None
        self._label_base_color: QtGui.QColor = QtGui.QColor(DEFAULT_TEXT_COLOR)
        self._label = _ShapeLabelItem(self)
        self._label_h_align = "center"
        self._label_v_align = "middle"
        self._label_padding = 8.0
        self._label.document().contentsChanged.connect(self._update_label_geometry)
        self._apply_label_alignment()
        self._update_label_color()
        self._update_label_geometry()

    def _label_base_rect(self) -> QtCore.QRectF:
        raise NotImplementedError

    def label_text(self) -> str:
        return self._label.toPlainText()

    def set_label_text(self, text: str) -> None:
        self._label.setPlainText(text)
        self._label.setVisible(bool(text.strip()))
        self._update_label_geometry()

    def has_label(self) -> bool:
        return bool(self._label.toPlainText().strip())

    def label_alignment(self) -> tuple[str, str]:
        return self._label_h_align, self._label_v_align

    def set_label_alignment(
        self,
        *,
        horizontal: str | None = None,
        vertical: str | None = None,
    ) -> None:
        valid_h = {"left", "center", "right"}
        valid_v = {"top", "middle", "bottom"}
        changed = False
        if horizontal in valid_h and horizontal != self._label_h_align:
            self._label_h_align = horizontal
            changed = True
        if vertical in valid_v and vertical != self._label_v_align:
            self._label_v_align = vertical
            changed = True
        if changed:
            self._apply_label_alignment()
            self._update_label_geometry()

    def edit_label(self) -> None:
        self._begin_label_edit()

    def set_label_font_pixel_size(self, value: float) -> None:
        font = QtGui.QFont(self._label.font())
        font.setPixelSize(int(value))
        self._label.setFont(font)
        self._update_label_geometry()

    def label_color(self) -> QtGui.QColor:
        return QtGui.QColor(self._label.defaultTextColor())

    def label_has_custom_color(self) -> bool:
        override = getattr(self, "_label_color_override", None)
        return isinstance(override, QtGui.QColor) and override.isValid()

    def set_label_color(self, color: QtGui.QColor | str) -> None:
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return
        self._label_color_override = QtGui.QColor(qcolor)
        self._label.setDefaultTextColor(self._label_color_override)

    def reset_label_color(
        self,
        *,
        update: bool = True,
        base_color: QtGui.QColor | str | None = None,
    ) -> None:
        self._label_color_override = None
        if base_color is None:
            base = QtGui.QColor(DEFAULT_TEXT_COLOR)
        else:
            base = QtGui.QColor(base_color)
            if not base.isValid():
                base = QtGui.QColor(DEFAULT_TEXT_COLOR)
        self._label_base_color = base
        if update:
            self._update_label_color()

    def label_item(self) -> QtWidgets.QGraphicsTextItem:
        return self._label

    def _apply_label_alignment(self) -> None:
        option = self._label.document().defaultTextOption()
        if self._label_h_align == "left":
            option.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        elif self._label_h_align == "right":
            option.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        else:
            option.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        self._label.document().setDefaultTextOption(option)

    def _label_available_rect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF(self._label_base_rect())
        pad = self._label_padding
        rect.adjust(pad, pad, -pad, -pad)
        if rect.width() <= 0.0:
            rect.setWidth(1.0)
        if rect.height() <= 0.0:
            rect.setHeight(1.0)
        return rect

    def _update_label_geometry(self) -> None:
        rect = self._label_available_rect()
        self._label.setTextWidth(rect.width())
        br = self._label.boundingRect()
        left = br.left()
        right = br.right()
        top = br.top()
        bottom = br.bottom()
        width = br.width()
        height = br.height()

        if self._label_h_align == "left":
            x = rect.left() - left
        elif self._label_h_align == "right":
            x = rect.right() - right
        else:
            target_cx = rect.center().x()
            x = target_cx - (left + width / 2.0)

        if self._label_v_align == "top":
            y = rect.top() - top
        elif self._label_v_align == "bottom":
            y = rect.bottom() - bottom
        else:
            target_cy = rect.center().y()
            y = target_cy - (top + height / 2.0)

        base_rect = self._label_base_rect()
        min_x = base_rect.left() - left
        max_x = base_rect.right() - right
        min_y = base_rect.top() - top
        max_y = base_rect.bottom() - bottom
        x = max(min_x, min(x, max_x))
        y = max(min_y, min(y, max_y))
        self._label.setPos(x, y)
        self._label.setVisible(self.has_label())

    def _update_label_color(self) -> None:
        if hasattr(self, "_label") and self._label is not None:
            override = getattr(self, "_label_color_override", None)
            if isinstance(override, QtGui.QColor) and override.isValid():
                target = QtGui.QColor(override)
            else:
                base = getattr(self, "_label_base_color", QtGui.QColor(DEFAULT_TEXT_COLOR))
                target = QtGui.QColor(base)
            self._label.setDefaultTextColor(target)

    def _begin_label_edit(self) -> None:
        self._label.setVisible(True)
        self._apply_label_alignment()
        self._label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextEditorInteraction)
        self._label.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self._label.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        cursor = self._label.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.Document)
        self._label.setTextCursor(cursor)

    def _clear_label_highlight(self) -> None:
        if not hasattr(self, "_label") or self._label is None:
            return
        cursor = self._label.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self._label.setTextCursor(cursor)
        self._label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self._label.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self._label.clearFocus()

    def _finish_label_edit(self) -> None:
        if not hasattr(self, "_label") or self._label is None:
            return
        self._clear_label_highlight()
        if not self.has_label():
            self._label.setVisible(False)
        self._update_label_geometry()

    def copy_label_from(self, other: "ShapeLabelMixin") -> None:
        if not isinstance(other, ShapeLabelMixin):
            return
        self._label_h_align, self._label_v_align = other.label_alignment()
        other_label = other.label_item()
        self._label.setFont(QtGui.QFont(other_label.font()))
        if other.label_has_custom_color():
            self.set_label_color(other.label_color())
        else:
            self.reset_label_color(update=True, base_color=other_label.defaultTextColor())
        self._apply_label_alignment()
        self.set_label_text(other.label_text())

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if not bool(value):
                self._clear_label_highlight()
        return super().itemChange(change, value)


__all__ = ["ShapeLabelMixin", "_ShapeLabelItem"]
