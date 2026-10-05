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

from collections.abc import Iterable, Mapping

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
    pen_dash_array_string,
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
        attrs.extend(brush_attributes(brush_getter(), item) if callable(brush_getter) else ["fill='none'"])
    pen_getter = getattr(item, "pen", None)
    if callable(pen_getter):
        attrs.extend(pen_attributes(pen_getter(), item))
    attrs.extend(item_style_attributes(item))
    if extra_attrs:
        attrs.extend(extra_attrs)
    # Adapter-specific attributes override defaults (e.g. rounded brackets).
    return format_drawsvg_attributes(attrs)


def _pen_dash_array_string(pen: QtGui.QPen) -> str | None:
    return pen_dash_array_string(pen)


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

def _escape_draw_text(value: str) -> str:

    return (

        value.replace('\\', '\\\\')

        .replace("'", "\'")

        .replace('\n', '\\n')

        .replace('\r', '\\r')

    )

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

                visual_lines.append(_qt_text_slice(block_text, start, line.textLength()))

        block = block.next()

    return visual_lines or [""]

def _qt_text_slice(text: str, start: int, length: int) -> str:
    """Qt layout offsets count UTF-16 units, whereas Python counts code points."""
    return text.encode("utf-16-le")[start * 2:(start + length) * 2].decode("utf-16-le")


def _xml_attribute_literal(value: str) -> str:
    """Quote a Python literal that drawsvg can write verbatim into XML."""
    escaped = html.escape(value, quote=True)
    # XML normalizes literal whitespace in attributes; references preserve it.
    escaped = escaped.replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")
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
    lines: list[str], var_name: str, item: QtWidgets.QGraphicsTextItem,
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
            rtl = layout.textOption().textDirection() == QtCore.Qt.LayoutDirection.RightToLeft
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

    pixel_size = float(font.pixelSize())

    if pixel_size <= 0.0:

        point_size = font.pointSizeF()

        if point_size > 0.0:

            screen = QtGui.QGuiApplication.primaryScreen()

            dpi = screen.logicalDotsPerInch() if screen else 96.0

            pixel_size = point_size * dpi / 72.0

    if pixel_size <= 0.0:

        pixel_size = fm.height()

    size = pixel_size

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

                baseline_offset = layout.position().y() + first_line.y() + first_line.ascent()

    anchor_x = (

        text_left if h_align == "left"

        else (text_left + br.width() if h_align == "right"

              else text_left + br.width() / 2.0)

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

    json_lines = [line if line else "\u00A0" for line in raw_lines]

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

def export_drawsvg_py(
    scene: QtWidgets.QGraphicsScene,
    parent: QtWidgets.QWidget | None = None,
    *,
    margins: ExportMargins | None = None,
):

    scene_items = scene.items()
    parents = scene_item_parents(scene_items)
    shape_items = [
        item
        for item in scene_items
        if export_item_is_visible(item, parents)
        and (SHAPE_REGISTRY.definition_for_item(item) is not None
             or isinstance(item, ASSET_ITEM_TYPES))
    ]

    if shape_items:

        rect = export_item_bounds(shape_items[0], parents)

        for it in shape_items[1:]:

            rect = rect.united(export_item_bounds(it, parents))

    else:

        rect = QtCore.QRectF()

    if margins is None:
        padding = 5.0
        rect = rect.adjusted(-padding, -padding, padding, padding)
        left = math.floor(rect.left())
        top = math.floor(rect.top())
        right = math.ceil(rect.right())
        bottom = math.ceil(rect.bottom())
        width = max(1, int(right - left))
        height = max(1, int(bottom - top))
        ox = int(left)
        oy = int(top)
    else:
        if not shape_items:
            raise ValueError("Cannot apply custom export margins to an empty scene")
        rect = expand_export_rect(rect, margins)
        ox, oy, width, height = rect.getRect()

    items = list(reversed(shape_items))

    label_counter = 0

    lines = []

    lines.append("# Auto-generated from PySide6 Canvas to drawsvg")

    lines.append("import drawsvg as draw")

    lines.append("")

    lines.extend(STYLE_PRELUDE.strip().splitlines())
    lines.append("")

    lines.append("def build_drawing():")

    lines.append(f"    d = draw.Drawing({width}, {height}, origin=({ox}, {oy}), viewBox='{ox} {oy} {width} {height}')")

    lines.append(

        f"    d.append(draw.Rectangle({ox}, {oy}, {width}, {height}, fill='white', stroke='none'))"

    )

    lines.append("")

    for instance, it in enumerate(items):

        if isinstance(it, ASSET_ITEM_TYPES):
            item_start = len(lines)
            attrs = _format_item_attributes(it, include_fill=False, extra_attrs=["fill='none'"])
            var_name = export_asset_item(
                it, lines, attributes=attrs,
                transform_suffix=_item_transform_suffix(it), instance=instance,
            )
            lines.append(f"    d.append({var_name})")
            _finish_styled_item(lines, item_start, it)
            lines.append("")
            continue

        definition = SHAPE_REGISTRY.definition_for_item(it)
        if definition is None:
            continue
        adapter = definition.python_export_adapter
        item_start = len(lines)

        if adapter == "rectangle" and isinstance(

            it, QtWidgets.QGraphicsRectItem

        ):

            r = it.rect()

            x = r.x()

            y = r.y()

            w = r.width()

            h = r.height()

            transform_suffix = _item_transform_suffix(it)

            rx = getattr(it, "rx", 0)

            ry = getattr(it, "ry", 0)

            label_id = None

            if isinstance(it, RectItem) and getattr(it, "has_label", lambda: False)():

                label_counter += 1

                label_id = f"rect_label_{label_counter}"

            extra_attrs = []

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            if rx:

                extra_attrs.append(f"rx={rx:.2f}")

            if ry:

                extra_attrs.append(f"ry={ry:.2f}")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            lines.append(

                f"    _rect = draw.Rectangle({x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}, {attr_str}{transform_suffix})"

            )

            lines.append("    d.append(_rect)")

            if label_id:

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    parents=parents,

                    var_name="rect_label",

                    label_kind="rect",

                )

            lines.append("")

        elif adapter == "split_rounded_rectangle" and isinstance(it, SplitRoundedRectItem):
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
            top_fill = "none" if top_brush.style() == QtCore.Qt.BrushStyle.NoBrush else top_brush.color().name()
            top_opacity = top_brush.color().alphaF()
            lines.append(f"    # SplitRoundedRect ratio={ratio:.6f} top_fill='{top_fill}' top_opacity={top_opacity:.3f}")
            # Keep the border constructor before the fills for safe AST reimport;
            # append it after the fills to match Qt's painter order.
            lines.append(f"    _split_rect = draw.Rectangle({x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}, {attr_str}{transform_suffix})")
            rx = max(0.0, min(rx_raw, w / 2.0, 50.0))
            ry = max(0.0, min(ry_raw, h / 2.0, 50.0))
            base_path = QtGui.QPainterPath()
            if rx > 0.0 or ry > 0.0:
                base_path.addRoundedRect(r, rx, ry)
            else:
                base_path.addRect(r)
            line_y = max(y, min(y + h, y + h * ratio))
            for var_name, brush, clip_y, clip_height in (
                ("_split_top", top_brush, y, line_y-y),
                ("_split_bottom", it.bottomBrush(), line_y, y+h-line_y),
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
                lines.append(f"    {var_name} = draw.Path('{path_cmd}', {attr}{transform_suffix})")
                lines.append(f"    d.append({var_name})")
            lines.append("    d.append(_split_rect)")
            divider_pen = getattr(it, "_divider_pen", it.pen())
            divider_attrs = pen_attributes(divider_pen, it)
            if it.effectiveOpacity() < 1:
                divider_attrs.append(f"opacity={it.effectiveOpacity():.12g}")
            divider_attr = format_drawsvg_attributes(divider_attrs)
            lines.append(f"    _split_div = draw.Line({x:.2f}, {line_y:.2f}, {x+w:.2f}, {line_y:.2f}, {divider_attr}{transform_suffix})")
            lines.append("    d.append(_split_div)")
            lines.append("")

        elif adapter == "ellipse" and isinstance(it, QtWidgets.QGraphicsEllipseItem):

            r = it.rect()

            x = r.x()

            y = r.y()

            w = r.width()

            h = r.height()

            cx = x + w / 2.0

            cy = y + h / 2.0

            rx = w / 2.0

            ry = h / 2.0

            transform_suffix = _item_transform_suffix(it)

            label_id = None

            if isinstance(it, ShapeLabelMixin) and getattr(it, "has_label", lambda: False)():

                label_counter += 1

                label_id = f"ellipse_label_{label_counter}"

            extra_attrs: list[str] = []

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            lines.append(

                f"    _ell = draw.Ellipse({cx:.2f}, {cy:.2f}, {rx:.2f}, {ry:.2f}, {attr_str}{transform_suffix})"

            )

            lines.append("    d.append(_ell)")

            if label_id:

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    var_name="ellipse_label",
                    parents=parents,

                    label_kind="ellipse",

                )

            lines.append("")

        elif adapter == "circle" and isinstance(it, QtWidgets.QGraphicsEllipseItem):

            r = it.rect()

            x = r.x()

            y = r.y()

            w = r.width()

            h = r.height()

            d_avg = (w + h) / 2.0

            radius = d_avg / 2.0

            cx = x + w / 2.0

            cy = y + h / 2.0

            transform_suffix = _item_transform_suffix(it)

            label_id = None

            if isinstance(it, ShapeLabelMixin) and getattr(it, "has_label", lambda: False)():

                label_counter += 1

                label_id = f"circle_label_{label_counter}"

            extra_attrs: list[str] = []

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            lines.append(

                f"    _circ = draw.Circle({cx:.2f}, {cy:.2f}, {radius:.2f}, {attr_str}{transform_suffix})"

            )

            lines.append("    d.append(_circ)")

            if label_id:

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    var_name="circle_label",
                    parents=parents,

                    label_kind="circle",

                )

            lines.append("")

        elif adapter == "triangle" and isinstance(it, QtWidgets.QGraphicsPolygonItem):

            poly = it.polygon()

            pts = []

            for p in poly:

                pts.extend([p.x(), p.y()])

            br = it.boundingRect()

            transform_suffix = _item_transform_suffix(it)

            attr_str = _format_item_attributes(it)

            coord_str = ", ".join(f"{v:.2f}" for v in pts)

            lines.append(

                f"    _tri = draw.Lines({coord_str}, close=True, {attr_str}{transform_suffix})"

            )

            lines.append("    d.append(_tri)")

            lines.append("")

        elif adapter == "diamond" and isinstance(it, DiamondItem):

            poly = it.polygon()

            pts: list[float] = []

            for p in poly:

                pts.extend([p.x(), p.y()])

            br = it.boundingRect()

            transform_suffix = _item_transform_suffix(it)

            label_id = None

            if isinstance(it, ShapeLabelMixin) and getattr(it, "has_label", lambda: False)():

                label_counter += 1

                label_id = f"diamond_label_{label_counter}"

            extra_attrs = []

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            coord_str = ", ".join(f"{v:.2f}" for v in pts)

            lines.append(

                f"    _diamond = draw.Lines({coord_str}, close=True, {attr_str}{transform_suffix})"

            )

            lines.append("    d.append(_diamond)")

            if label_id:
                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    var_name="diamond_label",
                    parents=parents,

                    label_kind="diamond",

                )

            lines.append("")

        elif adapter == "block_arrow" and isinstance(it, BlockArrowItem):

            poly = it.polygon()

            pts: list[float] = []

            for p in poly:

                pts.extend([p.x(), p.y()])

            br = it.boundingRect()

            transform_suffix = _item_transform_suffix(it)

            attr_str = _format_item_attributes(it)

            lines.append(

                f"    # BlockArrow head_ratio={it.head_ratio():.6f} shaft_ratio={it.shaft_ratio():.6f}"

            )

            coord_str = ", ".join(f"{v:.2f}" for v in pts)

            lines.append(

                f"    _block_arrow = draw.Lines({coord_str}, close=True, {attr_str}{transform_suffix})"

            )

            lines.append("    d.append(_block_arrow)")

            lines.append("")

        elif adapter == "diagram" and isinstance(it, DiagramItem):

            path_cmd = _painter_path_to_svg(it.path())

            if not path_cmd:
                continue

            label_id = None

            if it.has_label():

                label_counter += 1

                label_id = f"diagram_label_{label_counter}"

            payload = json.dumps(
                {
                    "type_id": str(it.data(0)),
                    "size": [it._w, it._h],
                    "parameters": it.parameters(),
                },
                separators=(",", ":"),
            )

            extra_attrs = [f"data_diagram={_xml_attribute_literal(payload)}", "data_xml_escaped='true'"]

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            lines.append(

                f"    _diagram = draw.Path('{path_cmd}', {attr_str}{_item_transform_suffix(it)})"

            )

            lines.append("    d.append(_diagram)")

            if label_id:

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    var_name="diagram_label",
                    parents=parents,

                    label_kind="diagram",

                )

            lines.append("")

        elif adapter == "curvy_right_bracket" and isinstance(it, CurvyBracketItem):

            x = 0.0

            y = 0.0

            w = it.width()

            h = it.height()

            path = QtGui.QPainterPath(it.path())

            transform_suffix = _item_transform_suffix(it)

            path_cmd = _painter_path_to_svg(path)

            if not path_cmd:

                continue

            attr_str = _format_item_attributes(
                it,
                extra_attrs=(
                    "stroke_linecap='round'",
                    "stroke_linejoin='round'",
                ),
            )

            bracket_side = (
                "left" if it.data(0) == "Curvy Left Bracket" else "right"
            )

            lines.append(

                f"    # CurvyBracket x={x:.2f} y={y:.2f} w={w:.2f} h={h:.2f} hook_ratio={it.hook_ratio():.6f} side={bracket_side}"

            )

            lines.append(

                f"    _path = draw.Path('{path_cmd}', {attr_str}{transform_suffix})"

            )

            lines.append("    d.append(_path)")

            lines.append("")

        elif adapter == "line" and isinstance(it, LineItem):

            pen = it.pen()

            points = [QtCore.QPointF(p) for p in it._points]

            if not points:

                continue

            path_cmd = "M " + " L ".join(f"{pt.x():.2f} {pt.y():.2f}" for pt in points)

            attrs = [_format_item_attributes(it, include_fill=False, extra_attrs=("fill='none'",))]

            arrow_start = getattr(it, "arrow_start", False)
            arrow_end = getattr(it, "arrow_end", False)
            arrow_length = float(
                getattr(it, "_arrow_head_length", getattr(it, "_arrow_size", 10.0))
            )
            arrow_width = float(
                getattr(it, "_arrow_head_width", getattr(it, "_arrow_size", 10.0))
            )

            if arrow_start or arrow_end:
                attrs.append(f"data_arrow_start={'True' if arrow_start else 'False'}")
                attrs.append(f"data_arrow_end={'True' if arrow_end else 'False'}")
                attrs.append(f"data_arrow_head_length={arrow_length:.2f}")
                attrs.append(f"data_arrow_head_width={arrow_width:.2f}")

            attr_str = format_drawsvg_attributes(attrs)

            transform_suffix = _item_transform_suffix(it)

            lines.append(f"    _path = draw.Path('{path_cmd}', {attr_str}{transform_suffix})")

            if arrow_start or arrow_end:

                start_flag = "true" if arrow_start else "false"

                end_flag = "true" if arrow_end else "false"

                lines.append(

                    f"    # Arrowheads: start={start_flag}, end={end_flag}, length={arrow_length:.2f}, width={arrow_width:.2f}"

                )

                local_polys: list[list[QtCore.QPointF]] = []

                if arrow_start and len(it._points) >= 2:

                    local_polys.append(

                        _arrowhead_polygon(
                            it._points[1], it._points[0], arrow_length, arrow_width
                        )

                    )

                if arrow_end and len(it._points) >= 2:

                    local_polys.append(

                        _arrowhead_polygon(

                            it._points[-2],
                            it._points[-1],
                            arrow_length,
                            arrow_width,

                        )

                    )

                arrow_pen = QtGui.QPen(pen)
                arrow_pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
                arrow_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
                arrow_attrs = brush_attributes(QtGui.QBrush(pen.color()), it)
                arrow_attrs.extend(pen_attributes(arrow_pen, it))
                arrow_attrs.extend(item_style_attributes(it))

                arrow_attr_str = format_drawsvg_attributes(arrow_attrs)

                for poly in local_polys:

                    abs_poly = [QtCore.QPointF(p) for p in poly]

                    arrow_cmd = (

                        "M "

                        + " L ".join(

                            f"{pt.x():.2f} {pt.y():.2f}" for pt in abs_poly

                        )

                        + " Z"

                    )

                    lines.append(

                        f"    _arrow_head = draw.Path('{arrow_cmd}', {arrow_attr_str}{transform_suffix})"

                    )

                    lines.append("    d.append(_arrow_head)")

            lines.append("    d.append(_path)")

            lines.append("")

        elif adapter == "free_path" and isinstance(it, FreePathItem):

            path_cmd = _painter_path_to_svg(it.path())
            if not path_cmd:
                continue
            attrs = [_format_item_attributes(it, extra_attrs=(
                f"data_free_path={_xml_attribute_literal(json.dumps(it.path_payload(), separators=(',', ':')))}",
                "data_xml_escaped='true'",
                f"data_free_path_type={str(it.data(0) or it.path_kind)!r}",
            ))]
            lines.append(
                f"    _path = draw.Path('{path_cmd}', {format_drawsvg_attributes(attrs)}{_item_transform_suffix(it)})"
            )
            lines.append("    d.append(_path)")
            lines.append("")

        elif adapter == "text" and isinstance(it, QtWidgets.QGraphicsTextItem):

            br = it.boundingRect()

            x_top = br.left()

            y_top = br.top()

            font = it.font()

            fm = QtGui.QFontMetricsF(font)

            # robuste Pixelgröße aus Font bestimmen

            pixel_size = float(font.pixelSize())

            if pixel_size <= 0.0:

                point_size = font.pointSizeF()

                if point_size > 0.0:

                    screen = QtGui.QGuiApplication.primaryScreen()

                    dpi = screen.logicalDotsPerInch() if screen else 96.0

                    pixel_size = point_size * dpi / 72.0

            if pixel_size <= 0.0:

                pixel_size = fm.height()

            size = pixel_size

            raw_text = it.toPlainText()
            text_lines = _visual_text_lines(it)

            line_px = fm.lineSpacing()
            line_ratio = line_px / size if size > 0.0 else 1.0

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

            text_x = x_top + doc_margin
            text_y = y_top + doc_margin

            base_attrs = [
                f"fill='{color.name()}'",
                f"opacity={it.effectiveOpacity():.6f}",
                *_text_font_attributes(font),
                "text_anchor='start'",
                "dominant_baseline='alphabetic'",
                f"line_height={line_ratio:.6f}",
                "xml__space='preserve'",
                f"data_doc_margin={doc_margin:.4f}",
                f"data_font_px={pixel_size:.4f}",
                "data_scale=1.000000",
                f"data_raw_text={_xml_attribute_literal(raw_text)}",
            ]
            base_attrs.append(f"data_box_w={br.width():.4f}")
            base_attrs.append(f"data_box_h={br.height():.4f}")
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

            json_lines = [line if line else "\u00A0" for line in text_lines]
            if len(json_lines) == 1:
                text_literal = json.dumps(json_lines[0], ensure_ascii=False)
            else:
                text_literal = json.dumps(json_lines, ensure_ascii=False)

            transform_suffix = _item_transform_suffix(it)

            lines.append(
                f"    _text = draw.Text({text_literal}, {size:.2f}, {text_x:.2f}, {text_y:.2f}, {base_attr_str}{transform_suffix})"
            )
            _append_positioned_text_lines(lines, "_text", it)
            lines.append("    d.append(_text)")
            lines.append("")

        elif adapter == "folder_tree" and isinstance(it, FolderTreeItem):

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

                start = QtCore.QPointF(parent_center.x(), parent_center.y() + offset)

                end = QtCore.QPointF(parent_center.x(), child_center.y())

                lines.append(

                    f"    _folder_tree.append(draw.Line({start.x():.2f}, {start.y():.2f}, {end.x():.2f}, {end.y():.2f}, {line_attr}))"

                )

                horizontal_start = QtCore.QPointF(parent_center.x(), child_center.y())

                horizontal_end = QtCore.QPointF(

                    child_center.x() - (dot_radius - 1.0), child_center.y()

                )

                lines.append(

                    f"    _folder_tree.append(draw.Line({horizontal_start.x():.2f}, {horizontal_start.y():.2f}, {horizontal_end.x():.2f}, {horizontal_end.y():.2f}, {line_attr}))"

                )

            for node in order:

                info = info_map.get(node)

                if not info:

                    continue

                text_rect = info.get("text_rect")

                if text_rect is None:

                    continue

                label = it._node_label(node)

                text = repr(label)

                text_x = text_rect.left()

                center_y = text_rect.center().y()

                baseline = center_y + (fm.ascent() - fm.descent()) / 2.0

                pen = folder_pen if getattr(node, "is_folder", False) else file_pen

                color = pen.color()

                font_size = _font_pixel_size(font)

                attrs = [

                    f"fill='{color.name()}'",

                    *_text_font_attributes(font),

                ]

                if color.alphaF() < 1.0:

                    attrs.append(f"fill_opacity={color.alphaF():.2f}")

                attr_str = format_drawsvg_attributes(attrs)

                lines.append(

                    f"    _folder_tree.append(draw.Text({text}, {font_size:.2f}, {text_x:.2f}, {baseline:.2f}, {attr_str}))"

                )

            lines.append("    d.append(_folder_tree)")

            lines.append("")

        _finish_styled_item(lines, item_start, it)

    lines.append("    return d")

    lines.append("")

    lines.append("if __name__ == '__main__':")

    lines.append("    d = build_drawing()")

    lines.append("    # Creates an SVG file next to the script:")

    lines.append("    d.save_svg('canvas.svg')")

    code = "\n".join(lines)

    path, _ = QtWidgets.QFileDialog.getSaveFileName(

        parent,

        "Save as drawsvg-.py…",

        "canvas_drawsvg.py",

        "Python (*.py)",

    )

    if path:

        try:

            with open(path, "w", encoding="utf-8") as f:

                f.write(code)

            if parent is not None:

                parent.statusBar().showMessage(f"Exported: {path}", 5000)

        except Exception as e:

            QtWidgets.QMessageBox.critical(parent, "Error saving file", str(e))
