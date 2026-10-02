from __future__ import annotations

import pytest
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets

from items import TextItem
from items.base import HANDLE_OFFSET
from shape_registry import SHAPE_REGISTRY
from export_drawsvg import export_drawsvg_py
from import_drawsvg import import_drawsvg_py


@pytest.fixture(scope="module", autouse=True)
def text_test_font(application):
    # Windows' offscreen plugin has no system fonts. Use real glyph metrics
    # when Arial is available, without changing the rest of the test suite.
    path = Path("C:/Windows/Fonts/arial.ttf")
    font_id = QtGui.QFontDatabase.addApplicationFont(str(path)) if path.exists() else -1
    if path.exists():
        assert font_id >= 0
    yield
    if font_id >= 0:
        QtGui.QFontDatabase.removeApplicationFont(font_id)


@pytest.mark.parametrize("text", ["dasd dd", "Short", "A much longer text", "First\nSecond line"])
def test_text_boxes_fit_content(application, text):
    item = TextItem(30, 40, 200, 80)
    item.setPlainText(text)
    document = item.document()
    bounds = item.boundingRect()
    assert bounds.size() == document.size()
    assert bounds.width() == pytest.approx(document.idealWidth())
    assert item.pos() == QtCore.QPointF(30, 40)
    block = document.begin()
    while block.isValid():
        assert block.layout().lineCount() == 1
        block = block.next()
    item.setSelected(True)
    left = next(handle for handle in item._handles if handle._direction == "left")
    right = next(handle for handle in item._handles if handle._direction == "right")
    assert left.pos().x() == pytest.approx(-HANDLE_OFFSET)
    assert right.pos().x() == pytest.approx(bounds.right() + HANDLE_OFFSET)
    item.setSelected(False)


@pytest.mark.parametrize("margin", [0, 4, 9])
@pytest.mark.parametrize("alignment", ["left", "center", "right"])
def test_manual_text_box_reserves_equal_margins(application, margin, alignment):
    item = TextItem(0, 0, 200, 80)
    item.set_size(400, 150)
    item.setPlainText("dasd dd")
    item.set_document_margin(margin)
    item.set_text_alignment(horizontal=alignment)
    document = item.document()
    line = document.begin().layout().lineAt(0)
    assert document.size().width() == pytest.approx(400)
    assert line.width() == pytest.approx(400 - 2 * margin)
    assert item.boundingRect().size() == QtCore.QSizeF(400, 150)


@pytest.mark.parametrize("rotation", [0, 35, 90])
def test_auto_fit_preserves_position_when_font_margin_or_content_changes(canvas_view, rotation):
    item = canvas_view.add_shape("Text", QtCore.QPointF(100, 200))
    item.setRotation(rotation)
    item.setScale(1.4)
    anchor = item.mapToScene(QtCore.QPointF())
    item.setPlainText("dasd dd")
    initial_size = item.boundingRect().size()
    font = item.font()
    font.setPointSizeF(48)
    item.setFont(font)
    assert item.boundingRect().width() > initial_size.width()
    item.set_document_margin(10)
    assert item.boundingRect().size() == item.document().size()
    actual = item.mapToScene(QtCore.QPointF())
    assert actual.x() == pytest.approx(anchor.x())
    assert actual.y() == pytest.approx(anchor.y())
    canvas_view.scene().clearSelection()


def test_finishing_direct_text_edit_refits_box(application):
    item = TextItem(0, 0, 200, 80)
    item.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextEditorInteraction)
    before = item.boundingRect().width()
    cursor = item.textCursor()
    cursor.select(QtGui.QTextCursor.SelectionType.Document)
    cursor.insertText("dasd dd, longer text")
    item.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert item.boundingRect().width() > before
    assert item.boundingRect().size() == item.document().size()


@pytest.mark.parametrize("manual", [False, True])
def test_text_fit_mode_and_geometry_survive_registry_roundtrip(application, manual):
    item = SHAPE_REGISTRY.create("Text", 0, 0)
    item.setPlainText("dasd dd")
    if manual:
        item.set_size(120, 200)
    payload = SHAPE_REGISTRY.serialize(item)
    assert payload["auto_size"] is (not manual)
    restored = SHAPE_REGISTRY.restore(payload)
    assert restored.boundingRect() == item.boundingRect()
    restored.setPlainText("A longer replacement text")
    if manual:
        assert restored.boundingRect().size() == QtCore.QSizeF(120, 200)
    else:
        assert restored.boundingRect().size() == restored.document().size()


def test_legacy_text_box_keeps_saved_size_until_fit_is_requested(application):
    item = SHAPE_REGISTRY.restore({"shape": "Text", "text": "dasd dd", "size": [250, 90]})
    assert item.boundingRect().size() == QtCore.QSizeF(250, 90)
    item.fit_to_text()
    assert item.boundingRect().size() == item.document().size()
    assert item.boundingRect().width() < 250


def test_fit_to_text_is_available_for_existing_fields(canvas_view):
    item = canvas_view.add_shape("Text", QtCore.QPointF(100, 100))
    item.setPlainText("dasd dd")
    item.set_size(400, 120)
    menu = QtWidgets.QMenu()
    callbacks = canvas_view._create_shape_style_actions(menu, item)
    fit = next(action for action in callbacks if action.text() == "Fit to text")
    callbacks[fit]()
    assert item.boundingRect().size() == item.document().size()
    assert item.boundingRect().width() < 400
    canvas_view.scene().clearSelection()


def test_auto_fit_updates_while_typing(application):
    item = TextItem(0, 0, 200, 80)
    cursor = item.textCursor()
    cursor.select(QtGui.QTextCursor.SelectionType.Document)
    cursor.insertText("dasd dd, a longer text")
    assert item.boundingRect().size() == item.document().size()


def test_fit_context_menu_undo_restores_manual_box(canvas_view, monkeypatch):
    view = canvas_view
    item = view.add_shape("Text", QtCore.QPointF(100, 100))
    item.setPlainText("dasd dd")
    item.set_size(400, 120)
    view.history().capture_now()
    before = view._serialize_scene_state()

    class FitMenu(QtWidgets.QMenu):
        def exec(self, _position):
            return next(action for action in self.actions() if action.text() == "Fit to text")

    monkeypatch.setattr(QtWidgets, "QMenu", FitMenu)
    view.resize(900, 700)
    view.centerOn(item.sceneBoundingRect().center())
    point = view.mapFromScene(item.mapToScene(item.boundingRect().center()))
    event = QtGui.QContextMenuEvent(
        QtGui.QContextMenuEvent.Reason.Mouse, point, view.viewport().mapToGlobal(point)
    )
    view.contextMenuEvent(event)
    after = view._serialize_scene_state()
    assert after != before
    view.undo()
    assert view._serialize_scene_state() == before
    view.redo()
    assert view._serialize_scene_state() == after
    view.scene().clearSelection()


@pytest.mark.parametrize("manual", [False, True])
def test_python_export_preserves_text_fit_mode(canvas_view, monkeypatch, tmp_path, manual):
    item = canvas_view.add_shape("Text", QtCore.QPointF(100, 100))
    item.setPlainText("dasd dd")
    if manual:
        item.set_size(120, 150)
    path = tmp_path / "text.py"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    export_drawsvg_py(canvas_view.scene())
    scene = QtWidgets.QGraphicsScene()
    assert import_drawsvg_py(scene, path=path) == path.resolve()
    restored = next(item for item in scene.items() if isinstance(item, TextItem))
    assert restored.auto_sizes_to_text() is (not manual)
    assert restored.boundingRect().width() == pytest.approx(item.boundingRect().width(), abs=0.01)
    assert restored.boundingRect().height() == pytest.approx(item.boundingRect().height(), abs=0.01)
    canvas_view.scene().clearSelection()


@pytest.mark.parametrize("text", ["", " ", "\n", "   \n"])
def test_empty_auto_field_has_valid_geometry(application, text):
    item = TextItem(0, 0, 100, 50)
    item.setPlainText(text)
    assert item.boundingRect().width() >= 10
    assert item.boundingRect().height() >= 10


@pytest.mark.parametrize("alignment", ["left", "center", "right"])
def test_fitted_multiline_alignment_uses_whole_box(application, alignment):
    item = TextItem(0, 0, 200, 80)
    item.setPlainText("abc\nshort")
    item.set_text_alignment(horizontal=alignment)
    line = item.document().begin().layout().lineAt(0)
    free_width = item.boundingRect().width() - 2 * item.document().documentMargin() - line.naturalTextWidth()
    assert free_width > 0
    expected_x = {"left": 0, "center": free_width / 2, "right": free_width}[alignment]
    assert line.naturalTextRect().x() == pytest.approx(expected_x)
