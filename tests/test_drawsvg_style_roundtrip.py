from __future__ import annotations

import ast
import runpy
from xml.etree import ElementTree as ET

import pytest
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from asset_service import BitmapAssetService
from bitmap_item import BitmapItem
from export_drawsvg import export_drawsvg_py
from import_drawsvg import import_drawsvg_py
from items import RectItem
from items.svg import SvgItem
from items.svg_assets import SvgAssetParser
from shape_registry import SHAPE_REGISTRY

NS = {'svg': 'http://www.w3.org/2000/svg'}


def _export_roundtrip(scene, monkeypatch, tmp_path, name):
    path = tmp_path / f'{name}.py'
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), ''))
    export_drawsvg_py(scene)
    code = path.read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            assert all(alias.name in {'drawsvg', 'math', 'html', 'base64', 'json', 'xml.etree.ElementTree'} for alias in node.names)
        assert not isinstance(node, ast.ImportFrom)
    svg = runpy.run_path(str(path))['build_drawing']().as_svg()
    renderer = QtSvg.QSvgRenderer(svg.encode())
    assert renderer.isValid()
    image = QtGui.QImage(renderer.defaultSize(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    return path, ET.fromstring(svg), image


def _styled_asset(kind):
    if kind == 'svg':
        data = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="20" height="10" fill="red"/></svg>'
        return SvgItem(SvgAssetParser().parse(data), width=60, height=30)
    image = QtGui.QImage(20, 10, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.red)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, 'PNG')
    return BitmapItem(BitmapAssetService().import_bytes(bytes(data)).asset, width=60, height=30)


@pytest.mark.parametrize('width', [0, 3])
def test_cosmetic_pen_survives_safe_roundtrip(application, monkeypatch, tmp_path, width):
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create('Line', 0, 0, 100, 60)
    scene.addItem(item)
    pen = QtGui.QPen(QtGui.QColor(10, 20, 30, 96))
    pen.setWidthF(width)
    pen.setCosmetic(True)
    pen.setDashPattern([2, 1, 4, 1])
    pen.setDashOffset(1.5)
    item.setPen(pen)
    item.setScale(3)
    path, first, first_image = _export_roundtrip(scene, monkeypatch, tmp_path, 'first')
    restored_scene = QtWidgets.QGraphicsScene()
    assert import_drawsvg_py(restored_scene, path=path) == path
    restored = next(i for i in restored_scene.items() if i.parentItem() is None)
    assert restored.pen().widthF() == width
    assert restored.pen().isCosmetic()
    assert restored.pen().dashPattern() == pytest.approx(pen.dashPattern())
    assert restored.pen().dashOffset() == pytest.approx(1.5)
    assert restored.pen().color().alpha() == 96
    _, second, second_image = _export_roundtrip(restored_scene, monkeypatch, tmp_path, 'second')
    for attribute in ('stroke-width', 'vector-effect', 'stroke-dasharray', 'stroke-dashoffset', 'stroke-opacity', 'transform'):
        assert second.find('svg:path', NS).get(attribute) == first.find('svg:path', NS).get(attribute)
    assert first_image == second_image


@pytest.mark.parametrize('kind', ['bitmap', 'svg'])
def test_asset_shadow_survives_safe_roundtrip(application, monkeypatch, tmp_path, kind):
    scene = QtWidgets.QGraphicsScene()
    group = QtWidgets.QGraphicsItemGroup()
    scene.addItem(group)
    item = _styled_asset(kind)
    scene.addItem(item)
    group.addToGroup(item)
    group.setOpacity(0.5)
    group.setTransform(QtGui.QTransform(1, 0.2, 0.3, 1, 20, 30))
    item.setOpacity(0.6)
    item.setScale(2)
    item.setRotation(12)
    effect = QtWidgets.QGraphicsDropShadowEffect()
    effect.setOffset(16, -7)
    effect.setBlurRadius(8)
    effect.setColor(QtGui.QColor(12, 34, 56, 128))
    item.setGraphicsEffect(effect)
    path, first, first_image = _export_roundtrip(scene, monkeypatch, tmp_path, 'first')
    for turn in range(2):
        restored_scene = QtWidgets.QGraphicsScene()
        assert import_drawsvg_py(restored_scene, path=path) == path
        restored = next(i for i in restored_scene.items() if i.parentItem() is None)
        shadow = restored.graphicsEffect()
        assert isinstance(shadow, QtWidgets.QGraphicsDropShadowEffect)
        assert shadow.offset() == QtCore.QPointF(16, -7)
        assert shadow.blurRadius() == 8
        assert shadow.color() == effect.color()
        assert restored.opacity() == pytest.approx(0.3)
        path, second, second_image = _export_roundtrip(restored_scene, monkeypatch, tmp_path, f'second{turn}')
        for tag in ('feOffset', 'feFlood', 'feGaussianBlur'):
            assert second.find(f'.//svg:{tag}', NS).attrib == first.find(f'.//svg:{tag}', NS).attrib
        assert first_image == second_image


@pytest.mark.parametrize('kind', ['bitmap', 'svg'])
@pytest.mark.parametrize('invalid', ['[]', '{broken', '{"shadow":{"offset_x":"broken"}}', '{"opacity":NaN}', '{"shadow":{"blur_radius":Infinity}}'])
def test_asset_style_metadata_rejects_malformed_input(application, monkeypatch, tmp_path, kind, invalid):
    scene = QtWidgets.QGraphicsScene()
    item = _styled_asset(kind)
    scene.addItem(item)
    path, _, _ = _export_roundtrip(scene, monkeypatch, tmp_path, 'invalid')
    module = ast.parse(path.read_text(encoding='utf-8'))
    name = '_bitmap' if kind == 'bitmap' else '_svg'
    statement = next(n for n in ast.walk(module) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
    if kind == 'bitmap':
        statement.value.keywords.append(ast.keyword(arg='data_item_style', value=ast.Constant(invalid)))
    else:
        wrapper = ET.fromstring(ast.literal_eval(statement.value.args[0]))
        wrapper.set('data-item-style', invalid)
        statement.value.args[0] = ast.Constant(ET.tostring(wrapper, encoding='unicode'))
    path.write_text('d = draw.Drawing(200, 200)\n_rect = draw.Rectangle(0, 0, 20, 20)\n' + ast.unparse(statement), encoding='utf-8')
    target = QtWidgets.QGraphicsScene()
    existing = RectItem(5, 6, 7, 8)
    target.addItem(existing)
    messages = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'critical', lambda *args: messages.append(args[-1]))
    assert import_drawsvg_py(target, path=path) is None
    assert messages
    assert [i for i in target.items() if i.parentItem() is None] == [existing]
    assert existing.rect() == QtCore.QRectF(0, 0, 7, 8)
