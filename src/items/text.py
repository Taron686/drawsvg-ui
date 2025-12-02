"""Text and grouping items."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .base import ResizableItem, ResizeHandle, RotationHandle, _should_draw_selection
from constants import PEN_SELECTED, DEFAULT_TEXT_COLOR, DEFAULT_FONT_FAMILY


class TextItem(ResizableItem, QtWidgets.QGraphicsTextItem):
    """Editable text item whose bounding box stays user-controlled."""

    _MIN_DIMENSION = 10.0
    _VALID_H_ALIGN = ("left", "center", "right")
    _VALID_V_ALIGN = ("top", "middle", "bottom")
    _VALID_DIRECTIONS = {
        "ltr": QtCore.Qt.LayoutDirection.LeftToRight,
        "rtl": QtCore.Qt.LayoutDirection.RightToLeft,
    }

    def __init__(self, x, y, w, h):
        QtWidgets.QGraphicsTextItem.__init__(self, "Text")
        self._box_size = QtCore.QSizeF(1.0, 1.0)
        self._auto_size = False
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
        self._auto_size = not (w and w > 0.0 and h and h > 0.0)
        self._set_box_size(width, height, update_origin=True, from_init=True)
        self.setPos(x, y)

    def setPlainText(self, text: str) -> None:  # type: ignore[override]
        super().setPlainText(text)
        if self._auto_size:
            content_rect = QtWidgets.QGraphicsTextItem.boundingRect(self)
            self._set_box_size(
                content_rect.width(), content_rect.height(), update_origin=True
            )
            self._auto_size = False
        else:
            self._update_document_constraints()
            self._update_transform_origin()
            if _should_draw_selection(self):
                self.update_handles()
        self.update()

    def setFont(self, font: QtGui.QFont) -> None:  # type: ignore[override]
        super().setFont(font)
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
        self._update_document_constraints()
        self._update_transform_origin()
        if _should_draw_selection(self):
            self.update_handles()
        self.update()

    def set_size(self, width: float, height: float, adjust_origin: bool = True) -> None:
        """Resize the bounding box without scaling the text."""

        self._auto_size = False
        self._set_box_size(width, height, update_origin=adjust_origin)

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
            snapped = self._snap_position_value(QtCore.QPointF(self.pos()))
            if isinstance(snapped, QtCore.QPointF) and snapped != self.pos():
                QtWidgets.QGraphicsTextItem.setPos(self, snapped)

    def _update_document_constraints(self, *, adjust_layout: bool = False) -> None:
        doc = self.document()
        if doc is None:
            return
        margin = doc.documentMargin()
        available_width = self._box_size.width() - 2.0 * margin
        text_width = available_width if available_width > 0.0 else -1.0
        page_width = (
            available_width if available_width > 0.0 else self._box_size.width()
        )
        doc_height = max(self._MIN_DIMENSION, self._box_size.height())
        self.setTextWidth(text_width)
        doc.setPageSize(QtCore.QSizeF(max(0.0, page_width), doc_height))
        if adjust_layout:
            doc.adjustSize()
            self.setTextWidth(text_width)
            doc.setPageSize(QtCore.QSizeF(max(0.0, page_width), doc_height))
        self._apply_text_alignment()
        self._update_content_offset()

    def _apply_text_alignment(self) -> None:
        doc = self.document()
        if doc is None:
            return
        option = doc.defaultTextOption()
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
        for child in self.childItems():
            if isinstance(child, (ResizeHandle, RotationHandle)):
                continue
            child_rect = child.mapToParent(child.boundingRect()).boundingRect()
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
