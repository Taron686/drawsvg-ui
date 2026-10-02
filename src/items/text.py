# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Text and grouping items."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .base import ResizableItem, ResizeHandle, RotationHandle, _should_draw_selection
from constants import PEN_SELECTED, DEFAULT_TEXT_COLOR, DEFAULT_FONT_FAMILY


class TextItem(ResizableItem, QtWidgets.QGraphicsTextItem):
    """Editable text with a fitted box, or an explicitly resized wrapping box."""

    _MIN_DIMENSION = 10.0
    _VALID_H_ALIGN = ("left", "center", "right")
    _VALID_V_ALIGN = ("top", "middle", "bottom")
    _VALID_DIRECTIONS = {
        "ltr": QtCore.Qt.LayoutDirection.LeftToRight,
        "rtl": QtCore.Qt.LayoutDirection.RightToLeft,
    }

    def __init__(self, x, y, w, h, *, auto_size: bool = True):
        QtWidgets.QGraphicsTextItem.__init__(self, "Text")
        self._box_size = QtCore.QSizeF(1.0, 1.0)
        self._auto_size = auto_size
        self._fitting_text = False
        self._text_h_align = "left"
        self._text_v_align = "top"
        self._text_direction = "ltr"
        self._content_offset = QtCore.QPointF()
        ResizableItem.__init__(self)
        font = QtGui.QFont(DEFAULT_FONT_FAMILY)
        font.setPointSizeF(24.0)
        super().setFont(font)
        self.setDefaultTextColor(DEFAULT_TEXT_COLOR)
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable,
        )
        base_rect = QtWidgets.QGraphicsTextItem.boundingRect(self)
        width = float(w) if w and w > 0.0 else base_rect.width()
        height = float(h) if h and h > 0.0 else base_rect.height()
        self._set_box_size(width, height, update_origin=True, from_init=True)
        if self._auto_size:
            self._fit_box_to_document()
        self.setPos(x, y)
        self.document().contentsChanged.connect(self._fit_box_to_document)

    def setPlainText(self, text: str) -> None:  # type: ignore[override]
        super().setPlainText(text)
        if self._auto_size:
            self._fit_box_to_document()
        else:
            self._update_document_constraints()
            self._update_transform_origin()
            if _should_draw_selection(self):
                self.update_handles()
        self.update()

    def setFont(self, font: QtGui.QFont) -> None:  # type: ignore[override]
        super().setFont(font)
        if self._auto_size:
            self._fit_box_to_document()
            return
        self._update_document_constraints()
        self._update_transform_origin()
        if _should_draw_selection(self):
            self.update_handles()
        self.update()

    def paint(self, painter, option, widget=None):
        rect = self.boundingRect()
        painter.save()
        painter.setClipRect(rect)
        painter.translate(self._content_offset)
        opt = QtWidgets.QStyleOptionGraphicsItem(option)
        opt.state &= ~QtWidgets.QStyle.StateFlag.State_Selected
        super().paint(painter, opt, widget)
        painter.restore()
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.restore()

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus()
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        self.setPlainText(self.toPlainText())

    def set_document_margin(self, margin: float) -> None:
        """Adjust the QTextDocument margin and keep layout in sync."""

        doc = self.document()
        if doc is None:
            return
        doc.setDocumentMargin(max(0.0, float(margin)))
        if self._auto_size:
            self._fit_box_to_document()
            return
        self._update_document_constraints()
        self._update_transform_origin()
        if _should_draw_selection(self):
            self.update_handles()
        self.update()

    def set_size(self, width: float, height: float, adjust_origin: bool = True) -> None:
        """Resize the bounding box without scaling the text."""

        self._auto_size = False
        self._set_box_size(width, height, update_origin=adjust_origin)

    def auto_sizes_to_text(self) -> bool:
        return self._auto_size

    def fit_to_text(self) -> None:
        """Fit the field to its text and continue fitting subsequent edits."""
        self._auto_size = True
        self._fit_box_to_document()

    def _fit_box_to_document(self) -> None:
        if not self._auto_size or self._fitting_text:
            return
        self._fitting_text = True
        try:
            self._update_document_constraints()
            # Measure without a width constraint, then lay out all explicit lines
            # against the fitted width so center/right alignment shares one box.
            self.setTextWidth(-1.0)
            self.document().setPageSize(QtCore.QSizeF(-1.0, -1.0))
            size = self.document().size()
            anchor = self.mapToParent(QtCore.QPointF())
            self._set_box_size(
                size.width(), size.height(), update_origin=True, snap_position=False
            )
            delta = anchor - self.mapToParent(QtCore.QPointF())
            if not delta.isNull():
                # Changing the pivot of a rotated/scaled item must not move its text.
                # This compensation is geometry maintenance, not a grid-snapped drag.
                flag = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
                sends_changes = bool(self.flags() & flag)
                self.setFlag(flag, False)
                try:
                    self.setPos(self.pos() + delta)
                finally:
                    self.setFlag(flag, sends_changes)
        finally:
            self._fitting_text = False

    def text_alignment(self) -> tuple[str, str]:
        return self._text_h_align, self._text_v_align

    def set_text_alignment(
        self,
        *,
        horizontal: str | None = None,
        vertical: str | None = None,
    ) -> None:
        changed = False
        if horizontal in self._VALID_H_ALIGN and horizontal != self._text_h_align:
            self._text_h_align = horizontal
            changed = True
        if vertical in self._VALID_V_ALIGN and vertical != self._text_v_align:
            self._text_v_align = vertical
            changed = True
        if changed:
            self._update_document_constraints()
            self._update_transform_origin()
            if _should_draw_selection(self):
                self.update_handles()
            self.update()

    def text_direction(self) -> str:
        return self._text_direction

    def set_text_direction(self, direction: str) -> None:
        if direction not in self._VALID_DIRECTIONS:
            return
        if direction == self._text_direction:
            return
        self._text_direction = direction
        self._update_document_constraints()
        self._update_transform_origin()
        if _should_draw_selection(self):
            self.update_handles()
        self.update()

    def boundingRect(self) -> QtCore.QRectF:  # type: ignore[override]
        return QtCore.QRectF(
            0.0,
            0.0,
            self._box_size.width(),
            self._box_size.height(),
        )

    def shape(self) -> QtGui.QPainterPath:  # type: ignore[override]
        path = QtGui.QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def _set_box_size(
        self,
        width: float,
        height: float,
        *,
        update_origin: bool,
        from_init: bool = False,
        snap_position: bool = True,
    ) -> None:
        width = max(self._MIN_DIMENSION, float(width))
        height = max(self._MIN_DIMENSION, float(height))
        prev_width = self._box_size.width()
        prev_height = self._box_size.height()
        size_changed = (
            abs(prev_width - width) > 1e-3 or abs(prev_height - height) > 1e-3
        )
        if not from_init:
            self.prepareGeometryChange()
        self._box_size = QtCore.QSizeF(width, height)
        self._update_document_constraints(adjust_layout=size_changed and not from_init)
        if update_origin:
            self._update_transform_origin()
        if not from_init and _should_draw_selection(self):
            self.update_handles()
        if not from_init:
            self.update()
            if snap_position:
                snapped = self._snap_position_value(QtCore.QPointF(self.pos()))
                if isinstance(snapped, QtCore.QPointF) and snapped != self.pos():
                    QtWidgets.QGraphicsTextItem.setPos(self, snapped)

    def _update_document_constraints(self, *, adjust_layout: bool = False) -> None:
        doc = self.document()
        if doc is None:
            return
        # Qt includes both document margins in the supplied width.
        text_width = self._box_size.width()
        self.setTextWidth(text_width)
        doc.setPageSize(QtCore.QSizeF(text_width, -1.0))
        if adjust_layout:
            doc.documentLayout().documentSize()
        self._apply_text_alignment()
        self._update_content_offset()

    def _apply_text_alignment(self) -> None:
        doc = self.document()
        if doc is None:
            return
        option = doc.defaultTextOption()
        option.setWrapMode(
            QtGui.QTextOption.WrapMode.NoWrap
            if self._auto_size
            else QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        alignment = option.alignment()
        alignment &= ~(
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignHCenter
        )
        if self._text_h_align == "right":
            alignment |= QtCore.Qt.AlignmentFlag.AlignRight
        elif self._text_h_align == "center":
            alignment |= QtCore.Qt.AlignmentFlag.AlignHCenter
        else:
            alignment |= QtCore.Qt.AlignmentFlag.AlignLeft
        option.setAlignment(alignment)
        option.setTextDirection(self._VALID_DIRECTIONS[self._text_direction])
        doc.setDefaultTextOption(option)

    def _update_content_offset(self) -> None:
        content_rect = QtWidgets.QGraphicsTextItem.boundingRect(self)
        box = self._box_size

        left = content_rect.left()
        top = content_rect.top()
        right = content_rect.right()
        bottom = content_rect.bottom()

        # Horizontal offset
        if self._text_h_align == "right":
            dx = box.width() - right
        elif self._text_h_align == "center":
            dx = (box.width() - content_rect.width()) * 0.5 - left
        else:
            dx = -left
        min_dx = -left
        max_dx = box.width() - right
        dx = max(min_dx, min(dx, max_dx))

        # Vertical offset
        if self._text_v_align == "bottom":
            dy = box.height() - bottom
        elif self._text_v_align == "middle":
            dy = (box.height() - content_rect.height()) * 0.5 - top
        else:
            dy = -top
        min_dy = -top
        max_dy = box.height() - bottom
        dy = max(min_dy, min(dy, max_dy))

        self._content_offset = QtCore.QPointF(dx, dy)

    def _update_transform_origin(self) -> None:
        self.setTransformOriginPoint(
            self._box_size.width() / 2.0, self._box_size.height() / 2.0
        )


class GroupItem(ResizableItem, QtWidgets.QGraphicsItemGroup):
    """Group of multiple items with shared handles."""

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
        self.setHandlesChildEvents(False)

    def _handle_rect(self) -> QtCore.QRectF:  # type: ignore[override]
        tight = self._contentRect()
        if not tight.isNull():
            return tight
        return QtWidgets.QGraphicsItemGroup.boundingRect(self)

    def _contentRect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF()
        first = True
        children = list(self.childItems())
        while children:
            child = children.pop()
            if isinstance(child, (ResizeHandle, RotationHandle)):
                continue
            if isinstance(child, GroupItem):
                children.extend(child.childItems())
                continue
            # Map content directly into this group: Qt's cached subgroup bounds
            # include helper handles and can retain obsolete child geometry.
            child_rect = child.mapToItem(self, child.boundingRect()).boundingRect()
            rect = child_rect if first else rect.united(child_rect)
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


__all__ = ["GroupItem", "TextItem"]
