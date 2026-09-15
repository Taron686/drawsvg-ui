from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

import export_drawsvg
import import_drawsvg


def test_immediate_undo_preserves_pending_move_and_redo(canvas_view):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(10, 10), snap_to_grid=False)
    original = item.pos()
    item.moveBy(31, 17)
    moved = item.pos()
    history = canvas_view.history()
    # Exercise the pending-change contract independently of Qt signal scheduling.
    history.mark_dirty()
    assert history._timer.isActive()
    history.undo()
    items = canvas_view._serialize_scene_state()["items"]
    assert len(items) == 1
    assert items[0]["pos"] == pytest.approx([original.x(), original.y()])
    history.redo()
    assert canvas_view._serialize_scene_state()["items"][0]["pos"] == pytest.approx([moved.x(), moved.y()])


def test_hover_is_view_only_and_clears_on_selection_and_leave(canvas_view):
    canvas_view.resize(900, 700)
    canvas_view.show()
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(30, 30), snap_to_grid=False)
    canvas_view.scene().clearSelection()
    canvas_view.centerOn(item)
    QtWidgets.QApplication.processEvents()
    before = json.dumps(canvas_view._serialize_scene_state(), sort_keys=True)
    point = canvas_view.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseMove(canvas_view.viewport(), point)
    assert canvas_view._hover_preview_item is item
    image = QtGui.QImage(900, 700, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(image)
    canvas_view.render(painter)
    painter.end()
    assert json.dumps(canvas_view._serialize_scene_state(), sort_keys=True) == before
    item.setSelected(True)
    assert canvas_view._hover_preview_item is None
    item.setSelected(False)
    canvas_view._set_hover_preview_item(item)
    QtWidgets.QApplication.sendEvent(canvas_view, QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert canvas_view._hover_preview_item is None


def test_hover_handles_deleted_item(canvas_view):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(20, 20))
    item.setSelected(False)
    canvas_view._set_hover_preview_item(item)
    canvas_view.scene().clear()
    assert canvas_view._valid_hover_preview() is None


@pytest.mark.parametrize("alignment,anchor", [("left", "start"), ("center", "middle"), ("right", "end")])
def test_aligned_text_export_and_roundtrip(canvas_view, monkeypatch, tmp_path: Path, alignment, anchor):
    item = canvas_view.add_shape("Text", QtCore.QPointF(70, 90), snap_to_grid=False)
    item.setPlainText("Alignment")
    item.set_text_alignment(horizontal=alignment)
    item.setRotation(23)
    item.setScale(1.3)
    original_transform = item.sceneTransform()
    path = tmp_path / "aligned.py"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    export_drawsvg.export_drawsvg_py(canvas_view.scene())
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    text_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Text"]
    call = text_calls[0]
    attributes = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    assert attributes["text_anchor"] == anchor
    text_x = ast.literal_eval(call.args[2])
    bounds = item.boundingRect()
    expected = {"left": bounds.left() + item.document().documentMargin(), "center": bounds.center().x(), "right": bounds.right() - item.document().documentMargin()}[alignment]
    assert text_x == pytest.approx(expected, abs=0.01)
    import_drawsvg.import_drawsvg_py(canvas_view.scene())
    restored = [it for it in canvas_view.scene().items() if it.data(0) == "Text"][0]
    assert restored.text_alignment()[0] == alignment
    for point in [QtCore.QPointF(), QtCore.QPointF(100, 50)]:
        expected_point = original_transform.map(point)
        actual_point = restored.sceneTransform().map(point)
        assert actual_point.x() == pytest.approx(expected_point.x(), abs=0.001)
        assert actual_point.y() == pytest.approx(expected_point.y(), abs=0.001)


@pytest.mark.parametrize("alignment,anchor,text_x", [("center", "middle", 270), ("right", "end", 462), ("center", "start", 78)])
def test_legacy_aligned_text_import(canvas_view, monkeypatch, tmp_path: Path, alignment, anchor, text_x):
    """Accept public scaled/rotated text and older start-anchor editor files."""
    path = tmp_path / "legacy.py"
    path.write_text(
        "import drawsvg as draw\n"
        "d = draw.Drawing(800, 600)\n"
        f"_text = draw.Text('Legacy', 32, {text_x}, 98, font_family='Arial', "
        f"text_anchor='{anchor}', data_text_h='{alignment}', data_text_v='top', "
        "data_box_w=200, data_box_h=70, data_scale=2, data_font_px=16, "
        "data_doc_margin=4, transform='rotate(23 270 160)')\n"
        "d.append(_text)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    import_drawsvg.import_drawsvg_py(canvas_view.scene())
    item = [it for it in canvas_view.scene().items() if it.data(0) == "Text"][0]
    assert item.pos().x() == pytest.approx(70)
    assert item.pos().y() == pytest.approx(90)
    assert item.scale() == pytest.approx(2)
    assert item.rotation() == pytest.approx(23)
    assert item.text_alignment()[0] == alignment
