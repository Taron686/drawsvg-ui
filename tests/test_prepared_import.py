"""Document preparation must not announce or replace an unaccepted document."""

from pathlib import Path

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import document_controller
import import_drawsvg
import main_window
from canvas_view import CanvasView
from asset_service import BitmapAssetService
from bitmap_item import BitmapItem
from document_controller import DocumentWindowRegistry
from document_format import ProjectDocument
from document_io import save_project
from main_window import MainWindow


@pytest.fixture
def editor(application, tmp_path):
    registry = DocumentWindowRegistry()
    window = MainWindow(
        recent_files_path=tmp_path / "recent.json",
        window_registry=registry,
        recovery_enabled=False,
        settings=QtCore.QSettings(
            str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
        ),
    )
    yield window
    for candidate in registry.windows():
        candidate._force_close = True
        candidate.close()


@pytest.fixture
def python_file(tmp_path):
    path = tmp_path / "drawing.py"
    path.write_text(
        "d = draw.Drawing(402, 363, origin=(-253, -468))\n"
        "_rect = draw.Rectangle(-246, -461, 160, 100, fill='white')\n"
        "d.append(_rect)\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(params=[".py", ".drawsvg"])
def target_file(request, tmp_path, python_file, application):
    if request.param == ".py":
        return python_file
    canvas = CanvasView()
    canvas.add_shape("Rectangle", QtCore.QPointF(20, 30), snap_to_grid=False)
    path = tmp_path / "drawing.drawsvg"
    save_project(path, ProjectDocument(scene=canvas._serialize_scene_state()))
    canvas.close()
    return path


def _open(editor, path):
    if path.suffix == ".drawsvg":
        return editor._open_project_path(path)
    return editor._open_python_document(path)


def test_import_preparation_does_not_announce_loaded(editor, python_file):
    prepared = CanvasView()
    messages = []
    editor.statusBar().messageChanged.connect(messages.append)
    try:
        assert import_drawsvg.import_drawsvg_py(
            prepared.scene(), editor, python_file
        ) == python_file.resolve()
        assert not any(message.startswith("Loaded:") for message in messages)
        assert editor.canvas._serialize_scene_state()["items"] == []
    finally:
        prepared.close()


def test_python_loaded_status_is_emitted_once_after_document_is_ready(editor, python_file):
    observations = []

    def observe(message):
        if message.startswith("Loaded:"):
            observations.append((
                editor.document_controller.dirty,
                editor.document_controller.revision,
                any(item.data(0) == "Rectangle" for item in editor.canvas.scene().items()),
            ))

    editor.statusBar().messageChanged.connect(observe)
    result = editor._open_python_document(python_file)
    assert observations == [(True, 1, True)]
    assert result is main_window.OpenResult.OPENED


def test_python_cancel_does_not_announce_loaded(editor, python_file, monkeypatch):
    editor.canvas.add_shape("Ellipse", QtCore.QPointF(30, 40), snap_to_grid=False)
    before = editor.canvas._serialize_scene_state()
    messages = []
    editor.statusBar().messageChanged.connect(messages.append)
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "cancel")

    result = editor._open_python_document(python_file)

    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas._serialize_scene_state() == before
    assert not any(message.startswith("Loaded:") for message in messages)
    assert result is main_window.OpenResult.CANCELLED


def test_python_dialog_cancel_preserves_document(editor, monkeypatch):
    editor.canvas.add_shape("Ellipse", QtCore.QPointF(30, 40), snap_to_grid=False)
    before = editor.canvas._serialize_scene_state()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_args: ("", ""))

    result = editor._open_python_document()

    assert editor.canvas._serialize_scene_state() == before
    assert editor._window_registry.windows() == (editor,)
    assert result is main_window.OpenResult.CANCELLED


def test_python_import_error_shows_one_dialog_parented_to_current_window(editor, tmp_path, monkeypatch):
    path = tmp_path / "invalid.py"
    path.write_text("print('unrelated')\n", encoding="utf-8")
    editor.canvas.add_shape("Ellipse", QtCore.QPointF(30, 40), snap_to_grid=False)
    before = editor.canvas._serialize_scene_state()
    dialogs = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda parent, title, text: dialogs.append((parent, title, text)))

    result = editor._open_python_document(path)

    assert len(dialogs) == 1
    assert dialogs[0][0] is editor
    assert editor.canvas._serialize_scene_state() == before
    assert result is main_window.OpenResult.FAILED


@pytest.mark.parametrize("reason", ["cancel", "save_cancel", "save_error"])
def test_recent_target_survives_cancelled_replacement(editor, target_file, monkeypatch, reason):
    editor.canvas.add_shape("Ellipse", QtCore.QPointF(30, 40), snap_to_grid=False)
    before = editor.canvas._serialize_scene_state()
    editor._remember_recent_file(target_file)
    old_history = editor._recent_files_path.read_bytes()
    decision = "cancel" if reason == "cancel" else "save"
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: decision)
    destination = "" if reason == "save_cancel" else str(target_file.parent / "current.drawsvg")
    save_dialogs = []
    errors = []

    def choose_save(parent, *_args):
        save_dialogs.append(parent)
        return destination, ""

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", choose_save)
    if reason == "save_error":
        def fail_save(*_args):
            raise OSError("unwritable destination")
        monkeypatch.setattr(document_controller, "save_project", fail_save)
        monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda parent, title, text: errors.append((parent, text)))

    result = _open(editor, target_file)
    editor._open_recent_file(str(target_file))

    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas._serialize_scene_state() == before
    assert editor._recent_files_path.read_bytes() == old_history
    assert result is main_window.OpenResult.CANCELLED
    assert save_dialogs == ([] if reason == "cancel" else [editor, editor])
    if reason == "save_error":
        assert len(errors) == 2
        assert all(parent is editor and "unwritable destination" in text for parent, text in errors)


def test_recent_valid_target_survives_apply_error(editor, target_file, monkeypatch):
    editor._remember_recent_file(target_file)
    before = editor.canvas._serialize_scene_state()
    old_history = editor._recent_files_path.read_bytes()
    restore = editor.canvas._restore_scene_state
    failures_remaining = 1

    def fail_first_restore(state):
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            editor.canvas.clear_canvas()
            raise RuntimeError("failed after clearing canvas")
        return restore(state)

    monkeypatch.setattr(editor.canvas, "_restore_scene_state", fail_first_restore)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: None)

    result = _open(editor, target_file)

    assert result is main_window.OpenResult.FAILED
    assert editor.canvas._serialize_scene_state() == before
    assert editor._recent_files_path.read_bytes() == old_history


@pytest.mark.parametrize("suffix", [".py", ".drawsvg"])
@pytest.mark.parametrize("exists", [False, True])
def test_recent_invalid_target_is_removed_at_preparation_failure(editor, tmp_path, monkeypatch, suffix, exists):
    path = tmp_path / ("invalid" + suffix)
    if exists:
        path.write_text("invalid document", encoding="utf-8")
    editor._remember_recent_file(path)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: None)

    result = _open(editor, path)

    assert editor._recent_files == []
    assert not editor.recent_files_menu.isEnabled()
    assert result is main_window.OpenResult.FAILED


@pytest.mark.parametrize("failure", ["unknown", "none", "exception"])
def test_template_preparation_failure_preserves_current_document(editor, monkeypatch, failure):
    editor.canvas.add_shape("Ellipse", QtCore.QPointF(30, 40), snap_to_grid=False)
    before = editor.canvas._serialize_scene_state()
    old_id = editor.document_controller.document_id
    dialogs = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda parent, title, text: dialogs.append((parent, title, text)))
    if failure != "unknown":
        def broken_shape(*_args, **_kwargs):
            if failure == "exception":
                raise RuntimeError("template creation failed")
            return None
        monkeypatch.setattr(CanvasView, "add_shape", broken_shape)

    result = editor.new_document_from_template("Unknown" if failure == "unknown" else "Flowchart")

    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas._serialize_scene_state() == before
    assert editor.document_controller.document_id == old_id
    assert result is main_window.OpenResult.FAILED
    assert len(dialogs) == 1


def test_blank_template_is_unsaved_in_existing_window(editor):
    old_id = editor.document_controller.document_id
    result = editor.new_document_from_template("Blank")

    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas._serialize_scene_state()["items"] == []
    assert editor.document_controller.document_id != old_id
    assert editor.document_controller.path is None
    assert editor.document_controller.dirty
    assert editor.document_controller.revision == 1
    assert result is main_window.OpenResult.OPENED


def test_successful_open_fits_master_page_in_current_window(editor, target_file, application):
    editor.show()
    application.processEvents()
    editor.canvas.scale(0.01, 0.01)

    result = _open(editor, target_file)
    application.processEvents()

    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas.transform().m11() > 0.1
    viewport = editor.canvas.viewport().rect()
    page = editor.canvas.mapFromScene(editor.canvas._page_item.sceneBoundingRect()).boundingRect()
    assert viewport.adjusted(-2, -2, 2, 2).contains(page)
    assert result is main_window.OpenResult.OPENED


@pytest.mark.parametrize("reason", ["cancel", "invalid"])
def test_unsuccessful_open_preserves_view(editor, target_file, application, monkeypatch, reason):
    editor.show()
    application.processEvents()
    editor.canvas.add_shape("Ellipse", QtCore.QPointF(30, 40), snap_to_grid=False)
    editor.canvas.scale(1.7, 1.7)
    transform = editor.canvas.transform()
    center = editor.canvas.mapToScene(editor.canvas.viewport().rect().center())
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "cancel")
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: None)
    if reason == "invalid":
        target_file.write_text("invalid document", encoding="utf-8")

    _open(editor, target_file)

    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas.transform() == transform
    assert editor.canvas.mapToScene(editor.canvas.viewport().rect().center()) == center


@pytest.mark.parametrize("operation", ["new", "template"])
def test_new_and_template_clear_old_state_but_keep_bitmap_clipboard(editor, application, monkeypatch, operation):
    image = QtGui.QImage(12, 8, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("#123456"))
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    assert buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    asset = BitmapAssetService().import_bytes(bytes(data)).asset
    canvas = editor.canvas
    canvas.set_bitmap_assets((asset,))
    canvas.add_bitmap_item(asset, QtCore.QPointF(30, 40))
    assert canvas._copy_selected_items()
    canvas.add_guide("vertical", 100)
    layer = canvas.layer_manager().add_layer("Old locked layer")
    canvas.layer_manager().set_layer_locked(layer.id, True)
    canvas.set_connector_creation_enabled(True)
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "discard")
    try:
        result = editor.new_document() if operation == "new" else editor.new_document_from_template("Flowchart")

        assert result is main_window.OpenResult.OPENED
        assert editor.canvas is canvas
        assert editor._window_registry.windows() == (editor,)
        assert not canvas.bitmap_assets()
        assert not canvas.guides()
        assert canvas.layer_manager().serialize_state() == [
            {"id": "layer-1", "name": "Layer 1", "visible": True, "locked": False}
        ]
        assert not canvas.connector_creation_enabled()
        assert not canvas.scene().selectedItems()
        assert not canvas.history().can_undo()
        assert canvas._paste_clipboard_items(QtCore.QPointF(300, 200))
        pasted = [item for item in canvas.scene().items() if isinstance(item, BitmapItem)]
        assert len(pasted) == 1
        assert pasted[0].asset.data == bytes(data)
        assert canvas.bitmap_assets() == (asset,)
    finally:
        application.clipboard().clear()
