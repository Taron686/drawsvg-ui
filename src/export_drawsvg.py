# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

import json
import html

import math

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from constants import DEFAULT_FONT_FAMILY
from export_margins import ExportMargins, expand_export_rect
from export_drawsvg_styles import (
    STYLE_PRELUDE,
    finish_styled_item as _finish_styled_item,
    brush_attributes,
    format_drawsvg_attributes,
    item_style_attributes,
    pen_attributes,
    split_style_attribute,
)

from items import (
    BlockArrowItem,
    CurvyBracketItem,
    DiamondItem,
    DiagramItem,
    FolderTreeItem,
    LineItem,
    RectItem,
    ShapeLabelMixin,
    SplitRoundedRectItem,
    TextItem,
)
from shape_registry import SHAPE_REGISTRY
from items.shapes.paths import FreePathItem
from export_drawsvg_assets import (
    ASSET_ITEM_TYPES,
    export_asset_item,
    export_item_bounds,
    export_item_is_visible,
    scene_item_parents,
)


def _format_item_attributes(
    item: QtWidgets.QGraphicsItem,
    *,
    include_fill: bool = True,
    extra_attrs: Iterable[str] | None = None,
) -> str:
    """Return a drawsvg-compatible attribute string for ``item``.

    Parameters

    ----------

    item:

        The graphics item whose pen/brush information should be exported.

    include_fill:

        Whether fill information should be included (set to ``False`` for

        stroke-only shapes).

    extra_attrs:

        Optional iterable of additional attributes that should be appended to

        the generated string (e.g., rounded corner radii).

    """

    attrs: list[str] = []
    if include_fill:
        brush_getter = getattr(item, "brush", None)
        attrs.extend(
            brush_attributes(brush_getter(), item)
            if callable(brush_getter)
            else ["fill='none'"]
        )
    pen_getter = getattr(item, "pen", None)
    if callable(pen_getter):
        attrs.extend(pen_attributes(pen_getter(), item))
    attrs.extend(item_style_attributes(item))
    if extra_attrs:
        attrs.extend(extra_attrs)
    # Adapter-specific attributes override defaults (e.g. rounded brackets).
    return format_drawsvg_attributes(attrs)


def _item_transform_suffix(item: QtWidgets.QGraphicsItem) -> str:
    """Return the item's complete scene transform as a drawsvg argument."""

    transform = item.sceneTransform()

    matrix = (
        f"matrix({transform.m11():.6f} {transform.m12():.6f} "
        f"{transform.m21():.6f} {transform.m22():.6f} "
        f"{transform.m31():.6f} {transform.m32():.6f})"
    )

    return f", transform='{matrix}'"


def _scene_transform_components(
    item: QtWidgets.QGraphicsItem,
) -> tuple[QtCore.QPointF, float, float]:
    """Return top-level position, rotation and uniform scale for an item."""

    transform = item.sceneTransform()

    scale = math.hypot(transform.m11(), transform.m12())

    rotation = math.degrees(math.atan2(transform.m12(), transform.m11()))

    origin = item.transformOriginPoint()

    mapped_origin = transform.map(origin)

    position = mapped_origin - origin

    return position, rotation, scale


def _visual_text_lines(item: QtWidgets.QGraphicsTextItem) -> list[str]:
    """Return the lines produced by Qt's text layout, including soft wraps."""

    document = item.document()

    if document is None:
        return item.toPlainText().splitlines() or [""]

    document.documentLayout()

    visual_lines: list[str] = []

    block = document.begin()

    while block.isValid():
        block_text = block.text()

        layout = block.layout()

        if layout is None or layout.lineCount() == 0:
            visual_lines.append(block_text)

        else:
            for index in range(layout.lineCount()):
                line = layout.lineAt(index)

                start = line.textStart()

                visual_lines.append(
                    _qt_text_slice(block_text, start, line.textLength())
                )

        block = block.next()

    return visual_lines or [""]


def _qt_text_slice(text: str, start: int, length: int) -> str:
    """Qt layout offsets count UTF-16 units, whereas Python counts code points."""
    return text.encode("utf-16-le")[start * 2 : (start + length) * 2].decode(
        "utf-16-le"
    )


def _xml_attribute_literal(value: str) -> str:
    """Quote a Python literal that drawsvg can write verbatim into XML."""
    escaped = html.escape(value, quote=True)
    # XML normalizes literal whitespace in attributes; references preserve it.
    escaped = (
        escaped.replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")
    )
    return repr(escaped)


def _font_pixel_size(font: QtGui.QFont) -> float:
    if font.pixelSize() > 0:
        return float(font.pixelSize())
    screen = QtGui.QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen else 96.0
    if font.pointSizeF() > 0:
        return font.pointSizeF() * dpi / 72.0
    return QtGui.QFontMetricsF(font).height()


def _text_font_attributes(font: QtGui.QFont) -> list[str]:
    return [
        f"font_family={_xml_attribute_literal(font.family())}",
        f"font_weight={'bold' if font.bold() else 'normal'!r}",
        f"font_style={'italic' if font.italic() else 'normal'!r}",
        f"text_decoration={'underline' if font.underline() else 'none'!r}",
        "data_xml_escaped='true'",
    ]


def _append_positioned_text_lines(
    lines: list[str],
    var_name: str,
    item: QtWidgets.QGraphicsTextItem,
) -> None:
    """Bake Qt visual lines and baselines into portable SVG tspans."""
    document = item.document()
    document.documentLayout().documentSize()
    offset = getattr(item, "_content_offset", QtCore.QPointF())
    lines.append(f"    {var_name}.escaped_text = ''")
    lines.append(f"    {var_name}.children.clear()")
    block = document.begin()
    while block.isValid():
        layout = block.layout()
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            text = _qt_text_slice(block.text(), line.textStart(), line.textLength())
            rect = line.naturalTextRect().translated(layout.position() + offset)
            rtl = (
                layout.textOption().textDirection()
                == QtCore.Qt.LayoutDirection.RightToLeft
            )
            x = rect.right() if rtl else rect.left()
            y = layout.position().y() + line.y() + line.ascent() + offset.y()
            lines.append(
                f"    {var_name}.append_line({text!r}, x={x:.4f}, y={y:.4f}, "
                f"direction={'rtl' if rtl else 'ltr'!r}, text_anchor='start')"
            )
        block = block.next()


def _export_shape_label(
    item: ShapeLabelMixin,
    lines: list[str],
    *,
    shape_id: str | None,
    var_name: str = "shape_label",
    label_kind: str | None = None,
    parents: Mapping[QtWidgets.QGraphicsItem, QtWidgets.QGraphicsItem],
) -> None:
    if not shape_id:
        return
    if not getattr(item, "has_label", lambda: False)():
        return
    text_value = getattr(item, "label_text", lambda: "")()
    if not text_value:
        return
    label_item = getattr(item, "label_item", lambda: None)()
    if label_item is None or not export_item_is_visible(label_item, parents):
        return
    raw_lines = _visual_text_lines(label_item)
    if not raw_lines:
        raw_lines = [text_value]
    font = label_item.font()
    fm = QtGui.QFontMetricsF(font)
    pixel_size = size = _font_pixel_size(font)
    line_px = fm.lineSpacing()
    line_ratio = line_px / size if size > 0.0 else 1.0
    br = label_item.boundingRect()
    text_left = br.left()
    text_top = br.top()
    h_align, v_align = getattr(item, "label_alignment", lambda: ("center", "middle"))()
    anchor_map = {"left": "start", "center": "middle", "right": "end"}
    text_anchor = anchor_map.get(h_align, "middle")
    baseline_offset = 0.0
    doc = label_item.document()
    if doc is not None:
        block = doc.begin()
        if block.isValid():
            layout = block.layout()
            if layout is not None and layout.lineCount() > 0:
                first_line = layout.lineAt(0)
                baseline_offset = (
                    layout.position().y() + first_line.y() + first_line.ascent()
                )
    anchor_x = (
        text_left
        if h_align == "left"
        else (
            text_left + br.width()
            if h_align == "right"
            else text_left + br.width() / 2.0
        )
    )
    first_baseline_y = text_top + baseline_offset
    color = label_item.defaultTextColor()
    attrs = [
        f"fill='{color.name()}'",
        f"opacity={label_item.effectiveOpacity():.6f}",
        *_text_font_attributes(font),
        f"text_anchor='{text_anchor}'",
        "dominant_baseline='alphabetic'",
        f"line_height={line_ratio:.6f}",
        "xml__space='preserve'",
        "data_shape_label='true'",
        f"data_label_id='{shape_id}'",
        f"data_label_h='{h_align}'",
        f"data_label_v='{v_align}'",
        f"data_font_px={pixel_size:.4f}",
        f"data_raw_label={_xml_attribute_literal(text_value)}",
    ]
    if item.label_has_custom_color():
        attrs.append("data_label_color_override='true'")
    if label_kind:
        attrs.append(f"data_label_kind='{label_kind}'")
    if label_kind == "rect":
        attrs.append("data_rect_label='true'")
    if color.alphaF() < 1.0:
        attrs.append(f"fill_opacity={color.alphaF():.2f}")
    attr_str = format_drawsvg_attributes(attrs)
    transform_suffix = _item_transform_suffix(label_item)
    json_lines = [line if line else "\u00a0" for line in raw_lines]
    if len(json_lines) == 1:
        text_literal = json.dumps(json_lines[0], ensure_ascii=False)
    else:
        text_literal = json.dumps(json_lines, ensure_ascii=False)
    lines.append(f"    # Multiline label for {shape_id}")
    lines.append(
        f"    _{var_name} = draw.Text({text_literal}, {size:.2f}, {anchor_x:.2f}, {first_baseline_y:.2f}, {attr_str}{transform_suffix})"
    )
    _append_positioned_text_lines(lines, f"_{var_name}", label_item)
    lines.append(f"    d.append(_{var_name})")


def _painter_path_to_svg(path: QtGui.QPainterPath) -> str:
    """Return a compact SVG path string for ``path``.

    The conversion flattens the painter path into polygons and emits

    ``M/L`` commands for each subpath.  Rounded corners are approximated by

    straight segments using Qt's internal flattening tolerance which is

    sufficient for the exported preview rendering.

    """

    segments: list[str] = []

    for poly in path.toSubpathPolygons():
        if not poly:
            continue

        commands: list[str] = []

        points = list(poly)

        closed = False

        if len(points) >= 2:
            first = points[0]

            last = points[-1]

            if math.hypot(first.x() - last.x(), first.y() - last.y()) <= 1e-4:
                closed = True

                points = points[:-1]

        start = points[0]

        commands.append(f"M {start.x():.2f} {start.y():.2f}")

        for point in points[1:]:
            commands.append(f"L {point.x():.2f} {point.y():.2f}")

        if closed:
            commands.append("Z")

        segments.append(" ".join(commands))

    return " ".join(segments)


def _arrowhead_polygon(
    start: QtCore.QPointF,
    end: QtCore.QPointF,
    length: float,
    width: float,
) -> list[QtCore.QPointF]:
    """Return a list of points describing an arrowhead polygon."""

    line = QtCore.QLineF(start, end)

    tip = QtCore.QPointF(end)

    distance = line.length()

    if distance <= 1e-6:
        return [tip, tip, tip]

    arrow_length = max(float(length), 0.0)

    arrow_width = max(float(width), 0.0)

    if arrow_length <= 1e-6 or arrow_width <= 1e-6:
        return [tip, tip, tip]

    unit_x = (end.x() - start.x()) / distance

    unit_y = (end.y() - start.y()) / distance

    perp_x = -unit_y

    perp_y = unit_x

    base_center = QtCore.QPointF(
        tip.x() - unit_x * arrow_length,
        tip.y() - unit_y * arrow_length,
    )

    half_width = arrow_width / 2.0

    left_point = QtCore.QPointF(
        base_center.x() + perp_x * half_width,
        base_center.y() + perp_y * half_width,
    )

    right_point = QtCore.QPointF(
        base_center.x() - perp_x * half_width,
        base_center.y() - perp_y * half_width,
    )

    return [
        tip,
        left_point,
        right_point,
    ]


@dataclass
class _ExportContext:
    """State the per-adapter exporters share while emitting one script."""

    lines: list[str]
    parents: Mapping[QtWidgets.QGraphicsItem, QtWidgets.QGraphicsItem]
    label_counter: int = 0

    def label_id(
        self,
        item: QtWidgets.QGraphicsItem,
        kind: str,
        label_type: type = ShapeLabelMixin,
    ) -> str | None:
        """Reserve the next label id for ``item`` if it carries a label."""
        if not (
            isinstance(item, label_type) and getattr(item, "has_label", lambda: False)()
        ):
            return None
        self.label_counter += 1
        return f"{kind}_label_{self.label_counter}"

    def export_label(
        self, item: ShapeLabelMixin, label_id: str | None, kind: str
    ) -> None:
        if label_id:
            _export_shape_label(
                item,
                self.lines,
                shape_id=label_id,
                parents=self.parents,
                var_name=f"{kind}_label",
                label_kind=kind,
            )


# Each exporter appends the drawsvg source for one item to ``ctx.lines`` and
# returns False when it emitted nothing (the item is then skipped entirely).


def _label_attrs(label_id: str | None) -> list[str]:
    return [f"data_label_id='{label_id}'"] if label_id else []


def _polygon_coords(item: QtWidgets.QGraphicsPolygonItem) -> str:
    return ", ".join(f"{v:.2f}" for p in item.polygon() for v in (p.x(), p.y()))


def _export_rectangle(ctx: _ExportContext, it: QtWidgets.QGraphicsRectItem) -> bool:
    r = it.rect()
    rx = getattr(it, "rx", 0)
    ry = getattr(it, "ry", 0)
    label_id = ctx.label_id(it, "rect", RectItem)
    extra_attrs = _label_attrs(label_id)
    if rx:
        extra_attrs.append(f"rx={rx:.2f}")
    if ry:
        extra_attrs.append(f"ry={ry:.2f}")
    attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)
    ctx.lines.append(
        f"    _rect = draw.Rectangle({r.x():.2f}, {r.y():.2f}, {r.width():.2f}, {r.height():.2f}, "
        f"{attr_str}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_rect)")
    ctx.export_label(it, label_id, "rect")
    ctx.lines.append("")
    return True


def _export_split_rounded_rectangle(
    ctx: _ExportContext, it: SplitRoundedRectItem
) -> bool:
    lines = ctx.lines
    r = it.rect()
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    transform_suffix = _item_transform_suffix(it)
    rx_raw = getattr(it, "rx", 0.0)
    ry_raw = getattr(it, "ry", rx_raw)
    extra_attrs = ["fill='none'", split_style_attribute(it), "data_xml_escaped='true'"]
    if rx_raw:
        extra_attrs.append(f"rx={rx_raw:.2f}")
    if ry_raw:
        extra_attrs.append(f"ry={ry_raw:.2f}")
    attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)
    ratio = it.divider_ratio()
    top_brush = it.topBrush()
    top_fill = (
        "none"
        if top_brush.style() == QtCore.Qt.BrushStyle.NoBrush
        else top_brush.color().name()
    )
    top_opacity = top_brush.color().alphaF()
    lines.append(
        f"    # SplitRoundedRect ratio={ratio:.6f} top_fill='{top_fill}' top_opacity={top_opacity:.3f}"
    )
    # Keep the border constructor before the fills for safe AST reimport;
    # append it after the fills to match Qt's painter order.
    lines.append(
        f"    _split_rect = draw.Rectangle({x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}, {attr_str}{transform_suffix})"
    )
    rx = max(0.0, min(rx_raw, w / 2.0, 50.0))
    ry = max(0.0, min(ry_raw, h / 2.0, 50.0))
    base_path = QtGui.QPainterPath()
    if rx > 0.0 or ry > 0.0:
        base_path.addRoundedRect(r, rx, ry)
    else:
        base_path.addRect(r)
    line_y = max(y, min(y + h, y + h * ratio))
    for var_name, brush, clip_y, clip_height in (
        ("_split_top", top_brush, y, line_y - y),
        ("_split_bottom", it.bottomBrush(), line_y, y + h - line_y),
    ):
        if clip_height <= 0 or brush.style() == QtCore.Qt.BrushStyle.NoBrush:
            continue
        clip = QtGui.QPainterPath()
        clip.addRect(x, clip_y, w, clip_height)
        fill_path = base_path.intersected(clip)
        path_cmd = _painter_path_to_svg(fill_path)
        if not path_cmd:
            continue
        fill_attrs = brush_attributes(brush, it, bounds=fill_path.boundingRect())
        fill_attrs.append("stroke='none'")
        if it.effectiveOpacity() < 1:
            fill_attrs.append(f"opacity={it.effectiveOpacity():.12g}")
        attr = format_drawsvg_attributes(fill_attrs)
        lines.append(
            f"    {var_name} = draw.Path('{path_cmd}', {attr}{transform_suffix})"
        )
        lines.append(f"    d.append({var_name})")
    lines.append("    d.append(_split_rect)")
    divider_pen = it.divider_pen()
    divider_attrs = pen_attributes(divider_pen, it)
    if it.effectiveOpacity() < 1:
        divider_attrs.append(f"opacity={it.effectiveOpacity():.12g}")
    divider_attr = format_drawsvg_attributes(divider_attrs)
    lines.append(
        f"    _split_div = draw.Line({x:.2f}, {line_y:.2f}, {x + w:.2f}, {line_y:.2f}, {divider_attr}{transform_suffix})"
    )
    lines.append("    d.append(_split_div)")
    lines.append("")
    return True


def _export_ellipse(ctx: _ExportContext, it: QtWidgets.QGraphicsEllipseItem) -> bool:
    r = it.rect()
    rx = r.width() / 2.0
    ry = r.height() / 2.0
    label_id = ctx.label_id(it, "ellipse")
    attr_str = _format_item_attributes(it, extra_attrs=_label_attrs(label_id))
    ctx.lines.append(
        f"    _ell = draw.Ellipse({r.x() + rx:.2f}, {r.y() + ry:.2f}, {rx:.2f}, {ry:.2f}, "
        f"{attr_str}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_ell)")
    ctx.export_label(it, label_id, "ellipse")
    ctx.lines.append("")
    return True


def _export_circle(ctx: _ExportContext, it: QtWidgets.QGraphicsEllipseItem) -> bool:
    r = it.rect()
    w = r.width()
    h = r.height()
    radius = (w + h) / 2.0 / 2.0
    label_id = ctx.label_id(it, "circle")
    attr_str = _format_item_attributes(it, extra_attrs=_label_attrs(label_id))
    ctx.lines.append(
        f"    _circ = draw.Circle({r.x() + w / 2.0:.2f}, {r.y() + h / 2.0:.2f}, {radius:.2f}, "
        f"{attr_str}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_circ)")
    ctx.export_label(it, label_id, "circle")
    ctx.lines.append("")
    return True


def _export_triangle(ctx: _ExportContext, it: QtWidgets.QGraphicsPolygonItem) -> bool:
    ctx.lines.append(
        f"    _tri = draw.Lines({_polygon_coords(it)}, close=True, "
        f"{_format_item_attributes(it)}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_tri)")
    ctx.lines.append("")
    return True


def _export_diamond(ctx: _ExportContext, it: DiamondItem) -> bool:
    label_id = ctx.label_id(it, "diamond")
    attr_str = _format_item_attributes(it, extra_attrs=_label_attrs(label_id))
    ctx.lines.append(
        f"    _diamond = draw.Lines({_polygon_coords(it)}, close=True, "
        f"{attr_str}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_diamond)")
    ctx.export_label(it, label_id, "diamond")
    ctx.lines.append("")
    return True


def _export_block_arrow(ctx: _ExportContext, it: BlockArrowItem) -> bool:
    ctx.lines.append(
        f"    # BlockArrow head_ratio={it.head_ratio():.6f} shaft_ratio={it.shaft_ratio():.6f}"
    )
    ctx.lines.append(
        f"    _block_arrow = draw.Lines({_polygon_coords(it)}, close=True, "
        f"{_format_item_attributes(it)}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_block_arrow)")
    ctx.lines.append("")
    return True


def _export_diagram(ctx: _ExportContext, it: DiagramItem) -> bool:
    path_cmd = _painter_path_to_svg(it.path())
    if not path_cmd:
        return False
    label_id = ctx.label_id(it, "diagram", DiagramItem)
    payload = json.dumps(
        {
            "type_id": str(it.data(0)),
            "size": list(it.size()),
            "parameters": it.parameters(),
        },
        separators=(",", ":"),
    )
    extra_attrs = [
        f"data_diagram={_xml_attribute_literal(payload)}",
        "data_xml_escaped='true'",
        *_label_attrs(label_id),
    ]
    attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)
    ctx.lines.append(
        f"    _diagram = draw.Path('{path_cmd}', {attr_str}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_diagram)")
    ctx.export_label(it, label_id, "diagram")
    ctx.lines.append("")
    return True


def _export_curvy_bracket(ctx: _ExportContext, it: CurvyBracketItem) -> bool:
    path_cmd = _painter_path_to_svg(QtGui.QPainterPath(it.path()))
    if not path_cmd:
        return False
    attr_str = _format_item_attributes(
        it,
        extra_attrs=(
            "stroke_linecap='round'",
            "stroke_linejoin='round'",
        ),
    )
    bracket_side = "left" if it.data(0) == "Curvy Left Bracket" else "right"
    ctx.lines.append(
        f"    # CurvyBracket x={0.0:.2f} y={0.0:.2f} w={it.width():.2f} h={it.height():.2f} "
        f"hook_ratio={it.hook_ratio():.6f} side={bracket_side}"
    )
    ctx.lines.append(
        f"    _path = draw.Path('{path_cmd}', {attr_str}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_path)")
    ctx.lines.append("")
    return True


def _export_line(ctx: _ExportContext, it: LineItem) -> bool:
    lines = ctx.lines
    pen = it.pen()
    points = it.points()
    if not points:
        return False
    path_cmd = "M " + " L ".join(f"{pt.x():.2f} {pt.y():.2f}" for pt in points)
    attrs = [
        _format_item_attributes(it, include_fill=False, extra_attrs=("fill='none'",))
    ]

    arrow_start = it.arrow_start
    arrow_end = it.arrow_end
    arrow_length = float(it.arrow_head_length())
    arrow_width = float(it.arrow_head_width())
    if arrow_start or arrow_end:
        attrs.append(f"data_arrow_start={'True' if arrow_start else 'False'}")
        attrs.append(f"data_arrow_end={'True' if arrow_end else 'False'}")
        attrs.append(f"data_arrow_head_length={arrow_length:.2f}")
        attrs.append(f"data_arrow_head_width={arrow_width:.2f}")

    transform_suffix = _item_transform_suffix(it)
    lines.append(
        f"    _path = draw.Path('{path_cmd}', {format_drawsvg_attributes(attrs)}{transform_suffix})"
    )

    if arrow_start or arrow_end:
        start_flag = "true" if arrow_start else "false"
        end_flag = "true" if arrow_end else "false"
        lines.append(
            f"    # Arrowheads: start={start_flag}, end={end_flag}, length={arrow_length:.2f}, width={arrow_width:.2f}"
        )
        local_polys: list[list[QtCore.QPointF]] = []
        if arrow_start and len(points) >= 2:
            local_polys.append(
                _arrowhead_polygon(points[1], points[0], arrow_length, arrow_width)
            )
        if arrow_end and len(points) >= 2:
            local_polys.append(
                _arrowhead_polygon(points[-2], points[-1], arrow_length, arrow_width)
            )
        arrow_pen = QtGui.QPen(pen)
        arrow_pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
        arrow_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
        arrow_attrs = brush_attributes(QtGui.QBrush(pen.color()), it)
        arrow_attrs.extend(pen_attributes(arrow_pen, it))
        arrow_attrs.extend(item_style_attributes(it))
        arrow_attr_str = format_drawsvg_attributes(arrow_attrs)
        for poly in local_polys:
            arrow_cmd = (
                "M " + " L ".join(f"{pt.x():.2f} {pt.y():.2f}" for pt in poly) + " Z"
            )
            lines.append(
                f"    _arrow_head = draw.Path('{arrow_cmd}', {arrow_attr_str}{transform_suffix})"
            )
            lines.append("    d.append(_arrow_head)")

    lines.append("    d.append(_path)")
    lines.append("")
    return True


def _export_free_path(ctx: _ExportContext, it: FreePathItem) -> bool:
    path_cmd = _painter_path_to_svg(it.path())
    if not path_cmd:
        return False
    attrs = [
        _format_item_attributes(
            it,
            extra_attrs=(
                f"data_free_path={_xml_attribute_literal(json.dumps(it.path_payload(), separators=(',', ':')))}",
                "data_xml_escaped='true'",
                f"data_free_path_type={str(it.data(0) or it.path_kind)!r}",
            ),
        )
    ]
    ctx.lines.append(
        f"    _path = draw.Path('{path_cmd}', {format_drawsvg_attributes(attrs)}{_item_transform_suffix(it)})"
    )
    ctx.lines.append("    d.append(_path)")
    ctx.lines.append("")
    return True


def _export_text(ctx: _ExportContext, it: QtWidgets.QGraphicsTextItem) -> bool:
    br = it.boundingRect()
    font = it.font()
    fm = QtGui.QFontMetricsF(font)
    size = _font_pixel_size(font)
    raw_text = it.toPlainText()
    text_lines = _visual_text_lines(it)
    line_ratio = fm.lineSpacing() / size if size > 0.0 else 1.0

    color = it.defaultTextColor()
    doc_margin = it.document().documentMargin() if it.document() else 0.0
    h_align = v_align = None
    if hasattr(it, "text_alignment"):
        try:
            h_align, v_align = it.text_alignment()
        except Exception:
            h_align = v_align = None
    text_dir = None
    if hasattr(it, "text_direction"):
        try:
            text_dir = it.text_direction()
        except Exception:
            text_dir = None

    text_x = br.left() + doc_margin
    text_y = br.top() + doc_margin

    base_attrs = [
        f"fill='{color.name()}'",
        f"opacity={it.effectiveOpacity():.6f}",
        *_text_font_attributes(font),
        "text_anchor='start'",
        "dominant_baseline='alphabetic'",
        f"line_height={line_ratio:.6f}",
        "xml__space='preserve'",
        f"data_doc_margin={doc_margin:.4f}",
        f"data_font_px={size:.4f}",
        "data_scale=1.000000",
        f"data_raw_text={_xml_attribute_literal(raw_text)}",
        f"data_box_w={br.width():.4f}",
        f"data_box_h={br.height():.4f}",
    ]
    if isinstance(it, TextItem):
        base_attrs.append(f"data_auto_size={it.auto_sizes_to_text()!r}")
    if h_align:
        base_attrs.append(f"data_text_h='{h_align}'")
    if v_align:
        base_attrs.append(f"data_text_v='{v_align}'")
    if text_dir:
        base_attrs.append(f"data_text_dir='{text_dir}'")
        base_attrs.append(f"direction='{text_dir}'")
        base_attrs.append("unicode_bidi='embed'")
    if color.alphaF() < 1.0:
        base_attrs.append(f"fill_opacity={color.alphaF():.2f}")
    base_attr_str = format_drawsvg_attributes(base_attrs)

    json_lines = [line if line else " " for line in text_lines]
    text_literal = json.dumps(
        json_lines[0] if len(json_lines) == 1 else json_lines, ensure_ascii=False
    )

    ctx.lines.append(
        f"    _text = draw.Text({text_literal}, {size:.2f}, {text_x:.2f}, {text_y:.2f}, "
        f"{base_attr_str}{_item_transform_suffix(it)})"
    )
    _append_positioned_text_lines(ctx.lines, "_text", it)
    ctx.lines.append("    d.append(_text)")
    ctx.lines.append("")
    return True


def _export_folder_tree(ctx: _ExportContext, it: FolderTreeItem) -> bool:
    lines = ctx.lines
    structure_json = json.dumps(it.structure(), ensure_ascii=False)
    pos, rotation, scale = _scene_transform_components(it)
    br = it.boundingRect()
    transform = it.sceneTransform()
    matrix = (
        f"matrix({transform.m11():.6f} {transform.m12():.6f} {transform.m21():.6f} "
        f"{transform.m22():.6f} {transform.m31():.6f} {transform.m32():.6f})"
    )
    lines.append(
        f"    # FolderTree pos=({pos.x():.6f}, {pos.y():.6f}) size=({br.width():.2f}, {br.height():.2f}) rotation={rotation:.6f} scale={scale:.6f} structure={structure_json}"
    )
    group_attrs = format_drawsvg_attributes(item_style_attributes(it))
    group_suffix = f", {group_attrs}" if group_attrs else ""
    lines.append(f"    _folder_tree = draw.Group(transform='{matrix}'{group_suffix})")

    line_pen = getattr(it, "_line_pen", QtGui.QPen(QtGui.QColor("#7a7a7a")))
    folder_pen = getattr(it, "_folder_pen", QtGui.QPen(QtGui.QColor("#9bd97c")))
    file_pen = getattr(it, "_file_pen", QtGui.QPen(QtGui.QColor("#f58db2")))
    font = getattr(it, "_font", QtGui.QFont(DEFAULT_FONT_FAMILY, 11))
    fm = QtGui.QFontMetricsF(font)
    dot_radius = float(getattr(it, "_dot_radius", 6.0))
    offset = dot_radius - 1.0
    order = list(getattr(it, "_order", []))
    info_map = getattr(it, "_node_info", {})
    line_attr = format_drawsvg_attributes(pen_attributes(line_pen, it))

    for node in order:
        node_parent = getattr(node, "parent", None)
        if node_parent is None:
            continue
        info = info_map.get(node)
        parent_info = info_map.get(node_parent)
        if not info or not parent_info:
            continue
        parent_center = parent_info.get("dot_center")
        child_center = info.get("dot_center")
        if parent_center is None or child_center is None:
            continue
        px = parent_center.x()
        cy = child_center.y()
        lines.append(
            f"    _folder_tree.append(draw.Line({px:.2f}, {parent_center.y() + offset:.2f}, {px:.2f}, {cy:.2f}, {line_attr}))"
        )
        lines.append(
            f"    _folder_tree.append(draw.Line({px:.2f}, {cy:.2f}, {child_center.x() - offset:.2f}, {cy:.2f}, {line_attr}))"
        )

    font_size = _font_pixel_size(font)
    for node in order:
        info = info_map.get(node)
        if not info:
            continue
        text_rect = info.get("text_rect")
        if text_rect is None:
            continue
        text = repr(it.node_label(node))
        baseline = text_rect.center().y() + (fm.ascent() - fm.descent()) / 2.0
        pen = folder_pen if getattr(node, "is_folder", False) else file_pen
        color = pen.color()
        attrs = [
            f"fill='{color.name()}'",
            *_text_font_attributes(font),
        ]
        if color.alphaF() < 1.0:
            attrs.append(f"fill_opacity={color.alphaF():.2f}")
        attr_str = format_drawsvg_attributes(attrs)
        lines.append(
            f"    _folder_tree.append(draw.Text({text}, {font_size:.2f}, {text_rect.left():.2f}, {baseline:.2f}, {attr_str}))"
        )

    lines.append("    d.append(_folder_tree)")
    lines.append("")
    return True


# python_export_adapter name -> (required item type, exporter)
_ADAPTER_EXPORTERS: dict[str, tuple[type, Callable[[_ExportContext, Any], bool]]] = {
    "rectangle": (QtWidgets.QGraphicsRectItem, _export_rectangle),
    "split_rounded_rectangle": (SplitRoundedRectItem, _export_split_rounded_rectangle),
    "ellipse": (QtWidgets.QGraphicsEllipseItem, _export_ellipse),
    "circle": (QtWidgets.QGraphicsEllipseItem, _export_circle),
    "triangle": (QtWidgets.QGraphicsPolygonItem, _export_triangle),
    "diamond": (DiamondItem, _export_diamond),
    "block_arrow": (BlockArrowItem, _export_block_arrow),
    "diagram": (DiagramItem, _export_diagram),
    "curvy_right_bracket": (CurvyBracketItem, _export_curvy_bracket),
    "line": (LineItem, _export_line),
    "free_path": (FreePathItem, _export_free_path),
    "text": (QtWidgets.QGraphicsTextItem, _export_text),
    "folder_tree": (FolderTreeItem, _export_folder_tree),
}


def svg_name_for_script(path: str | Path) -> str:
    """Return '<script stem>.svg'; reject names that are blank, contain
    whitespace or have no letter/digit."""
    stem = Path(path).stem
    if not stem.strip():
        raise ValueError("File name must not be empty.")
    if any(ch.isspace() for ch in stem):
        raise ValueError(f"File name must not contain spaces: {stem!r}")
    if not any(ch.isalnum() for ch in stem):
        raise ValueError(f"File name must contain a letter or digit: {stem!r}")
    return f"{stem}.svg"


def export_drawsvg_py(
    scene: QtWidgets.QGraphicsScene,
    parent: QtWidgets.QWidget | None = None,
    *,
    margins: ExportMargins | None = None,
) -> None:
    scene_items = scene.items()
    parents = scene_item_parents(scene_items)
    shape_items = [
        item
        for item in scene_items
        if export_item_is_visible(item, parents)
        and (
            SHAPE_REGISTRY.definition_for_item(item) is not None
            or isinstance(item, ASSET_ITEM_TYPES)
        )
    ]

    if shape_items:
        rect = export_item_bounds(shape_items[0], parents)
        for it in shape_items[1:]:
            rect = rect.united(export_item_bounds(it, parents))
    else:
        rect = QtCore.QRectF()

    if margins is None:
        aligned = rect.adjusted(-5.0, -5.0, 5.0, 5.0).toAlignedRect()
        ox, oy = aligned.x(), aligned.y()
        width, height = max(1, aligned.width()), max(1, aligned.height())
    else:
        if not shape_items:
            raise ValueError("Cannot apply custom export margins to an empty scene")
        rect = expand_export_rect(rect, margins)
        ox, oy, width, height = rect.getRect()

    lines = [
        "# Auto-generated from PySide6 Canvas to drawsvg",
        "import drawsvg as draw",
        "",
        *STYLE_PRELUDE.strip().splitlines(),
        "",
        "def build_drawing():",
        f"    d = draw.Drawing({width}, {height}, origin=({ox}, {oy}), viewBox='{ox} {oy} {width} {height}')",
        f"    d.append(draw.Rectangle({ox}, {oy}, {width}, {height}, fill='white', stroke='none'))",
        "",
    ]
    ctx = _ExportContext(lines, parents)

    for instance, it in enumerate(reversed(shape_items)):
        item_start = len(lines)
        if isinstance(it, ASSET_ITEM_TYPES):
            attrs = _format_item_attributes(
                it, include_fill=False, extra_attrs=["fill='none'"]
            )
            var_name = export_asset_item(
                it,
                lines,
                attributes=attrs,
                transform_suffix=_item_transform_suffix(it),
                instance=instance,
            )
            lines.append(f"    d.append({var_name})")
            _finish_styled_item(lines, item_start, it)
            lines.append("")
            continue

        definition = SHAPE_REGISTRY.definition_for_item(it)
        if definition is None:
            continue
        exporter = _ADAPTER_EXPORTERS.get(definition.python_export_adapter)
        if (
            exporter is not None
            and isinstance(it, exporter[0])
            and not exporter[1](ctx, it)
        ):
            continue
        _finish_styled_item(lines, item_start, it)

    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        parent,
        "Save as drawsvg-.py…",
        "canvas_drawsvg.py",
        "Python (*.py)",
    )
    if path:
        if Path(path).suffix.casefold() != ".py":
            path = f"{path}.py"
        svg_name = svg_name_for_script(path)
        lines.extend(
            [
                "    return d",
                "",
                "if __name__ == '__main__':",
                "    d = build_drawing()",
                "    # Creates an SVG file next to the script:",
                f"    d.save_svg({svg_name!r})",
            ]
        )
        code = "\n".join(lines)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            if parent is not None:
                parent.statusBar().showMessage(f"Exported: {path}", 5000)
        except Exception as e:
            QtWidgets.QMessageBox.critical(parent, "Error saving file", str(e))
