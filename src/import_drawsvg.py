from __future__ import annotations

import ast
import math
import re
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from items import RectItem, EllipseItem, LineItem, TextItem, TriangleItem


_ROT_RE = re.compile(r"rotate\(([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\)")


def _parse_call(line: str) -> tuple[list[Any], dict[str, Any]]:
    """Parse a drawsvg call line and return args and kwargs."""
    call_src = line.split("=", 1)[1].strip()
    node = ast.parse(call_src, mode="eval").body
    args = []
    for a in node.args:
        if isinstance(a, ast.Name):
            args.append(a.id)
        else:
            args.append(ast.literal_eval(a))
    kwargs: dict[str, Any] = {}
    for kw in node.keywords:
        v = kw.value
        if isinstance(v, ast.Name):
            kwargs[kw.arg] = v.id
        else:
            kwargs[kw.arg] = ast.literal_eval(v)
    return args, kwargs


def _apply_style(item: QtWidgets.QGraphicsItem, kwargs: dict[str, Any]) -> None:
    if isinstance(item, (QtWidgets.QGraphicsRectItem, QtWidgets.QGraphicsEllipseItem, LineItem, TriangleItem)):
        if kwargs.get("fill") == "none":
            item.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        elif "fill" in kwargs:
            color = QtGui.QColor(kwargs["fill"])
            if "fill_opacity" in kwargs:
                color.setAlphaF(float(kwargs["fill_opacity"]))
            item.setBrush(color)
        pen = item.pen()
        if "stroke" in kwargs:
            pen.setColor(QtGui.QColor(kwargs["stroke"]))
        if "stroke_width" in kwargs:
            pen.setWidthF(float(kwargs["stroke_width"]))
        item.setPen(pen)
    elif isinstance(item, TextItem):
        if "fill" in kwargs:
            color = QtGui.QColor(kwargs["fill"])
            if "fill_opacity" in kwargs:
                color.setAlphaF(float(kwargs["fill_opacity"]))
            item.setDefaultTextColor(color)
        if "font_family" in kwargs:
            font = item.font()
            font.setFamily(str(kwargs["font_family"]))
            item.setFont(font)


def _parse_rotate(val: str) -> float:
    m = _ROT_RE.match(val)
    if m:
        return float(m.group(1))
    return 0.0


def import_drawsvg_py(scene: QtWidgets.QGraphicsScene, parent: QtWidgets.QWidget | None = None) -> None:
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        parent, "Load drawsvg-.py…", "", "Python (*.py)"
    )
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        scene.clear()
        for raw in lines:
            line = raw.strip()
            if line.startswith("d = draw.Drawing("):
                args, kwargs = _parse_call(line)
                if len(args) >= 2:
                    ox = oy = 0.0
                    if "origin" in kwargs and isinstance(kwargs["origin"], (tuple, list)):
                        ox, oy = map(float, kwargs["origin"][:2])
                    scene.setSceneRect(float(ox), float(oy), float(args[0]), float(args[1]))
            elif line.startswith("_rect = draw.Rectangle("):
                args, kwargs = _parse_call(line)
                x, y, w, h = map(float, args[:4])
                rx = min(float(kwargs.get("rx", 0.0)), 50.0)
                ry = min(float(kwargs.get("ry", 0.0)), 50.0)
                if "rx" in kwargs and "ry" not in kwargs:
                    ry = rx
                if "ry" in kwargs and "rx" not in kwargs:
                    rx = ry
                item = RectItem(x, y, w, h, rx, ry)
                _apply_style(item, kwargs)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Rectangle")
                scene.addItem(item)
            elif line.startswith("_ell = draw.Ellipse("):
                args, kwargs = _parse_call(line)
                cx, cy, rx, ry = map(float, args[:4])
                x = cx - rx
                y = cy - ry
                w = 2 * rx
                h = 2 * ry
                item = EllipseItem(x, y, w, h)
                _apply_style(item, kwargs)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Ellipse")
                scene.addItem(item)
            elif line.startswith("_circ = draw.Circle("):
                args, kwargs = _parse_call(line)
                cx, cy, r = map(float, args[:3])
                x = cx - r
                y = cy - r
                w = h = 2 * r
                item = EllipseItem(x, y, w, h)
                _apply_style(item, kwargs)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Circle")
                scene.addItem(item)
            elif line.startswith("_tri = draw.Lines("):
                args, kwargs = _parse_call(line)
                coords = [float(a) for a in args]
                xs = coords[0::2]
                ys = coords[1::2]
                x = min(xs)
                y = min(ys)
                w = max(xs) - x
                h = max(ys) - y
                item = TriangleItem(x, y, w, h)
                _apply_style(item, kwargs)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Triangle")
                scene.addItem(item)
            elif line.startswith("_path = draw.Path("):
                args, kwargs = _parse_call(line)
                if args:
                    cmd = args[0]
                    parts = cmd.split()
                    if len(parts) >= 6 and parts[0] == "M":
                        coords: list[float] = []
                        i = 1
                        while i < len(parts):
                            coords.append(float(parts[i]))
                            coords.append(float(parts[i + 1]))
                            i += 2
                            if i < len(parts) and parts[i] == "L":
                                i += 1
                            else:
                                break
                        if len(coords) >= 4:
                            pts = [
                                QtCore.QPointF(coords[i], coords[i + 1])
                                for i in range(0, len(coords), 2)
                            ]
                            arrow_start = "marker_start" in kwargs
                            arrow_end = "marker_end" in kwargs
                            angle = 0.0
                            if "transform" in kwargs:
                                angle = _parse_rotate(kwargs["transform"])
                            item = LineItem(
                                0.0,
                                0.0,
                                points=pts,
                                arrow_start=arrow_start,
                                arrow_end=arrow_end,
                            )
                            _apply_style(item, kwargs)
                            item.setRotation(angle)
                            item.setData(0, "Arrow" if arrow_start or arrow_end else "Line")
                            scene.addItem(item)
            elif line.startswith("_line = draw.Lines("):
                args, kwargs = _parse_call(line)
                coords = list(map(float, args))
                pts = [
                    QtCore.QPointF(coords[i], coords[i + 1])
                    for i in range(0, len(coords), 2)
                ]
                angle = 0.0
                if "transform" in kwargs:
                    angle = _parse_rotate(kwargs["transform"])
                item = LineItem(0.0, 0.0, points=pts)
                _apply_style(item, kwargs)
                item.setRotation(angle)
                item.setData(0, "Line")
                scene.addItem(item)
            elif line.startswith("_line = draw.Line("):
                args, kwargs = _parse_call(line)
                x1, y1, x2, y2 = map(float, args[:4])
                dx, dy = x2 - x1, y2 - y1
                length = math.hypot(dx, dy)
                angle = math.degrees(math.atan2(dy, dx))
                if "transform" in kwargs:
                    angle = _parse_rotate(kwargs["transform"])
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                item = LineItem(cx - length / 2.0, cy, length)
                _apply_style(item, kwargs)
                item.setRotation(angle)
                item.setData(0, "Line")
                scene.addItem(item)
            elif line.startswith("_text = draw.Text("):
                args, kwargs = _parse_call(line)
                text = args[0]
                size = float(args[1])
                x = float(args[2])
                baseline = float(args[3])
                item = TextItem(0, 0, 0, 0)
                item.setPlainText(text)
                font = item.font()
                font.setPointSizeF(size)
                item.setFont(font)
                _apply_style(item, kwargs)
                font = item.font()
                fm = QtGui.QFontMetrics(font)
                y = baseline - fm.ascent()
                item.setPos(x, y)
                br = item.boundingRect()
                item.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Text")
                scene.addItem(item)
        if parent is not None:
            parent.statusBar().showMessage(f"Loaded: {path}", 5000)
    except Exception as e:
        QtWidgets.QMessageBox.critical(parent, "Error loading file", str(e))
