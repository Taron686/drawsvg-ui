"""Registry contracts for the built-in canvas shapes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from constants import DEFAULTS, SHAPES
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
from items.shapes.paths import BezierPathItem, FreePathItem
from style_presets import apply_style_data, style_data

ShapeFactory = Callable[[float, float, float, float], QtWidgets.QGraphicsItem]
ShapeSerializer = Callable[[QtWidgets.QGraphicsItem], dict[str, Any]]
ShapeRestorer = Callable[[Mapping[str, Any]], QtWidgets.QGraphicsItem]


def _enum_to_int(value: Any) -> int:
    return int(value.value) if hasattr(value, "value") else int(value)


def _color_to_data(color: QtGui.QColor) -> dict[str, float | str]:
    return {"name": color.name(), "alpha": float(color.alphaF())}


def _color_from_data(data: Mapping[str, Any] | None) -> QtGui.QColor:
    name = str(data.get("name", "#000000")) if data else "#000000"
    alpha = float(data.get("alpha", 1.0)) if data else 1.0
    color = QtGui.QColor(name)
    color.setAlphaF(alpha)
    return color


def _brush_to_data(brush: QtGui.QBrush) -> dict[str, Any]:
    style = _enum_to_int(brush.style())
    data: dict[str, Any] = {"style": style}
    if style != _enum_to_int(QtCore.Qt.BrushStyle.NoBrush):
        data["color"] = _color_to_data(brush.color())
    gradient = brush.gradient()
    if isinstance(gradient, QtGui.QLinearGradient):
        data["linear_gradient"] = {
            "start": [gradient.start().x(), gradient.start().y()],
            "end": [gradient.finalStop().x(), gradient.finalStop().y()],
            "coordinate_mode": _enum_to_int(gradient.coordinateMode()),
            "stops": [
                [float(position), _color_to_data(color)]
                for position, color in gradient.stops()
            ],
        }
    return data


def _brush_from_data(data: Mapping[str, Any] | None) -> QtGui.QBrush:
    default_style = _enum_to_int(QtCore.Qt.BrushStyle.NoBrush)
    style = int(data.get("style", default_style)) if data else default_style
    brush = QtGui.QBrush(QtCore.Qt.BrushStyle(style))
    color_data = data.get("color") if data else None
    if style != default_style and isinstance(color_data, Mapping):
        brush.setColor(_color_from_data(color_data))
    gradient_data = data.get("linear_gradient") if data else None
    if isinstance(gradient_data, Mapping):
        start = gradient_data.get("start")
        end = gradient_data.get("end")
        if isinstance(start, (list, tuple)) and isinstance(end, (list, tuple)) and len(start) == 2 and len(end) == 2:
            gradient = QtGui.QLinearGradient(float(start[0]), float(start[1]), float(end[0]), float(end[1]))
            gradient.setCoordinateMode(QtGui.QGradient.CoordinateMode(int(gradient_data.get("coordinate_mode", 2))))
            for stop in gradient_data.get("stops", []):
                if isinstance(stop, (list, tuple)) and len(stop) == 2 and isinstance(stop[1], Mapping):
                    gradient.setColorAt(float(stop[0]), _color_from_data(stop[1]))
            brush = QtGui.QBrush(gradient)
    return brush


def _pen_to_data(pen: QtGui.QPen) -> dict[str, Any]:
    data: dict[str, Any] = {
        "color": _color_to_data(pen.color()),
        "width": float(pen.widthF()),
        "style": _enum_to_int(pen.style()),
        "cap": _enum_to_int(pen.capStyle()),
        "join": _enum_to_int(pen.joinStyle()),
        "cosmetic": bool(pen.isCosmetic()),
    }
    pattern = pen.dashPattern()
    if pattern:
        data["dash"] = [float(value) for value in pattern]
    return data


def _pen_from_data(data: Mapping[str, Any] | None) -> QtGui.QPen:
    pen = QtGui.QPen()
    if not data:
        return pen
    color_data = data.get("color")
    if isinstance(color_data, Mapping):
        pen.setColor(_color_from_data(color_data))
    pen.setWidthF(float(data.get("width", pen.widthF())))
    pen.setStyle(QtCore.Qt.PenStyle(int(data.get("style", _enum_to_int(pen.style())))))
    pen.setCapStyle(
        QtCore.Qt.PenCapStyle(int(data.get("cap", _enum_to_int(pen.capStyle()))))
    )
    pen.setJoinStyle(
        QtCore.Qt.PenJoinStyle(int(data.get("join", _enum_to_int(pen.joinStyle()))))
    )
    pen.setCosmetic(bool(data.get("cosmetic", pen.isCosmetic())))
    dash = data.get("dash")
    if isinstance(dash, list):
        pen.setDashPattern([float(value) for value in dash])
    return pen


def _font_size(font: QtGui.QFont) -> str | None:
    if font.pixelSize() > 0:
        return f"{font.pixelSize()}px"
    if font.pointSizeF() > 0:
        return f"{font.pointSizeF():g}pt"
    return None


def _serialize_label(item: ShapeLabelMixin) -> dict[str, Any] | None:
    if not item.has_label():
        return None
    label = item.label_item()
    horizontal, vertical = item.label_alignment()
    data: dict[str, Any] = {
        "text": label.toPlainText(),
        "font": label.font().toString(),
        "color": _color_to_data(label.defaultTextColor()),
        "alignment": [horizontal, vertical],
    }
    font_size = _font_size(label.font())
    if font_size:
        data["font_size"] = font_size
    return data


def _apply_label(item: ShapeLabelMixin, data: Mapping[str, Any] | None) -> None:
    if not data:
        return
    text = data.get("text")
    if isinstance(text, str):
        item.set_label_text(text)
    font_value = data.get("font")
    if isinstance(font_value, str):
        font = QtGui.QFont()
        font.fromString(font_value)
        item.label_item().setFont(font)
    color_data = data.get("color")
    if isinstance(color_data, Mapping):
        item.set_label_color(_color_from_data(color_data))
    alignment = data.get("alignment")
    if isinstance(alignment, (list, tuple)) and len(alignment) == 2:
        item.set_label_alignment(
            horizontal=str(alignment[0]), vertical=str(alignment[1])
        )


def _size(
    data: Mapping[str, Any], fallback: tuple[float, float]
) -> tuple[float, float]:
    value = data.get("size")
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    return fallback


def _serialize_rect(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, RectItem)
    rect = item.rect()
    data: dict[str, Any] = {
        "size": [float(rect.width()), float(rect.height())],
        "rx": float(getattr(item, "rx", 0.0)),
        "ry": float(getattr(item, "ry", 0.0)),
        "pen": _pen_to_data(item.pen()),
        "brush": _brush_to_data(item.brush()),
    }
    label = _serialize_label(item)
    if label:
        data["label"] = label
    return data


def _restore_rect(type_id: str, data: Mapping[str, Any]) -> RectItem:
    width, height = _size(data, DEFAULTS[type_id])
    rx = float(data.get("rx", 0.0))
    ry = float(data.get("ry", rx))
    item = RectItem(0.0, 0.0, width, height, rx, ry)
    item.setPen(
        _pen_from_data(
            data.get("pen") if isinstance(data.get("pen"), Mapping) else None
        )
    )
    item.setBrush(
        _brush_from_data(
            data.get("brush") if isinstance(data.get("brush"), Mapping) else None
        )
    )
    label = data.get("label")
    _apply_label(item, label if isinstance(label, Mapping) else None)
    return item


def _serialize_split(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, SplitRoundedRectItem)
    rect = item.rect()
    return {
        "size": [float(rect.width()), float(rect.height())],
        "rx": float(getattr(item, "rx", 0.0)),
        "ry": float(getattr(item, "ry", 0.0)),
        "divider_ratio": float(item.divider_ratio()),
        "pen": _pen_to_data(item.pen()),
        "bottom_brush": _brush_to_data(item.bottomBrush()),
        "top_brush": _brush_to_data(item.topBrush()),
    }


def _restore_split(data: Mapping[str, Any]) -> SplitRoundedRectItem:
    width, height = _size(data, DEFAULTS["Split Rounded Rectangle"])
    rx = float(data.get("rx", 0.0))
    item = SplitRoundedRectItem(0.0, 0.0, width, height, rx, float(data.get("ry", rx)))
    item.setPen(
        _pen_from_data(
            data.get("pen") if isinstance(data.get("pen"), Mapping) else None
        )
    )
    bottom = data.get("bottom_brush")
    top = data.get("top_brush")
    item.setBottomBrush(
        _brush_from_data(bottom if isinstance(bottom, Mapping) else None)
    )
    item.setTopBrush(_brush_from_data(top if isinstance(top, Mapping) else None))
    if data.get("divider_ratio") is not None:
        item.set_divider_ratio(float(data["divider_ratio"]))
    return item


def _serialize_ellipse(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, EllipseItem)
    rect = item.rect()
    data: dict[str, Any] = {
        "size": [float(rect.width()), float(rect.height())],
        "pen": _pen_to_data(item.pen()),
        "brush": _brush_to_data(item.brush()),
    }
    label = _serialize_label(item)
    if label:
        data["label"] = label
    return data


def _restore_ellipse(type_id: str, data: Mapping[str, Any]) -> EllipseItem:
    width, height = _size(data, DEFAULTS[type_id])
    item = EllipseItem(0.0, 0.0, width, height)
    item.setPen(
        _pen_from_data(
            data.get("pen") if isinstance(data.get("pen"), Mapping) else None
        )
    )
    item.setBrush(
        _brush_from_data(
            data.get("brush") if isinstance(data.get("brush"), Mapping) else None
        )
    )
    label = data.get("label")
    _apply_label(item, label if isinstance(label, Mapping) else None)
    return item


def _serialize_polygon(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, QtWidgets.QGraphicsPolygonItem)
    width = getattr(item, "_w", None)
    height = getattr(item, "_h", None)
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        rect = item.boundingRect()
        width, height = rect.width(), rect.height()
    data = {
        "size": [float(width), float(height)],
        "pen": _pen_to_data(item.pen()),
        "brush": _brush_to_data(item.brush()),
    }
    if isinstance(item, ShapeLabelMixin):
        label = _serialize_label(item)
        if label:
            data["label"] = label
    return data


def _restore_polygon(type_id: str, data: Mapping[str, Any]) -> QtWidgets.QGraphicsItem:
    width, height = _size(data, DEFAULTS[type_id])
    item: QtWidgets.QGraphicsItem
    if type_id == "Triangle":
        item = TriangleItem(0.0, 0.0, width, height)
    elif type_id == "Diamond":
        item = DiamondItem(0.0, 0.0, width, height)
    else:
        block = BlockArrowItem(0.0, 0.0, width, height)
        if data.get("head_ratio") is not None:
            block.set_head_ratio(float(data["head_ratio"]))
        if data.get("shaft_ratio") is not None:
            block.set_shaft_ratio(float(data["shaft_ratio"]))
        item = block
    item.setPen(
        _pen_from_data(
            data.get("pen") if isinstance(data.get("pen"), Mapping) else None
        )
    )  # type: ignore[attr-defined]
    item.setBrush(
        _brush_from_data(
            data.get("brush") if isinstance(data.get("brush"), Mapping) else None
        )
    )  # type: ignore[attr-defined]
    label = data.get("label")
    if isinstance(item, ShapeLabelMixin):
        _apply_label(item, label if isinstance(label, Mapping) else None)
    return item


def _serialize_block_arrow(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, BlockArrowItem)
    data = _serialize_polygon(item)
    data["head_ratio"] = float(item.head_ratio())
    data["shaft_ratio"] = float(item.shaft_ratio())
    return data


def _serialize_line(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, LineItem)
    data: dict[str, Any] = {
        "points": [[float(point.x()), float(point.y())] for point in item._points],
        "arrow_start": bool(item.arrow_start),
        "arrow_end": bool(item.arrow_end),
        "pen": _pen_to_data(item.pen()),
    }
    data["arrow_head"] = {
        "length": float(item.arrow_head_length()),
        "width": float(item.arrow_head_width()),
    }
    return data


def _restore_line(data: Mapping[str, Any]) -> LineItem:
    points = []
    points_raw = data.get("points")
    if isinstance(points_raw, list):
        points = [
            QtCore.QPointF(float(point[0]), float(point[1]))
            for point in points_raw
            if isinstance(point, (list, tuple)) and len(point) == 2
        ]
    arrow_head = data.get("arrow_head")
    length = width = None
    if isinstance(arrow_head, Mapping):
        if arrow_head.get("length") is not None:
            length = float(arrow_head["length"])
        if arrow_head.get("width") is not None:
            width = float(arrow_head["width"])
    item = LineItem(
        0.0,
        0.0,
        points=points or None,
        arrow_start=bool(data.get("arrow_start", False)),
        arrow_end=bool(data.get("arrow_end", False)),
        arrow_head_length=length,
        arrow_head_width=width,
    )
    item.setPen(
        _pen_from_data(
            data.get("pen") if isinstance(data.get("pen"), Mapping) else None
        )
    )
    return item


def _serialize_free_path(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, FreePathItem)
    data = item.path_payload()
    data["pen"] = _pen_to_data(item.pen())
    data["brush"] = _brush_to_data(item.brush())
    return data


def _restore_free_path(type_id: str, data: Mapping[str, Any]) -> FreePathItem:
    start = data.get("start", [0.0, 0.0])
    segments = data.get("segments", [])
    closed = bool(data.get("closed", type_id == "Free Polygon"))
    item_type = BezierPathItem if type_id == "Bezier Path" else FreePathItem
    item = item_type(
        0.0,
        0.0,
        closed=closed,
        start=start if isinstance(start, (list, tuple)) else [0.0, 0.0],
        segments=segments if isinstance(segments, list) else None,
        path_kind={
            "Free Polyline": "polyline",
            "Free Polygon": "polygon",
            "Bezier Path": "bezier",
        }[type_id],
    )
    item.setPen(_pen_from_data(data.get("pen") if isinstance(data.get("pen"), Mapping) else None))
    item.setBrush(_brush_from_data(data.get("brush") if isinstance(data.get("brush"), Mapping) else None))
    return item


def _serialize_bracket(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, CurvyBracketItem)
    return {
        "size": [float(item.width()), float(item.height())],
        "hook_ratio": float(item.hook_ratio()),
        "pen": _pen_to_data(item.pen()),
    }


def _create_bracket(
    x: float, y: float, width: float, height: float, rotation: float = 0.0
) -> CurvyBracketItem:
    item = CurvyBracketItem(x, y, width, height)
    item.setRotation(rotation)
    return item


def _restore_bracket(
    data: Mapping[str, Any], rotation: float = 0.0
) -> CurvyBracketItem:
    width, height = _size(data, DEFAULTS["Curvy Right Bracket"])
    hook = float(data.get("hook_ratio", CurvyBracketItem.DEFAULT_HOOK_RATIO))
    item = CurvyBracketItem(0.0, 0.0, width, height, hook)
    item.setRotation(rotation)
    item.setPen(
        _pen_from_data(
            data.get("pen") if isinstance(data.get("pen"), Mapping) else None
        )
    )
    item.setBrush(
        _brush_from_data(
            data.get("brush") if isinstance(data.get("brush"), Mapping) else None
        )
    )
    return item


def _serialize_text(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, TextItem)
    rect = item.boundingRect()
    horizontal, vertical = item.text_alignment()
    data: dict[str, Any] = {
        "size": [float(rect.width()), float(rect.height())],
        "text": item.toPlainText(),
        "font": item.font().toString(),
        "color": _color_to_data(item.defaultTextColor()),
        "alignment": [horizontal, vertical],
        "direction": item.text_direction(),
    }
    font_size = _font_size(item.font())
    if font_size:
        data["font_size"] = font_size
    if item.document() is not None:
        data["document_margin"] = float(item.document().documentMargin())
    return data


def _restore_text(data: Mapping[str, Any]) -> TextItem:
    width, height = _size(data, DEFAULTS["Text"])
    item = TextItem(0.0, 0.0, width, height)
    if isinstance(data.get("text"), str):
        item.setPlainText(str(data["text"]))
    if isinstance(data.get("font"), str):
        font = QtGui.QFont()
        font.fromString(str(data["font"]))
        item.setFont(font)
    color = data.get("color")
    if isinstance(color, Mapping):
        item.setDefaultTextColor(_color_from_data(color))
    if data.get("document_margin") is not None:
        item.set_document_margin(float(data["document_margin"]))
    alignment = data.get("alignment")
    if isinstance(alignment, (list, tuple)) and len(alignment) == 2:
        item.set_text_alignment(
            horizontal=str(alignment[0]), vertical=str(alignment[1])
        )
    if isinstance(data.get("direction"), str):
        item.set_text_direction(str(data["direction"]))
    return item


def _serialize_folder(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, FolderTreeItem)
    return {"structure": item.structure()}


def _restore_folder(data: Mapping[str, Any]) -> FolderTreeItem:
    structure = data.get("structure")
    return FolderTreeItem(
        0.0,
        0.0,
        0.0,
        0.0,
        structure=structure if isinstance(structure, Mapping) else None,  # type: ignore[arg-type]
    )


_DIAGRAM_KINDS = {
    "Hexagon": "hexagon",
    "Parallelogram": "parallelogram",
    "Database": "database",
    "Document": "document",
    "Multiple Document": "multiple_document",
    "Cloud": "cloud",
    "Callout": "callout",
    "Table": "table",
    "Swimlane": "swimlane",
}


def _serialize_diagram(item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
    assert isinstance(item, DiagramItem)
    data: dict[str, Any] = {
        "size": [float(item._w), float(item._h)],
        "parameters": item.parameters(),
        "pen": _pen_to_data(item.pen()),
        "brush": _brush_to_data(item.brush()),
    }
    label = _serialize_label(item)
    if label:
        data["label"] = label
    return data


def _restore_diagram(type_id: str, data: Mapping[str, Any]) -> DiagramItem:
    width, height = _size(data, DEFAULTS[type_id])
    item = DiagramItem(0.0, 0.0, width, height, _DIAGRAM_KINDS[type_id])
    parameters = data.get("parameters")
    if isinstance(parameters, Mapping):
        item.apply_parameters(dict(parameters))
    item.setPen(
        _pen_from_data(
            data.get("pen") if isinstance(data.get("pen"), Mapping) else None
        )
    )
    item.setBrush(
        _brush_from_data(
            data.get("brush") if isinstance(data.get("brush"), Mapping) else None
        )
    )
    label = data.get("label")
    _apply_label(item, label if isinstance(label, Mapping) else None)
    return item


@dataclass(frozen=True)
class ShapeDefinition:
    type_id: str
    palette_label: str
    default_size: tuple[float, float]
    factory: ShapeFactory
    serializer: ShapeSerializer
    restorer: ShapeRestorer
    python_export_adapter: str


class ShapeRegistry:
    def __init__(
        self,
        definitions: tuple[ShapeDefinition, ...],
        extensions: tuple[ShapeDefinition, ...] = (),
    ) -> None:
        self._definitions = definitions
        self._extensions = extensions
        all_definitions = definitions + extensions
        self._by_type_id = {
            definition.type_id: definition for definition in all_definitions
        }
        if len(self._by_type_id) != len(all_definitions):
            raise ValueError("Shape type IDs must be unique")

    def definitions(self) -> tuple[ShapeDefinition, ...]:
        return self._definitions

    def extension_definitions(self) -> tuple[ShapeDefinition, ...]:
        return self._extensions

    def palette_definitions(self) -> tuple[ShapeDefinition, ...]:
        return self._definitions + self._extensions

    def type_ids(self) -> tuple[str, ...]:
        return tuple(definition.type_id for definition in self._definitions)

    def get(self, type_id: str) -> ShapeDefinition | None:
        return self._by_type_id.get(type_id.strip())

    def type_id_from_payload(self, data: Mapping[str, Any]) -> str | None:
        value = data.get("type_id")
        if not isinstance(value, str) or not value:
            value = data.get("shape")
        return value if isinstance(value, str) and value in self._by_type_id else None

    def definition_for_item(
        self, item: QtWidgets.QGraphicsItem
    ) -> ShapeDefinition | None:
        value = item.data(0)
        return self.get(value) if isinstance(value, str) else None

    def create(
        self,
        type_id: str,
        x: float,
        y: float,
        width: float | None = None,
        height: float | None = None,
    ) -> QtWidgets.QGraphicsItem | None:
        definition = self.get(type_id)
        if definition is None:
            return None
        default_width, default_height = definition.default_size
        item = definition.factory(
            x,
            y,
            default_width if width is None else width,
            default_height if height is None else height,
        )
        item.setData(0, definition.type_id)
        return item

    def serialize(self, item: QtWidgets.QGraphicsItem) -> dict[str, Any] | None:
        definition = self.definition_for_item(item)
        if definition is None:
            return None
        data = definition.serializer(item)
        data["shape"] = definition.palette_label
        data["type_id"] = definition.type_id
        style = style_data(item)
        if style is not None:
            data["item_style"] = style
        return data

    def restore(self, data: Mapping[str, Any]) -> QtWidgets.QGraphicsItem | None:
        type_id = self.type_id_from_payload(data)
        definition = self.get(type_id) if type_id is not None else None
        if definition is None:
            return None
        item = definition.restorer(data)
        item.setData(0, definition.type_id)
        style = data.get("item_style")
        apply_style_data(item, style if isinstance(style, Mapping) else None)
        return item


_DEFINITIONS = (
    ShapeDefinition(
        "Rectangle",
        "Rectangle",
        DEFAULTS["Rectangle"],
        lambda x, y, w, h: RectItem(x, y, w, h),
        _serialize_rect,
        lambda data: _restore_rect("Rectangle", data),
        "rectangle",
    ),
    ShapeDefinition(
        "Rounded Rectangle",
        "Rounded Rectangle",
        DEFAULTS["Rounded Rectangle"],
        lambda x, y, w, h: RectItem(x, y, w, h, 15.0, 15.0),
        _serialize_rect,
        lambda data: _restore_rect("Rounded Rectangle", data),
        "rectangle",
    ),
    ShapeDefinition(
        "Split Rounded Rectangle",
        "Split Rounded Rectangle",
        DEFAULTS["Split Rounded Rectangle"],
        lambda x, y, w, h: SplitRoundedRectItem(x, y, w, h, 15.0, 15.0),
        _serialize_split,
        _restore_split,
        "split_rounded_rectangle",
    ),
    ShapeDefinition(
        "Ellipse",
        "Ellipse",
        DEFAULTS["Ellipse"],
        lambda x, y, w, h: EllipseItem(x, y, w, h),
        _serialize_ellipse,
        lambda data: _restore_ellipse("Ellipse", data),
        "ellipse",
    ),
    ShapeDefinition(
        "Circle",
        "Circle",
        DEFAULTS["Circle"],
        lambda x, y, w, h: EllipseItem(x, y, w, h),
        _serialize_ellipse,
        lambda data: _restore_ellipse("Circle", data),
        "circle",
    ),
    ShapeDefinition(
        "Triangle",
        "Triangle",
        DEFAULTS["Triangle"],
        lambda x, y, w, h: TriangleItem(x, y, w, h),
        _serialize_polygon,
        lambda data: _restore_polygon("Triangle", data),
        "triangle",
    ),
    ShapeDefinition(
        "Diamond",
        "Diamond",
        DEFAULTS["Diamond"],
        lambda x, y, w, h: DiamondItem(x, y, w, h),
        _serialize_polygon,
        lambda data: _restore_polygon("Diamond", data),
        "diamond",
    ),
    ShapeDefinition(
        "Line",
        "Line",
        DEFAULTS["Line"],
        lambda x, y, w, h: LineItem(x, y, w),
        _serialize_line,
        _restore_line,
        "line",
    ),
    ShapeDefinition(
        "Arrow",
        "Arrow",
        DEFAULTS["Arrow"],
        lambda x, y, w, h: LineItem(x, y, w, arrow_end=True),
        _serialize_line,
        _restore_line,
        "line",
    ),
    ShapeDefinition(
        "Block Arrow",
        "Block Arrow",
        DEFAULTS["Block Arrow"],
        lambda x, y, w, h: BlockArrowItem(x, y, w, h),
        _serialize_block_arrow,
        lambda data: _restore_polygon("Block Arrow", data),
        "block_arrow",
    ),
    ShapeDefinition(
        "Curvy Right Bracket",
        "Curvy Right Bracket",
        DEFAULTS["Curvy Right Bracket"],
        _create_bracket,
        _serialize_bracket,
        _restore_bracket,
        "curvy_right_bracket",
    ),
    ShapeDefinition(
        "Curvy Left Bracket",
        "Curvy Left Bracket",
        DEFAULTS["Curvy Left Bracket"],
        lambda x, y, w, h: _create_bracket(x, y, w, h, 180.0),
        _serialize_bracket,
        lambda data: _restore_bracket(data, 180.0),
        "curvy_right_bracket",
    ),
    ShapeDefinition(
        "Text",
        "Text",
        DEFAULTS["Text"],
        lambda x, y, w, h: TextItem(x, y, w, h),
        _serialize_text,
        _restore_text,
        "text",
    ),
    ShapeDefinition(
        "Folder Tree",
        "Folder Tree",
        DEFAULTS["Folder Tree"],
        lambda x, y, w, h: FolderTreeItem(x, y, w, h),
        _serialize_folder,
        _restore_folder,
        "folder_tree",
    ),
)

_EXTENSION_DEFINITIONS = (
    *(
        ShapeDefinition(
            type_id,
            type_id,
            DEFAULTS[type_id],
            lambda x, y, w, h, kind=kind: DiagramItem(x, y, w, h, kind),
            _serialize_diagram,
            lambda data, type_id=type_id: _restore_diagram(type_id, data),
            "diagram",
        )
        for type_id, kind in _DIAGRAM_KINDS.items()
    ),
    ShapeDefinition(
        "Free Polyline",
        "Free Polyline",
        (150.0, 100.0),
        lambda x, y, w, h: FreePathItem(
            x,
            y,
            start=[0.0, h * 0.82],
            segments=[
                {"kind": "line", "end": [w * 0.3, h * 0.2]},
                {"kind": "line", "end": [w * 0.62, h * 0.72]},
                {"kind": "line", "end": [w, h * 0.12]},
            ],
            path_kind="polyline",
        ),
        _serialize_free_path,
        lambda data: _restore_free_path("Free Polyline", data),
        "free_path",
    ),
    ShapeDefinition(
        "Free Polygon",
        "Free Polygon",
        (150.0, 100.0),
        lambda x, y, w, h: FreePathItem(
            x,
            y,
            closed=True,
            start=[w * 0.12, h * 0.88],
            segments=[
                {"kind": "line", "end": [w * 0.28, h * 0.12]},
                {"kind": "line", "end": [w * 0.92, h * 0.32]},
                {"kind": "line", "end": [w * 0.8, h * 0.92]},
            ],
            path_kind="polygon",
        ),
        _serialize_free_path,
        lambda data: _restore_free_path("Free Polygon", data),
        "free_path",
    ),
    ShapeDefinition(
        "Bezier Path",
        "Bezier Path",
        (150.0, 100.0),
        lambda x, y, w, h: BezierPathItem(x, y, w, h),
        _serialize_free_path,
        lambda data: _restore_free_path("Bezier Path", data),
        "free_path",
    ),
)

if tuple(definition.type_id for definition in _DEFINITIONS) != SHAPES:
    raise RuntimeError("Shape registry and legacy shape constants are out of sync")

SHAPE_REGISTRY = ShapeRegistry(_DEFINITIONS, _EXTENSION_DEFINITIONS)
