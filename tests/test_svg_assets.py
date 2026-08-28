from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items.svg import SVG_ITEM_TYPE_ID, SvgItem
from items.svg_assets import SvgAssetError, SvgAssetParser, SvgLimits


SIMPLE_SVG = b"""\
<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">
  <rect id="shape" width="40" height="20" fill="#e02020"/>
</svg>
"""


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.parametrize(
    "source",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/a.png"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://example.test/a.svg#x)"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<!DOCTYPE svg [<!ENTITY x "boom">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
        b'<?xml-stylesheet href="https://example.test/a.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg" xml:base="https://example.test/"><use href="#local"/></svg>',
    ],
)
def test_parser_rejects_external_or_active_content(source):
    with pytest.raises(SvgAssetError):
        SvgAssetParser().parse(source)


def test_parser_enforces_depth_and_element_limits():
    deep_svg = "<svg>" + "<g>" * 5 + "</g>" * 5 + "</svg>"
    with pytest.raises(SvgAssetError, match="depth"):
        SvgAssetParser(SvgLimits(max_depth=5)).parse(deep_svg)

    many_elements = "<svg>" + "<rect/>" * 5 + "</svg>"
    with pytest.raises(SvgAssetError, match="element count"):
        SvgAssetParser(SvgLimits(max_elements=5)).parse(many_elements)


def test_parser_bounds_use_expansion_and_rejects_cycles():
    expansion = b"""\
    <svg xmlns="http://www.w3.org/2000/svg">
      <defs><g id="many"><rect/><rect/><rect/></g></defs>
      <use href="#many"/><use href="#many"/>
    </svg>
    """
    with pytest.raises(SvgAssetError, match="use expansion"):
        SvgAssetParser(SvgLimits(max_use_expansions=7)).parse(expansion)

    cycle = b"""\
    <svg xmlns="http://www.w3.org/2000/svg">
      <defs><g id="a"><use href="#b"/></g><g id="b"><use href="#a"/></g></defs>
      <use href="#a"/>
    </svg>
    """
    with pytest.raises(SvgAssetError, match="Cyclic use"):
        SvgAssetParser().parse(cycle)


def test_use_budget_interrupts_branched_expansion():
    definitions = ['<g id="level0"><rect/></g>']
    for level in range(1, 16):
        definitions.append(
            f'<g id="level{level}"><use href="#level{level - 1}"/>'
            f'<use href="#level{level - 1}"/></g>'
        )
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg"><defs>'
        + "".join(definitions)
        + '</defs><use href="#level15"/></svg>'
    )

    with pytest.raises(SvgAssetError, match="use expansion"):
        SvgAssetParser(SvgLimits(max_use_expansions=100)).parse(source)


def test_storage_and_clipboard_roundtrip_revalidate_digest():
    parser = SvgAssetParser()
    asset = parser.parse(SIMPLE_SVG)

    assert parser.restore(asset.storage_record(), asset.data) == asset
    assert parser.from_clipboard(asset.clipboard_payload()) == asset

    tampered = asset.clipboard_payload()
    tampered["asset_id"] = "sha256:" + "0" * 64
    with pytest.raises(SvgAssetError, match="digest"):
        parser.from_clipboard(tampered)


def test_rejected_svg_does_not_mutate_scene(app):
    scene = QtWidgets.QGraphicsScene()
    before = tuple(scene.items())

    with pytest.raises(SvgAssetError):
        SvgItem.add_validated_to_scene(
            scene,
            b'<svg xmlns="http://www.w3.org/2000/svg"><use href="https://example.test/a.svg#x"/></svg>',
        )

    assert tuple(scene.items()) == before


def test_svg_item_project_payload_roundtrip_and_scene_render(app):
    asset = SvgAssetParser().parse(SIMPLE_SVG)
    item = SvgItem(asset, x=7, y=9, width=80, height=40)
    item.setRotation(15)
    item.setScale(1.25)
    item.setZValue(3)

    payload = item.to_item_payload()
    assert payload["type_id"] == SVG_ITEM_TYPE_ID
    assert "data" not in payload

    restored = SvgItem.from_item_payload(payload, {asset.asset_id: asset})
    assert restored.asset_id == asset.asset_id
    assert restored.pos() == QtCore.QPointF(7, 9)
    assert restored.boundingRect().size() == QtCore.QSizeF(80, 40)
    assert restored.rotation() == 15
    assert restored.scale() == 1.25

    scene = QtWidgets.QGraphicsScene()
    restored.setPos(0, 0)
    restored.setRotation(0)
    restored.setScale(1)
    scene.addItem(restored)
    image = QtGui.QImage(80, 40, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    scene.render(painter, QtCore.QRectF(0, 0, 80, 40), restored.boundingRect())
    painter.end()

    assert QtGui.QColor(image.pixel(40, 20)).alpha() > 0


def test_svg_item_clipboard_factory(app):
    asset = SvgAssetParser().parse(SIMPLE_SVG)
    item = SvgItem.from_clipboard_payload(asset.clipboard_payload(), x=4, y=5)

    assert item.asset_id == asset.asset_id
    assert item.pos() == QtCore.QPointF(4, 5)
