# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Standalone drawsvg adapters for embedded assets and routed connectors."""

from __future__ import annotations

import ast
import base64
import html
import json
import math
from collections.abc import Iterable, Mapping
from xml.etree import ElementTree as ET

from PySide6 import QtCore, QtWidgets

from bitmap_item import BitmapItem
from connectors import ConnectorItem
from export_drawsvg_styles import format_drawsvg_attributes, item_style_attributes
from items import ShapeLabelMixin
from items.svg import SvgItem
from scene_codec import KEY_TRANSIENT


ASSET_ITEM_TYPES = (BitmapItem, SvgItem, ConnectorItem)


def scene_item_parents(items: Iterable[QtWidgets.QGraphicsItem]) -> dict:
    """Read child relationships without changing Qt ownership of scene roots."""
    # parentItem() can transfer a scene-owned root back to Python (Qt 6.9).
    return {child: item for item in items for child in item.childItems()}


def export_item_is_visible(
    item: QtWidgets.QGraphicsItem,
    parents: Mapping[QtWidgets.QGraphicsItem, QtWidgets.QGraphicsItem],
) -> bool:
    """Exclude hidden items and every descendant of editor-only helpers."""
    if not item.isVisible() or item.effectiveOpacity() <= 0:
        return False
    ancestor = item
    while ancestor is not None:
        if ancestor.data(KEY_TRANSIENT):
            return False
        ancestor = parents.get(ancestor)
    return True


def export_item_bounds(
    item: QtWidgets.QGraphicsItem,
    parents: Mapping[QtWidgets.QGraphicsItem, QtWidgets.QGraphicsItem],
) -> QtCore.QRectF:
    """Include the exported label and enabled effects in scene coordinates."""
    bounds = item.sceneBoundingRect()
    effect = item.graphicsEffect()
    if isinstance(item, ShapeLabelMixin):
        label = item.label_item()
        if label is not None and export_item_is_visible(label, parents):
            bounds = bounds.united(label.sceneBoundingRect())
    if effect is not None and effect.isEnabled():
        if isinstance(effect, QtWidgets.QGraphicsDropShadowEffect):
            # Qt shadow offset/blur are device coordinates, unaffected by item transforms.
            source = QtCore.QRectF(bounds)
            bounds = bounds.united(effect.boundingRectFor(source))
            # The generated Gaussian filter reserves three sigma (radius / 2).
            extent = 1.5 * effect.blurRadius()
            offset = effect.offset()
            filter_bounds = source.adjusted(
                min(0.0, offset.x()) - extent, min(0.0, offset.y()) - extent,
                max(0.0, offset.x()) + extent, max(0.0, offset.y()) + extent,
            )
            bounds = bounds.united(filter_bounds)
        else:
            local = item.mapRectFromScene(bounds)
            bounds = bounds.united(item.mapRectToScene(effect.boundingRectFor(local)))
    return bounds


def _xml_attribute(value: str) -> str:
    return html.escape(value, quote=True).replace("\n", "&#10;").replace("\r", "&#13;").replace("\t", "&#9;")


def _svg_content(item: SvgItem, instance: int, transform: str) -> str:
    """Embed a separate vector document with its own viewport and CSS cascade."""
    root = ET.fromstring(item.asset.data)
    rect = item.boundingRect()
    # Qt stretches the source viewBox when rendering into the item rectangle.
    # Preserve its user coordinate viewport while suppressing aspect fitting
    # inside the embedded document as well as on its image.
    root.set("preserveAspectRatio", "none")
    viewbox = item._renderer.viewBoxF()
    if viewbox.isEmpty():
        viewbox = QtCore.QRectF(0, 0, rect.width(), rect.height())
    root.set("viewBox", f"{viewbox.x():.9g} {viewbox.y():.9g} {viewbox.width():.9g} {viewbox.height():.9g}")
    # Qt decodes SVG images at their intrinsic size. Reserve the displayed
    # resolution so a small source vector does not become a blurred thumbnail.
    matrix = item.sceneTransform()
    root.set("width", str(max(1, math.ceil(rect.width() * math.hypot(matrix.m11(), matrix.m12())))))
    root.set("height", str(max(1, math.ceil(rect.height() * math.hypot(matrix.m21(), matrix.m22())))))
    # Qt's SVG image-format plugin recognizes an unprefixed svg root only.
    # The parser accepts exclusively SVG elements, so a default namespace is safe.
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
        for key in list(node.attrib):
            if key.startswith("{http://www.w3.org/1999/xlink}"):
                node.set("xlink:" + key.rsplit("}", 1)[-1], node.attrib.pop(key))
                root.set("xmlns:xlink", "http://www.w3.org/1999/xlink")
    root.set("xmlns", "http://www.w3.org/2000/svg")
    vector = base64.b64encode(ET.tostring(root, encoding="utf-8")).decode("ascii")
    wrapper = ET.Element("{http://www.w3.org/2000/svg}g", {
        "data-asset-svg": base64.b64encode(item.asset.data).decode("ascii"),
        "data-asset-width": f"{rect.width():.9g}",
        "data-asset-height": f"{rect.height():.9g}",
        "transform": transform,
        "opacity": f"{item.effectiveOpacity():.9g}",
    })
    ET.SubElement(wrapper, "{http://www.w3.org/2000/svg}image", {
        "x": "0", "y": "0",
        "width": f"{rect.width():.9g}",
        "height": f"{rect.height():.9g}",
        "preserveAspectRatio": "none",
        "href": f"data:image/svg+xml;base64,{vector}",
    })
    return ET.tostring(wrapper, encoding="unicode")


def export_asset_item(item, lines: list[str], *, attributes: str, transform_suffix: str, instance: int) -> str:
    """Emit literal primitives that require only drawsvg at runtime."""
    if isinstance(item, BitmapItem):
        rect = item.boundingRect()
        uri = f"data:{item.asset.media_type};base64,{base64.b64encode(item.asset.data).decode('ascii')}"
        name = _xml_attribute(item.asset_name)
        # The embedded asset name already requires the XML escaping marker.
        style = ", ".join(attr for attr in item_style_attributes(item) if not attr.startswith("data_xml_escaped="))
        style_suffix = f", {style}" if style else ""
        lines.append(f"    _bitmap = draw.Image(0, 0, {rect.width():.9g}, {rect.height():.9g}, path={uri!r}, preserveAspectRatio='none', data_asset_name={name!r}, data_xml_escaped='true'{style_suffix}{transform_suffix})")
        return "_bitmap"
    if isinstance(item, SvgItem):
        transform = item.sceneTransform()
        matrix = f"matrix({transform.m11():.6f} {transform.m12():.6f} {transform.m21():.6f} {transform.m22():.6f} {transform.m31():.6f} {transform.m32():.6f})"
        content = _svg_content(item, instance, matrix)
        wrapper = ET.fromstring(content)
        for attribute in item_style_attributes(item):
            name, value = attribute.split("=", 1)
            wrapper.set(name.replace("_", "-"), html.unescape(str(ast.literal_eval(value))))
        content = ET.tostring(wrapper, encoding="unicode")
        lines.append(f"    _svg = draw.Raw({content!r})")
        return "_svg"
    if isinstance(item, ConnectorItem):
        # Preserve the manager's routed path rather than recomputing endpoints.
        points = item.route_points()
        command = "M " + " L ".join(f"{point.x():.6f} {point.y():.6f}" for point in points) if points else ""
        payload = item.to_data()
        payload["route_points"] = [[point.x(), point.y()] for point in points]
        metadata = _xml_attribute(json.dumps(payload, separators=(",", ":")))
        attributes = format_drawsvg_attributes([
            attributes, f"data_connector={metadata!r}", "data_xml_escaped='true'",
        ])
        lines.append(f"    _connector = draw.Path({command!r}, {attributes}{transform_suffix})")
        return "_connector"
    raise TypeError(f"Unsupported asset item: {type(item).__name__}")
