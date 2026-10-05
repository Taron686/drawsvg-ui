from __future__ import annotations

import base64
from xml.etree import ElementTree as ET

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items.svg import SvgItem
from items.svg_assets import SvgAssetParser
from test_drawsvg_python_assets import _export, _rect


def _pixel(image, bounds, x, y):
    return image.pixelColor(round(x - bounds.left()), round(y - bounds.top()))


def test_percentage_svg_dimensions_keep_the_asset_viewport(application, monkeypatch, tmp_path):
    source = b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="100%" height="100%" fill="red"/></svg>'
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(SvgItem(SvgAssetParser().parse(source), 0, 0, 20, 20))
    scene.addItem(_rect(100, 0, 20, 20))
    root, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    assert _pixel(image, bounds, 10, 10) == QtGui.QColor("red")
    for x in (30, 50, 90):
        assert _pixel(image, bounds, x, 10) == QtGui.QColor("white")
    image_node = next(node for node in root.iter() if node.tag.endswith("image"))
    uri = image_node.get("href")
    assert uri.startswith("data:image/svg+xml;base64,")
    document = ET.fromstring(base64.b64decode(uri.split(",", 1)[1]))
    assert document.tag.endswith("svg")
    assert next(node for node in document if node.tag.endswith("rect")).get("width") == "100%"


def test_offset_viewbox_stretches_under_a_scene_affine_transform(application, monkeypatch, tmp_path):
    source = b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10" viewBox="10 20 20 10" preserveAspectRatio="xMidYMid meet"><rect x="10" y="20" width="20" height="10" fill="red"/></svg>'
    scene = QtWidgets.QGraphicsScene()
    item = SvgItem(SvgAssetParser().parse(source), 40, 30, 60, 50)
    item.setTransform(QtGui.QTransform(1, .2, .3, 1, 0, 0))
    scene.addItem(item)
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    for local in (QtCore.QPointF(30, 3), QtCore.QPointF(30, 47)):
        point = item.mapToScene(local)
        assert _pixel(image, bounds, point.x(), point.y()) == QtGui.QColor("red")


@pytest.mark.parametrize("selector", ["rect", ".painted", "svg rect", "svg > rect"])
def test_svg_styles_are_confined_to_each_instance(application, monkeypatch, tmp_path, selector):
    scene = QtWidgets.QGraphicsScene()
    for x, color in ((0, "#2040e0"), (40, "#20e040")):
        source = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><style>{selector} {{fill: {color};}}</style><rect class="painted" width="20" height="20"/></svg>'.encode()
        scene.addItem(SvgItem(SvgAssetParser().parse(source), x, 0, 20, 20))
    unrelated = _rect(80, 0, 20, 20)
    unrelated.setBrush(QtGui.QColor("#e02020"))
    scene.addItem(unrelated)
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    for x, color in ((10, "#2040e0"), (50, "#20e040"), (90, "#e02020")):
        assert _pixel(image, bounds, x, 10) == QtGui.QColor(color)


def test_root_styles_and_gradient_references_survive_embedding(application, monkeypatch, tmp_path):
    source = b'''<svg xmlns="http://www.w3.org/2000/svg" id="root" viewBox="0 0 20 20">
      <style>svg rect {fill: url(#paint);} #root > rect {stroke: #2040e0; stroke-width: 2;}</style>
      <defs><linearGradient id="paint"><stop stop-color="#20e040"/></linearGradient></defs>
      <rect width="20" height="20"/>
    </svg>'''
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(SvgItem(SvgAssetParser().parse(source), 0, 0, 20, 20))
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    assert _pixel(image, bounds, 10, 10) == QtGui.QColor("#20e040")
    assert _pixel(image, bounds, 0, 10) == QtGui.QColor("#2040e0")


@pytest.mark.parametrize("aspect", ["none", "xMidYMid meet", "xMaxYMax slice"])
def test_embedded_vector_matches_the_source_renderer(application, monkeypatch, tmp_path, aspect):
    source = f'''<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="10 20 20 10" preserveAspectRatio="{aspect}">
      <rect x="10" y="20" width="10" height="10" fill="#2040e0"/>
      <rect x="20" y="20" width="10" height="10" fill="#20e040"/>
    </svg>'''.encode()
    scene = QtWidgets.QGraphicsScene()
    item = SvgItem(SvgAssetParser().parse(source), 40, 30, 60, 50)
    item.setTransform(QtGui.QTransform(1, .2, .3, 1, 0, 0))
    scene.addItem(item)
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    expected = QtGui.QImage(image.size(), image.format())
    expected.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(expected)
    painter.translate(-bounds.left(), -bounds.top())
    painter.setWorldTransform(item.sceneTransform(), True)
    item._renderer.render(painter, item.boundingRect())
    painter.end()
    for x in (8, 20, 40, 52):
        for y in (3, 25, 47):
            point = item.mapToScene(QtCore.QPointF(x, y))
            assert _pixel(image, bounds, point.x(), point.y()) == _pixel(expected, bounds, point.x(), point.y())


def test_embedded_vector_clips_content_at_its_own_viewport(application, monkeypatch, tmp_path):
    source = b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="100" height="100" fill="red"/></svg>'
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(SvgItem(SvgAssetParser().parse(source), 0, 0, 20, 20))
    scene.addItem(_rect(100, 0, 20, 20))
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    assert _pixel(image, bounds, 10, 10) == QtGui.QColor("red")
    for x in (30, 50, 90):
        assert _pixel(image, bounds, x, 10) == QtGui.QColor("white")


def test_separate_vectors_preserve_same_named_gradient_references(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    for x, color in ((0, "#2040e0"), (40, "#20e040")):
        source = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <style>svg #painted {{fill: url(#paint);}}</style>
          <defs><linearGradient id="paint"><stop stop-color="{color}"/></linearGradient></defs>
          <rect id="painted" width="20" height="20"/>
        </svg>'''.encode()
        scene.addItem(SvgItem(SvgAssetParser().parse(source), x, 0, 20, 20))
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    assert _pixel(image, bounds, 10, 10) == QtGui.QColor("#2040e0")
    assert _pixel(image, bounds, 50, 10) == QtGui.QColor("#20e040")


@pytest.mark.parametrize("scale, rotation", [(1, 0), (2, 23)])
def test_scaled_vector_keeps_sharp_edges_in_qt(application, monkeypatch, tmp_path, scale, rotation):
    source = b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="8" fill="red"/><path d="M 1 1 L 19 19" stroke="blue" stroke-width=".5"/></svg>'
    scene = QtWidgets.QGraphicsScene()
    item = SvgItem(SvgAssetParser().parse(source), 0, 0, 300, 300)
    item.setScale(scale)
    item.setRotation(rotation)
    scene.addItem(item)
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    expected = QtGui.QImage(image.size(), image.format())
    expected.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(expected)
    painter.translate(-bounds.left(), -bounds.top())
    painter.setWorldTransform(item.sceneTransform(), True)
    item._renderer.render(painter, item.boundingRect())
    painter.end()
    # Native 20px decoding introduces a broad blurred fringe when enlarged.
    for x in (45, 50, 55, 60):
        point = item.mapToScene(QtCore.QPointF(x, 80))
        assert _pixel(image, bounds, point.x(), point.y()) == _pixel(expected, bounds, point.x(), point.y())
