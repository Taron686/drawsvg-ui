from __future__ import annotations

import ast
import runpy
from xml.etree import ElementTree as ET

import pytest
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from export_drawsvg import export_drawsvg_py
from shape_registry import SHAPE_REGISTRY
from style_presets import KEY_STYLE, apply_preset

NS = {'svg': 'http://www.w3.org/2000/svg'}


def _export(scene, monkeypatch, tmp_path):
    path = tmp_path / 'styles.py'
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), ''))
    export_drawsvg_py(scene)
    code = path.read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            assert all(alias.name == 'drawsvg' for alias in node.names)
        assert not isinstance(node, ast.ImportFrom)
    svg = runpy.run_path(str(path))['build_drawing']().as_svg()
    return ET.fromstring(svg), svg


def _scene(type_id='Rectangle'):
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create(type_id, 0, 0, 100, 60)
    assert item is not None
    scene.addItem(item)
    return scene, item


@pytest.mark.parametrize('preset,colors', [('ocean', ['#d7f0ff', '#2686c2']), ('sunset', ['#ffe2bf', '#e36c54'])])
def test_preset_exports_native_gradient_stops(application, monkeypatch, tmp_path, preset, colors):
    scene, item = _scene()
    apply_preset(item, preset)
    root, _ = _export(scene, monkeypatch, tmp_path)
    gradient = root.find('.//svg:linearGradient', NS)
    assert gradient is not None
    stops = gradient.findall('svg:stop', NS)
    assert [stop.get('stop-color') for stop in stops] == colors
    assert [float(stop.get('offset')) for stop in stops] == [0, 1]
    shape = root.findall('svg:rect', NS)[-1]
    assert shape.get('fill') == f"url(#{gradient.get('id')})"


@pytest.mark.parametrize('kind', ['linear', 'radial'])
def test_logical_gradient_keeps_transform_spread_and_stop_alpha(application, monkeypatch, tmp_path, kind):
    scene, item = _scene()
    gradient = QtGui.QLinearGradient(5, 7, 80, 40) if kind == 'linear' else QtGui.QRadialGradient(40, 30, 22, 35, 25)
    gradient.setSpread(QtGui.QGradient.Spread.ReflectSpread)
    gradient.setColorAt(0, QtGui.QColor(255, 0, 0, 64))
    gradient.setColorAt(1, QtGui.QColor(0, 0, 255, 192))
    brush = QtGui.QBrush(gradient)
    brush.setTransform(QtGui.QTransform(1, 0.2, 0.3, 2, 8, 9))
    item.setBrush(brush)
    root, _ = _export(scene, monkeypatch, tmp_path)
    definition = root.find(f'.//svg:{kind}Gradient', NS)
    assert definition is not None
    assert definition.get('gradientUnits') == 'userSpaceOnUse'
    assert definition.get('gradientTransform') == 'matrix(1 0.2 0.3 2 8 9)'
    assert definition.get('spreadMethod') == 'reflect'
    assert [float(s.get('stop-opacity')) for s in definition.findall('svg:stop', NS)] == pytest.approx([64 / 255, 192 / 255])
    if kind == 'radial':
        assert [float(definition.get(a)) for a in ('cx', 'cy', 'r', 'fx', 'fy')] == [40, 30, 22, 35, 25]


@pytest.mark.parametrize('type_id,tag', [('Rectangle', 'rect'), ('Line', 'path'), ('Free Polygon', 'path')])
def test_pen_alpha_dashes_caps_and_joins_are_consistent(application, monkeypatch, tmp_path, type_id, tag):
    scene, item = _scene(type_id)
    pen = QtGui.QPen(QtGui.QColor(10, 20, 30, 96))
    pen.setWidthF(3)
    pen.setDashPattern([2, 1, 4, 1])
    pen.setDashOffset(1.5)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.BevelJoin)
    item.setPen(pen)
    root, _ = _export(scene, monkeypatch, tmp_path)
    element = root.findall(f'svg:{tag}', NS)[-1]
    assert float(element.get('stroke-opacity')) == pytest.approx(96 / 255)
    assert float(element.get('stroke-width')) == 3
    assert list(map(float, element.get('stroke-dasharray').split())) == [6, 3, 12, 3]
    assert float(element.get('stroke-dashoffset')) == 4.5
    assert element.get('stroke-linecap') == 'round'
    assert element.get('stroke-linejoin') == 'bevel'


@pytest.mark.parametrize('type_id,tag', [('Rectangle', 'rect'), ('Line', 'path'), ('Free Polygon', 'path')])
def test_no_pen_exports_no_stroke(application, monkeypatch, tmp_path, type_id, tag):
    scene, item = _scene(type_id)
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    root, _ = _export(scene, monkeypatch, tmp_path)
    assert root.findall(f'svg:{tag}', NS)[-1].get('stroke') == 'none'


@pytest.mark.parametrize('blur', [0, 8])
def test_shadow_exports_structured_filter_with_scene_coordinates(application, monkeypatch, tmp_path, blur):
    scene, item = _scene()
    item.setScale(2)
    item.setRotation(30)
    effect = QtWidgets.QGraphicsDropShadowEffect()
    effect.setOffset(16, -7)
    effect.setBlurRadius(blur)
    effect.setColor(QtGui.QColor(12, 34, 56, 128))
    item.setGraphicsEffect(effect)
    root, _ = _export(scene, monkeypatch, tmp_path)
    filter_ = root.find('.//svg:filter', NS)
    assert filter_ is not None
    assert filter_.get('filterUnits') == 'userSpaceOnUse'
    assert filter_.get('primitiveUnits') == 'userSpaceOnUse'
    offset = filter_.find('svg:feOffset', NS)
    assert [float(offset.get(a)) for a in ('dx', 'dy')] == [16, -7]
    flood = filter_.find('svg:feFlood', NS)
    assert flood.get('flood-color') == '#0c2238'
    assert float(flood.get('flood-opacity')) == pytest.approx(128 / 255)
    assert filter_.find('svg:feComposite', NS) is not None
    merge = filter_.find('svg:feMerge', NS)
    assert merge is not None
    assert merge.findall('svg:feMergeNode', NS)[-1].get('in') == 'SourceGraphic'
    assert (filter_.find('svg:feGaussianBlur', NS) is not None) == bool(blur)
    group = root.find(f".//svg:g[@filter='url(#{filter_.get('id')})']", NS)
    assert group is not None and group.get('transform') is None
    assert group.find('.//svg:rect', NS) is not None
    assert not root.findall('.//svg:image', NS)
    bounds = item.sceneBoundingRect()
    x, y, w, h = (float(filter_.get(a)) for a in ('x', 'y', 'width', 'height'))
    assert x <= min(bounds.left(), bounds.left() + 16) - blur
    assert y <= min(bounds.top(), bounds.top() - 7) - blur
    assert x + w >= max(bounds.right(), bounds.right() + 16) + blur
    assert y + h >= max(bounds.bottom(), bounds.bottom() - 7) + blur


def test_transformed_child_keeps_effective_opacity(application, monkeypatch, tmp_path):
    scene, item = _scene()
    group = QtWidgets.QGraphicsItemGroup()
    scene.addItem(group)
    group.addToGroup(item)
    group.setOpacity(0.4)
    group.setRotation(20)
    item.setOpacity(0.5)
    item.setBrush(QtGui.QColor(255, 0, 0, 64))
    root, _ = _export(scene, monkeypatch, tmp_path)
    shape = root.findall('svg:rect', NS)[-1]
    assert float(shape.get('opacity')) == pytest.approx(0.2)
    assert float(shape.get('fill-opacity')) == pytest.approx(64 / 255)
    assert shape.get('transform').startswith('matrix(')


def test_compound_free_path_keeps_odd_even_hole_in_rendered_svg(application, monkeypatch, tmp_path):
    scene, item = _scene('Free Polygon')
    path = QtGui.QPainterPath()
    path.addRect(0, 0, 100, 60)
    path.addRect(25, 15, 50, 30)
    item.setPath(path)
    item.setBrush(QtGui.QColor('red'))
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    root, svg = _export(scene, monkeypatch, tmp_path)
    assert root.find('svg:path', NS).get('fill-rule') == 'evenodd'
    renderer = QtSvg.QSvgRenderer(svg.encode())
    assert renderer.isValid()
    image = QtGui.QImage(renderer.defaultSize(), QtGui.QImage.Format.Format_RGBA8888)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    assert image.pixelColor(55, 35).name() == '#ffffff'
    assert image.pixelColor(15, 15).name() == '#ff0000'


def test_invalid_shadow_metadata_is_ignored_safely(application, monkeypatch, tmp_path):
    scene, item = _scene()
    item.setData(KEY_STYLE, {'version': 1, 'shadow': {'offset_x': 'broken', 'blur_radius': float('nan')}})
    root, _ = _export(scene, monkeypatch, tmp_path)
    assert root.find('.//svg:filter', NS) is None


def test_split_top_gradient_and_divider_pen_keep_styles(application, monkeypatch, tmp_path):
    scene, item = _scene('Split Rounded Rectangle')
    gradient = QtGui.QLinearGradient(0, 0, 1, 0)
    gradient.setCoordinateMode(QtGui.QGradient.CoordinateMode.ObjectBoundingMode)
    gradient.setColorAt(0, QtGui.QColor('red'))
    gradient.setColorAt(1, QtGui.QColor('blue'))
    item.setTopBrush(QtGui.QBrush(gradient))
    item._divider_pen = QtGui.QPen(QtCore.Qt.PenStyle.NoPen)
    root, _ = _export(scene, monkeypatch, tmp_path)
    assert root.find('.//svg:linearGradient', NS) is not None
    assert root.find('svg:path', NS).get('fill').startswith('url(#')
    assert root.find('svg:path', NS).get('stroke') == 'none'


def test_split_effect_groups_all_primitives_once(application, monkeypatch, tmp_path):
    scene, item = _scene('Split Rounded Rectangle')
    apply_preset(item, 'soft-shadow')
    root, _ = _export(scene, monkeypatch, tmp_path)
    filters = root.findall('.//svg:filter', NS)
    assert len(filters) == 1
    group = root.find(f".//svg:g[@filter='url(#{filters[0].get('id')})']", NS)
    assert group is not None
    assert len(group.findall('.//svg:rect', NS)) == 1
    assert len(group.findall('.//svg:path', NS)) >= 2


def test_split_transparent_top_does_not_paint_bottom_brush_under_it(application, monkeypatch, tmp_path):
    scene, item = _scene('Split Rounded Rectangle')
    item.setTopBrush(QtGui.QColor(255, 0, 0, 128))
    item.setBrush(QtGui.QColor('blue'))
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    item._divider_pen = QtGui.QPen(QtCore.Qt.PenStyle.NoPen)
    root, svg = _export(scene, monkeypatch, tmp_path)
    renderer = QtSvg.QSvgRenderer(svg.encode())
    image = QtGui.QImage(renderer.defaultSize(), QtGui.QImage.Format.Format_RGBA8888)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    x, y, _, _ = map(float, root.get('viewBox').split())
    top = image.pixelColor(int(50-x), int(10-y))
    bottom = image.pixelColor(int(50-x), int(50-y))
    assert top.red() == 255 and 125 <= top.green() <= 128 and top.blue() == top.green()
    assert bottom.name() == '#0000ff'


@pytest.mark.parametrize('mode,translation', [(QtGui.QGradient.CoordinateMode.ObjectMode, (0.25, 0.1)), (QtGui.QGradient.CoordinateMode.ObjectBoundingMode, (25, 6))])
def test_object_gradient_brush_transform_matches_qt_interior_pixels(application, monkeypatch, tmp_path, mode, translation):
    scene, item = _scene()
    gradient = QtGui.QLinearGradient(0, 0, 1, 1)
    gradient.setCoordinateMode(mode)
    gradient.setColorAt(0, QtGui.QColor('red'))
    gradient.setColorAt(1, QtGui.QColor('blue'))
    brush = QtGui.QBrush(gradient)
    brush.setTransform(QtGui.QTransform.fromTranslate(*translation))
    item.setBrush(brush)
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    root, svg = _export(scene, monkeypatch, tmp_path)
    renderer = QtSvg.QSvgRenderer(svg.encode())
    actual = QtGui.QImage(renderer.defaultSize(), QtGui.QImage.Format.Format_RGBA8888)
    reference = QtGui.QImage(renderer.defaultSize(), QtGui.QImage.Format.Format_RGBA8888)
    actual.fill(QtCore.Qt.GlobalColor.white)
    reference.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(actual)
    renderer.render(painter)
    painter.end()
    x, y, w, h = map(float, root.get('viewBox').split())
    painter = QtGui.QPainter(reference)
    scene.render(painter, QtCore.QRectF(reference.rect()), QtCore.QRectF(x, y, w, h))
    painter.end()
    for px, py in ((20, 20), (45, 35), (75, 45), (95, 55)):
        actual_color = actual.pixelColor(px, py)
        reference_color = reference.pixelColor(px, py)
        assert max(abs(actual_color.red()-reference_color.red()), abs(actual_color.blue()-reference_color.blue())) <= 2


def test_cosmetic_zero_width_pen_keeps_one_pixel_dash_units(application, monkeypatch, tmp_path):
    scene, item = _scene('Line')
    pen = QtGui.QPen(QtGui.QColor('red'))
    pen.setWidthF(0)
    pen.setDashPattern([2, 1])
    item.setPen(pen)
    item.setScale(3)
    root, _ = _export(scene, monkeypatch, tmp_path)
    path = root.find('svg:path', NS)
    assert float(path.get('stroke-width')) == 1
    assert list(map(float, path.get('stroke-dasharray').split())) == [2, 1]
    assert path.get('vector-effect') == 'non-scaling-stroke'


def test_arrow_heads_inherit_item_opacity(application, monkeypatch, tmp_path):
    scene, item = _scene('Arrow')
    item.setOpacity(0.4)
    root, _ = _export(scene, monkeypatch, tmp_path)
    paths = root.findall('svg:path', NS)
    assert len(paths) >= 2
    assert all(float(path.get('opacity') or 1) == pytest.approx(0.4) for path in paths)


def test_folder_tree_group_keeps_item_opacity(application, monkeypatch, tmp_path):
    scene, item = _scene('Folder Tree')
    item.setOpacity(0.4)
    root, _ = _export(scene, monkeypatch, tmp_path)
    group = root.find('svg:g', NS)
    assert group is not None
    assert float(group.get('opacity') or 1) == pytest.approx(0.4)
