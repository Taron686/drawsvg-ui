from __future__ import annotations

import ast
import base64
import runpy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from asset_service import BitmapAssetService
from bitmap_item import BitmapItem
from connectors import ConnectorEndpoint, ConnectorItem
from export_drawsvg import export_drawsvg_py
from items import RectItem
from items.svg import SvgItem
from items.svg_assets import SvgAssetParser
from scene_codec import KEY_TRANSIENT


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 20 10"><rect x="10" y="20" width="20" height="10" fill="#e02020"/></svg>'


def _bitmap() -> BitmapItem:
    image = QtGui.QImage(12, 8, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("#e02020"))
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    asset = BitmapAssetService().import_bytes(bytes(data)).asset
    return BitmapItem(asset, 120, 50, 60, 50)


def _svg() -> SvgItem:
    return SvgItem(SvgAssetParser().parse(SVG), 120, 50, 60, 50)


def _connector() -> ConnectorItem:
    item = ConnectorItem(
        ConnectorEndpoint.free(QtCore.QPointF(120, 50)),
        ConnectorEndpoint.free(QtCore.QPointF(180, 100)),
        pen=QtGui.QPen(QtGui.QColor("#e02020"), 4),
    )
    item.set_route_points([QtCore.QPointF(120, 50), QtCore.QPointF(180, 50), QtCore.QPointF(180, 100)])
    return item


def _rect(x=0, y=0, width=20, height=20):
    item = RectItem(x, y, width, height)
    item.setData(0, "Rectangle")
    return item


def _export(scene, monkeypatch, tmp_path):
    output = tmp_path / "scene.py"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **kw: (str(output), "Python (*.py)"))
    export_drawsvg_py(scene)
    module = ast.parse(output.read_text(encoding="utf-8"))
    imports = [node.names[0].name for node in module.body if isinstance(node, ast.Import)]
    assert set(imports) <= {"drawsvg", "math", "base64", "json", "html", "xml.etree.ElementTree"}
    generated = runpy.run_path(str(output))
    svg_path = tmp_path / "scene.svg"
    generated["build_drawing"]().save_svg(str(svg_path))
    root = ET.fromstring(svg_path.read_bytes())
    renderer = QtSvg.QSvgRenderer(str(svg_path))
    assert renderer.isValid()
    bounds = renderer.viewBoxF()
    image = QtGui.QImage(round(bounds.width()), round(bounds.height()), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    return root, bounds, image, output


@pytest.mark.parametrize("factory", [_bitmap, _svg, _connector], ids=["bitmap", "svg", "connector"])
@pytest.mark.parametrize("mixed", [False, True], ids=["alone", "mixed"])
def test_export_preserves_assets_geometry_and_rendered_content(application, monkeypatch, tmp_path, factory, mixed):
    scene = QtWidgets.QGraphicsScene()
    item = factory()
    item.setRotation(23)
    scene.addItem(item)
    if mixed:
        scene.addItem(_rect())
    root, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    assert bounds.contains(item.sceneBoundingRect())
    assert any(image.pixelColor(x, y).red() > 150 and image.pixelColor(x, y).green() < 70 for y in range(image.height()) for x in range(image.width()))
    if isinstance(item, BitmapItem):
        nodes = [node for node in root.iter() if node.tag.endswith("image")]
        assert len(nodes) == 1
        href = nodes[0].get("{http://www.w3.org/1999/xlink}href") or nodes[0].get("href")
        assert base64.b64decode(href.split(",", 1)[1]) == item.asset.data
        assert nodes[0].get("preserveAspectRatio") == "none"
    elif isinstance(item, SvgItem):
        assert any(node.get("data-asset-svg") for node in root.iter())
    else:
        route = next(node for node in root.iter() if node.get("data-connector"))
        assert "180" in route.get("d")
        assert route.get("stroke") == "#e02020"
        assert float(route.get("stroke-width")) == 4


def test_hidden_and_transient_items_do_not_expand_export(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    visible = _rect()
    visible.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    scene.addItem(visible)
    group = QtWidgets.QGraphicsItemGroup()
    scene.addItem(group)
    hidden = _bitmap()
    scene.addItem(hidden)
    group.addToGroup(hidden)
    group.setVisible(False)
    guide = _rect(-5000, -5000, 10000, 10000)
    guide.setData(KEY_TRANSIENT, True)
    scene.addItem(guide)
    root, bounds, _, _ = _export(scene, monkeypatch, tmp_path)
    assert bounds == QtCore.QRectF(-5, -5, 30, 30)
    assert not any(node.tag.endswith("image") for node in root.iter())


def test_assets_follow_scene_stacking_order_and_full_parent_transform(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    group = QtWidgets.QGraphicsItemGroup()
    group.setTransform(QtGui.QTransform(1, .3, .2, 1, 30, 40))
    scene.addItem(group)
    bitmap = _bitmap()
    scene.addItem(bitmap)
    bitmap.setParentItem(group)
    svg = _svg()
    scene.addItem(svg)
    svg.setZValue(2)
    rect = _rect()
    rect.setZValue(1)
    scene.addItem(rect)
    root, bounds, _, _ = _export(scene, monkeypatch, tmp_path)
    exported = [node for node in root if node.tag.rsplit("}", 1)[-1] not in {"defs"}][1:]
    assert exported[0].tag.endswith("image")
    assert "matrix(1.000000 0.300000 0.200000 1.000000" in exported[0].get("transform")
    assert exported[1].tag.endswith("rect")
    assert exported[2].get("data-asset-svg")
    assert bounds.contains(bitmap.sceneBoundingRect())


def test_asset_display_stretches_to_rectangle(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_svg())
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    # The SVG's 2:1 source fills the item's 60x50 display rectangle in Qt.
    assert image.pixelColor(round(150 - bounds.left()), round(52 - bounds.top())).green() < 70
    assert image.pixelColor(round(150 - bounds.left()), round(98 - bounds.top())).green() < 70


def test_shape_label_bounds_and_shadow_extents_are_included(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    rect = _rect()
    rect.set_label_text("Label much wider than its shape")
    rect.label_item().setPos(100, 50)
    scene.addItem(rect)
    effect = QtWidgets.QGraphicsDropShadowEffect()
    effect.setOffset(80, 60)
    effect.setBlurRadius(10)
    rect.setGraphicsEffect(effect)
    _, bounds, _, _ = _export(scene, monkeypatch, tmp_path)
    assert bounds.contains(rect.label_item().sceneBoundingRect())
    assert bounds.contains(rect.mapRectToScene(effect.boundingRectFor(rect.boundingRect())))


def test_inline_svg_instances_isolate_ids_in_attributes_and_css(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    source = b'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 20 10">
      <style>#painted { fill: url(#paint); }</style>
      <defs><linearGradient id="paint"><stop stop-color="#e02020"/></linearGradient><rect id="tile" width="20" height="10" fill="url(#paint)"/></defs>
      <use id="painted" xlink:href="#tile"/>
    </svg>'''
    asset = SvgAssetParser().parse(source)
    scene.addItem(SvgItem(asset, 120, 50, 60, 50))
    scene.addItem(SvgItem(asset, 220, 50, 60, 50))
    root, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    wrappers = [node for node in root.iter() if node.get("data-asset-svg")]
    assert len(wrappers) == 2
    # Each vector is a separate SVG document, so local IDs and styles cannot
    # collide even when two instances preserve the same original names.
    for wrapper in wrappers:
        vector = next(node for node in wrapper if node.tag.endswith("image"))
        uri = vector.get("href") or vector.get("{http://www.w3.org/1999/xlink}href")
        assert uri.startswith("data:image/svg+xml;base64,")
        document = ET.fromstring(base64.b64decode(uri.split(",", 1)[1]))
        ids = {node.get("id") for node in document.iter() if node.get("id")}
        assert ids == {"paint", "tile", "painted"}
        style = next(node for node in document.iter() if node.tag.endswith("style"))
        assert "url(#paint)" in style.text
        assert "#painted {" in style.text
        use = next(node for node in document.iter() if node.tag.endswith("use"))
        assert use.get("{http://www.w3.org/1999/xlink}href")[1:] in ids
    for x in (150, 250):
        pixel = image.pixelColor(round(x - bounds.left()), round(75 - bounds.top()))
        assert pixel.red() > 150 and pixel.green() < 70


def test_empty_visible_scene_ignores_hidden_asset_bounds(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = _bitmap()
    item.setVisible(False)
    scene.addItem(item)
    root, bounds, _, _ = _export(scene, monkeypatch, tmp_path)
    assert bounds == QtCore.QRectF(-5, -5, 10, 10)
    assert not any(node.tag.endswith("image") for node in root.iter())


def test_transformed_shadow_bounds_keep_qt_scene_offset(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = _rect(0, 0, 20, 20)
    item.setPos(100, 100)
    item.setRotation(180)
    item.setScale(2)
    effect = QtWidgets.QGraphicsDropShadowEffect()
    effect.setOffset(80, 60)
    effect.setBlurRadius(10)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    _, bounds, _, _ = _export(scene, monkeypatch, tmp_path)
    # Qt's shadow offset and blur are device/scene coordinates at export scale 1.
    assert bounds.contains(effect.boundingRectFor(item.sceneBoundingRect()))


def test_svg_stylesheet_does_not_restyle_other_scene_items(application, monkeypatch, tmp_path):
    source = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><style>rect { fill: #2040e0; }</style><rect width="20" height="10"/></svg>'
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(SvgItem(SvgAssetParser().parse(source), 120, 50, 60, 50))
    rect = _rect()
    rect.setBrush(QtGui.QColor("#e02020"))
    scene.addItem(rect)
    _, bounds, image, _ = _export(scene, monkeypatch, tmp_path)
    source_pixel = image.pixelColor(round(150 - bounds.left()), round(75 - bounds.top()))
    unrelated_pixel = image.pixelColor(round(10 - bounds.left()), round(10 - bounds.top()))
    assert source_pixel.blue() > 150 and source_pixel.red() < 70
    assert unrelated_pixel.red() > 150 and unrelated_pixel.blue() < 70


def test_valid_empty_svg_asset_exports_metadata(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    asset = SvgAssetParser().parse(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    scene.addItem(SvgItem(asset, 10, 20, 30, 40))
    root, bounds, _, _ = _export(scene, monkeypatch, tmp_path)
    assert bounds == QtCore.QRectF(5, 15, 40, 50)
    assert any(node.get("data-asset-svg") for node in root.iter())


def test_large_shadow_bounds_contain_generated_filter_region(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = _rect()
    item.setPos(100, 100)
    item.setRotation(180)
    item.setScale(2)
    effect = QtWidgets.QGraphicsDropShadowEffect()
    effect.setOffset(80, 60)
    effect.setBlurRadius(40)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    _, bounds, _, _ = _export(scene, monkeypatch, tmp_path)
    # Source bounds are [88,88,44,44], 3 sigma=60, scene offset=(80,60).
    assert bounds.contains(QtCore.QRectF(28, 28, 244, 224))
