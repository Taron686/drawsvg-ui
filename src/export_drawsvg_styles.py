# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Serialize Qt paints and effects using native, standalone drawsvg objects."""

from __future__ import annotations

import ast
import html
import json
import math
from collections.abc import Iterable, Mapping

from PySide6 import QtCore, QtGui, QtWidgets

from style_presets import style_data


def format_drawsvg_attributes(attributes: Iterable[str]) -> str:
    """Compose keyword fragments once; later adapter values override defaults."""
    source = '_attributes(' + ', '.join(attributes) + ')'
    call = ast.parse(source, mode='eval').body
    # Fragments may contain commas inside literals, JSON metadata, or gradients.
    unique = {keyword.arg: ast.get_source_segment(source, keyword) for keyword in call.keywords}
    return ', '.join(unique.values())


# These helpers are copied into the generated module. They depend only on its
# ``import drawsvg as draw`` and never on Qt or this editor.
STYLE_PRELUDE = '''
def _drawsvg_gradient(kind, coords, stops, attrs):
    if kind == 'linear':
        gradient = draw.LinearGradient(*coords, **attrs)
    else:
        cx, cy, radius, fx, fy, fr = coords
        gradient = draw.RadialGradient(cx, cy, radius, fx=fx, fy=fy, fr=fr, **attrs)
    for offset, color, alpha in stops:
        gradient.add_stop(offset, color, opacity=alpha)
    return gradient


def _drawsvg_effect(element, rect, shadow):
    dx, dy, radius, color, alpha = shadow
    x, y, width, height = rect
    # Qt uses a different blur kernel. Gaussian sigma=radius/2 is an
    # approximation; allow three sigma on every side to avoid clipping.
    margin = 1.5 * radius
    left = min(x, x + dx) - margin
    top = min(y, y + dy) - margin
    right = max(x + width, x + width + dx) + margin
    bottom = max(y + height, y + height + dy) + margin
    effect = draw.Filter(x=left, y=top, width=max(1, right-left),
                         height=max(1, bottom-top), filterUnits='userSpaceOnUse',
                         primitiveUnits='userSpaceOnUse', color_interpolation_filters='sRGB')
    if radius > 0:
        effect.append(draw.FilterItem('feGaussianBlur', in_='SourceAlpha',
                                     stdDeviation=radius/2, result='shadow-alpha'))
    effect.append(draw.FilterItem('feOffset', in_='shadow-alpha' if radius > 0 else 'SourceAlpha',
                                 dx=dx, dy=dy, result='shadow-offset'))
    effect.append(draw.FilterItem('feFlood', flood_color=color, flood_opacity=alpha,
                                 result='shadow-color'))
    effect.append(draw.FilterItem('feComposite', in_='shadow-color', in2='shadow-offset',
                                 operator='in', result='shadow'))
    merge = draw.FilterItem('feMerge')
    merge.append(draw.FilterItem('feMergeNode', in_='shadow'))
    merge.append(draw.FilterItem('feMergeNode', in_='SourceGraphic'))
    effect.append(merge)
    # Qt shadow offset/radius use device coordinates. Apply the filter outside
    # the item's transform so rotations and scaling do not change those values.
    transform = element.args.pop('transform', None)
    source = draw.Group(transform=transform) if transform else draw.Group()
    source.append(element)
    result = draw.Group(filter=effect)
    result.append(source)
    return result
'''


def _matrix(transform: QtGui.QTransform) -> list[float]:
    return [transform.m11(), transform.m12(), transform.m21(), transform.m22(), transform.dx(), transform.dy()]


def _matrix_string(transform: QtGui.QTransform) -> str:
    return 'matrix(' + ' '.join(f'{v:.12g}' for v in _matrix(transform)) + ')'


def _metadata(name: str, data: object) -> str:
    value = html.escape(json.dumps(data, separators=(',', ':'), ensure_ascii=False), quote=True)
    value = value.replace('\r', '&#13;').replace('\n', '&#10;').replace('\t', '&#9;')
    return f'{name}={value!r}'


def brush_data(brush: QtGui.QBrush) -> dict:
    """Literal editor metadata, independent of the generated SVG coordinates."""
    gradient = brush.gradient()
    if gradient is None:
        return {'kind': 'solid', 'style': brush.style().value, 'color': brush.color().name(), 'alpha': brush.color().alphaF()}
    if isinstance(gradient, QtGui.QLinearGradient):
        kind = 'linear'
        coords = [gradient.start().x(), gradient.start().y(), gradient.finalStop().x(), gradient.finalStop().y()]
    elif isinstance(gradient, QtGui.QRadialGradient):
        kind = 'radial'
        coords = [gradient.center().x(), gradient.center().y(), gradient.radius(), gradient.focalPoint().x(), gradient.focalPoint().y(), gradient.focalRadius()]
    else:
        raise ValueError('Unsupported gradient kind')
    return {'kind': kind, 'coords': coords, 'coordinate_mode': gradient.coordinateMode().value,
            'spread': gradient.spread().value, 'stops': [[float(p), c.name(), c.alphaF()] for p, c in gradient.stops()],
            'transform': _matrix(brush.transform())}


def split_style_attribute(item) -> str:
    pen = item._divider_pen
    divider = {'color': pen.color().name(), 'alpha': pen.color().alphaF(), 'width': pen.widthF(),
               'style': pen.style().value, 'cosmetic': pen.isCosmetic(), 'cap': pen.capStyle().value,
               'join': pen.joinStyle().value, 'dash': list(pen.dashPattern()), 'offset': pen.dashOffset(), 'miter': pen.miterLimit()}
    return _metadata('data_qt_split', {'top': brush_data(item.topBrush()), 'bottom': brush_data(item.bottomBrush()), 'divider_pen': divider})


def _paint_bounds(item: QtWidgets.QGraphicsItem) -> QtCore.QRectF:
    if isinstance(item, (QtWidgets.QGraphicsRectItem, QtWidgets.QGraphicsEllipseItem)):
        return item.rect()
    if isinstance(item, QtWidgets.QGraphicsPathItem):
        return item.path().boundingRect()
    if isinstance(item, QtWidgets.QGraphicsPolygonItem):
        return item.polygon().boundingRect()
    return item.boundingRect()


def brush_attributes(brush: QtGui.QBrush, item: QtWidgets.QGraphicsItem, paint: str = 'fill', *, bounds: QtCore.QRectF | None = None) -> list[str]:
    """Return paint arguments; gradients preserve stops, spread and coordinates."""
    if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
        return [f"{paint}='none'"]
    gradient = brush.gradient()
    if gradient is None:
        color = brush.color()
        return [f'{paint}={color.name()!r}', f'{paint}_opacity={color.alphaF():.12g}']
    if isinstance(gradient, QtGui.QLinearGradient):
        kind = 'linear'
        coords = [gradient.start().x(), gradient.start().y(), gradient.finalStop().x(), gradient.finalStop().y()]
    elif isinstance(gradient, QtGui.QRadialGradient):
        kind = 'radial'
        coords = [gradient.center().x(), gradient.center().y(), gradient.radius(), gradient.focalPoint().x(), gradient.focalPoint().y(), gradient.focalRadius()]
    else:
        raise ValueError('drawsvg Python export supports linear and radial gradients; conical gradients need an explicit SVG approximation')
    transform = brush.transform()
    mode = gradient.coordinateMode()
    if mode in (QtGui.QGradient.CoordinateMode.ObjectMode, QtGui.QGradient.CoordinateMode.ObjectBoundingMode):
        bounds = _paint_bounds(item) if bounds is None else bounds
        box = QtGui.QTransform(bounds.width(), 0, 0, bounds.height(), bounds.x(), bounds.y())
        # Qt matrix multiplication applies the left transform first. ObjectMode
        # transforms in normalized space; ObjectBoundingMode in logical space.
        transform = transform * box if mode == QtGui.QGradient.CoordinateMode.ObjectMode else box * transform
    elif mode == QtGui.QGradient.CoordinateMode.StretchToDeviceMode:
        raise ValueError('StretchToDeviceMode gradients require a fixed paint device and cannot be exported as portable item styles')
    stops = [[float(offset), color.name(), float(color.alphaF())] for offset, color in gradient.stops()]
    attrs = {'gradientUnits': 'userSpaceOnUse', 'gradientTransform': _matrix_string(transform),
             'spreadMethod': {QtGui.QGradient.Spread.PadSpread: 'pad', QtGui.QGradient.Spread.RepeatSpread: 'repeat', QtGui.QGradient.Spread.ReflectSpread: 'reflect'}[gradient.spread()]}
    metadata = brush_data(brush)
    return [f'{paint}=_drawsvg_gradient({kind!r}, {coords!r}, {stops!r}, {attrs!r})',
            _metadata('data_qt_brush' if paint == 'fill' else 'data_qt_pen_brush', metadata), "data_xml_escaped='true'"]


def pen_dash_array_string(pen: QtGui.QPen) -> str | None:
    if pen.style() in (QtCore.Qt.PenStyle.NoPen, QtCore.Qt.PenStyle.SolidLine):
        return None
    width = pen.widthF() or 1.0
    pattern = pen.dashPattern()
    return ' '.join(f'{value * width:.12g}' for value in pattern) if pattern else None


def pen_attributes(pen: QtGui.QPen, item: QtWidgets.QGraphicsItem | None = None) -> list[str]:
    if pen.style() == QtCore.Qt.PenStyle.NoPen:
        return ["stroke='none'"]
    if item is not None:
        attrs = brush_attributes(pen.brush(), item, 'stroke')
    else:
        color = pen.color()
        attrs = [f'stroke={color.name()!r}', f'stroke_opacity={color.alphaF():.12g}']
    attrs.append(f'stroke_width={(pen.widthF() or 1.0):.2f}')
    attrs.append("data_pen_units='svg'")
    attrs.append(f'data_qt_pen_style={pen.style().value}')
    cap = {QtCore.Qt.PenCapStyle.FlatCap: 'butt', QtCore.Qt.PenCapStyle.SquareCap: 'square', QtCore.Qt.PenCapStyle.RoundCap: 'round'}[pen.capStyle()]
    join = {QtCore.Qt.PenJoinStyle.MiterJoin: 'miter', QtCore.Qt.PenJoinStyle.SvgMiterJoin: 'miter', QtCore.Qt.PenJoinStyle.BevelJoin: 'bevel', QtCore.Qt.PenJoinStyle.RoundJoin: 'round'}[pen.joinStyle()]
    attrs.extend([f'stroke_linecap={cap!r}', f'stroke_linejoin={join!r}'])
    # Qt expresses the miter limit in pen widths, SVG in half widths.
    attrs.append(f'stroke_miterlimit={2 * pen.miterLimit():.12g}')
    dash = pen_dash_array_string(pen)
    if dash:
        attrs.extend([f'stroke_dasharray={dash!r}', f'stroke_dashoffset={pen.dashOffset() * (pen.widthF() or 1.0):.12g}'])
    if pen.isCosmetic():
        attrs.extend(["vector_effect='non-scaling-stroke'", f'data_qt_pen_width={pen.widthF():.12g}'])
    return attrs


def shadow_parameters(item: QtWidgets.QGraphicsItem) -> tuple[float, float, float, str, float] | None:
    effect = item.graphicsEffect()
    if effect is not None:
        if not isinstance(effect, QtWidgets.QGraphicsDropShadowEffect) or not effect.isEnabled():
            return None
        color = effect.color()
        values = (effect.xOffset(), effect.yOffset(), effect.blurRadius())
    else:
        data = style_data(item) or {}
        shadow = data.get('shadow')
        if not isinstance(shadow, Mapping) or not shadow:
            return None
        try:
            values = tuple(float(shadow.get(k, 0)) for k in ('offset_x', 'offset_y', 'blur_radius'))
        except (TypeError, ValueError, OverflowError):
            return None
        color = QtGui.QColor(str(shadow.get('color', '#00000000')))
    if not all(math.isfinite(v) for v in values) or not color.isValid():
        return None
    return (*values[:2], max(0.0, values[2]), color.name(), color.alphaF())


def item_style_attributes(item: QtWidgets.QGraphicsItem) -> list[str]:
    attrs: list[str] = []
    opacity = item.effectiveOpacity()
    if opacity < 1:
        attrs.append(f'opacity={opacity:.12g}')
    if isinstance(item, (QtWidgets.QGraphicsPathItem, QtWidgets.QGraphicsPolygonItem)):
        rule = item.path().fillRule() if isinstance(item, QtWidgets.QGraphicsPathItem) else item.fillRule()
        attrs.append(f"fill_rule={'evenodd' if rule == QtCore.Qt.FillRule.OddEvenFill else 'nonzero'!r}")
    data = style_data(item) or {}
    shadow = shadow_parameters(item)
    if shadow:
        dx, dy, radius, color, alpha = shadow
        qt_color = QtGui.QColor(color)
        qt_color.setAlphaF(alpha)
        data['shadow'] = {'offset_x': dx, 'offset_y': dy, 'blur_radius': radius, 'color': qt_color.name(QtGui.QColor.NameFormat.HexArgb)}
    else:
        data.pop('shadow', None)
    if opacity < 1:
        data['opacity'] = opacity
    if data:
        attrs.extend([_metadata('data_item_style', data), "data_xml_escaped='true'"])
    return attrs


def append_styled_item(lines: list[str], item: QtWidgets.QGraphicsItem, var_name: str) -> None:
    shadow = shadow_parameters(item)
    if shadow:
        bounds = item.sceneBoundingRect()
        pending = list(item.childItems())
        while pending:
            child = pending.pop()
            if not child.isVisible() or child.effectiveOpacity() <= 0:
                continue
            bounds = bounds.united(child.mapRectToScene(child.boundingRect()))
            pending.extend(child.childItems())
        rect = (bounds.x(), bounds.y(), bounds.width(), bounds.height())
        lines.append(f'    d.append(_drawsvg_effect({var_name}, {rect!r}, {shadow!r}))')
    else:
        lines.append(f'    d.append({var_name})')


def finish_styled_item(lines: list[str], start: int, item: QtWidgets.QGraphicsItem) -> None:
    """Apply an item effect once to all its primitives, including its label."""
    shadow = shadow_parameters(item)
    if not shadow:
        return
    lines.insert(start, '    _effect_source = draw.Group()')
    for index in range(start + 1, len(lines)):
        if lines[index].startswith('    d.append('):
            lines[index] = lines[index].replace('    d.append(', '    _effect_source.append(', 1)
    append_styled_item(lines, item, '_effect_source')
