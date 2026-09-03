"""Shared Qt painter export path for SVG, PNG, and PDF output.

The renderer deliberately has no dependency on the editor view.  Callers supply
the relevant scene rectangles and any editor-only items which must be hidden
while the scene is painted.
"""

from __future__ import annotations

import base64
import warnings
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
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


class ShadowStyle(str, Enum):
    """The portable representation selected for an export shadow."""

    SOFT_RASTER = "soft_raster"
    HARD_VECTOR = "hard_vector"


class FontFallbackWarning(UserWarning):
    """Warn that an export uses a substitute font family."""


@dataclass(frozen=True)
class ExportShadow:
    """A portable drop shadow applied to the rendered scene."""

    offset_x: float = 3.0
    offset_y: float = 3.0
    blur_radius: float = 4.0
    style: ShadowStyle = ShadowStyle.SOFT_RASTER
    color: QtGui.QColor = field(
        default_factory=lambda: QtGui.QColor(0, 0, 0, 96)
    )

    def __post_init__(self) -> None:
        if self.blur_radius < 0.0:
            raise ValueError("Shadow blur radius must not be negative")


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
    shadow: ExportShadow | None = None


@dataclass(frozen=True)
class _ShadowRaster:
    """A tightly cropped shadow image and its page-pixel destination."""

    image: QtGui.QImage
    target_rect: QtCore.QRectF


class ExportRenderer:
    """Render a :class:`QGraphicsScene` through one common painter path."""

    _MAX_SHADOW_PIXELS = 16_000_000
    _MAX_PAGE_PIXELS = 64_000_000

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
                    svg = self._svg_with_background(
                        self._scene_svg_with_text_paths(source_rect, request.scale),
                        source_rect,
                        request.background,
                    )
                else:
                    generator = QtSvg.QSvgGenerator()
                    generator.setFileName(str(output_path))
                    generator.setSize(self._pixel_size(source_rect, request.scale))
                    generator.setViewBox(
                        QtCore.QRectF(0.0, 0.0, source_rect.width(), source_rect.height())
                    )
                    painter = QtGui.QPainter(generator)
                    if not painter.isActive():
                        raise RuntimeError(f"Could not open SVG output: {output_path}")
                    try:
                        self._paint(
                            painter,
                            source_rect,
                            None,
                            request.text_strategy,
                        )
                    finally:
                        painter.end()
                    svg = self._svg_with_background(
                        output_path.read_bytes(), source_rect, request.background
                    )
                if request.shadow is not None:
                    if request.shadow.style is ShadowStyle.HARD_VECTOR:
                        svg = self._svg_with_hard_shadow(svg, request.shadow)
                    else:
                        svg = self._svg_with_raster_shadow(
                            svg,
                            source_rect,
                            request.background,
                            request.text_strategy,
                            request.shadow,
                            request.scale,
                        )
                output_path.write_bytes(svg)
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
                        request.shadow,
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
                        shadow=request.shadow,
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

        with self._temporary_export_state(request.hidden_items):
            rect = QtCore.QRectF()
            for item in self._scene.items():
                if item.isVisible():
                    rect = rect.united(item.sceneBoundingRect())
        return (self._valid_rect(rect),)

    @staticmethod
    def _valid_rect(rect: QtCore.QRectF) -> QtCore.QRectF:
        normalized = rect.normalized()
        if normalized.isEmpty():
            raise ValueError("Cannot export an empty scene rectangle")
        return normalized

    @staticmethod
    def _pixel_size(rect: QtCore.QRectF, scale: float) -> QtCore.QSize:
        size = QtCore.QSize(
            max(1, ceil(rect.width() * scale)),
            max(1, ceil(rect.height() * scale)),
        )
        if size.width() * size.height() > ExportRenderer._MAX_PAGE_PIXELS:
            raise ValueError("Export page exceeds the 64 megapixel pixel budget")
        return size

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
        shadow: ExportShadow | None = None,
    ) -> None:
        if target_rect is None:
            target_rect = QtCore.QRectF(
                0.0, 0.0, source_rect.width(), source_rect.height()
            )
        painter.save()
        try:
            if background is not None:
                painter.fillRect(target_rect, background)
            if shadow is not None and shadow.style is ShadowStyle.HARD_VECTOR:
                self._paint_hard_shadow(painter, source_rect, target_rect, text_strategy, shadow)
                return
            if shadow is not None:
                shadow_raster = self._shadow_raster(
                    source_rect, target_rect, text_strategy, shadow
                )
                painter.drawImage(shadow_raster.target_rect, shadow_raster.image)
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

    def _shadow_raster(
        self,
        source_rect: QtCore.QRectF,
        target_rect: QtCore.QRectF,
        text_strategy: TextStrategy,
        shadow: ExportShadow,
    ) -> _ShadowRaster:
        """Rasterize and crop only the soft-shadow layer."""

        shadow_target_rect = self._shadow_target_rect(source_rect, target_rect, shadow)
        size = shadow_target_rect.size()
        if size.width() * size.height() > self._MAX_SHADOW_PIXELS:
            raise ValueError(
                "Soft shadow exceeds the 16 megapixel pixel budget; "
                "use a lower scale or ShadowStyle.HARD_VECTOR"
            )
        content = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        content.fill(QtCore.Qt.GlobalColor.transparent)
        content_painter = QtGui.QPainter(content)
        try:
            self._paint_scene(
                content_painter,
                self._target_to_source_rect(source_rect, target_rect, shadow_target_rect),
                QtCore.QRectF(content.rect()),
                text_strategy,
            )
        finally:
            content_painter.end()

        shadow_scene = QtWidgets.QGraphicsScene()
        pixmap_item = shadow_scene.addPixmap(QtGui.QPixmap.fromImage(content))
        scale = target_rect.width() / source_rect.width()
        pixmap_item.setGraphicsEffect(
            QtWidgets.QGraphicsDropShadowEffect(
                blurRadius=shadow.blur_radius * scale,
                offset=QtCore.QPointF(shadow.offset_x * scale, shadow.offset_y * scale),
                color=shadow.color,
            )
        )
        result = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(QtCore.Qt.GlobalColor.transparent)
        result_painter = QtGui.QPainter(result)
        try:
            shadow_scene.render(
                result_painter,
                QtCore.QRectF(result.rect()),
                QtCore.QRectF(result.rect()),
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        finally:
            result_painter.end()
        erase_painter = QtGui.QPainter(result)
        try:
            erase_painter.setCompositionMode(
                QtGui.QPainter.CompositionMode.CompositionMode_DestinationOut
            )
            erase_painter.drawImage(0, 0, content)
        finally:
            erase_painter.end()
        bounds = self._alpha_bounds(result)
        if bounds.isEmpty():
            return _ShadowRaster(
                QtGui.QImage(1, 1, QtGui.QImage.Format.Format_ARGB32_Premultiplied),
                QtCore.QRectF(shadow_target_rect.topLeft(), QtCore.QSizeF(1.0, 1.0)),
            )
        return _ShadowRaster(
            result.copy(bounds),
            QtCore.QRectF(
                shadow_target_rect.x() + bounds.x(),
                shadow_target_rect.y() + bounds.y(),
                bounds.width(),
                bounds.height(),
            ),
        )

    def _shadow_target_rect(
        self,
        source_rect: QtCore.QRectF,
        target_rect: QtCore.QRectF,
        shadow: ExportShadow,
    ) -> QtCore.QRectF:
        content_rect = QtCore.QRectF()
        for item in self._scene.items(source_rect):
            if item.isVisible():
                content_rect = content_rect.united(item.sceneBoundingRect())
        content_rect = content_rect.intersected(source_rect)
        if content_rect.isEmpty():
            return QtCore.QRectF(0.0, 0.0, 1.0, 1.0)
        margin = abs(shadow.blur_radius) * 2.0
        content_rect.adjust(
            min(0.0, shadow.offset_x) - margin,
            min(0.0, shadow.offset_y) - margin,
            max(0.0, shadow.offset_x) + margin,
            max(0.0, shadow.offset_y) + margin,
        )
        content_rect = content_rect.intersected(source_rect)
        scale_x = target_rect.width() / source_rect.width()
        scale_y = target_rect.height() / source_rect.height()
        left = max(target_rect.left(), (content_rect.left() - source_rect.left()) * scale_x)
        top = max(target_rect.top(), (content_rect.top() - source_rect.top()) * scale_y)
        right = min(target_rect.right(), (content_rect.right() - source_rect.left()) * scale_x)
        bottom = min(target_rect.bottom(), (content_rect.bottom() - source_rect.top()) * scale_y)
        return QtCore.QRectF(left, top, right - left, bottom - top).toAlignedRect()

    @staticmethod
    def _target_to_source_rect(
        source_rect: QtCore.QRectF,
        target_rect: QtCore.QRectF,
        crop_target_rect: QtCore.QRectF,
    ) -> QtCore.QRectF:
        return QtCore.QRectF(
            source_rect.left()
            + (crop_target_rect.left() - target_rect.left())
            * source_rect.width()
            / target_rect.width(),
            source_rect.top()
            + (crop_target_rect.top() - target_rect.top())
            * source_rect.height()
            / target_rect.height(),
            crop_target_rect.width() * source_rect.width() / target_rect.width(),
            crop_target_rect.height() * source_rect.height() / target_rect.height(),
        )

    @staticmethod
    def _alpha_bounds(image: QtGui.QImage) -> QtCore.QRect:
        alpha = image.convertToFormat(QtGui.QImage.Format.Format_Alpha8)
        data = bytes(alpha.bits()[: alpha.sizeInBytes()])
        left, top = alpha.width(), alpha.height()
        right = bottom = -1
        for y in range(alpha.height()):
            row = data[y * alpha.bytesPerLine() : y * alpha.bytesPerLine() + alpha.width()]
            non_empty = [x for x, value in enumerate(row) if value]
            if non_empty:
                left = min(left, non_empty[0])
                right = max(right, non_empty[-1])
                top = min(top, y)
                bottom = y
        if right < left:
            return QtCore.QRect()
        return QtCore.QRect(left, top, right - left + 1, bottom - top + 1)

    def _paint_hard_shadow(
        self,
        painter: QtGui.QPainter,
        source_rect: QtCore.QRectF,
        target_rect: QtCore.QRectF,
        text_strategy: TextStrategy,
        shadow: ExportShadow,
    ) -> None:
        """Paint a vector duplicate; PDF keeps this path free of image objects."""

        svg = self._scene_svg(source_rect)
        if text_strategy is TextStrategy.CONVERT_TO_PATHS:
            svg = QtCore.QByteArray(self._svg_text_to_paths(bytes(svg)))
        renderer = QtSvg.QSvgRenderer(self._svg_with_hard_shadow(bytes(svg), shadow))
        if not renderer.isValid():
            raise RuntimeError("Could not render hard-shadow export")
        renderer.render(painter, target_rect)

    def _paint_scene(
        self,
        painter: QtGui.QPainter,
        source_rect: QtCore.QRectF,
        target_rect: QtCore.QRectF,
        text_strategy: TextStrategy,
    ) -> None:
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

    def _scene_svg_with_text_paths(
        self, source_rect: QtCore.QRectF, scale: float = 1.0
    ) -> QtCore.QByteArray:
        return QtCore.QByteArray(
            self._svg_text_to_paths(bytes(self._scene_svg(source_rect, scale)))
        )

    def _scene_svg(
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
        return data

    @staticmethod
    def _svg_with_background(
        svg: QtCore.QByteArray,
        source_rect: QtCore.QRectF,
        background: QtGui.QColor | None,
    ) -> bytes:
        root = ElementTree.fromstring(bytes(svg))
        namespace = root.tag.partition("}")[0].removeprefix("{")
        rect_tag = f"{{{namespace}}}rect" if namespace else "rect"
        if background is not None:
            attributes = {
                "id": "export-background",
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

    def _svg_with_raster_shadow(
        self,
        svg: bytes,
        source_rect: QtCore.QRectF,
        background: QtGui.QColor | None,
        text_strategy: TextStrategy,
        shadow: ExportShadow,
        scale: float,
    ) -> bytes:
        size = self._pixel_size(source_rect, scale)
        target_rect = QtCore.QRectF(0.0, 0.0, size.width(), size.height())
        shadow_raster = self._shadow_raster(
            source_rect, target_rect, text_strategy, shadow
        )
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        if not buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Could not create shadow raster buffer")
        try:
            if not shadow_raster.image.save(buffer, "PNG"):
                raise RuntimeError("Could not encode shadow raster")
        finally:
            buffer.close()

        root = ElementTree.fromstring(svg)
        namespace = root.tag.partition("}")[0].removeprefix("{")
        tag = lambda name: f"{{{namespace}}}{name}" if namespace else name
        image_element = ElementTree.Element(
            tag("image"),
            {
                "x": f"{shadow_raster.target_rect.x() / scale:.6g}",
                "y": f"{shadow_raster.target_rect.y() / scale:.6g}",
                "width": f"{shadow_raster.target_rect.width() / scale:.6g}",
                "height": f"{shadow_raster.target_rect.height() / scale:.6g}",
                "preserveAspectRatio": "none",
                "href": "data:image/png;base64,"
                + base64.b64encode(bytes(data)).decode("ascii"),
            },
        )
        root.insert(1 if background is not None else 0, image_element)
        return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _svg_with_hard_shadow(svg: bytes, shadow: ExportShadow) -> bytes:
        """Add a fully vector, unblurred silhouette behind SVG content."""

        root = ElementTree.fromstring(svg)
        namespace = root.tag.partition("}")[0].removeprefix("{")
        tag = lambda name: f"{{{namespace}}}{name}" if namespace else name
        protected: set[ElementTree.Element] = set()
        for child in list(root):
            if child.tag.endswith("defs") or child.attrib.get("id") == "export-background":
                protected.add(child)
        content = [child for child in list(root) if child not in protected]
        for child in content:
            root.remove(child)
        shadow_group = ElementTree.Element(
            tag("g"),
            {"transform": f"translate({shadow.offset_x:.6g} {shadow.offset_y:.6g})"},
        )
        shadow_group.extend(deepcopy(content))
        color = shadow.color.name(QtGui.QColor.NameFormat.HexRgb)
        for element in shadow_group.iter():
            if "fill" in element.attrib and element.attrib["fill"] != "none":
                element.set("fill", color)
                element.set("fill-opacity", f"{shadow.color.alphaF():.6g}")
            if "stroke" in element.attrib and element.attrib["stroke"] != "none":
                element.set("stroke", color)
                element.set("stroke-opacity", f"{shadow.color.alphaF():.6g}")
        root.append(shadow_group)
        root.extend(content)
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
