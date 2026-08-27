"""Shared Qt painter export path for SVG, PNG, and PDF output.

The renderer deliberately has no dependency on the editor view.  Callers supply
the relevant scene rectangles and any editor-only items which must be hidden
while the scene is painted.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from math import ceil
from pathlib import Path
from xml.etree import ElementTree

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets


class ExportArea(str, Enum):
    """The scene region to render."""

    SELECTION = "selection"
    CURRENT_PAGE = "current_page"
    CANVAS = "canvas"
    ALL_PAGES = "all_pages"


class TextStrategy(str, Enum):
    """How text is represented in portable vector exports."""

    KEEP_TEXT = "keep_text"
    CONVERT_TO_PATHS = "convert_to_paths"


class FontFallbackWarning(UserWarning):
    """Warn that an export uses a substitute font family."""


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
    text_strategy: TextStrategy = TextStrategy.KEEP_TEXT
    font_fallback_reporter: Callable[[str, str], None] | None = None


class ExportRenderer:
    """Render a :class:`QGraphicsScene` through one common painter path."""

    def __init__(self, scene: QtWidgets.QGraphicsScene):
        self._scene = scene

    def export_svg(self, path: str | Path, request: ExportRequest) -> tuple[Path, ...]:
        """Write one SVG per requested scene rectangle."""

        source_rects = self._source_rects(request)
        output_paths = self._output_paths(path, len(source_rects), request.area)
        self._report_font_fallbacks(request)
        with self._temporary_export_state(request.hidden_items):
            for output_path, source_rect in zip(output_paths, source_rects, strict=True):
                if request.text_strategy is TextStrategy.CONVERT_TO_PATHS:
                    output_path.write_bytes(
                        self._svg_with_background(
                            self._scene_svg_with_text_paths(source_rect, request.scale),
                            source_rect,
                            request.background,
                        )
                    )
                    continue
                generator = QtSvg.QSvgGenerator()
                generator.setFileName(str(output_path))
                generator.setSize(self._pixel_size(source_rect, request.scale))
                generator.setViewBox(QtCore.QRectF(0.0, 0.0, source_rect.width(), source_rect.height()))
                painter = QtGui.QPainter(generator)
                if not painter.isActive():
                    raise RuntimeError(f"Could not open SVG output: {output_path}")
                try:
                    self._paint(
                        painter,
                        source_rect,
                        request.background,
                        request.text_strategy,
                    )
                finally:
                    painter.end()
        return output_paths

    def export_png(self, path: str | Path, request: ExportRequest) -> tuple[Path, ...]:
        """Write one PNG per requested scene rectangle."""

        source_rects = self._source_rects(request)
        output_paths = self._output_paths(path, len(source_rects), request.area)
        self._report_font_fallbacks(request)
        with self._temporary_export_state(request.hidden_items):
            for output_path, source_rect in zip(output_paths, source_rects, strict=True):
                image = QtGui.QImage(
                    self._pixel_size(source_rect, request.scale),
                    QtGui.QImage.Format.Format_ARGB32_Premultiplied,
                )
                image.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QtGui.QPainter(image)
                try:
                    self._paint(
                        painter,
                        source_rect,
                        request.background,
                        request.text_strategy,
                        QtCore.QRectF(image.rect()),
                    )
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
        self._report_font_fallbacks(request)
        with self._temporary_export_state(request.hidden_items):
            painter = QtGui.QPainter(writer)
            if not painter.isActive():
                raise RuntimeError(f"Could not open PDF output: {output_path}")
            try:
                for index, source_rect in enumerate(source_rects):
                    if index:
                        writer.setPageSize(self._pdf_page_size(source_rect))
                        writer.newPage()
                    self._paint(
                        painter,
                        source_rect,
                        request.background,
                        request.text_strategy,
                    )
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
        text_strategy: TextStrategy,
        target_rect: QtCore.QRectF | None = None,
    ) -> None:
        if target_rect is None:
            target_rect = QtCore.QRectF(
                0.0, 0.0, source_rect.width(), source_rect.height()
            )
        painter.save()
        try:
            if background is not None:
                painter.fillRect(target_rect, background)
            if text_strategy is TextStrategy.CONVERT_TO_PATHS:
                svg = self._scene_svg_with_text_paths(source_rect)
                renderer = QtSvg.QSvgRenderer(svg)
                if not renderer.isValid():
                    raise RuntimeError("Could not render text-path export")
                renderer.render(painter, target_rect)
            else:
                self._scene.render(
                    painter,
                    target_rect,
                    source_rect,
                    QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                )
        finally:
            painter.restore()

    def _scene_svg_with_text_paths(
        self, source_rect: QtCore.QRectF, scale: float = 1.0
    ) -> QtCore.QByteArray:
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        if not buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Could not create text-path export buffer")

        generator = QtSvg.QSvgGenerator()
        generator.setOutputDevice(buffer)
        generator.setSize(self._pixel_size(source_rect, scale))
        generator.setViewBox(
            QtCore.QRectF(0.0, 0.0, source_rect.width(), source_rect.height())
        )
        painter = QtGui.QPainter(generator)
        if not painter.isActive():
            buffer.close()
            raise RuntimeError("Could not create text-path export")
        try:
            self._scene.render(
                painter,
                QtCore.QRectF(0.0, 0.0, source_rect.width(), source_rect.height()),
                source_rect,
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        finally:
            painter.end()
            buffer.close()
        return QtCore.QByteArray(self._svg_text_to_paths(bytes(data)))

    @staticmethod
    def _svg_with_background(
        svg: QtCore.QByteArray,
        source_rect: QtCore.QRectF,
        background: QtGui.QColor | None,
    ) -> bytes:
        if background is None:
            return bytes(svg)

        root = ElementTree.fromstring(bytes(svg))
        namespace = root.tag.partition("}")[0].removeprefix("{")
        rect_tag = f"{{{namespace}}}rect" if namespace else "rect"
        attributes = {
            "x": "0",
            "y": "0",
            "width": f"{source_rect.width():.6g}",
            "height": f"{source_rect.height():.6g}",
            "fill": background.name(QtGui.QColor.NameFormat.HexRgb),
        }
        if background.alpha() != 255:
            attributes["fill-opacity"] = f"{background.alphaF():.6g}"
        root.insert(0, ElementTree.Element(rect_tag, attributes))
        return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

    @classmethod
    def _svg_text_to_paths(cls, svg: bytes) -> bytes:
        root = ElementTree.fromstring(svg)
        namespace = root.tag.partition("}")[0].removeprefix("{")
        if namespace:
            ElementTree.register_namespace("", namespace)
        text_tag = f"{{{namespace}}}text" if namespace else "text"
        path_tag = f"{{{namespace}}}path" if namespace else "path"

        for parent in root.iter():
            for index, element in list(enumerate(parent)):
                if element.tag != text_tag:
                    continue
                value = "".join(element.itertext())
                path = QtGui.QPainterPath()
                font = cls._font_from_svg(element)
                x = float(element.attrib.get("x", "0"))
                y = float(element.attrib.get("y", "0"))
                path.addText(QtCore.QPointF(x, y), font, value)
                attributes = {
                    key: attr_value
                    for key, attr_value in element.attrib.items()
                    if key
                    not in {
                        "x",
                        "y",
                        "font-family",
                        "font-size",
                        "font-weight",
                        "font-style",
                        "xml:space",
                    }
                }
                attributes["d"] = cls._painter_path_data(path)
                replacement = ElementTree.Element(path_tag, attributes)
                replacement.tail = element.tail
                parent.remove(element)
                parent.insert(index, replacement)
        return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _font_from_svg(element: ElementTree.Element) -> QtGui.QFont:
        family = element.attrib.get("font-family", QtGui.QFont().family())
        font = QtGui.QFont(family)
        font.setPixelSize(max(1, round(float(element.attrib.get("font-size", "9")))))
        weight = int(float(element.attrib.get("font-weight", "400")))
        font.setWeight(QtGui.QFont.Weight(max(100, min(900, weight))))
        font.setItalic(element.attrib.get("font-style") == "italic")
        return font

    @staticmethod
    def _painter_path_data(path: QtGui.QPainterPath) -> str:
        commands: list[str] = []
        index = 0
        while index < path.elementCount():
            element = path.elementAt(index)
            if element.isMoveTo():
                commands.append(f"M{element.x:.6g},{element.y:.6g}")
            elif element.isLineTo():
                commands.append(f"L{element.x:.6g},{element.y:.6g}")
            elif element.isCurveTo() and index + 2 < path.elementCount():
                control = path.elementAt(index + 1)
                end = path.elementAt(index + 2)
                commands.append(
                    f"C{element.x:.6g},{element.y:.6g} "
                    f"{control.x:.6g},{control.y:.6g} "
                    f"{end.x:.6g},{end.y:.6g}"
                )
                index += 2
            index += 1
        return " ".join(commands)

    def _report_font_fallbacks(self, request: ExportRequest) -> None:
        substitutions: set[tuple[str, str]] = set()
        for item in self._scene.items():
            font_getter = getattr(item, "font", None)
            font = font_getter() if callable(font_getter) else getattr(item, "_font", None)
            if not isinstance(font, QtGui.QFont):
                continue
            requested = font.family()
            resolved = self._resolved_font_family(font)
            if requested and resolved and requested.casefold() != resolved.casefold():
                substitutions.add((requested, resolved))

        for requested, resolved in sorted(substitutions):
            if request.font_fallback_reporter is not None:
                request.font_fallback_reporter(requested, resolved)
            else:
                warnings.warn(
                    f"Font '{requested}' is unavailable; export uses '{resolved}'.",
                    FontFallbackWarning,
                    stacklevel=3,
                )

    @staticmethod
    def _resolved_font_family(font: QtGui.QFont) -> str:
        return QtGui.QFontInfo(font).family()

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
