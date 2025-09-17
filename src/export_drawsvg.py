from collections.abc import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from constants import SHAPES
from items import LineItem, SplitRoundedRectItem


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

    if extra_attrs:
        attrs.extend(extra_attrs)

    return ", ".join(attrs)


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
        start = poly[0]
        commands.append(f"M {start.x():.2f} {start.y():.2f}")
        for point in poly[1:]:
            commands.append(f"L {point.x():.2f} {point.y():.2f}")
        commands.append("Z")
        segments.append(" ".join(commands))
    return " ".join(segments)


def export_drawsvg_py(scene: QtWidgets.QGraphicsScene, parent: QtWidgets.QWidget | None = None):
    rect = scene.itemsBoundingRect()
    width = int(rect.width())
    height = int(rect.height())
    ox = int(rect.x())
    oy = int(rect.y())

    items = [it for it in scene.items() if it.data(0) in SHAPES]
    items.reverse()

    lines = []
    lines.append("# Auto-generated from PySide6 Canvas to drawsvg")
    lines.append("import drawsvg as draw")
    lines.append("")
    lines.append("def build_drawing():")
    lines.append(f"    d = draw.Drawing({width}, {height}, origin=({ox}, {oy}))")
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
            extra_attrs = []
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
            attr_str = _format_item_attributes(it)
            if abs(ang) > 1e-6:
                lines.append(
                    f"    _ell = draw.Ellipse({cx:.2f}, {cy:.2f}, {rx:.2f}, {ry:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"
                )
            else:
                lines.append(
                    f"    _ell = draw.Ellipse({cx:.2f}, {cy:.2f}, {rx:.2f}, {ry:.2f}, {attr_str})"
                )
            lines.append("    d.append(_ell)")
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
            attr_str = _format_item_attributes(it)
            if abs(ang) > 1e-6:
                lines.append(
                    f"    _circ = draw.Circle({cx:.2f}, {cy:.2f}, {radius:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"
                )
            else:
                lines.append(
                    f"    _circ = draw.Circle({cx:.2f}, {cy:.2f}, {radius:.2f}, {attr_str})"
                )
            lines.append("    d.append(_circ)")
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

        elif shape in ("Line", "Arrow") and isinstance(it, LineItem):
            pen = it.pen()
            ang = it.rotation()
            cx = it.pos().x() + it.transformOriginPoint().x()
            cy = it.pos().y() + it.transformOriginPoint().y()
            abs_pts: list[float] = []
            for p in it._points:
                abs_pts.extend([it.pos().x() + p.x(), it.pos().y() + p.y()])
            arrow_start = getattr(it, "arrow_start", False)
            arrow_end = getattr(it, "arrow_end", False)
            if arrow_start or arrow_end:
                lines.append("    _arrow = draw.Marker(-0.1, -0.51, 0.9, 0.5, scale=4, orient='auto')")
                lines.append(
                    f"    _arrow.append(draw.Lines(-0.1, 0.5, -0.1, -0.5, 0.9, 0, fill='{pen.color().name()}', close=True))"
                )
                path_cmd = "M " + " L ".join(
                    f"{abs_pts[i]:.2f} {abs_pts[i+1]:.2f}" for i in range(0, len(abs_pts), 2)
                )
                attrs = [
                    f"stroke='{pen.color().name()}'",
                    f"stroke_width={pen.widthF():.2f}",
                    "fill='none'",
                ]
                if arrow_start:
                    attrs.append("marker_start=_arrow")
                if arrow_end:
                    attrs.append("marker_end=_arrow")
                attr_str = ", ".join(attrs)
                if abs(ang) > 1e-6:
                    lines.append(
                        f"    _path = draw.Path('{path_cmd}', {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"
                    )
                else:
                    lines.append(f"    _path = draw.Path('{path_cmd}', {attr_str})")
                lines.append("    d.append(_arrow)")
                lines.append("    d.append(_path)")
                lines.append("")
            else:
                attr_str = (
                    f"stroke='{pen.color().name()}', "
                    f"stroke_width={pen.widthF():.2f}, "
                    "fill='none'"
                )
                if len(abs_pts) == 4:
                    x1, y1, x2, y2 = abs_pts
                    if abs(ang) > 1e-6:
                        lines.append(
                            f"    _line = draw.Line({x1:.2f}, {y1:.2f}, {x2:.2f}, {y2:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"
                        )
                    else:
                        lines.append(
                            f"    _line = draw.Line({x1:.2f}, {y1:.2f}, {x2:.2f}, {y2:.2f}, {attr_str})"
                        )
                    lines.append("    d.append(_line)")
                    lines.append("")
                else:
                    coord_str = ", ".join(f"{v:.2f}" for v in abs_pts)
                    if abs(ang) > 1e-6:
                        lines.append(
                    f"    _line = draw.Lines({coord_str}, close=False, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"
                        )
                    else:
                        lines.append(
                    f"    _line = draw.Lines({coord_str}, close=False, {attr_str})"
                        )
                    lines.append("    d.append(_line)")
                    lines.append("")

        elif shape == "Text" and isinstance(it, QtWidgets.QGraphicsTextItem):
            br = it.boundingRect()
            cx = it.pos().x() + br.width() / 2.0
            cy = it.pos().y() + br.height() / 2.0
            s = it.scale()
            x = cx - br.width() * s / 2.0
            y = cy - br.height() * s / 2.0
            ang = it.rotation()
            font = it.font()
            size = font.pointSizeF()
            if size <= 0:  # fall back to pixel size when point size is unset
                size = float(font.pixelSize())
            size *= s
            text = repr(it.toPlainText())[1:-1]
            color = it.defaultTextColor()
            attrs = [f"fill='{color.name()}'", f"font_family='{font.family()}'"]
            if color.alphaF() < 1.0:
                attrs.append(f"fill_opacity={color.alphaF():.2f}")
            attr_str = ", ".join(attrs)
            fm = QtGui.QFontMetrics(font)
            baseline = y + fm.ascent() * s
            if abs(ang) > 1e-6:
                lines.append(
                    f"    _text = draw.Text('{text}', {size:.2f}, {x:.2f}, {baseline:.2f}, {attr_str}, transform='rotate({ang:.2f} {cx:.2f} {cy:.2f})')"
                )
            else:
                lines.append(
                    f"    _text = draw.Text('{text}', {size:.2f}, {x:.2f}, {baseline:.2f}, {attr_str})"
                )
            lines.append("    d.append(_text)")
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
