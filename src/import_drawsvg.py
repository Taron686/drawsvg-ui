# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

from __future__ import annotations

import ast
import base64
import html
from contextlib import nullcontext
from dataclasses import dataclass, field
import math
import json
import re
from xml.etree import ElementTree
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from items import (
    BlockArrowItem,
    CurvyBracketItem,
    DiamondItem,
    DiagramItem,
    EllipseItem,
    FolderTreeItem,
    LineItem,
    RectItem,
    ShapeLabelMixin,
    SplitRoundedRectItem,
    TextItem,
    TriangleItem,
)
from items.shapes.paths import FreePathItem

from shape_registry import SHAPE_REGISTRY
from asset_service import BitmapAssetService
from bitmap_item import BitmapItem
from connectors import ConnectorItem
from items.svg import SvgItem
from items.svg_assets import SvgAssetParser
from style_presets import apply_style_data

from constants import DEFAULTS, PEN_STYLE_DASH_ARRAYS


_ROT_RE = re.compile(r"rotate\(([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\)")
_MATRIX_RE = re.compile(r"matrix\(([^)]*)\)")
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
        elif (
            kw.arg in {"fill", "stroke"}
            and isinstance(v, ast.Call)
            and isinstance(v.func, ast.Name)
            and v.func.id == "_drawsvg_gradient"
            and len(v.args) == 4
            and not v.keywords
        ):
            # Only accept the exporter's literal gradient descriptor.  Never
            # evaluate code; data_qt_brush below restores the editor brush.
            for argument in v.args:
                ast.literal_eval(argument)
            kwargs[kw.arg] = "none"
        else:
            kwargs[kw.arg] = ast.literal_eval(v)
    if kwargs.get("data_xml_escaped") == "true":
        kwargs = {
            key: html.unescape(value) if isinstance(value, str) else value
            for key, value in kwargs.items()
        }
    return args, kwargs


def _apply_pen_details(
    pen: QtGui.QPen, kwargs: Mapping[str, Any]
) -> QtCore.Qt.PenStyle | None:
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
        if kwargs.get("data_pen_units") == "svg":
            unit = pen.widthF() if pen.widthF() > 0 else 1.0
            dash_pattern = [value / unit for value in dash_pattern]
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
    if "stroke_dashoffset" in kwargs:
        unit = (
            pen.widthF()
            if kwargs.get("data_pen_units") == "svg" and pen.widthF() > 0
            else 1.0
        )
        pen.setDashOffset(float(kwargs["stroke_dashoffset"]) / unit)
    if "data_qt_pen_style" in kwargs:
        pen.setStyle(QtCore.Qt.PenStyle(int(kwargs["data_qt_pen_style"])))
        if pen.style() == QtCore.Qt.PenStyle.CustomDashLine and dash_pattern:
            pen.setDashPattern(dash_pattern)
    if kwargs.get("stroke") == "none" and "data_qt_pen_brush" not in kwargs:
        pen.setStyle(QtCore.Qt.PenStyle.NoPen)
    return style_to_apply


def _prepare_pen(
    item: QtWidgets.QAbstractGraphicsShapeItem, kwargs: Mapping[str, Any]
) -> QtGui.QPen:
    pen = item.pen()
    if "stroke" in kwargs:
        pen.setColor(QtGui.QColor(kwargs["stroke"]))
        if "stroke_opacity" in kwargs:
            color = pen.color()
            color.setAlphaF(float(kwargs["stroke_opacity"]))
            pen.setColor(color)
    if "stroke_width" in kwargs:
        pen.setWidthF(float(kwargs["stroke_width"]))
    if "data_qt_pen_width" in kwargs:
        width = kwargs["data_qt_pen_width"]
        if (
            isinstance(width, bool)
            or not isinstance(width, (int, float))
            or not math.isfinite(width)
            or width < 0
        ):
            raise ValueError("Exported pen width must be a finite nonnegative number")
        pen.setWidthF(width)
    if kwargs.get("vector_effect") == "non-scaling-stroke":
        pen.setCosmetic(True)
    if kwargs.get("stroke") == "none" and "data_qt_pen_brush" not in kwargs:
        pen.setStyle(QtCore.Qt.PenStyle.NoPen)
    cap = {
        "butt": QtCore.Qt.PenCapStyle.FlatCap,
        "round": QtCore.Qt.PenCapStyle.RoundCap,
        "square": QtCore.Qt.PenCapStyle.SquareCap,
    }.get(kwargs.get("stroke_linecap"))
    join = {
        "miter": QtCore.Qt.PenJoinStyle.MiterJoin,
        "round": QtCore.Qt.PenJoinStyle.RoundJoin,
        "bevel": QtCore.Qt.PenJoinStyle.BevelJoin,
    }.get(kwargs.get("stroke_linejoin"))
    if cap is not None:
        pen.setCapStyle(cap)
    if join is not None:
        pen.setJoinStyle(join)
    return pen


def _apply_style(item: QtWidgets.QGraphicsItem, kwargs: dict[str, Any]) -> None:
    if isinstance(
        item,
        (
            QtWidgets.QGraphicsRectItem,
            QtWidgets.QGraphicsEllipseItem,
            LineItem,
            FreePathItem,
            TriangleItem,
            DiamondItem,
            BlockArrowItem,
            CurvyBracketItem,
            DiagramItem,
            ConnectorItem,
        ),
    ):
        if kwargs.get("fill") == "none":
            item.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        elif "fill" in kwargs:
            color = QtGui.QColor(kwargs["fill"])
            if "fill_opacity" in kwargs:
                color.setAlphaF(float(kwargs["fill_opacity"]))
            item.setBrush(color)
        pen = _prepare_pen(item, kwargs)
        style_to_apply = _apply_pen_details(pen, kwargs)
        item.setPen(pen)
        if (
            isinstance(item, LineItem)
            and style_to_apply is not None
            and "data_qt_pen_style" not in kwargs
        ):
            item.set_pen_style(style_to_apply)
    elif isinstance(item, TextItem):
        if "fill" in kwargs:
            color = QtGui.QColor(kwargs["fill"])
            if "fill_opacity" in kwargs:
                color.setAlphaF(float(kwargs["fill_opacity"]))
            item.setDefaultTextColor(color)
        font = item.font()
        if "font_family" in kwargs:
            font.setFamily(str(kwargs["font_family"]))
        _apply_text_font_style(font, kwargs)
        item.setFont(font)
    _apply_exported_item_style(item, kwargs)


def _apply_exported_item_style(
    item: QtWidgets.QGraphicsItem, kwargs: dict[str, Any]
) -> None:
    brush_value = kwargs.get("data_qt_brush")
    if brush_value is not None and hasattr(item, "setBrush"):
        item.setBrush(_brush_from_exported_data(json.loads(str(brush_value))))
    pen_brush_value = kwargs.get("data_qt_pen_brush")
    if pen_brush_value is not None and hasattr(item, "setPen"):
        pen = item.pen()
        pen.setBrush(_brush_from_exported_data(json.loads(str(pen_brush_value))))
        item.setPen(pen)
    style_value = kwargs.get("data_item_style")
    if style_value is not None:
        data = json.loads(str(style_value))
        if not isinstance(data, dict):
            raise ValueError("Exported item style must be an object")
        if "opacity" in data:
            opacity = data["opacity"]
            if (
                isinstance(opacity, bool)
                or not isinstance(opacity, (int, float))
                or not math.isfinite(opacity)
                or not 0 <= opacity <= 1
            ):
                raise ValueError(
                    "Exported opacity must be a finite number between zero and one"
                )
        shadow = data.get("shadow")
        if shadow is not None:
            if not isinstance(shadow, dict):
                raise ValueError("Exported shadow must be an object")
            for name in ("offset_x", "offset_y", "blur_radius"):
                value = shadow.get(name, 0.0)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError("Exported shadow values must be finite numbers")
            if (
                shadow.get("blur_radius", 0.0) < 0
                or not QtGui.QColor(str(shadow.get("color", "#00000000"))).isValid()
            ):
                raise ValueError("Exported shadow has invalid blur or color")
        apply_style_data(item, data)
        if "opacity" in data:
            item.setOpacity(float(data["opacity"]))
    elif "opacity" in kwargs:
        item.setOpacity(float(kwargs["opacity"]))


def _brush_from_exported_data(data: dict[str, Any]) -> QtGui.QBrush:
    if data["kind"] == "solid":
        brush = QtGui.QBrush(QtCore.Qt.BrushStyle(int(data["style"])))
        color = QtGui.QColor(data["color"])
        color.setAlphaF(float(data["alpha"]))
        brush.setColor(color)
        return brush
    coords = [float(value) for value in data["coords"]]
    if data["kind"] == "linear" and len(coords) == 4:
        gradient = QtGui.QLinearGradient(*coords)
    elif data["kind"] == "radial" and len(coords) == 6:
        gradient = QtGui.QRadialGradient(*coords)
    else:
        raise ValueError("Unsupported exported gradient")
    gradient.setCoordinateMode(
        QtGui.QGradient.CoordinateMode(int(data["coordinate_mode"]))
    )
    gradient.setSpread(QtGui.QGradient.Spread(int(data["spread"])))
    for position, color_name, alpha in data["stops"]:
        color = QtGui.QColor(color_name)
        color.setAlphaF(float(alpha))
        gradient.setColorAt(float(position), color)
    brush = QtGui.QBrush(gradient)
    brush.setTransform(QtGui.QTransform(*[float(value) for value in data["transform"]]))
    return brush


def _restore_exported_split(item: SplitRoundedRectItem, value: str) -> None:
    data = json.loads(value)
    item.setTopBrush(_brush_from_exported_data(data["top"]))
    item.setBottomBrush(_brush_from_exported_data(data["bottom"]))
    divider = data["divider_pen"]
    color = QtGui.QColor(divider["color"])
    color.setAlphaF(float(divider["alpha"]))
    pen = QtGui.QPen(color)
    pen.setWidthF(float(divider["width"]))
    pen.setCosmetic(bool(divider["cosmetic"]))
    pen.setCapStyle(QtCore.Qt.PenCapStyle(int(divider["cap"])))
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle(int(divider["join"])))
    pen.setMiterLimit(float(divider["miter"]))
    style = QtCore.Qt.PenStyle(int(divider["style"]))
    if style == QtCore.Qt.PenStyle.CustomDashLine and divider["dash"]:
        pen.setDashPattern([float(value) for value in divider["dash"]])
        pen.setDashOffset(float(divider["offset"]))
    else:
        pen.setStyle(style)
    item.set_divider_pen(pen)


def _apply_text_font_style(font: QtGui.QFont, kwargs: dict[str, Any]) -> None:
    if "font_weight" in kwargs:
        font.setBold(kwargs["font_weight"] == "bold")
    if "font_style" in kwargs:
        font.setItalic(kwargs["font_style"] == "italic")
    if "text_decoration" in kwargs:
        font.setUnderline("underline" in str(kwargs["text_decoration"]))


def _parse_rotate(val: str) -> float:
    m = _ROT_RE.match(val)
    if m:
        return float(m.group(1))
    return 0.0


def _apply_transform(item: QtWidgets.QGraphicsItem, value: str) -> None:
    """Apply a drawsvg rotate or affine matrix transform to a graphics item."""
    matrix_match = _MATRIX_RE.fullmatch(str(value).strip())
    if matrix_match is not None:
        parts = matrix_match.group(1).replace(",", " ").split()
        if len(parts) != 6:
            raise ValueError(f"Invalid matrix transform: {value}")
        m11, m12, m21, m22, dx, dy = map(float, parts)
        transform = QtGui.QTransform(m11, m12, m21, m22, dx, dy)
        local_offset = item.pos()
        scale_x = math.hypot(m11, m12)
        scale_y = math.hypot(m21, m22)
        determinant = m11 * m22 - m12 * m21
        if (
            scale_x > 0.0
            and determinant > 0.0
            and math.isclose(scale_x, scale_y, rel_tol=1e-6, abs_tol=1e-6)
        ):
            origin = item.transformOriginPoint()
            item.setPos(transform.map(origin + local_offset) - origin)
            item.setRotation(math.degrees(math.atan2(m12, m11)))
            item.setScale(scale_x)
        else:
            offset_dx = dx + m11 * local_offset.x() + m21 * local_offset.y()
            offset_dy = dy + m12 * local_offset.x() + m22 * local_offset.y()
            item.setPos(0.0, 0.0)
            item.setRotation(0.0)
            item.setScale(1.0)
            item.setTransform(
                QtGui.QTransform(m11, m12, m21, m22, offset_dx, offset_dy)
            )
        return
    item.setRotation(_parse_rotate(str(value)))


@dataclass
class _ParserState:
    parsed_scene: QtWidgets.QGraphicsScene
    recognized_drawing: bool = False
    pending_split: dict[str, Any] | None = None
    pending_block: dict[str, Any] | None = None
    pending_bracket: dict[str, Any] | None = None
    pending_line: LineItem | None = None
    pending_folder_tree: FolderTreeItem | None = None
    shape_label_targets: dict[str, ShapeLabelMixin] = field(default_factory=dict)
    shape_label_pending: dict[str, dict[str, Any]] = field(default_factory=dict)


def _apply_shape_label(target: ShapeLabelMixin, data: dict[str, Any]) -> None:
    """
    Wendet gesammelte Label-Daten auf ein Shape an.
    Unterstützt sowohl 'text' (alt) als auch 'lines' (neu, mehrere Zeilen).
    NBSP (U+00A0) wird als leere Zeile interpretiert.
    """
    if "raw_label" in data:
        text_value = str(data["raw_label"])
    elif "lines" in data and isinstance(data["lines"], list):
        norm = ["" if s == "\xa0" or s == "&#160;" else str(s) for s in data["lines"]]
        text_value = "\n".join(norm)
    else:
        text_value = str(data.get("text", ""))
    label_font = target.label_item().font()
    if "font_family" in data:
        label_font.setFamily(str(data["font_family"]))
    _apply_text_font_style(label_font, data)
    target.label_item().setFont(label_font)
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
    target.set_label_text(text_value)
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


def _handle_split_comment(state: _ParserState, line: str) -> None:
    info: dict[str, Any] = {}
    for part in line.split()[2:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        value = value.rstrip(",")
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        info[key] = value
    state.pending_split = info


def _handle_block_comment(state: _ParserState, line: str) -> None:
    info = {}
    for part in line.split()[2:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        value = value.rstrip(",")
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        info[key] = value
    state.pending_block = info


def _handle_bracket_comment(state: _ParserState, line: str) -> None:
    info = {}
    for part in line.split()[2:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        value = value.rstrip(",")
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        info[key] = value
    state.pending_bracket = info


def _handle_folder_comment(state: _ParserState, line: str) -> None:
    info: dict[str, Any] = {}
    pos_match = re.search("pos=\\(([-0-9.]+),\\s*([-0-9.]+)\\)", line)
    if pos_match:
        info["x"] = float(pos_match.group(1))
        info["y"] = float(pos_match.group(2))
    rot_match = re.search("rotation=([-0-9.]+)", line)
    if rot_match:
        info["rotation"] = float(rot_match.group(1))
    scale_match = re.search("scale=([-0-9.]+)", line)
    if scale_match:
        info["scale"] = float(scale_match.group(1))
    size_match = re.search("size=\\(([-0-9.]+),\\s*([-0-9.]+)\\)", line)
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
    item.setScale(float(info.get("scale", 1.0)))
    item.setData(0, "Folder Tree")
    state.parsed_scene.addItem(item)
    state.pending_folder_tree = item


def _parse_arrow_comment(line: str) -> tuple[bool, bool, float | None, float | None]:
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
    return start_flag, end_flag, length_value, width_value


def _handle_arrow_comment(state: _ParserState, line: str) -> None:
    if not isinstance(state.pending_line, LineItem):
        return
    start_flag, end_flag, length_value, width_value = _parse_arrow_comment(line)
    if start_flag:
        state.pending_line.set_arrow_start(True)
    if end_flag:
        state.pending_line.set_arrow_end(True)
    if length_value is not None:
        state.pending_line.set_arrow_head_length(length_value)
    if width_value is not None:
        state.pending_line.set_arrow_head_width(width_value)
    state.pending_line.setData(0, "Arrow" if start_flag or end_flag else "Line")
    state.pending_line = None


def _handle_drawing(state: _ParserState, line: str) -> None:
    state.recognized_drawing = True
    args, kwargs = _parse_call(line)
    if len(args) >= 2:
        ox = oy = 0.0
        if "origin" in kwargs and isinstance(kwargs["origin"], (tuple, list)):
            ox, oy = map(float, kwargs["origin"][:2])
        state.parsed_scene.setSceneRect(
            float(ox), float(oy), float(args[0]), float(args[1])
        )


def _handle_folder_group(state: _ParserState, line: str) -> None:
    _args, kwargs = _parse_call(line)
    if state.pending_folder_tree is not None and "transform" in kwargs:
        state.pending_folder_tree.setPos(0.0, 0.0)
        state.pending_folder_tree.setRotation(0.0)
        state.pending_folder_tree.setScale(1.0)
        _apply_transform(state.pending_folder_tree, kwargs["transform"])
        _apply_exported_item_style(state.pending_folder_tree, kwargs)
    state.pending_folder_tree = None
    return


def _handle_folder_content(state: _ParserState, line: str) -> None:
    return


def _handle_bitmap(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    uri = str(kwargs.get("path", ""))
    match = re.fullmatch("data:(image/(?:png|jpeg|webp));base64,(.*)", uri)
    if match is None:
        raise ValueError("Bitmap export must contain an embedded image")
    data = base64.b64decode(match.group(2), validate=True)
    asset = BitmapAssetService().import_bytes(data, media_type=match.group(1)).asset
    item = BitmapItem(asset, width=float(args[2]), height=float(args[3]))
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    _apply_exported_item_style(item, kwargs)
    state.parsed_scene.addItem(item)


def _handle_svg(state: _ParserState, line: str) -> None:
    args, _kwargs = _parse_call(line)
    wrapper = ElementTree.fromstring(str(args[0]))
    if wrapper.tag not in {"g", "{http://www.w3.org/2000/svg}g"}:
        raise ValueError("SVG asset export must contain a group")
    data = base64.b64decode(wrapper.attrib["data-asset-svg"], validate=True)
    asset = SvgAssetParser().parse(data)
    item = SvgItem(
        asset,
        width=float(wrapper.attrib["data-asset-width"]),
        height=float(wrapper.attrib["data-asset-height"]),
    )
    if "transform" in wrapper.attrib:
        _apply_transform(item, wrapper.attrib["transform"])
    _apply_exported_item_style(
        item, {key.replace("-", "_"): value for key, value in wrapper.attrib.items()}
    )
    state.parsed_scene.addItem(item)


def _handle_connector(state: _ParserState, line: str) -> None:
    _args, kwargs = _parse_call(line)
    payload = json.loads(str(kwargs["data_connector"]))
    item = ConnectorItem.from_data(payload)
    points = [QtCore.QPointF(float(x), float(y)) for x, y in payload["route_points"]]
    if len(points) < 2 or any(
        not math.isfinite(value) for point in points for value in (point.x(), point.y())
    ):
        raise ValueError("Connector route must contain finite points")
    item.set_route_points(points)
    _apply_style(item, kwargs)
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    state.parsed_scene.addItem(item)


def _handle_split_rect(state: _ParserState, line: str) -> None:
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
    if state.pending_split is not None:
        ratio_val = state.pending_split.get("ratio")
        if ratio_val is not None:
            try:
                item.set_divider_ratio(float(ratio_val))
            except (TypeError, ValueError):
                pass
        top_fill = state.pending_split.get("top_fill")
        if top_fill == "none":
            item.setTopBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
        elif top_fill:
            color = QtGui.QColor(str(top_fill))
            opacity = state.pending_split.get("top_opacity")
            if opacity is not None:
                try:
                    color.setAlphaF(float(opacity))
                except (TypeError, ValueError):
                    pass
            item.setTopBrush(color)
    if "data_qt_split" in kwargs:
        _restore_exported_split(item, str(kwargs["data_qt_split"]))
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Split Rounded Rectangle")
    state.parsed_scene.addItem(item)
    state.pending_split = None


def _handle_rect(state: _ParserState, line: str) -> None:
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
        _apply_transform(item, kwargs["transform"])
    shape_name = "Rounded Rectangle" if rx or ry else "Rectangle"
    item.setData(0, shape_name)
    label_id = kwargs.get("data_label_id")
    if label_id:
        key = str(label_id)
        state.shape_label_targets[key] = item
        pending = state.shape_label_pending.pop(key, None)
        if pending:
            _apply_shape_label(item, pending)
    state.parsed_scene.addItem(item)


def _handle_ellipse(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    cx, cy, rx, ry = map(float, args[:4])
    x = cx - rx
    y = cy - ry
    w = 2 * rx
    h = 2 * ry
    item = EllipseItem(x, y, w, h)
    _apply_style(item, kwargs)
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Ellipse")
    label_id = kwargs.get("data_label_id")
    if label_id:
        key = str(label_id)
        state.shape_label_targets[key] = item
        pending = state.shape_label_pending.pop(key, None)
        if pending:
            _apply_shape_label(item, pending)
    state.parsed_scene.addItem(item)


def _handle_circle(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    cx, cy, r = map(float, args[:3])
    x = cx - r
    y = cy - r
    w = h = 2 * r
    item = EllipseItem(x, y, w, h)
    _apply_style(item, kwargs)
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Circle")
    label_id = kwargs.get("data_label_id")
    if label_id:
        key = str(label_id)
        state.shape_label_targets[key] = item
        pending = state.shape_label_pending.pop(key, None)
        if pending:
            _apply_shape_label(item, pending)
    state.parsed_scene.addItem(item)


def _handle_triangle(state: _ParserState, line: str) -> None:
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
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Triangle")
    state.parsed_scene.addItem(item)


def _handle_diamond(state: _ParserState, line: str) -> None:
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
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Diamond")
    label_id = kwargs.get("data_label_id")
    if label_id:
        key = str(label_id)
        state.shape_label_targets[key] = item
        pending = state.shape_label_pending.pop(key, None)
        if pending:
            _apply_shape_label(item, pending)
    state.parsed_scene.addItem(item)


def _handle_block_arrow(state: _ParserState, line: str) -> None:
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
    if state.pending_block is not None:
        head_ratio = state.pending_block.get("head_ratio")
        shaft_ratio = state.pending_block.get("shaft_ratio")
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
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Block Arrow")
    state.parsed_scene.addItem(item)
    state.pending_block = None


def _handle_diagram_path(
    state: _ParserState, kwargs: dict[str, Any], diagram_raw: Any
) -> None:
    if diagram_raw is not None:
        try:
            payload = json.loads(str(diagram_raw))
            if not isinstance(payload, Mapping):
                raise ValueError("Diagram payload must be an object")
            type_id = payload.get("type_id")
            if not isinstance(type_id, str):
                raise ValueError("Diagram payload has no type ID")
            definition = SHAPE_REGISTRY.get(type_id)
            if definition is None or definition.python_export_adapter != "diagram":
                raise ValueError("Unsupported diagram type")
            item = SHAPE_REGISTRY.create(type_id, 0.0, 0.0)
            if not isinstance(item, DiagramItem):
                raise ValueError("Diagram registry entry is invalid")
            size = payload.get("size")
            if isinstance(size, (list, tuple)) and len(size) == 2:
                item.set_size(float(size[0]), float(size[1]))
            parameters = payload.get("parameters")
            if isinstance(parameters, Mapping):
                item.apply_parameters(dict(parameters))
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        _apply_style(item, kwargs)
        if "transform" in kwargs:
            _apply_transform(item, kwargs["transform"])
        label_id = kwargs.get("data_label_id")
        if label_id:
            key = str(label_id)
            state.shape_label_targets[key] = item
            pending = state.shape_label_pending.pop(key, None)
            if pending:
                _apply_shape_label(item, pending)
        state.parsed_scene.addItem(item)
        return


def _handle_free_path(
    state: _ParserState, kwargs: dict[str, Any], free_path_raw: Any
) -> None:
    if free_path_raw is not None:
        try:
            payload = json.loads(str(free_path_raw))
            if not isinstance(payload, Mapping):
                raise ValueError("Free path payload must be an object")
            start = payload.get("start")
            segments = payload.get("segments")
            if not isinstance(start, (list, tuple)) or not isinstance(segments, list):
                raise ValueError("Free path payload is incomplete")
            path_type = str(kwargs.get("data_free_path_type", "Free Polyline"))
            if path_type not in {"Free Polyline", "Free Polygon", "Bezier Path"}:
                raise ValueError("Unsupported free path type")
            item = FreePathItem(
                0.0,
                0.0,
                closed=bool(payload.get("closed", path_type == "Free Polygon")),
                start=start,
                segments=segments,
                path_kind={
                    "Free Polyline": "polyline",
                    "Free Polygon": "polygon",
                    "Bezier Path": "bezier",
                }[path_type],
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        _apply_style(item, kwargs)
        if "transform" in kwargs:
            _apply_transform(item, kwargs["transform"])
        item.setData(0, path_type)
        state.parsed_scene.addItem(item)
        return


def _handle_bracket_path(state: _ParserState, kwargs: dict[str, Any]) -> None:
    x = float(state.pending_bracket.get("x", 0.0))
    y = float(state.pending_bracket.get("y", 0.0))
    w = float(state.pending_bracket.get("w", DEFAULTS["Curvy Right Bracket"][0]))
    h = float(state.pending_bracket.get("h", DEFAULTS["Curvy Right Bracket"][1]))
    ratio = state.pending_bracket.get("hook_ratio")
    hook_ratio = CurvyBracketItem.DEFAULT_HOOK_RATIO
    if ratio is not None:
        try:
            hook_ratio = float(ratio)
        except (TypeError, ValueError):
            hook_ratio = CurvyBracketItem.DEFAULT_HOOK_RATIO
    item = CurvyBracketItem(x, y, w, h, hook_ratio)
    _apply_style(item, kwargs)
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    bracket_type = (
        "Curvy Left Bracket"
        if state.pending_bracket.get("side") == "left"
        else "Curvy Right Bracket"
    )
    item.setData(0, bracket_type)
    state.parsed_scene.addItem(item)
    state.pending_bracket = None
    return


def _handle_path(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    diagram_raw = kwargs.get("data_diagram")
    if diagram_raw is not None:
        _handle_diagram_path(state, kwargs, diagram_raw)
        return
    free_path_raw = kwargs.get("data_free_path")
    if free_path_raw is not None:
        _handle_free_path(state, kwargs, free_path_raw)
        return
    if state.pending_bracket is not None:
        _handle_bracket_path(state, kwargs)
        return
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
                        else str(arrow_end_attr).strip().lower() in {"true", "1", "yes"}
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
                if "transform" in kwargs:
                    _apply_transform(item, kwargs["transform"])
                item.setData(0, "Arrow" if arrow_start or arrow_end else "Line")
                state.parsed_scene.addItem(item)
                state.pending_line = item
            else:
                state.pending_line = None


def _handle_polyline(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    coords = list(map(float, args))
    pts = [QtCore.QPointF(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)]
    item = LineItem(0.0, 0.0, points=pts)
    _apply_style(item, kwargs)
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Line")
    state.parsed_scene.addItem(item)
    state.pending_line = item


def _handle_line(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    x1, y1, x2, y2 = map(float, args[:4])
    item = LineItem(0.0, 0.0, points=[QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2)])
    _apply_style(item, kwargs)
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Line")
    state.parsed_scene.addItem(item)
    state.pending_line = item


def _normalize_entry(value: object) -> str:
    if isinstance(value, str):
        if value in {"\xa0", "&#160;"}:
            return ""
        return value
    return str(value)


def _update_label_metadata(data: dict[str, Any], kwargs: Mapping[str, Any]) -> None:
    if "data_label_h" in kwargs:
        data["h"] = kwargs.get("data_label_h")
    if "data_raw_label" in kwargs:
        data["raw_label"] = kwargs["data_raw_label"]
    for font_key in ("font_family", "font_weight", "font_style", "text_decoration"):
        if font_key in kwargs:
            data[font_key] = kwargs[font_key]
    if "data_label_v" in kwargs:
        data["v"] = kwargs.get("data_label_v")
    if "data_font_px" in kwargs:
        data["font_px"] = kwargs.get("data_font_px")
    if "fill" in kwargs and kwargs["fill"] is not None:
        data["color"] = kwargs.get("fill")
    if "data_label_color_override" in kwargs:
        data["color_override"] = kwargs.get("data_label_color_override")


def _handle_label(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    text_arg = args[0]
    flag_value = kwargs.get("data_shape_label")
    if flag_value is None:
        flag_value = kwargs.get("data_rect_label")
    if str(flag_value).lower() == "true":
        label_id = kwargs.get("data_label_id")
        key = str(label_id) if label_id is not None else None
        if key:
            data = state.shape_label_pending.setdefault(
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
            _update_label_metadata(data, kwargs)
            if isinstance(text_arg, (list, tuple)):
                data["lines"] = [_normalize_entry(entry) for entry in text_arg]
            else:
                normalized = _normalize_entry(text_arg)
                data.setdefault("lines", [])
                data["lines"].append(normalized)
            target = state.shape_label_targets.get(key)
            if target is not None:
                _apply_shape_label(target, data)
        return


def _prepare_text_font(
    item: TextItem, kwargs: dict[str, Any], data_font_px: Any, size: float
) -> float:
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
    return base_px


def _prepare_text_box(
    item: TextItem, data_box_w: Any, data_box_h: Any, data_doc_margin: Any
) -> None:
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


def _handle_text(state: _ParserState, line: str) -> None:
    args, kwargs = _parse_call(line)
    raw_text_arg = args[0]
    if isinstance(raw_text_arg, (list, tuple)):
        parts = []
        for entry in raw_text_arg:
            if isinstance(entry, str):
                if entry in {"\xa0", "&#160;"}:
                    parts.append("")
                else:
                    parts.append(entry)
            else:
                parts.append(str(entry))
        text = "\n".join(parts)
    else:
        text = str(raw_text_arg)
    if "data_raw_text" in kwargs:
        text = str(kwargs["data_raw_text"])
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
    base_px = _prepare_text_font(item, kwargs, data_font_px, size)
    _prepare_text_box(item, data_box_w, data_box_h, data_doc_margin)
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
    if kwargs.get("data_auto_size") is True:
        item.fit_to_text()
    doc_margin_scene = doc_margin * scale_factor
    x_pos = text_x - doc_margin_scene
    # Preserve the anchors used by older public Python exports.
    anchor = kwargs.get("text_anchor", "start")
    box_width = item.boundingRect().width() * scale_factor
    if anchor == "end":
        x_pos = text_x - (box_width - doc_margin_scene)
    elif anchor == "middle":
        x_pos = text_x - box_width / 2.0
    y_pos = text_y - doc_margin_scene
    item.setPos(x_pos, y_pos)
    br = item.boundingRect()
    item.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
    if "transform" in kwargs:
        _apply_transform(item, kwargs["transform"])
    item.setData(0, "Text")
    state.parsed_scene.addItem(item)


_COMMENT_HANDLERS = (
    ("# SplitRoundedRect", _handle_split_comment),
    ("# BlockArrow", _handle_block_comment),
    ("# CurvyBracket", _handle_bracket_comment),
    ("# FolderTree", _handle_folder_comment),
    ("# Arrowheads:", _handle_arrow_comment),
)

_STATEMENT_HANDLERS = (
    ("d = draw.Drawing(", _handle_drawing, False),
    ("_folder_tree = draw.Group(", _handle_folder_group, False),
    ("_folder_tree", _handle_folder_content, False),
    ("_bitmap = draw.Image(", _handle_bitmap, False),
    ("_svg = draw.Raw(", _handle_svg, False),
    ("_connector = draw.Path(", _handle_connector, False),
    ("_split_rect = draw.Rectangle(", _handle_split_rect, False),
    ("_rect = draw.Rectangle(", _handle_rect, False),
    ("_ell = draw.Ellipse(", _handle_ellipse, False),
    ("_circ = draw.Circle(", _handle_circle, False),
    ("_tri = draw.Lines(", _handle_triangle, False),
    ("_diamond = draw.Lines(", _handle_diamond, False),
    ("_block_arrow = draw.Lines(", _handle_block_arrow, False),
    (("_path = draw.Path(", "_diagram = draw.Path("), _handle_path, False),
    ("_line = draw.Lines(", _handle_polyline, False),
    ("_line = draw.Line(", _handle_line, False),
    ("_label = draw.Text(", _handle_label, True),
    ("_text = draw.Text(", _handle_text, False),
)


def _parse_line(state: _ParserState, line: str) -> None:
    if not line:
        state.pending_split = state.pending_block = state.pending_bracket = None
        state.pending_line = state.pending_folder_tree = None
        return
    if line.startswith("#"):
        for prefix, handler in _COMMENT_HANDLERS:
            if line.startswith(prefix):
                handler(state, line)
                break
        return
    for prefix, handler, contains in _STATEMENT_HANDLERS:
        if (prefix in line) if contains else line.startswith(prefix):
            handler(state, line)
            return


def _replace_imported_scene(
    state: _ParserState,
    target_scene: QtWidgets.QGraphicsScene,
    view: QtWidgets.QGraphicsView | None,
) -> None:
    parsed_scene_rect = state.parsed_scene.sceneRect()
    parsed_items = [
        item
        for item in reversed(state.parsed_scene.items())
        if item.parentItem() is None
    ]
    clear_method = getattr(view, "clear_canvas", None) if view is not None else None
    transaction_context = nullcontext()
    history_getter = getattr(view, "history", None) if view is not None else None
    if callable(history_getter):
        transaction = getattr(history_getter(), "transaction", None)
        if callable(transaction):
            transaction_context = transaction()
    with transaction_context:
        if callable(clear_method):
            clear_method()
        else:
            target_scene.clear()
        target_scene.setSceneRect(parsed_scene_rect)
        for item in parsed_items:
            state.parsed_scene.removeItem(item)
            target_scene.addItem(item)

        if view is not None:
            layer_manager_getter = getattr(view, "layer_manager", None)
            if callable(layer_manager_getter):
                sync_items = getattr(layer_manager_getter(), "sync_items", None)
                if callable(sync_items):
                    sync_items()
            ensure_pages = getattr(view, "ensure_pages_for_scene_items", None)
            if callable(ensure_pages):
                ensure_pages()


def import_drawsvg_py(
    scene: QtWidgets.QGraphicsScene,
    parent: QtWidgets.QWidget | None = None,
    path: str | Path | None = None,
) -> Path | None:
    if path is None:
        selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            parent, "Load drawsvg-.py…", "", "Python (*.py)"
        )
        if not selected_path:
            return None
        path = selected_path
    path = Path(path).expanduser().resolve()
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        target_scene = scene
        view = target_scene.parent()
        state = _ParserState(QtWidgets.QGraphicsScene())
        for raw in lines:
            _parse_line(state, raw.strip())

        # --- NEU: am Ende verbleibende pending Labels anwenden ---
        for key, data in list(state.shape_label_pending.items()):
            target = state.shape_label_targets.get(key)
            if target is not None:
                _apply_shape_label(target, data)
                state.shape_label_pending.pop(key, None)

        if not state.recognized_drawing:
            raise ValueError("The selected file does not contain a drawsvg drawing.")

        _replace_imported_scene(state, target_scene, view)
        return path
    except Exception as e:
        QtWidgets.QMessageBox.critical(parent, "Error loading file", str(e))
        return None
