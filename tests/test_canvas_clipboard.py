from __future__ import annotations

import json
from uuid import uuid4

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from asset_service import BitmapAssetService
from bitmap_item import BitmapItem
from canvas_view import CanvasView
from clipboard_service import CLIPBOARD_MIME_TYPE, ClipboardService
from connectors import ConnectorItem
from items import GroupItem, TextItem
from properties_panel import PlainTextEditor
from scene_codec import KEY_ITEM_ID, SceneCodec


@pytest.fixture(autouse=True)
def isolated_clipboard(application):
    assert application.platformName() == "offscreen"
    application.clipboard().clear()
    yield
    application.clipboard().clear()


def _show(view, application):
    view.resize(800, 600)
    view.show()
    view.activateWindow()
    application.processEvents()
    view.setFocus()


def _rect(view, x, y):
    item = view.add_shape("Rectangle", QtCore.QPointF(x, y), snap_to_grid=False)
    item.setRect(0, 0, 40, 30)
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    return item


def _key(view, key):
    QTest.keyClick(view.viewport(), key, QtCore.Qt.KeyboardModifier.ControlModifier)


def _paste_at(view, monkeypatch, point=QtCore.QPoint(270, 210)):
    # Only the external cursor query is replaced; Qt dispatch and scene edits run.
    monkeypatch.setattr(QtGui.QCursor, "pos", lambda: view.viewport().mapToGlobal(point))
    expected = view.mapToScene(point)
    _key(view, QtCore.Qt.Key.Key_V)
    return expected


def _state(view):
    return json.loads(json.dumps(view._serialize_scene_state()))


def test_ctrl_c_publishes_only_selected_objects_without_changing_history(
    canvas_view, application
):
    _show(canvas_view, application)
    selected = _rect(canvas_view, 10, 20)
    _rect(canvas_view, 100, 20)
    canvas_view.scene().clearSelection()
    selected.setSelected(True)
    canvas_view.history().capture_now()
    before = _state(canvas_view)
    states_before = len(canvas_view.history()._states)

    _key(canvas_view, QtCore.Qt.Key.Key_C)

    mime = application.clipboard().mimeData()
    assert mime is not None and mime.hasFormat(CLIPBOARD_MIME_TYPE)
    payload = json.loads(bytes(mime.data(CLIPBOARD_MIME_TYPE)))
    assert [item["id"] for item in payload["items"]] == [selected.data(KEY_ITEM_ID)]
    assert _state(canvas_view) == before
    assert len(canvas_view.history()._states) == states_before


@pytest.mark.parametrize("zoom", [0.5, 1.0, 2.0])
def test_ctrl_v_places_selection_at_current_cursor_and_preserves_spacing(
    canvas_view, application, monkeypatch, zoom
):
    _show(canvas_view, application)
    first = _rect(canvas_view, 10, 20)
    second = _rect(canvas_view, 100, 60)
    first.setSelected(True)
    canvas_view.history().capture_now()
    original_ids = {first.data(KEY_ITEM_ID), second.data(KEY_ITEM_ID)}
    canvas_view.setTransform(QtGui.QTransform.fromScale(zoom, zoom))
    canvas_view.centerOn(80, 70)
    _key(canvas_view, QtCore.Qt.Key.Key_C)
    before = _state(canvas_view)
    states_before = len(canvas_view.history()._states)

    target = _paste_at(canvas_view, monkeypatch)

    pasted = sorted(canvas_view.scene().selectedItems(), key=lambda item: item.x())
    assert len(pasted) == 2
    assert pasted[0].pos() == target
    assert pasted[1].pos() == target + QtCore.QPointF(90, 40)
    pasted_ids = {item.data(KEY_ITEM_ID) for item in pasted}
    assert pasted_ids.isdisjoint(original_ids)
    assert first.scene() is canvas_view.scene() and second.scene() is canvas_view.scene()
    assert len(canvas_view.history()._states) == states_before + 1

    canvas_view.undo()
    assert _state(canvas_view) == before
    canvas_view.redo()
    assert len(_state(canvas_view)["items"]) == 4
    assert pasted_ids <= {entry["id"] for entry in _state(canvas_view)["items"]}

    next_target = _paste_at(canvas_view, monkeypatch, QtCore.QPoint(310, 250))
    next_copy = sorted(canvas_view.scene().selectedItems(), key=lambda item: item.x())
    assert next_copy[0].pos() == next_target
    assert next_copy[1].pos() == next_target + QtCore.QPointF(90, 40)
    assert {item.data(KEY_ITEM_ID) for item in next_copy}.isdisjoint(pasted_ids | original_ids)


def test_group_paste_keeps_children_transforms_and_remaps_all_ids(
    canvas_view, application, monkeypatch
):
    _show(canvas_view, application)
    first = _rect(canvas_view, 10, 20)
    second = _rect(canvas_view, 100, 60)
    first.setSelected(True)
    canvas_view._group_selected_items()
    group = next(item for item in canvas_view.scene().selectedItems() if isinstance(item, GroupItem))
    group.setRotation(30)
    original = _state(canvas_view)["items"][0]
    old_ids = {original["id"], *(child["id"] for child in original["children"])}
    _key(canvas_view, QtCore.Qt.Key.Key_C)

    _paste_at(canvas_view, monkeypatch)

    pasted = canvas_view.scene().selectedItems()[0]
    assert isinstance(pasted, GroupItem) and pasted is not group
    assert pasted.rotation() == 30
    record = SceneCodec.serialize_items([pasted], canvas_view._serialize_item)[0]
    assert {record["id"], *(child["id"] for child in record["children"])}.isdisjoint(old_ids)
    for original_child, child in zip(original["children"], record["children"]):
        assert child["pos"] == original_child["pos"]
        assert child["transform"] == original_child["transform"]
    assert len(record["children"]) == 2


def test_paste_remaps_connector_targets_and_detaches_uncopied_targets(
    canvas_view, application, monkeypatch
):
    _show(canvas_view, application)
    first = _rect(canvas_view, 10, 20)
    second = _rect(canvas_view, 150, 20)
    manager = canvas_view.connector_manager()
    connector = manager.create_connector(manager.endpoint_for(first), manager.endpoint_for(second))
    canvas_view.scene().clearSelection()
    first.setSelected(True)
    connector.setSelected(True)
    original_free_position = QtCore.QPointF(connector.end_endpoint.position)
    _key(canvas_view, QtCore.Qt.Key.Key_C)

    _paste_at(canvas_view, monkeypatch)

    selection = canvas_view.scene().selectedItems()
    copied_connector = next(item for item in selection if isinstance(item, ConnectorItem))
    copied_shape = next(item for item in selection if not isinstance(item, ConnectorItem))
    assert copied_connector.start_endpoint.target_id == copied_shape.data(KEY_ITEM_ID)
    assert copied_connector.end_endpoint.target_id is None
    assert connector.start_endpoint.target_id == first.data(KEY_ITEM_ID)
    assert connector.end_endpoint.target_id == second.data(KEY_ITEM_ID)
    assert copied_connector.end_endpoint.position == original_free_position + (copied_shape.pos() - first.pos())
    old_start = QtCore.QPointF(copied_connector.start_endpoint.position)
    canvas_view._grid_size_min = 0
    copied_shape.moveBy(17, 23)
    manager.notify_item_geometry_changed(copied_shape)
    assert copied_connector.start_endpoint.position == old_start + QtCore.QPointF(17, 23)


def test_bitmap_paste_between_canvases_carries_assets(application, monkeypatch):
    source, destination = CanvasView(), CanvasView()
    try:
        _show(source, application)
        image = QtGui.QImage(8, 6, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("#123456"))
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        assert image.save(buffer, "PNG")
        assets = BitmapAssetService()
        asset = assets.import_bytes(bytes(data)).asset
        source.set_bitmap_assets(assets.assets())
        original = source.add_bitmap_item(asset, QtCore.QPointF(10, 20), 40, 30)
        _key(source, QtCore.Qt.Key.Key_C)
        _show(destination, application)
        existing = _rect(destination, -60, -40)

        target = _paste_at(destination, monkeypatch)

        pasted = destination.scene().selectedItems()[0]
        assert isinstance(pasted, BitmapItem)
        assert pasted.pos() == target
        assert pasted.asset_sha256 == original.asset_sha256
        assert pasted.data(KEY_ITEM_ID) != original.data(KEY_ITEM_ID)
        assert existing.scene() is destination.scene()
        assert destination.bitmap_assets() == (asset,)
        destination.undo()
        assert len(_state(destination)["items"]) == 1
        destination.redo()
        assert any(isinstance(item, BitmapItem) for item in destination.scene().items())
    finally:
        source.close()
        destination.close()


@pytest.mark.parametrize("raw", [b"broken", ClipboardService.encode([
    {"id": str(uuid4()), "type_id": "Unknown", "shape": "Unknown"}
])])
def test_invalid_paste_leaves_scene_selection_assets_and_history_unchanged(
    canvas_view, application, monkeypatch, raw
):
    _show(canvas_view, application)
    _rect(canvas_view, 10, 20)
    canvas_view.history().capture_now()
    before = _state(canvas_view)
    selected = canvas_view.scene().selectedItems()
    states_before = len(canvas_view.history()._states)
    mime = QtCore.QMimeData()
    mime.setData(CLIPBOARD_MIME_TYPE, raw)
    application.clipboard().setMimeData(mime)

    _paste_at(canvas_view, monkeypatch)

    assert _state(canvas_view) == before
    assert canvas_view.scene().selectedItems() == selected
    assert canvas_view.bitmap_assets() == ()
    assert len(canvas_view.history()._states) == states_before


def test_active_canvas_text_keeps_native_copy_paste(canvas_view, application):
    _show(canvas_view, application)
    text = canvas_view.add_shape("Text", QtCore.QPointF(10, 20), snap_to_grid=False)
    assert isinstance(text, TextItem)
    text.setPlainText("editable text")
    text.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextEditorInteraction)
    text.setFocus()
    cursor = text.textCursor()
    cursor.select(QtGui.QTextCursor.SelectionType.Document)
    text.setTextCursor(cursor)
    _key(canvas_view, QtCore.Qt.Key.Key_C)
    assert application.clipboard().text() == "editable text"
    assert not application.clipboard().mimeData().hasFormat(CLIPBOARD_MIME_TYPE)
    application.clipboard().setText("replacement")
    _key(canvas_view, QtCore.Qt.Key.Key_V)
    assert text.toPlainText() == "replacement"
    assert len(_state(canvas_view)["items"]) == 1


def test_focused_plain_text_field_does_not_copy_selected_graphics(
    canvas_view, application
):
    host = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(host)
    layout.addWidget(canvas_view)
    editor = PlainTextEditor()
    layout.addWidget(editor)
    try:
        host.show()
        host.activateWindow()
        application.processEvents()
        _rect(canvas_view, 10, 20)
        editor.setPlainText("panel text")
        editor.setFocus()
        editor.selectAll()
        QTest.keyClick(editor, QtCore.Qt.Key.Key_C, QtCore.Qt.KeyboardModifier.ControlModifier)
        assert application.clipboard().text() == "panel text"
        assert not application.clipboard().mimeData().hasFormat(CLIPBOARD_MIME_TYPE)
        application.clipboard().setText("panel paste")
        QTest.keyClick(editor, QtCore.Qt.Key.Key_V, QtCore.Qt.KeyboardModifier.ControlModifier)
        assert editor.toPlainText() == "panel paste"
        assert len(_state(canvas_view)["items"]) == 1
    finally:
        canvas_view.setParent(None)
        host.close()


def test_empty_copy_and_text_only_paste_preserve_canvas_and_clipboard(
    canvas_view, application, monkeypatch
):
    _show(canvas_view, application)
    _rect(canvas_view, 10, 20)
    canvas_view.scene().clearSelection()
    application.clipboard().setText("keep this text")
    before = _state(canvas_view)
    _key(canvas_view, QtCore.Qt.Key.Key_C)
    assert application.clipboard().text() == "keep this text"
    _paste_at(canvas_view, monkeypatch)
    assert _state(canvas_view) == before


def test_paste_with_pointer_outside_viewport_preserves_scene(
    canvas_view, application, monkeypatch
):
    _show(canvas_view, application)
    _rect(canvas_view, 10, 20)
    _key(canvas_view, QtCore.Qt.Key.Key_C)
    before = _state(canvas_view)
    _paste_at(canvas_view, monkeypatch, QtCore.QPoint(-50, -50))
    assert _state(canvas_view) == before


def test_pasted_group_survives_staging_deletion_and_event_loop(
    canvas_view, application, monkeypatch
):
    import gc

    _show(canvas_view, application)
    first = _rect(canvas_view, 10, 20)
    _rect(canvas_view, 100, 60)
    first.setSelected(True)
    canvas_view._group_selected_items()
    _key(canvas_view, QtCore.Qt.Key.Key_C)
    _paste_at(canvas_view, monkeypatch)
    group = canvas_view.scene().selectedItems()[0]
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    gc.collect()
    application.processEvents()
    assert group.scene() is canvas_view.scene()
    assert len(group.childItems()) >= 2
    record = SceneCodec.serialize_items([group], canvas_view._serialize_item)[0]
    assert len(record["children"]) == 2
    for child in group.childItems():
        assert child.scene() is canvas_view.scene()


def test_main_window_copy_paste_updates_document_and_keeps_field_shortcuts(
    application, monkeypatch, tmp_path
):
    from main_window import MainWindow

    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(
        recent_files_path=tmp_path / "recent.json", settings=settings,
        recovery_enabled=False,
    )
    try:
        _show(window, application)
        view = window.canvas
        view.setFocus()
        _rect(view, 10, 20)
        view.history().capture_now()
        _key(view, QtCore.Qt.Key.Key_C)
        target = _paste_at(view, monkeypatch)
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        application.processEvents()
        assert len(_state(view)["items"]) == 2
        assert view.scene().selectedItems()[0].pos() == target
        assert window.actionUndo.isEnabled()
        assert window.document_controller.dirty
        field = window.findChild(QtWidgets.QLineEdit)
        assert field is not None
        field.setFocus()
        field.setText("input text")
        field.selectAll()
        QTest.keyClick(field, QtCore.Qt.Key.Key_C, QtCore.Qt.KeyboardModifier.ControlModifier)
        assert application.clipboard().text() == "input text"
        application.clipboard().setText("input replacement")
        QTest.keyClick(field, QtCore.Qt.Key.Key_V, QtCore.Qt.KeyboardModifier.ControlModifier)
        assert field.text() == "input replacement"
        assert len(_state(view)["items"]) == 2
    finally:
        window._force_close = True
        window.close()
