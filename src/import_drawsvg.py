# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import ast
import math
import json
import re
from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from items import (
    BlockArrowItem,
    CurvyBracketItem,
    DiamondItem,
    EllipseItem,
    FolderTreeItem,
    LineItem,
    RectItem,
    ShapeLabelMixin,
    SplitRoundedRectItem,
    TextItem,
    TriangleItem,
)

from constants import DEFAULTS, PEN_STYLE_DASH_ARRAYS


_ROT_RE = re.compile(r"rotate\(([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\)")
_DASH_ARRAY_TO_STYLE = {
    tuple(round(val, 2) for val in pattern): style
    for style, pattern in PEN_STYLE_DASH_ARRAYS.items()
    if pattern
}


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
    if isinstance(item, (QtWidgets.QGraphicsRectItem, QtWidgets.QGraphicsEllipseItem, LineItem, TriangleItem, DiamondItem, BlockArrowItem)):
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
        dash_pattern = None
        dash_value = kwargs.get("stroke_dasharray")
        if dash_value is not None:
            if isinstance(dash_value, (list, tuple)):
                dash_pattern = [float(v) for v in dash_value]
            else:
                parts = str(dash_value).replace(",", " ").split()
                try:
                    dash_pattern = [float(part) for part in parts]
                except ValueError:
                    dash_pattern = []
        style_to_apply: QtCore.Qt.PenStyle | None = None
        if dash_pattern is not None:
            if not dash_pattern:
                style_to_apply = QtCore.Qt.PenStyle.SolidLine
            else:
                rounded = tuple(round(val, 2) for val in dash_pattern)
                style_to_apply = _DASH_ARRAY_TO_STYLE.get(rounded)
        if style_to_apply is not None:
            pen.setStyle(style_to_apply)
        elif dash_pattern:
            pen.setStyle(QtCore.Qt.PenStyle.CustomDashLine)
            pen.setDashPattern(dash_pattern)
        item.setPen(pen)
        if isinstance(item, LineItem) and style_to_apply is not None:
            item.set_pen_style(style_to_apply)
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

        cleared = False
        view = scene.parent()
        if view is not None:
            clear_method = getattr(view, "clear_canvas", None)
            if callable(clear_method):
                clear_method()
                cleared = True
        if not cleared:
            scene.clear()

        pending_split: dict[str, Any] | None = None
        pending_block: dict[str, Any] | None = None
        pending_bracket: dict[str, Any] | None = None
        pending_line: LineItem | None = None

        # Neu: Mapping von Label-ID -> Ziel-Shape sowie Sammelcontainer für mehrzeilige Label
        shape_label_targets: dict[str, ShapeLabelMixin] = {}
        shape_label_pending: dict[str, dict[str, Any]] = {}

        def _apply_shape_label(target: ShapeLabelMixin, data: dict[str, Any]) -> None:
            """
            Wendet gesammelte Label-Daten auf ein Shape an.
            Unterstützt sowohl 'text' (alt) als auch 'lines' (neu, mehrere Zeilen).
            NBSP (U+00A0) wird als leere Zeile interpretiert.
            """
            if "lines" in data and isinstance(data["lines"], list):
                norm = [("" if (s == "\u00A0" or s == "&#160;") else str(s)) for s in data["lines"]]
                text_value = "\n".join(norm)
            else:
                text_value = str(data.get("text", ""))

            target.set_label_text(text_value)
            target.set_label_alignment(
                horizontal=str(data.get("h")) if data.get("h") else None,
                vertical=str(data.get("v")) if data.get("v") else None,
            )
            font_px = data.get("font_px")
            if font_px is not None:
                try:
                    target.set_label_font_pixel_size(float(font_px))
                except (TypeError, ValueError):
                    pass
            color_value = data.get("color")
            if color_value is not None:
                color = QtGui.QColor(str(color_value))
                if color.isValid():
                    override_flag = data.get("color_override")
                    override = False
                    if isinstance(override_flag, str):
                        override = override_flag.strip().lower() in {"1", "true", "yes", "on"}
                    elif isinstance(override_flag, (int, float)):
                        override = bool(override_flag)
                    elif isinstance(override_flag, bool):
                        override = override_flag
                    if override:
                        target.set_label_color(color)
                    else:
                        target.reset_label_color(update=True, base_color=color)

        for raw in lines:
            line = raw.strip()
            if not line:
                pending_split = None
                pending_block = None
                pending_bracket = None
                pending_line = None
                continue

            if line.startswith("#"):
                if line.startswith("# SplitRoundedRect"):
                    info: dict[str, Any] = {}
                    for part in line.split()[2:]:
                        if "=" not in part:
                            continue
                        key, value = part.split("=", 1)
                        value = value.rstrip(",")
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        info[key] = value
                    pending_split = info
                elif line.startswith("# BlockArrow"):
                    info = {}
                    for part in line.split()[2:]:
                        if "=" not in part:
                            continue
                        key, value = part.split("=", 1)
                        value = value.rstrip(",")
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        info[key] = value
                    pending_block = info
                elif line.startswith("# CurvyBracket"):
                    info = {}
                    for part in line.split()[2:]:
                        if "=" not in part:
                            continue
                        key, value = part.split("=", 1)
                        value = value.rstrip(",")
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        info[key] = value
                    pending_bracket = info
                elif line.startswith("# FolderTree"):
                    info: dict[str, Any] = {}
                    pos_match = re.search(r"pos=\(([-0-9.]+),\s*([-0-9.]+)\)", line)
                    if pos_match:
                        info["x"] = float(pos_match.group(1))
                        info["y"] = float(pos_match.group(2))
                    rot_match = re.search(r"rotation=([-0-9.]+)", line)
                    if rot_match:
                        info["rotation"] = float(rot_match.group(1))
                    size_match = re.search(r"size=\(([-0-9.]+),\s*([-0-9.]+)\)", line)
                    if size_match:
                        info["w"] = float(size_match.group(1))
                        info["h"] = float(size_match.group(2))
                    struct_index = line.find("structure=")
                    structure_data: Any = None
                    if struct_index != -1:
                        struct_text = line[struct_index + len("structure=") :].strip()
                        try:
                            structure_data = json.loads(struct_text)
                        except json.JSONDecodeError:
                            structure_data = None
                    info["structure"] = structure_data
                    x = float(info.get("x", 0.0))
                    y = float(info.get("y", 0.0))
                    w = float(info.get("w", DEFAULTS["Folder Tree"][0]))
                    h = float(info.get("h", DEFAULTS["Folder Tree"][1]))
                    structure = structure_data if isinstance(structure_data, Mapping) else None
                    item = FolderTreeItem(x, y, w, h, structure)
                    rotation = float(info.get("rotation", 0.0))
                    if rotation:
                        item.setRotation(rotation)
                    item.setData(0, "Folder Tree")
                    scene.addItem(item)
                elif line.startswith("# Arrowheads:") and pending_line is not None:
                    comment = line.split(":", 1)[1]
                    start_flag = False
                    end_flag = False
                    length_value: float | None = None
                    width_value: float | None = None
                    for part in comment.split(","):
                        if "=" not in part:
                            continue
                        key, value = part.split("=", 1)
                        key = key.strip().lower()
                        raw_value = value.strip()
                        lower_value = raw_value.lower()
                        if key == "start":
                            start_flag = lower_value in {"true", "1", "yes"}
                        elif key == "end":
                            end_flag = lower_value in {"true", "1", "yes"}
                        elif key == "length":
                            try:
                                length_value = float(raw_value)
                            except (TypeError, ValueError):
                                length_value = None
                        elif key == "width":
                            try:
                                width_value = float(raw_value)
                            except (TypeError, ValueError):
                                width_value = None
                    if start_flag:
                        pending_line.set_arrow_start(True)
                    if end_flag:
                        pending_line.set_arrow_end(True)
                    if length_value is not None:
                        setter = getattr(pending_line, "set_arrow_head_length", None)
                        if callable(setter):
                            setter(length_value)
                    if width_value is not None:
                        setter = getattr(pending_line, "set_arrow_head_width", None)
                        if callable(setter):
                            setter(width_value)
                    pending_line.setData(
                        0, "Arrow" if (start_flag or end_flag) else "Line"
                    )
                    pending_line = None
                continue

            if line.startswith("d = draw.Drawing("):
                args, kwargs = _parse_call(line)
                if len(args) >= 2:
                    ox = oy = 0.0
                    if "origin" in kwargs and isinstance(kwargs["origin"], (tuple, list)):
                        ox, oy = map(float, kwargs["origin"][:2])
                    scene.setSceneRect(float(ox), float(oy), float(args[0]), float(args[1]))

            elif line.startswith("_folder_tree"):
                continue

            elif line.startswith("_split_rect = draw.Rectangle("):
                args, kwargs = _parse_call(line)
                x, y, w, h = map(float, args[:4])
                rx = min(float(kwargs.get("rx", 0.0)), 50.0)
                ry = min(float(kwargs.get("ry", rx)), 50.0)
                if "rx" in kwargs and "ry" not in kwargs:
                    ry = rx
                if "ry" in kwargs and "rx" not in kwargs:
                    rx = ry
                item = SplitRoundedRectItem(x, y, w, h, rx, ry)
                _apply_style(item, kwargs)
                if pending_split is not None:
                    ratio_val = pending_split.get("ratio")
                    if ratio_val is not None:
                        try:
                            item.set_divider_ratio(float(ratio_val))
                        except (TypeError, ValueError):
                            pass
                    top_fill = pending_split.get("top_fill")
                    if top_fill == "none":
                        item.setTopBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
                    elif top_fill:
                        color = QtGui.QColor(str(top_fill))
                        opacity = pending_split.get("top_opacity")
                        if opacity is not None:
                            try:
                                color.setAlphaF(float(opacity))
                            except (TypeError, ValueError):
                                pass
                        item.setTopBrush(color)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Split Rounded Rectangle")
                scene.addItem(item)
                pending_split = None

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
                shape_name = "Rounded Rectangle" if (rx or ry) else "Rectangle"
                item.setData(0, shape_name)
                label_id = kwargs.get("data_label_id")
                if label_id:
                    key = str(label_id)
                    shape_label_targets[key] = item
                    pending = shape_label_pending.pop(key, None)
                    if pending:
                        _apply_shape_label(item, pending)
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
                label_id = kwargs.get("data_label_id")
                if label_id:
                    key = str(label_id)
                    shape_label_targets[key] = item
                    pending = shape_label_pending.pop(key, None)
                    if pending:
                        _apply_shape_label(item, pending)
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
                label_id = kwargs.get("data_label_id")
                if label_id:
                    key = str(label_id)
                    shape_label_targets[key] = item
                    pending = shape_label_pending.pop(key, None)
                    if pending:
                        _apply_shape_label(item, pending)
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

            elif line.startswith("_diamond = draw.Lines("):
                args, kwargs = _parse_call(line)
                coords = [float(a) for a in args]
                xs = coords[0::2]
                ys = coords[1::2]
                x = min(xs)
                y = min(ys)
                w = max(xs) - x
                h = max(ys) - y
                item = DiamondItem(x, y, w, h)
                _apply_style(item, kwargs)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Diamond")
                label_id = kwargs.get("data_label_id")
                if label_id:
                    key = str(label_id)
                    shape_label_targets[key] = item
                    pending = shape_label_pending.pop(key, None)
                    if pending:
                        _apply_shape_label(item, pending)
                scene.addItem(item)

            elif line.startswith("_block_arrow = draw.Lines("):
                args, kwargs = _parse_call(line)
                coords = [float(a) for a in args]
                xs = coords[0::2]
                ys = coords[1::2]
                x = min(xs)
                y = min(ys)
                w = max(xs) - x
                h = max(ys) - y
                item = BlockArrowItem(x, y, w, h)
                _apply_style(item, kwargs)
                if pending_block is not None:
                    head_ratio = pending_block.get("head_ratio")
                    shaft_ratio = pending_block.get("shaft_ratio")
                    if head_ratio is not None:
                        try:
                            item.set_head_ratio(float(head_ratio), update_handles=False)
                        except (TypeError, ValueError):
                            pass
                    if shaft_ratio is not None:
                        try:
                            item.set_shaft_ratio(float(shaft_ratio))
                        except (TypeError, ValueError):
                            item.update_handles()
                    else:
                        item.update_handles()
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Block Arrow")
                scene.addItem(item)
                pending_block = None

            elif line.startswith("_path = draw.Path("):
                args, kwargs = _parse_call(line)
                if pending_bracket is not None:
                    x = float(pending_bracket.get("x", 0.0))
                    y = float(pending_bracket.get("y", 0.0))
                    w = float(pending_bracket.get("w", DEFAULTS["Curvy Right Bracket"][0]))
                    h = float(pending_bracket.get("h", DEFAULTS["Curvy Right Bracket"][1]))
                    ratio = pending_bracket.get("hook_ratio")
                    hook_ratio = CurvyBracketItem.DEFAULT_HOOK_RATIO
                    if ratio is not None:
                        try:
                            hook_ratio = float(ratio)
                        except (TypeError, ValueError):
                            hook_ratio = CurvyBracketItem.DEFAULT_HOOK_RATIO
                    item = CurvyBracketItem(x, y, w, h, hook_ratio)
                    _apply_style(item, kwargs)
                    if "transform" in kwargs:
                        item.setRotation(_parse_rotate(kwargs["transform"]))
                    item.setData(0, "Curvy Right Bracket")
                    scene.addItem(item)
                    pending_bracket = None
                    continue
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
                            arrow_start_attr = kwargs.get("data_arrow_start")
                            arrow_end_attr = kwargs.get("data_arrow_end")
                            if arrow_start_attr is not None:
                                arrow_start = (
                                    arrow_start_attr
                                    if isinstance(arrow_start_attr, bool)
                                    else str(arrow_start_attr).strip().lower()
                                    in {"true", "1", "yes"}
                                )
                            if arrow_end_attr is not None:
                                arrow_end = (
                                    arrow_end_attr
                                    if isinstance(arrow_end_attr, bool)
                                    else str(arrow_end_attr).strip().lower()
                                    in {"true", "1", "yes"}
                                )
                            arrow_head_length = kwargs.get("data_arrow_head_length")
                            arrow_head_width = kwargs.get("data_arrow_head_width")
                            try:
                                arrow_head_length_value = (
                                    float(arrow_head_length)
                                    if arrow_head_length is not None
                                    else None
                                )
                            except (TypeError, ValueError):
                                arrow_head_length_value = None
                            try:
                                arrow_head_width_value = (
                                    float(arrow_head_width)
                                    if arrow_head_width is not None
                                    else None
                                )
                            except (TypeError, ValueError):
                                arrow_head_width_value = None
                            angle = 0.0
                            if "transform" in kwargs:
                                angle = _parse_rotate(kwargs["transform"])
                            item = LineItem(
                                0.0,
                                0.0,
                                points=pts,
                                arrow_start=arrow_start,
                                arrow_end=arrow_end,
                                arrow_head_length=arrow_head_length_value,
                                arrow_head_width=arrow_head_width_value,
                            )
                            _apply_style(item, kwargs)
                            item.setRotation(angle)
                            item.setData(0, "Arrow" if arrow_start or arrow_end else "Line")
                            scene.addItem(item)
                            pending_line = item
                        else:
                            pending_line = None

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
                pending_line = item

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
                pending_line = item

            # --- NEU: _label = draw.Text(...) mehrzeilig zusammenführen ---
            elif "_label = draw.Text(" in line:
                args, kwargs = _parse_call(line)
                text_arg = args[0]

                flag_value = kwargs.get("data_shape_label")
                if flag_value is None:
                    flag_value = kwargs.get("data_rect_label")

                if str(flag_value).lower() == "true":
                    label_id = kwargs.get("data_label_id")
                    key = str(label_id) if label_id is not None else None
                    if key:
                        data = shape_label_pending.setdefault(
                            key,
                            {
                                "lines": [],
                                "h": None,
                                "v": None,
                                "font_px": None,
                                "color": None,
                                "color_override": None,
                            },
                        )
                        if "data_label_h" in kwargs:
                            data["h"] = kwargs.get("data_label_h")
                        if "data_label_v" in kwargs:
                            data["v"] = kwargs.get("data_label_v")
                        if "data_font_px" in kwargs:
                            data["font_px"] = kwargs.get("data_font_px")
                        if "fill" in kwargs and kwargs["fill"] is not None:
                            data["color"] = kwargs.get("fill")
                        if "data_label_color_override" in kwargs:
                            data["color_override"] = kwargs.get("data_label_color_override")

                        def _normalize_entry(value: object) -> str:
                            if isinstance(value, str):
                                if value in {"\u00A0", "&#160;"}:
                                    return ""
                                return value
                            return str(value)

                        if isinstance(text_arg, (list, tuple)):
                            data["lines"] = [_normalize_entry(entry) for entry in text_arg]
                        else:
                            normalized = _normalize_entry(text_arg)
                            data.setdefault("lines", [])
                            data["lines"].append(normalized)

                        target = shape_label_targets.get(key)
                        if target is not None:
                            _apply_shape_label(target, data)
                    continue

            elif line.startswith("_text = draw.Text("):
                args, kwargs = _parse_call(line)
                raw_text_arg = args[0]
                if isinstance(raw_text_arg, (list, tuple)):
                    parts = []
                    for entry in raw_text_arg:
                        if isinstance(entry, str):
                            if entry in {"\u00A0", "&#160;"}:
                                parts.append("")
                            else:
                                parts.append(entry)
                        else:
                            parts.append(str(entry))
                    text = "\n".join(parts)
                else:
                    text = str(raw_text_arg)
                size = float(args[1])
                text_x = float(args[2])
                text_y = float(args[3])

                item = TextItem(0, 0, 0, 0)
                item.setPlainText(text)

                data_font_px = kwargs.get("data_font_px")
                data_scale = kwargs.get("data_scale")
                data_doc_margin = kwargs.get("data_doc_margin")
                data_box_w = kwargs.get("data_box_w")
                data_box_h = kwargs.get("data_box_h")
                data_text_h = kwargs.get("data_text_h")
                data_text_v = kwargs.get("data_text_v")
                data_text_dir = kwargs.get("data_text_dir")

                # Export speichert Schriftgröße (Pixel) und Item-Skalierung separat
                font = item.font()
                base_px = None
                if data_font_px is not None:
                    try:
                        base_px = float(data_font_px)
                    except (TypeError, ValueError):
                        base_px = None
                if base_px is None or base_px <= 0.0:
                    base_px = float(font.pixelSize())
                    if base_px <= 0.0:
                        point_size = font.pointSizeF()
                        if point_size > 0.0:
                            screen = QtGui.QGuiApplication.primaryScreen()
                            dpi = screen.logicalDotsPerInch() if screen else 96.0
                            base_px = point_size * dpi / 72.0
                    if base_px <= 0.0:
                        fm = QtGui.QFontMetricsF(font)
                        base_px = fm.height()
                if base_px <= 0.0:
                    base_px = size if size > 0.0 else 1.0
                font.setPixelSize(max(1, int(round(base_px))))
                item.setFont(font)
                _apply_style(item, kwargs)

                box_w = box_h = None
                if data_box_w is not None:
                    try:
                        box_w = float(data_box_w)
                    except (TypeError, ValueError):
                        box_w = None
                if data_box_h is not None:
                    try:
                        box_h = float(data_box_h)
                    except (TypeError, ValueError):
                        box_h = None
                if box_w is not None or box_h is not None:
                    current = item.boundingRect()
                    width = box_w if box_w is not None else current.width()
                    height = box_h if box_h is not None else current.height()
                    item.set_size(width, height, adjust_origin=False)

                if data_doc_margin is not None and item.document():
                    try:
                        base_doc_margin = float(data_doc_margin)
                    except (TypeError, ValueError):
                        base_doc_margin = item.document().documentMargin()
                    item.set_document_margin(base_doc_margin)

                doc_margin = item.document().documentMargin() if item.document() else 0.0

                if data_scale is not None:
                    try:
                        scale_factor = float(data_scale)
                    except (TypeError, ValueError):
                        scale_factor = size / base_px if base_px > 0.0 else 1.0
                else:
                    scale_factor = size / base_px if base_px > 0.0 else 1.0
                if not math.isfinite(scale_factor) or scale_factor <= 0.0:
                    scale_factor = 1.0
                item.setScale(scale_factor)

                if data_text_h is not None or data_text_v is not None:
                    try:
                        h_align = str(data_text_h) if data_text_h is not None else None
                        v_align = str(data_text_v) if data_text_v is not None else None
                        item.set_text_alignment(horizontal=h_align, vertical=v_align)
                    except Exception:
                        pass
                if data_text_dir is not None:
                    try:
                        item.set_text_direction(str(data_text_dir))
                    except Exception:
                        pass

                doc_margin_scene = doc_margin * scale_factor
                box_w_scene = (
                    float(box_w) * scale_factor
                    if box_w is not None
                    else item.boundingRect().width() * scale_factor
                )
                if data_text_h == "right":
                    x_pos = text_x - (box_w_scene - doc_margin_scene)
                elif data_text_h == "center":
                    x_pos = text_x - box_w_scene / 2.0
                else:
                    x_pos = text_x - doc_margin_scene
                y_pos = text_y - doc_margin_scene
                item.setPos(x_pos, y_pos)
                br = item.boundingRect()
                item.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
                if "transform" in kwargs:
                    item.setRotation(_parse_rotate(kwargs["transform"]))
                item.setData(0, "Text")
                scene.addItem(item)

        # --- NEU: am Ende verbleibende pending Labels anwenden ---
        for key, data in list(shape_label_pending.items()):
            target = shape_label_targets.get(key)
            if target is not None:
                _apply_shape_label(target, data)
                shape_label_pending.pop(key, None)

        if view is not None:
            ensure_pages = getattr(view, "ensure_pages_for_scene_items", None)
            if callable(ensure_pages):
                ensure_pages()

        if parent is not None:
            parent.statusBar().showMessage(f"Loaded: {path}", 5000)
    except Exception as e:
        QtWidgets.QMessageBox.critical(parent, "Error loading file", str(e))
