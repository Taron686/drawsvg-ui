"""Shared Qt painter export path for SVG, PNG, and PDF output.

The renderer deliberately has no dependency on the editor view.  Callers supply
the relevant scene rectangles and any editor-only items which must be hidden
while the scene is painted.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from math import ceil
from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets


class ExportArea(str, Enum):
    """The scene region to render."""

    SELECTION = "selection"
    CURRENT_PAGE = "current_page"
    CANVAS = "canvas"
    ALL_PAGES = "all_pages"


@dataclass(frozen=True)
class ExportRequest:
    """Format-independent settings for an export operation.

    ``current_page`` and ``pages`` are scene-space rectangles.  This keeps the
    export core independent from the editor's page implementation.
    """

    area: ExportArea = ExportArea.CANVAS
    current_page: QtCore.QRectF | None = None
    pages: Sequence[QtCore.QRectF] = field(default_factory=tuple)
    hidden_items: Sequence[QtWidgets.QGraphicsItem] = field(default_factory=tuple)
    background: QtGui.QColor | None = field(
        default_factory=lambda: QtGui.QColor(QtCore.Qt.GlobalColor.white)
    )
    scale: float = 1.0


class ExportRenderer:
    """Render a :class:`QGraphicsScene` through one common painter path."""

    def __init__(self, scene: QtWidgets.QGraphicsScene):
        self._scene = scene

    def export_svg(self, path: str | Path, request: ExportRequest) -> tuple[Path, ...]:
        """Write one SVG per requested scene rectangle."""

        source_rects = self._source_rects(request)
        output_paths = self._output_paths(path, len(source_rects), request.area)
        with self._temporary_export_state(request.hidden_items):
            for output_path, source_rect in zip(output_paths, source_rects, strict=True):
                generator = QtSvg.QSvgGenerator()
                generator.setFileName(str(output_path))
                generator.setSize(self._pixel_size(source_rect, request.scale))
                generator.setViewBox(QtCore.QRectF(0.0, 0.0, source_rect.width(), source_rect.height()))
                painter = QtGui.QPainter(generator)
                if not painter.isActive():
                    raise RuntimeError(f"Could not open SVG output: {output_path}")
                try:
                    self._paint(painter, source_rect, request.background)
                finally:
                    painter.end()
        return output_paths

    def export_png(self, path: str | Path, request: ExportRequest) -> tuple[Path, ...]:
        """Write one PNG per requested scene rectangle."""

        source_rects = self._source_rects(request)
        output_paths = self._output_paths(path, len(source_rects), request.area)
        with self._temporary_export_state(request.hidden_items):
            for output_path, source_rect in zip(output_paths, source_rects, strict=True):
                image = QtGui.QImage(
                    self._pixel_size(source_rect, request.scale),
                    QtGui.QImage.Format.Format_ARGB32_Premultiplied,
                )
                image.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QtGui.QPainter(image)
                try:
                    self._paint(painter, source_rect, request.background)
                finally:
                    painter.end()
                if not image.save(str(output_path), "PNG"):
                    raise RuntimeError(f"Could not write PNG output: {output_path}")
        return output_paths

    def export_pdf(self, path: str | Path, request: ExportRequest) -> Path:
        """Write every requested rectangle as one page of a PDF file."""

        source_rects = self._source_rects(request)
        output_path = Path(path)
        writer = QtGui.QPdfWriter(str(output_path))
        writer.setResolution(72)
        writer.setPageSize(self._pdf_page_size(source_rects[0]))
        with self._temporary_export_state(request.hidden_items):
            painter = QtGui.QPainter(writer)
            if not painter.isActive():
                raise RuntimeError(f"Could not open PDF output: {output_path}")
            try:
                for index, source_rect in enumerate(source_rects):
                    if index:
                        writer.setPageSize(self._pdf_page_size(source_rect))
                        writer.newPage()
                    self._paint(painter, source_rect, request.background)
            finally:
                painter.end()
        return output_path

    def _source_rects(self, request: ExportRequest) -> tuple[QtCore.QRectF, ...]:
        if request.scale <= 0.0:
            raise ValueError("Export scale must be greater than zero")

        if request.area is ExportArea.SELECTION:
            selected = self._scene.selectedItems()
            if not selected:
                raise ValueError("Cannot export an empty selection")
            rect = QtCore.QRectF()
            for item in selected:
                rect = rect.united(item.sceneBoundingRect())
            return (self._valid_rect(rect),)

        if request.area is ExportArea.CURRENT_PAGE:
            if request.current_page is None:
                raise ValueError("Current-page export requires current_page")
            return (self._valid_rect(request.current_page),)

        if request.area is ExportArea.ALL_PAGES:
            if not request.pages:
                raise ValueError("All-pages export requires at least one page rectangle")
            return tuple(self._valid_rect(rect) for rect in request.pages)

        return (self._valid_rect(self._scene.itemsBoundingRect()),)

    @staticmethod
    def _valid_rect(rect: QtCore.QRectF) -> QtCore.QRectF:
        normalized = rect.normalized()
        if normalized.isEmpty():
            raise ValueError("Cannot export an empty scene rectangle")
        return normalized

    @staticmethod
    def _pixel_size(rect: QtCore.QRectF, scale: float) -> QtCore.QSize:
        return QtCore.QSize(
            max(1, ceil(rect.width() * scale)),
            max(1, ceil(rect.height() * scale)),
        )

    @staticmethod
    def _pdf_page_size(rect: QtCore.QRectF) -> QtGui.QPageSize:
        return QtGui.QPageSize(
            QtCore.QSizeF(rect.width(), rect.height()), QtGui.QPageSize.Unit.Point
        )

    @staticmethod
    def _output_paths(
        path: str | Path, count: int, area: ExportArea
    ) -> tuple[Path, ...]:
        output = Path(path)
        if area is not ExportArea.ALL_PAGES:
            return (output,)
        return tuple(
            output.with_name(f"{output.stem}_p{index:03d}{output.suffix}")
            for index in range(1, count + 1)
        )

    def _paint(
        self,
        painter: QtGui.QPainter,
        source_rect: QtCore.QRectF,
        background: QtGui.QColor | None,
    ) -> None:
        target_rect = QtCore.QRectF(0.0, 0.0, source_rect.width(), source_rect.height())
        painter.save()
        try:
            if background is not None:
                painter.fillRect(target_rect, background)
            self._scene.render(
                painter,
                target_rect,
                source_rect,
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        finally:
            painter.restore()

    @contextmanager
    def _temporary_export_state(
        self, hidden_items: Sequence[QtWidgets.QGraphicsItem]
    ) -> Iterator[None]:
        """Suppress editor-only visuals while restoring scene state exactly."""

        selected_items = tuple(self._scene.selectedItems())
        visibility = tuple((item, item.isVisible()) for item in hidden_items)
        blocker = QtCore.QSignalBlocker(self._scene)
        try:
            for item in selected_items:
                item.setSelected(False)
            for item, _was_visible in visibility:
                item.setVisible(False)
            yield
        finally:
            for item, was_visible in visibility:
                item.setVisible(was_visible)
            for item in tuple(self._scene.selectedItems()):
                item.setSelected(False)
            for item in selected_items:
                if item.scene() is self._scene:
                    item.setSelected(True)
            del blocker
