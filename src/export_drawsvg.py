from PySide6 import QtCore, QtGui, QtWidgets

from constants import SHAPES
from items import LineItem


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
        if shape == "Rectangle" and isinstance(it, QtWidgets.QGraphicsRectItem):
            r = it.rect()
            x = it.pos().x()
            y = it.pos().y()
            w = r.width()
            h = r.height()
            cx = x + w / 2.0
            cy = y + h / 2.0
            ang = it.rotation()
            brush = it.brush()
            pen = it.pen()
            attrs = []
            if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                attrs.append("fill='none'")
            else:
                bcol = brush.color()
                attrs.append(f"fill='{bcol.name()}'")
                attrs.append(f"fill_opacity={bcol.alphaF():.2f}")
            attrs.append(f"stroke='{pen.color().name()}'")
            attrs.append(f"stroke_width={pen.widthF():.2f}")
            rx = getattr(it, "rx", 0)
            ry = getattr(it, "ry", 0)
            if rx:
                attrs.append(f"rx={rx:.2f}")
            if ry:
                attrs.append(f"ry={ry:.2f}")
            attr_str = ", ".join(attrs)
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
            brush = it.brush()
            pen = it.pen()
            attrs = []
            if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                attrs.append("fill='none'")
            else:
                bcol = brush.color()
                attrs.append(f"fill='{bcol.name()}'")
                attrs.append(f"fill_opacity={bcol.alphaF():.2f}")
            attrs.append(f"stroke='{pen.color().name()}'")
            attrs.append(f"stroke_width={pen.widthF():.2f}")
            attr_str = ", ".join(attrs)
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
            brush = it.brush()
            pen = it.pen()
            attrs = []
            if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                attrs.append("fill='none'")
            else:
                bcol = brush.color()
                attrs.append(f"fill='{bcol.name()}'")
                attrs.append(f"fill_opacity={bcol.alphaF():.2f}")
            attrs.append(f"stroke='{pen.color().name()}'")
            attrs.append(f"stroke_width={pen.widthF():.2f}")
            attr_str = ", ".join(attrs)
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
            brush = it.brush()
            pen = it.pen()
            attrs = []
            if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                attrs.append("fill='none'")
            else:
                bcol = brush.color()
                attrs.append(f"fill='{bcol.name()}'")
                attrs.append(f"fill_opacity={bcol.alphaF():.2f}")
            attrs.append(f"stroke='{pen.color().name()}'")
            attrs.append(f"stroke_width={pen.widthF():.2f}")
            attr_str = ", ".join(attrs)
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
            x = it.pos().x()
            y = it.pos().y()
            br = it.boundingRect()
            cx = x + br.width() / 2.0
            cy = y + br.height() / 2.0
            ang = it.rotation()
            font = it.font()
            size = font.pointSizeF()
            if size <= 0:  # fall back to pixel size when point size is unset
                size = float(font.pixelSize())
            text = it.toPlainText().replace("'", "\'")
            color = it.defaultTextColor()
            attrs = [f"fill='{color.name()}'"]
            if color.alphaF() < 1.0:
                attrs.append(f"fill_opacity={color.alphaF():.2f}")
            attr_str = ", ".join(attrs)
            fm = QtGui.QFontMetrics(font)
            baseline = y + fm.ascent()
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
