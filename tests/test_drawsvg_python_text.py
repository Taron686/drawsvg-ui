"""Execute Python exports and validate text/data at the SVG and AST boundaries."""
from __future__ import annotations

import ast
import base64
import html
import json
import runpy
from xml.etree import ElementTree as ET

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import export_drawsvg
import import_drawsvg
from items import FolderTreeItem, TextItem
from shape_registry import SHAPE_REGISTRY

SVG = "{http://www.w3.org/2000/svg}"
SPECIAL = 'O\'Brien "quoted" & <tag> &amp; &#160;\\path 🙂\n\nlast\n'
FAMILY = 'O\'Brien "Font" & <family>'


def _export(scene, monkeypatch, tmp_path):
    path = tmp_path / "generated.py"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    export_drawsvg.export_drawsvg_py(scene)
    code = path.read_text(encoding="utf-8")
    # Generated code must require only drawsvg and the standard library.
    assert all(node.names[0].name in {"drawsvg", "html", "json"}
               for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Import))
    drawing = runpy.run_path(str(path))["build_drawing"]()
    drawing.save_svg(str(tmp_path / "generated.svg"))
    root = ET.parse(tmp_path / "generated.svg").getroot()
    return path, root


@pytest.mark.parametrize("type_id", [definition.type_id for definition in SHAPE_REGISTRY.palette_definitions()])
def test_every_registered_shape_executes_and_saves_valid_xml(application, monkeypatch, tmp_path, type_id):
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create(type_id, 0, 0)
    scene.addItem(item)
    path, root = _export(scene, monkeypatch, tmp_path)
    metadata = [node.attrib for node in root.iter()]
    adapter = SHAPE_REGISTRY.definition_for_item(item).python_export_adapter
    if adapter == "diagram":
        value = next(attrs["data-diagram"] for attrs in metadata if "data-diagram" in attrs)
        assert json.loads(value)["type_id"] == type_id
    elif adapter == "free_path":
        value = next(attrs["data-free-path"] for attrs in metadata if "data-free-path" in attrs)
        assert json.loads(value) == item.path_payload()
    restored = QtWidgets.QGraphicsScene()
    assert import_drawsvg.import_drawsvg_py(restored, path=path) == path.resolve()
    assert any(candidate.data(0) == type_id for candidate in restored.items())


def test_raw_text_xml_attributes_and_ast_roundtrip_preserve_entities_and_newlines(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = TextItem(15, 20, 300, 220, auto_size=False)
    item.setData(0, "Text")
    item.setPlainText(SPECIAL)
    font = QtGui.QFont(FAMILY)
    font.setPixelSize(22)
    font.setBold(True)
    font.setItalic(True)
    font.setUnderline(True)
    item.setFont(font)
    scene.addItem(item)
    path, root = _export(scene, monkeypatch, tmp_path)
    node = next(node for node in root.iter(SVG + "text") if "data-raw-text" in node.attrib)
    assert node.attrib["data-raw-text"] == SPECIAL
    assert node.attrib["font-family"] == FAMILY
    assert node.attrib["font-weight"] == "bold"
    assert node.attrib["font-style"] == "italic"
    assert node.attrib["text-decoration"] == "underline"
    assert "&amp;" in "".join(node.itertext())
    restored = QtWidgets.QGraphicsScene()
    assert import_drawsvg.import_drawsvg_py(restored, path=path)
    copy = next(candidate for candidate in restored.items() if isinstance(candidate, TextItem))
    assert copy.toPlainText() == SPECIAL
    assert copy.font().family() == FAMILY
    assert copy.font().bold() and copy.font().italic() and copy.font().underline()


@pytest.mark.parametrize("horizontal,vertical,direction", [
    ("left", "top", "ltr"), ("center", "middle", "ltr"), ("right", "bottom", "rtl")])
def test_visual_line_positions_follow_qt_wrap_alignment_and_direction(application, monkeypatch, tmp_path, horizontal, vertical, direction):
    scene = QtWidgets.QGraphicsScene()
    item = TextItem(0, 0, 145, 300, auto_size=False)
    item.setData(0, "Text")
    item.setPlainText("A long line that wraps in its text box\nShort")
    item.set_text_alignment(horizontal=horizontal, vertical=vertical)
    item.set_text_direction(direction)
    scene.addItem(item)
    item.document().documentLayout().documentSize()
    expected = []
    block = item.document().begin()
    while block.isValid():
        layout = block.layout()
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            rect = line.naturalTextRect().translated(layout.position() + item._content_offset)
            x = rect.right() if direction == "rtl" else rect.left()
            y = layout.position().y() + line.y() + line.ascent() + item._content_offset.y()
            expected.append((x, y))
        block = block.next()
    assert len(expected) > 2
    _, root = _export(scene, monkeypatch, tmp_path)
    node = next(node for node in root.iter(SVG + "text") if "data-raw-text" in node.attrib)
    assert node.attrib["direction"] == direction
    spans = list(node.iter(SVG + "tspan"))
    assert len(spans) == len(expected)
    for span, (x, y) in zip(spans, expected):
        assert float(span.attrib["x"]) == pytest.approx(x, abs=0.01)
        assert float(span.attrib["y"]) == pytest.approx(y, abs=0.01)


def test_shape_label_soft_wrap_and_raw_content_survive_xml_and_import(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create("Rectangle", 10, 20)
    item.set_label_text(SPECIAL + " Long words wrap in this label")
    item.set_label_alignment(horizontal="right", vertical="bottom")
    font = QtGui.QFont(FAMILY)
    font.setPixelSize(20)
    font.setBold(True)
    font.setItalic(True)
    font.setUnderline(True)
    item.label_item().setFont(font)
    item.set_label_text(item.label_text())
    scene.addItem(item)
    path, root = _export(scene, monkeypatch, tmp_path)
    node = next(node for node in root.iter(SVG + "text") if "data-shape-label" in node.attrib)
    assert node.attrib["data-raw-label"] == item.label_text()
    assert node.attrib["font-family"] == FAMILY
    assert node.attrib["font-weight"] == "bold"
    assert len(list(node.iter(SVG + "tspan"))) > len(item.label_text().splitlines())
    restored = QtWidgets.QGraphicsScene()
    assert import_drawsvg.import_drawsvg_py(restored, path=path)
    copy = next(candidate for candidate in restored.items() if candidate.data(0) == "Rectangle")
    assert copy.label_text() == item.label_text()
    assert copy.label_alignment() == ("right", "bottom")
    assert copy.label_item().font().family() == FAMILY
    assert copy.label_item().font().bold() and copy.label_item().font().italic() and copy.label_item().font().underline()


def test_folder_tree_names_and_font_are_python_and_xml_safe(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = FolderTreeItem(0, 0, 300, 100, structure={"name": SPECIAL, "folder": True, "children": []})
    item.setData(0, "Folder Tree")
    item._font = QtGui.QFont(FAMILY)
    item._font.setPixelSize(18)
    scene.addItem(item)
    path, root = _export(scene, monkeypatch, tmp_path)
    node = next(root.iter(SVG + "text"))
    assert node.attrib["font-family"] == FAMILY
    restored = QtWidgets.QGraphicsScene()
    assert import_drawsvg.import_drawsvg_py(restored, path=path)
    copy = next(candidate for candidate in restored.items() if isinstance(candidate, FolderTreeItem))
    assert copy.structure() == item.structure()


def test_legacy_attribute_values_are_not_unescaped():
    _, kwargs = import_drawsvg._parse_call('_text = draw.Text("x", 12, 0, 0, data_raw_text="literal &amp; &#160;")')
    assert kwargs["data_raw_text"] == "literal &amp; &#160;"


def test_soft_wrap_after_non_bmp_character_keeps_each_character(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = TextItem(0, 0, 90, 300, auto_size=False)
    item.setData(0, "Text")
    item.setPlainText("🙂🙂🙂 words after emoji wrap safely")
    scene.addItem(item)
    _, root = _export(scene, monkeypatch, tmp_path)
    node = next(node for node in root.iter(SVG + "text") if "data-raw-text" in node.attrib)
    assert "".join(node.itertext()) == item.toPlainText()
    block = item.document().begin()
    layout = block.layout()
    for index, span in enumerate(node.iter(SVG + "tspan")):
        line = layout.lineAt(index)
        cursor = QtGui.QTextCursor(item.document())
        cursor.setPosition(line.textStart())
        cursor.setPosition(line.textStart() + line.textLength(), QtGui.QTextCursor.MoveMode.KeepAnchor)
        assert (span.text or "") == cursor.selectedText()


def test_export_hidden_shape_label_has_no_text(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create("Rectangle", 0, 0)
    item.set_label_text("Hidden label")
    item.label_item().hide()
    scene.addItem(item)
    _, root = _export(scene, monkeypatch, tmp_path)
    assert not list(root.iter(SVG + "text"))


def _import_script(tmp_path, body):
    path = tmp_path / "import.py"
    path.write_text("import drawsvg as draw\ndef build_drawing():\n    d = draw.Drawing(200, 200)\n" + body + "\n    return d\n", encoding="utf-8")
    ET.fromstring(runpy.run_path(str(path))["build_drawing"]().as_svg())
    scene = QtWidgets.QGraphicsScene()
    assert import_drawsvg.import_drawsvg_py(scene, path=path)
    return scene


def test_embedded_bitmap_and_svg_restore_editable_asset_types(application, tmp_path):
    from bitmap_item import BitmapItem
    from items.svg import SvgItem
    image = QtGui.QImage(2, 3, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("red"))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    png = bytes(buffer.data())
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20"><rect width="10" height="20" fill="blue"/></svg>'
    raw = '<g xmlns="http://www.w3.org/2000/svg" data-asset-svg="' + base64.b64encode(svg).decode() + '" data-asset-width="60" data-asset-height="80" transform="matrix(1 0 0 1 20 30)" opacity="0.6"><rect width="60" height="80"/></g>'
    scene = _import_script(tmp_path,
        f"    _bitmap = draw.Image(0, 0, 40, 50, path={uri!r}, data_asset_name='tiny.png', opacity=0.5, transform='matrix(1 0 0 1 2 3)')\n    d.append(_bitmap)\n"
        f"    _svg = draw.Raw({raw!r})\n    d.append(_svg)")
    bitmap = next(item for item in scene.items() if isinstance(item, BitmapItem))
    vector = next(item for item in scene.items() if isinstance(item, SvgItem))
    assert bitmap.asset.data == png
    assert bitmap.boundingRect().size() == QtCore.QSizeF(40, 50)
    assert bitmap.scenePos() == QtCore.QPointF(2, 3)
    assert bitmap.opacity() == 0.5
    assert vector.asset.data == svg
    assert vector.boundingRect().size() == QtCore.QSizeF(60, 80)
    assert vector.scenePos() == QtCore.QPointF(20, 30)
    assert vector.opacity() == 0.6


def test_connector_literal_metadata_restores_route(application, tmp_path):
    from connectors import ConnectorEndpoint, ConnectorItem
    item = ConnectorItem(ConnectorEndpoint.free(QtCore.QPointF(1, 2)), ConnectorEndpoint.free(QtCore.QPointF(31, 42)))
    payload = item.to_data()
    payload["route_points"] = [[1, 2], [31, 2], [31, 42]]
    value = html.escape(json.dumps(payload), quote=True)
    scene = _import_script(tmp_path, f"    _connector = draw.Path('M 1 2 L 31 2 L 31 42', data_connector={value!r}, data_xml_escaped='true')\n    d.append(_connector)")
    copy = next(item for item in scene.items() if isinstance(item, ConnectorItem))
    assert copy.route_points() == (QtCore.QPointF(1, 2), QtCore.QPointF(31, 2), QtCore.QPointF(31, 42))


@pytest.mark.parametrize("body", [
    "    _bitmap = draw.Image(0, 0, 40, 50, path='data:image/png;base64,broken')",
    "    _svg = draw.Raw('<g data-asset-svg=\"broken\" data-asset-width=\"10\" data-asset-height=\"20\"/>')",
    "    _connector = draw.Path('M 1 2 L 3 4', data_connector='broken')",
])
def test_invalid_asset_metadata_keeps_existing_scene(application, monkeypatch, tmp_path, body):
    scene = QtWidgets.QGraphicsScene()
    existing = scene.addRect(0, 0, 10, 10)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a: None)
    path = tmp_path / "invalid.py"
    path.write_text("import drawsvg as draw\ndef build_drawing():\n    d = draw.Drawing(100, 100)\n" + body + "\n    return d\n")
    assert import_drawsvg.import_drawsvg_py(scene, path=path) is None
    assert scene.items() == [existing]


def test_style_gradient_ast_is_literal_only_and_restores_brush(application, tmp_path):
    data = {"kind": "linear", "coords": [0, 0, 1, 1], "coordinate_mode": 2, "spread": 0,
            "stops": [[0, "#ff0000", 1], [1, "#0000ff", 0.5]], "transform": [1, 0, 0, 1, 0, 0]}
    style = {"version": 1, "opacity": 0.6, "shadow": {"enabled": False}}
    path = tmp_path / "gradient.py"
    path.write_text("import drawsvg as draw\ndef _drawsvg_gradient(*args):\n    return draw.LinearGradient(0, 0, 1, 1)\ndef build_drawing():\n    d = draw.Drawing(100, 100)\n"
        + f"    _rect = draw.Rectangle(0, 0, 80, 90, fill=_drawsvg_gradient('linear', [0, 0, 1, 1], [[0, '#ff0000', 1], [1, '#0000ff', 0.5]], {{}}), data_qt_brush={html.escape(json.dumps(data), quote=True)!r}, data_item_style={html.escape(json.dumps(style), quote=True)!r}, data_xml_escaped='true')\n    d.append(_rect)\n    return d\n")
    ET.fromstring(runpy.run_path(str(path))["build_drawing"]().as_svg())
    scene = QtWidgets.QGraphicsScene()
    assert import_drawsvg.import_drawsvg_py(scene, path=path)
    copy = next(item for item in scene.items() if item.data(0) == "Rectangle")
    gradient = copy.brush().gradient()
    assert isinstance(gradient, QtGui.QLinearGradient)
    assert gradient.start() == QtCore.QPointF(0, 0)
    assert gradient.finalStop() == QtCore.QPointF(1, 1)
    assert gradient.stops()[1][1].alphaF() == pytest.approx(0.5, abs=1e-4)
    assert copy.opacity() == 0.6
    with pytest.raises(ValueError):
        import_drawsvg._parse_call("_rect = draw.Rectangle(0, 0, 10, 10, fill=_drawsvg_gradient(__import__('os'), [], [], {}))")


@pytest.mark.parametrize("style,offset", [(QtCore.Qt.PenStyle.DashLine, 0), (QtCore.Qt.PenStyle.CustomDashLine, 3)])
def test_native_pen_metadata_restores_qt_dash_style_and_units(application, tmp_path, style, offset):
    # Qt makes a pen CustomDashLine when setting a nonzero dash offset.
    scene = _import_script(tmp_path, f"    _rect = draw.Rectangle(0, 0, 80, 90, stroke='#123456', stroke_width=3, stroke_dasharray='12 6', stroke_dashoffset={offset * 3}, stroke_linecap='round', stroke_linejoin='bevel', data_pen_units='svg', data_qt_pen_style={style.value})\n    d.append(_rect)")
    copy = next(item for item in scene.items() if item.data(0) == "Rectangle")
    assert copy.pen().style() == style
    assert copy.pen().dashPattern() == [4, 2]
    assert copy.pen().dashOffset() == offset
    assert copy.pen().capStyle() == QtCore.Qt.PenCapStyle.RoundCap
    assert copy.pen().joinStyle() == QtCore.Qt.PenJoinStyle.BevelJoin


def test_text_effective_opacity_and_label_opacity_are_exported(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create("Text", 0, 0)
    item.setOpacity(0.4)
    scene.addItem(item)
    shape = SHAPE_REGISTRY.create("Rectangle", 100, 100)
    shape.set_label_text("Label")
    shape.setOpacity(0.5)
    shape.label_item().setOpacity(0.6)
    scene.addItem(shape)
    _, root = _export(scene, monkeypatch, tmp_path)
    nodes = list(root.iter(SVG + "text"))
    text = next(node for node in nodes if "data-raw-text" in node.attrib)
    label = next(node for node in nodes if "data-shape-label" in node.attrib)
    assert float(text.attrib["opacity"]) == 0.4
    assert float(label.attrib["opacity"]) == 0.3


def test_split_metadata_restores_both_brushes_after_legacy_comment(application, tmp_path):
    bottom = {"kind": "solid", "style": 1, "color": "#112233", "alpha": 0.7}
    top = {"kind": "linear", "coords": [0, 0, 1, 1], "coordinate_mode": 2, "spread": 0,
           "stops": [[0, "#ff0000", 1], [1, "#0000ff", 0.5]], "transform": [1, 0, 0, 1, 0, 0]}
    divider = {"color": "#445566", "alpha": 1, "width": 3, "style": 2, "cosmetic": True,
               "cap": 32, "join": 64, "dash": [4, 2], "offset": 0, "miter": 2}
    payload = html.escape(json.dumps({"top": top, "bottom": bottom, "divider_pen": divider}), quote=True)
    scene = _import_script(tmp_path, "    # SplitRoundedRect ratio=0.25 top_fill='#eeeeee' top_opacity=1\n"
                           + f"    _split_rect = draw.Rectangle(0, 0, 80, 90, fill='none', data_qt_split={payload!r}, data_xml_escaped='true')\n    d.append(_split_rect)")
    copy = next(item for item in scene.items() if item.data(0) == "Split Rounded Rectangle")
    assert isinstance(copy.topBrush().gradient(), QtGui.QLinearGradient)
    assert copy.bottomBrush().color().name() == "#112233"
    assert copy.bottomBrush().color().alphaF() == pytest.approx(0.7, abs=1e-4)
    assert copy.divider_ratio() == 0.25
    assert copy._divider_pen.widthF() == 3
    assert copy._divider_pen.style() == QtCore.Qt.PenStyle.DashLine


def test_pen_gradient_descriptor_is_safely_imported(application, tmp_path):
    data = {"kind": "linear", "coords": [0, 0, 1, 1], "coordinate_mode": 2, "spread": 0,
            "stops": [[0, "#ff0000", 1], [1, "#0000ff", 1]], "transform": [1, 0, 0, 1, 0, 0]}
    encoded = html.escape(json.dumps(data), quote=True)
    _, kwargs = import_drawsvg._parse_call(f"_rect = draw.Rectangle(0, 0, 80, 90, stroke=_drawsvg_gradient('linear', [0, 0, 1, 1], [[0, '#ff0000', 1], [1, '#0000ff', 1]], {{}}), data_qt_pen_brush={encoded!r}, data_xml_escaped='true', data_qt_pen_style=1)")
    item = SHAPE_REGISTRY.create("Rectangle", 0, 0)
    import_drawsvg._apply_style(item, kwargs)
    assert item.pen().style() == QtCore.Qt.PenStyle.SolidLine
    assert isinstance(item.pen().brush().gradient(), QtGui.QLinearGradient)
