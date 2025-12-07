# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import json

import math

from collections.abc import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from constants import SHAPES, PEN_STYLE_DASH_ARRAYS, DEFAULT_FONT_FAMILY

from items import (

    BlockArrowItem,

    CurvyBracketItem,

    DiamondItem,

    FolderTreeItem,

    LineItem,

    RectItem,

    ShapeLabelMixin,

    SplitRoundedRectItem,

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

        if callable(brush_getter):

            brush = brush_getter()

            if brush.style() == QtCore.Qt.BrushStyle.NoBrush:

                attrs.append("fill='none'")

            else:

                color = brush.color()

                attrs.append(f"fill='{color.name()}'")

                attrs.append(f"fill_opacity={color.alphaF():.2f}")

        else:

            attrs.append("fill='none'")

    pen_getter = getattr(item, "pen", None)

    if callable(pen_getter):

        pen = pen_getter()

        attrs.append(f"stroke='{pen.color().name()}'")

        attrs.append(f"stroke_width={pen.widthF():.2f}")

        dash_str = _pen_dash_array_string(pen)

        if dash_str:

            attrs.append(f"stroke_dasharray='{dash_str}'")

    if extra_attrs:

        attrs.extend(extra_attrs)

    return ", ".join(attrs)

def _pen_dash_array_string(pen: QtGui.QPen) -> str | None:

    dash_array = PEN_STYLE_DASH_ARRAYS.get(pen.style())

    if dash_array:

        return " ".join(f"{value:.2f}" for value in dash_array)

    pattern = pen.dashPattern()

    if pattern:

        return " ".join(f"{value:.2f}" for value in pattern)

    return None

def _escape_draw_text(value: str) -> str:

    return (

        value.replace('\\', '\\\\')

        .replace("'", "\'")

        .replace('\n', '\\n')

        .replace('\r', '\\r')

    )

def _export_shape_label(

    item: ShapeLabelMixin,

    lines: list[str],

    *,

    shape_id: str | None,

    angle: float,

    base_pos: tuple[float, float] | None = None,

    base_size: tuple[float, float] | None = None,

    var_name: str = "shape_label",

    label_kind: str | None = None,

) -> None:

    if not shape_id:

        return

    if not getattr(item, "has_label", lambda: False)():

        return

    text_value = getattr(item, "label_text", lambda: "")()

    if not text_value:

        return

    label_item = getattr(item, "label_item", lambda: None)()

    if label_item is None:

        return

    raw_lines = text_value.splitlines()

    if text_value.endswith(("\r", "\n")):

        raw_lines.append("")

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

    scale = label_item.scale() or 1.0

    size = pixel_size * scale

    line_px = fm.lineSpacing() * scale

    line_ratio = line_px / size if size > 0.0 else 1.0

    bounds = item.boundingRect()

    if base_pos is None:

        base_pos = (item.pos().x() + bounds.x(), item.pos().y() + bounds.y())

    if base_size is None:

        base_size = (bounds.width(), bounds.height())

    bx, by = base_pos

    bw, bh = base_size

    label_pos = label_item.pos()

    br = label_item.boundingRect()

    text_left = bx + label_pos.x() + br.left()

    text_top = by + label_pos.y() + br.top()

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

        f"font_family='{font.family()}'",

        f"text_anchor='{text_anchor}'",

        "dominant_baseline='alphabetic'",

        f"line_height={line_ratio:.6f}",

        "xml__space='preserve'",

        "data_shape_label='true'",

        f"data_label_id='{shape_id}'",

        f"data_label_h='{h_align}'",

        f"data_label_v='{v_align}'",

        f"data_font_px={pixel_size:.4f}",

    ]
    if item.label_has_custom_color():

        attrs.append("data_label_color_override='true'")

    if label_kind:

        attrs.append(f"data_label_kind='{label_kind}'")

    if label_kind == "rect":

        attrs.append("data_rect_label='true'")

    if color.alphaF() < 1.0:

        attrs.append(f"fill_opacity={color.alphaF():.2f}")

    attr_str = ", ".join(attrs)

    transform_suffix = ""

    if abs(angle) > 1e-6:

        cx = bx + bw / 2.0

        cy = by + bh / 2.0

        transform_suffix = f", transform='rotate({angle:.2f} {cx:.2f} {cy:.2f})'"

    json_lines = [line if line else "\u00A0" for line in raw_lines]

    if len(json_lines) == 1:

        text_literal = json.dumps(json_lines[0], ensure_ascii=False)

    else:

        text_literal = json.dumps(json_lines, ensure_ascii=False)

    lines.append(f"    # Multiline label for {shape_id}")

    lines.append(

        f"    _{var_name} = draw.Text({text_literal}, {size:.2f}, {anchor_x:.2f}, {first_baseline_y:.2f}, {attr_str}{transform_suffix})"

    )

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

def export_drawsvg_py(scene: QtWidgets.QGraphicsScene, parent: QtWidgets.QWidget | None = None):

    shape_items = [it for it in scene.items() if it.data(0) in SHAPES]

    if shape_items:

        rect = shape_items[0].sceneBoundingRect()

        for it in shape_items[1:]:

            rect = rect.united(it.sceneBoundingRect())

    else:

        rect = scene.itemsBoundingRect()

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

    items = list(reversed(shape_items))

    label_counter = 0

    lines = []

    lines.append("# Auto-generated from PySide6 Canvas to drawsvg")

    lines.append("import drawsvg as draw")

    lines.append("")

    lines.append("def build_drawing():")

    lines.append(f"    d = draw.Drawing({width}, {height}, origin=({ox}, {oy}), viewBox='{ox} {oy} {width} {height}')")

    lines.append(

        f"    d.append(draw.Rectangle({ox}, {oy}, {width}, {height}, fill='white', stroke='none'))"

    )

    lines.append("")

    for it in items:

        shape = it.data(0)

        if shape in ("Rectangle", "Rounded Rectangle") and isinstance(

            it, QtWidgets.QGraphicsRectItem

        ):

            r = it.rect()

            x = it.pos().x()

            y = it.pos().y()

            w = r.width()

            h = r.height()

            cx = x + w / 2.0

            cy = y + h / 2.0

            ang = it.rotation()

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

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _rect = draw.Rectangle({x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _rect = draw.Rectangle({x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}, {attr_str})"

                )

            lines.append("    d.append(_rect)")

            if label_id:

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    angle=ang,

                    base_pos=(x, y),

                    base_size=(w, h),

                    var_name="rect_label",

                    label_kind="rect",

                )

            lines.append("")

        elif shape == "Split Rounded Rectangle" and isinstance(it, SplitRoundedRectItem):

            r = it.rect()

            x = it.pos().x()

            y = it.pos().y()

            w = r.width()

            h = r.height()

            cx = x + w / 2.0

            cy = y + h / 2.0

            ang = it.rotation()

            rx_raw = getattr(it, "rx", 0.0)

            ry_raw = getattr(it, "ry", rx_raw)

            extra_attrs = []

            if rx_raw:

                extra_attrs.append(f"rx={rx_raw:.2f}")

            if ry_raw:

                extra_attrs.append(f"ry={ry_raw:.2f}")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            ratio = it.divider_ratio()

            top_brush = it.topBrush()

            if top_brush.style() == QtCore.Qt.BrushStyle.NoBrush:

                top_fill = "none"

                top_opacity = 1.0

            else:

                top_color = top_brush.color()

                top_fill = top_color.name()

                top_opacity = top_color.alphaF()

            lines.append(

                f"    # SplitRoundedRect ratio={ratio:.6f} top_fill='{top_fill}' top_opacity={top_opacity:.3f}"

            )

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _split_rect = draw.Rectangle({x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _split_rect = draw.Rectangle({x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}, {attr_str})"

                )

            lines.append("    d.append(_split_rect)")

            rect_scene = QtCore.QRectF(x, y, w, h)

            rx = max(0.0, min(rx_raw, w / 2.0, 50.0))

            ry = max(0.0, min(ry_raw, h / 2.0, 50.0))

            base_path = QtGui.QPainterPath()

            if rx > 0.0 or ry > 0.0:

                base_path.addRoundedRect(rect_scene, rx, ry)

            else:

                base_path.addRect(rect_scene)

            line_y = y + h * ratio

            line_y = max(y, min(y + h, line_y))

            top_height = max(0.0, line_y - y)

            if top_height > 0.0 and top_brush.style() != QtCore.Qt.BrushStyle.NoBrush:

                top_clip = QtGui.QPainterPath()

                top_clip.addRect(x, y, w, top_height)

                top_path = base_path.intersected(top_clip)

                path_cmd = _painter_path_to_svg(top_path)

                if path_cmd:

                    top_attrs = [f"fill='{top_fill}'", "stroke='none'"]

                    if top_fill != "none" and top_opacity < 1.0:

                        top_attrs.append(f"fill_opacity={top_opacity:.2f}")

                    attr = ", ".join(top_attrs)

                    if abs(ang) > 1e-6:

                        lines.append(

                            f"    _split_top = draw.Path('{path_cmd}', {attr}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                        )

                    else:

                        lines.append(f"    _split_top = draw.Path('{path_cmd}', {attr})")

                    lines.append("    d.append(_split_top)")

            divider_pen = getattr(it, "_divider_pen", it.pen())

            divider_attrs = [

                f"stroke='{divider_pen.color().name()}'",

                f"stroke_width={divider_pen.widthF():.2f}",

            ]

            divider_attr = ", ".join(divider_attrs)

            x2 = x + w

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _split_div = draw.Line({x:.2f}, {line_y:.2f}, {x2:.2f}, {line_y:.2f}, {divider_attr}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _split_div = draw.Line({x:.2f}, {line_y:.2f}, {x2:.2f}, {line_y:.2f}, {divider_attr})"

                )

            lines.append("    d.append(_split_div)")

            lines.append("")

        elif shape == "Ellipse" and isinstance(it, QtWidgets.QGraphicsEllipseItem):

            r = it.rect()

            x = it.pos().x()

            y = it.pos().y()

            w = r.width()

            h = r.height()

            cx = x + w / 2.0

            cy = y + h / 2.0

            rx = w / 2.0

            ry = h / 2.0

            ang = it.rotation()

            label_id = None

            if isinstance(it, ShapeLabelMixin) and getattr(it, "has_label", lambda: False)():

                label_counter += 1

                label_id = f"ellipse_label_{label_counter}"

            extra_attrs: list[str] = []

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _ell = draw.Ellipse({cx:.2f}, {cy:.2f}, {rx:.2f}, {ry:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _ell = draw.Ellipse({cx:.2f}, {cy:.2f}, {rx:.2f}, {ry:.2f}, {attr_str})"

                )

            lines.append("    d.append(_ell)")

            if label_id:

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    angle=ang,

                    base_pos=(x, y),

                    base_size=(w, h),

                    var_name="ellipse_label",

                    label_kind="ellipse",

                )

            lines.append("")

        elif shape == "Circle" and isinstance(it, QtWidgets.QGraphicsEllipseItem):

            r = it.rect()

            x = it.pos().x()

            y = it.pos().y()

            w = r.width()

            h = r.height()

            d_avg = (w + h) / 2.0

            radius = d_avg / 2.0

            cx = x + w / 2.0

            cy = y + h / 2.0

            ang = it.rotation()

            label_id = None

            if isinstance(it, ShapeLabelMixin) and getattr(it, "has_label", lambda: False)():

                label_counter += 1

                label_id = f"circle_label_{label_counter}"

            extra_attrs: list[str] = []

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _circ = draw.Circle({cx:.2f}, {cy:.2f}, {radius:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _circ = draw.Circle({cx:.2f}, {cy:.2f}, {radius:.2f}, {attr_str})"

                )

            lines.append("    d.append(_circ)")

            if label_id:

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    angle=ang,

                    base_pos=(x, y),

                    base_size=(w, h),

                    var_name="circle_label",

                    label_kind="circle",

                )

            lines.append("")

        elif shape == "Triangle" and isinstance(it, QtWidgets.QGraphicsPolygonItem):

            poly = it.polygon()

            x = it.pos().x()

            y = it.pos().y()

            pts = []

            for p in poly:

                pts.extend([x + p.x(), y + p.y()])

            br = it.boundingRect()

            cx = x + br.width() / 2.0

            cy = y + br.height() / 2.0

            ang = it.rotation()

            attr_str = _format_item_attributes(it)

            coord_str = ", ".join(f"{v:.2f}" for v in pts)

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _tri = draw.Lines({coord_str}, close=True, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _tri = draw.Lines({coord_str}, close=True, {attr_str})"

                )

            lines.append("    d.append(_tri)")

            lines.append("")

        elif shape == "Diamond" and isinstance(it, DiamondItem):

            poly = it.polygon()

            x = it.pos().x()

            y = it.pos().y()

            pts: list[float] = []

            for p in poly:

                pts.extend([x + p.x(), y + p.y()])

            br = it.boundingRect()

            cx = x + br.x() + br.width() / 2.0

            cy = y + br.y() + br.height() / 2.0

            ang = it.rotation()

            label_id = None

            if isinstance(it, ShapeLabelMixin) and getattr(it, "has_label", lambda: False)():

                label_counter += 1

                label_id = f"diamond_label_{label_counter}"

            extra_attrs = []

            if label_id:

                extra_attrs.append(f"data_label_id='{label_id}'")

            attr_str = _format_item_attributes(it, extra_attrs=extra_attrs)

            coord_str = ", ".join(f"{v:.2f}" for v in pts)

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _diamond = draw.Lines({coord_str}, close=True, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _diamond = draw.Lines({coord_str}, close=True, {attr_str})"

                )

            lines.append("    d.append(_diamond)")

            if label_id:

                base_pos = (x + br.x(), y + br.y())

                base_size = (br.width(), br.height())

                _export_shape_label(

                    it,

                    lines,

                    shape_id=label_id,

                    angle=ang,

                    base_pos=base_pos,

                    base_size=base_size,

                    var_name="diamond_label",

                    label_kind="diamond",

                )

            lines.append("")

        elif shape == "Block Arrow" and isinstance(it, BlockArrowItem):

            poly = it.polygon()

            x = it.pos().x()

            y = it.pos().y()

            pts: list[float] = []

            for p in poly:

                pts.extend([x + p.x(), y + p.y()])

            br = it.boundingRect()

            cx = x + br.width() / 2.0

            cy = y + br.height() / 2.0

            ang = it.rotation()

            attr_str = _format_item_attributes(it)

            lines.append(

                f"    # BlockArrow head_ratio={it.head_ratio():.6f} shaft_ratio={it.shaft_ratio():.6f}"

            )

            coord_str = ", ".join(f"{v:.2f}" for v in pts)

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _block_arrow = draw.Lines({coord_str}, close=True, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(

                    f"    _block_arrow = draw.Lines({coord_str}, close=True, {attr_str})"

                )

            lines.append("    d.append(_block_arrow)")

            lines.append("")

        elif shape == "Curvy Right Bracket" and isinstance(it, CurvyBracketItem):

            x = it.pos().x()

            y = it.pos().y()

            w = it.width()

            h = it.height()

            cx = x + w / 2.0

            cy = y + h / 2.0

            ang = it.rotation()

            path = QtGui.QPainterPath(it.path())

            path.translate(x, y)

            path_cmd = _painter_path_to_svg(path)

            if not path_cmd:

                continue

            attr_str = _format_item_attributes(it)

            lines.append(

                f"    # CurvyBracket x={x:.2f} y={y:.2f} w={w:.2f} h={h:.2f} hook_ratio={it.hook_ratio():.6f}"

            )

            if abs(ang) > 1e-6:

                lines.append(

                    f"    _path = draw.Path('{path_cmd}', {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"

                )

            else:

                lines.append(f"    _path = draw.Path('{path_cmd}', {attr_str})")

            lines.append("    d.append(_path)")

            lines.append("")

        elif shape in ("Line", "Arrow") and isinstance(it, LineItem):

            pen = it.pen()

            ang = it.rotation()

            pos = it.pos()

            origin = it.transformOriginPoint()

            cx = pos.x() + origin.x()

            cy = pos.y() + origin.y()

            points = [

                QtCore.QPointF(pos.x() + p.x(), pos.y() + p.y()) for p in it._points

            ]

            if not points:

                continue

            path_cmd = "M " + " L ".join(f"{pt.x():.2f} {pt.y():.2f}" for pt in points)

            attrs = [

                f"stroke='{pen.color().name()}'",

                f"stroke_width={pen.widthF():.2f}",

                "fill='none'",

            ]

            dash_str = _pen_dash_array_string(pen)

            if dash_str:

                attrs.append(f"stroke_dasharray='{dash_str}'")

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

            attr_str = ", ".join(attrs)

            transform_suffix = ""

            if abs(ang) > 1e-6:

                transform_suffix = f", transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})'"

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

                color = pen.color()

                arrow_attrs = [

                    f"fill='{color.name()}'",

                    f"stroke='{color.name()}'",

                    f"stroke_width={pen.widthF():.2f}",

                ]

                if color.alphaF() < 1.0:

                    arrow_attrs.append(f"fill_opacity={color.alphaF():.2f}")

                    arrow_attrs.append(f"stroke_opacity={color.alphaF():.2f}")

                arrow_attr_str = ", ".join(arrow_attrs)

                for poly in local_polys:

                    abs_poly = [

                        QtCore.QPointF(pos.x() + p.x(), pos.y() + p.y()) for p in poly

                    ]

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

        elif shape == "Text" and isinstance(it, QtWidgets.QGraphicsTextItem):

            br = it.boundingRect()

            s = it.scale() or 1.0

            cx = it.pos().x() + br.width() / 2.0

            cy = it.pos().y() + br.height() / 2.0

            x_top = cx - (br.width() * s) / 2.0

            y_top = cy - (br.height() * s) / 2.0

            ang = it.rotation()

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

            size = pixel_size * s

            raw_text = it.toPlainText()
            text_lines: list[str]
            doc = it.document()
            layout = doc.documentLayout() if doc is not None else None
            if doc is not None and layout is not None:
                text_lines = []
                block = doc.begin()
                while block.isValid():
                    layout.blockBoundingRect(block)
                    block_text = block.text()
                    block_layout = block.layout()
                    if block_layout is not None and block_layout.lineCount() > 0:
                        for idx in range(block_layout.lineCount()):
                            line = block_layout.lineAt(idx)
                            start = line.textStart()
                            length = line.textLength()
                            fragment = block_text[start : start + length]
                            text_lines.append(fragment)
                    else:
                        text_lines.append(block_text)
                    block = block.next()
                if not text_lines:
                    text_lines = [""]
            else:
                text_lines = raw_text.splitlines()
                if raw_text.endswith(("\r", "\n")):
                    text_lines.append("")
                if not text_lines:
                    text_lines = [raw_text]

            line_px = fm.lineSpacing() * s
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

            text_x = x_top + doc_margin * s
            text_y = y_top + doc_margin * s

            base_attrs = [
                f"fill='{color.name()}'",
                f"font_family='{font.family()}'",
                "text_anchor='start'",
                "dominant_baseline='text-before-edge'",
                "alignment_baseline='text-before-edge'",
                f"line_height={line_ratio:.6f}",
                "xml__space='preserve'",
                f"data_doc_margin={doc_margin:.4f}",
                f"data_font_px={pixel_size:.4f}",
                f"data_scale={s:.6f}",
            ]
            base_attrs.append(f"data_box_w={br.width():.4f}")
            base_attrs.append(f"data_box_h={br.height():.4f}")
            if h_align:
                base_attrs.append(f"data_text_h='{h_align}'")
            if v_align:
                base_attrs.append(f"data_text_v='{v_align}'")
            if text_dir:
                base_attrs.append(f"data_text_dir='{text_dir}'")
            if color.alphaF() < 1.0:
                base_attrs.append(f"fill_opacity={color.alphaF():.2f}")
            base_attr_str = ", ".join(base_attrs)

            json_lines = [line if line else "\u00A0" for line in text_lines]
            if len(json_lines) == 1:
                text_literal = json.dumps(json_lines[0], ensure_ascii=False)
            else:
                text_literal = json.dumps(json_lines, ensure_ascii=False)

            transform_suffix = ""
            if abs(ang) > 1e-6:
                transform_suffix = f", transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})'"

            lines.append(
                f"    _text = draw.Text({text_literal}, {size:.2f}, {text_x:.2f}, {text_y:.2f}, {base_attr_str}{transform_suffix})"
            )
            lines.append("    d.append(_text)")
            lines.append("")

        elif shape == "Folder Tree" and isinstance(it, FolderTreeItem):

            structure_json = json.dumps(it.structure(), ensure_ascii=False)

            pos = it.pos()

            rotation = it.rotation()

            br = it.boundingRect()

            transform = it.sceneTransform()

            matrix = (

                f"matrix({transform.m11():.6f} {transform.m12():.6f} {transform.m21():.6f} "

                f"{transform.m22():.6f} {transform.m31():.2f} {transform.m32():.2f})"

            )

            lines.append(

                f"    # FolderTree pos=({pos.x():.2f}, {pos.y():.2f}) size=({br.width():.2f}, {br.height():.2f}) rotation={rotation:.2f} structure={structure_json}"

            )

            lines.append(f"    _folder_tree = draw.Group(transform='{matrix}')")

            line_pen = getattr(it, "_line_pen", QtGui.QPen(QtGui.QColor("#7a7a7a")))

            folder_pen = getattr(it, "_folder_pen", QtGui.QPen(QtGui.QColor("#9bd97c")))

            file_pen = getattr(it, "_file_pen", QtGui.QPen(QtGui.QColor("#f58db2")))

            font = getattr(it, "_font", QtGui.QFont(DEFAULT_FONT_FAMILY, 11))

            fm = QtGui.QFontMetricsF(font)

            dot_radius = float(getattr(it, "_dot_radius", 6.0))

            offset = dot_radius - 1.0

            order = list(getattr(it, "_order", []))

            info_map = getattr(it, "_node_info", {})

            line_attr = (

                f"stroke='{line_pen.color().name()}', stroke_width={line_pen.widthF():.2f}"

            )

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

                text = repr(label)[1:-1]

                text_x = text_rect.left()

                center_y = text_rect.center().y()

                baseline = center_y + (fm.ascent() - fm.descent()) / 2.0

                pen = folder_pen if getattr(node, "is_folder", False) else file_pen

                color = pen.color()

                font_size = font.pointSizeF()

                if font_size <= 0.0:

                    font_size = float(font.pixelSize())

                attrs = [

                    f"fill='{color.name()}'",

                    f"font_family='{font.family()}'",

                ]

                if color.alphaF() < 1.0:

                    attrs.append(f"fill_opacity={color.alphaF():.2f}")

                attr_str = ", ".join(attrs)

                lines.append(

                    f"    _folder_tree.append(draw.Text('{text}', {font_size:.2f}, {text_x:.2f}, {baseline:.2f}, {attr_str}))"

                )

            lines.append("    d.append(_folder_tree)")

            lines.append("")

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

