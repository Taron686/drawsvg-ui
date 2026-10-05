"""Behavior at the editor's save/replace/recovery boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

import document_controller
from document_controller import DocumentWindowRegistry
from document_format import ProjectAsset, ProjectDocument
from document_io import load_project, save_project
from main_window import MainWindow
from recovery import RecoveryStore, scene_fingerprint


@pytest.fixture
def editor(application, tmp_path):
    registry = DocumentWindowRegistry()
    window = MainWindow(
        recent_files_path=tmp_path / "recent.json",
        window_registry=registry,
        recovery_store=RecoveryStore(tmp_path / "recovery"),
        check_startup_recovery=False,
    )
    yield window
    for remaining in registry.windows():
        remaining._force_close = True
        remaining.close()


def _target(window: MainWindow, tmp_path: Path) -> Path:
    target = tmp_path / "target.drawsvg"
    save_project(target, ProjectDocument(scene=window.canvas._serialize_scene_state()))
    return target


def _edit(window: MainWindow) -> None:
    assert window.canvas.add_shape_at_view_center("Rectangle") is not None


def _candidate(window: MainWindow, *, source_path=None):
    document = ProjectDocument(scene=window.canvas._serialize_scene_state())
    return window._recovery_store.write(
        document, source_path=source_path, revision=7,
        fingerprint=scene_fingerprint(document.scene),
    )


@pytest.mark.parametrize("choice", ["cancel", "discard", "save"])
def test_open_synchronizes_pending_edit_before_save_decision(
    editor, tmp_path, monkeypatch, choice
):
    target = _target(editor, tmp_path)
    _edit(editor)
    before = editor.canvas._serialize_scene_state()
    document_id = editor.document_controller.document_id
    saved = tmp_path / "previous.drawsvg"
    prompts = []
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: prompts.append(1) or choice)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(saved), ""))

    result = editor._open_project_path(target)

    assert prompts == [1]
    assert editor._window_registry.windows() == (editor,)
    if choice == "cancel":
        assert result.name == "CANCELLED"
        assert editor.canvas._serialize_scene_state() == before
        assert editor.document_controller.document_id == document_id
        assert editor.document_controller.dirty
    else:
        assert result.name == "OPENED"
        assert editor.document_controller.path == target.resolve()
        assert not editor.canvas._serialize_scene_state()["items"]
        assert not editor.document_controller.dirty
        if choice == "save":
            assert load_project(saved).scene == before


@pytest.mark.parametrize("save_failure", ["cancel", "error"])
def test_aborted_or_failed_save_prevents_open(editor, tmp_path, monkeypatch, save_failure):
    target = _target(editor, tmp_path)
    _edit(editor)
    editor.document_controller.refresh_dirty_state()
    assert editor.document_controller.write_recovery_if_needed()
    before = editor.canvas._serialize_scene_state()
    candidate = editor._recovery_store.candidates()[0]
    recovery_bytes = candidate.archive_path.read_bytes()
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "save")
    destination = "" if save_failure == "cancel" else str(tmp_path / "save.drawsvg")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_a, **_k: (destination, ""))
    errors = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: errors.append(_args[-1]))
    if save_failure == "error":
        def fail_write(*_args, **_kwargs):
            raise OSError("Disk full")
        monkeypatch.setattr(document_controller, "save_project", fail_write)

    result = editor._open_project_path(target)

    assert editor._window_registry.windows() == (editor,)
    assert result.name == "CANCELLED"
    assert editor.canvas._serialize_scene_state() == before
    assert editor.document_controller.dirty
    assert candidate.archive_path.read_bytes() == recovery_bytes
    assert len(errors) == (1 if save_failure == "error" else 0)


def test_save_as_on_open_target_keeps_just_saved_scene(editor, tmp_path, monkeypatch):
    target = _target(editor, tmp_path)
    _edit(editor)
    before = editor.canvas._serialize_scene_state()
    original_id = editor.document_controller.document_id
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "save")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(target), ""))

    result = editor._open_project_path(target)

    assert editor._window_registry.windows() == (editor,)
    assert result.name == "OPENED"
    assert editor.canvas._serialize_scene_state() == before
    assert load_project(target).scene == before
    assert editor.document_controller.document_id == original_id
    assert editor.document_controller.path == target.resolve()
    assert not editor.document_controller.dirty


def test_open_current_path_keeps_dirty_scene_without_prompt(editor, tmp_path, monkeypatch):
    path = tmp_path / "current.drawsvg"
    assert editor._save_document_to(path)
    _edit(editor)
    editor.document_controller.refresh_dirty_state()
    before = editor.canvas._serialize_scene_state()
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: pytest.fail("Duplicate open prompted"))

    result = editor._open_project_path(path)

    assert result.name == "OPENED"
    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas._serialize_scene_state() == before
    assert editor.document_controller.dirty


@pytest.mark.parametrize("save_first", [False, True])
def test_failed_replacement_rolls_back_and_preserves_recent_entry(
    editor, tmp_path, monkeypatch, save_first
):
    target = _target(editor, tmp_path)
    _edit(editor)
    editor.document_controller.refresh_dirty_state()
    assert editor.document_controller.write_recovery_if_needed()
    candidate = editor._recovery_store.candidates()[0]
    before = editor.canvas._serialize_scene_state()
    editor._remember_recent_file(target)
    item = next(item for item in editor.canvas.scene().items() if item.data(0) == "Rectangle")
    item.setSelected(True)
    editor._handle_selection_snapshot(editor.canvas._build_selection_snapshot())
    assert editor.properties_panel._current_item is item
    original_restore = editor.canvas._restore_scene_state
    attempts = []
    errors = []

    def fail_once(state):
        attempts.append(1)
        if len(attempts) == 1:
            editor.canvas.clear_canvas()
            raise RuntimeError("Target restore failed")
        original_restore(state)

    monkeypatch.setattr(editor.canvas, "_restore_scene_state", fail_once)
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "save" if save_first else "discard")
    saved = tmp_path / "previous.drawsvg"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(saved), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: errors.append(_args[-1]))

    editor._open_recent_file(str(target))

    assert editor._window_registry.windows() == (editor,)
    assert editor.canvas._serialize_scene_state() == before
    assert str(target.resolve()) in editor._recent_files
    assert editor.canvas.scene().selectedItems() == []
    assert editor.properties_panel._current_item is None
    assert editor.properties_panel._info_label.text() == "No object selected."
    assert len(errors) == 1
    assert editor.document_controller.dirty is (not save_first)
    if save_first:
        assert load_project(saved).scene == before
    else:
        assert candidate.archive_path.is_file()


def test_double_restore_failure_detaches_and_shows_one_reopen_message(editor, tmp_path, monkeypatch):
    target = _target(editor, tmp_path)
    original = tmp_path / "original.drawsvg"
    assert editor._save_document_to(original)
    original_bytes = original.read_bytes()
    _edit(editor)
    editor.document_controller.refresh_dirty_state()
    assert editor.document_controller.write_recovery_if_needed()
    candidate = editor._recovery_store.candidates()[0]
    recovery_bytes = candidate.archive_path.read_bytes()
    original_id = editor.document_controller.document_id
    errors = []

    def fail_restore(_state):
        editor.canvas.clear_canvas()
        raise RuntimeError("Cannot restore scene")

    monkeypatch.setattr(editor.canvas, "_restore_scene_state", fail_restore)
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "discard")
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: errors.append(_args[-1]))

    result = editor._open_project_path(target)

    assert editor._window_registry.windows() == (editor,)
    assert result.name == "FAILED"
    assert len(errors) == 1
    message = errors[0].lower()
    assert "reopen" in message or "open" in message and "again" in message
    assert editor.document_controller.path is None
    assert editor.document_controller.document_id != original_id
    assert editor.windowTitle() == "Untitled * — DrawSVG UI"
    assert original.read_bytes() == original_bytes
    assert candidate.archive_path.read_bytes() == recovery_bytes
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_a, **_k: ("", ""))
    assert not editor.save_document()
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize("operation", ["new", "template"])
def test_new_and_template_cancel_preserve_document(editor, monkeypatch, operation):
    _edit(editor)
    before = editor.canvas._serialize_scene_state()
    document_id = editor.document_controller.document_id
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "cancel")

    result = editor.new_document() if operation == "new" else editor.new_document_from_template("Flowchart")

    assert editor._window_registry.windows() == (editor,)
    assert result.name == "CANCELLED"
    assert editor.canvas._serialize_scene_state() == before
    assert editor.document_controller.document_id == document_id


def test_new_reuses_widgets_and_resets_document_baseline(editor, monkeypatch):
    _edit(editor)
    editor.canvas.set_grid_visible(False)
    canvas = editor.canvas
    controller = editor.document_controller
    original_id = controller.document_id
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "discard")

    result = editor.new_document()

    assert editor._window_registry.windows() == (editor,)
    assert result.name == "OPENED"
    assert editor.canvas is canvas
    assert editor.document_controller is controller
    assert controller.document_id != original_id
    assert controller.path is None
    assert not controller.dirty
    assert controller.revision == 0
    assert editor.canvas._serialize_scene_state()["items"] == []
    assert editor.canvas._serialize_scene_state()["grid_visible"] is False
    assert not canvas.history().can_undo()
    assert not canvas.history().can_redo()


@pytest.mark.parametrize("operation", ["close", "quit"])
@pytest.mark.parametrize("choice", ["cancel", "save_cancel", "save_error", "discard"])
def test_close_and_quit_resolve_pending_edits_once(editor, tmp_path, monkeypatch, operation, choice):
    _edit(editor)
    prompts = []
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: prompts.append(1) or ("save" if choice.startswith("save") else choice))
    destination = str(tmp_path / "saved.drawsvg") if choice == "save_error" else ""
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_a, **_k: (destination, ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: None)
    if choice == "save_error":
        def fail_write(*_args, **_kwargs):
            raise OSError("Disk full")
        monkeypatch.setattr(document_controller, "save_project", fail_write)

    result = editor.close() if operation == "close" else editor._request_quit()

    assert prompts == [1]
    assert result is (choice == "discard")
    assert editor._window_registry.windows() == (() if choice == "discard" else (editor,))


@pytest.mark.parametrize("state", ["items", "path", "dirty"])
def test_recovery_offer_requires_blank_clean_unsaved_document(editor, tmp_path, monkeypatch, state):
    candidate = _candidate(editor)
    archive = candidate.archive_path.read_bytes()
    metadata = candidate.metadata_path.read_bytes()
    if state == "items":
        _edit(editor)
    elif state == "path":
        assert editor._save_document_to(tmp_path / "current.drawsvg")
    else:
        editor.document_controller.refresh_dirty_state(force_dirty=True)
    before = editor.canvas._serialize_scene_state()
    monkeypatch.setattr(editor, "_ask_recovery_candidate", lambda _candidate: pytest.fail("Recovery offered over existing document"))

    editor._offer_recovery_candidates()

    assert editor.canvas._serialize_scene_state() == before
    assert candidate.archive_path.read_bytes() == archive
    assert candidate.metadata_path.read_bytes() == metadata


@pytest.mark.parametrize("choice", ["later", "discard"])
def test_recovery_later_or_discard_preserves_unselected_candidates(editor, monkeypatch, choice):
    _candidate(editor)
    _candidate(editor)
    first, second = editor._recovery_store.candidates()
    second_bytes = second.archive_path.read_bytes()
    offered = []

    def choose(candidate):
        offered.append(candidate.document_id)
        return choice if len(offered) == 1 else "later"

    monkeypatch.setattr(editor, "_ask_recovery_candidate", choose)
    editor._offer_recovery_candidates()

    assert offered == ([first.document_id] if choice == "later" else [first.document_id, second.document_id])
    assert first.archive_path.exists() is (choice == "later")
    assert second.archive_path.read_bytes() == second_bytes
    assert not editor.document_controller.dirty
    assert editor._window_registry.windows() == (editor,)


def test_recovery_keeps_source_identity_revision_and_archive(editor, tmp_path, monkeypatch):
    source = tmp_path / "original.drawsvg"
    candidate = _candidate(editor, source_path=source)
    archive = candidate.archive_path.read_bytes()
    monkeypatch.setattr(editor, "_ask_recovery_candidate", lambda _candidate: "recover")
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: pytest.fail("Blank recovery requested save"))

    editor._offer_recovery_candidates()

    assert editor._window_registry.windows() == (editor,)
    assert editor.document_controller.document_id == candidate.document_id
    assert editor.document_controller.path == source.resolve()
    assert editor.document_controller.revision == 7
    assert editor.document_controller.dirty
    assert candidate.archive_path.read_bytes() == archive
    assert editor.save_document()
    assert not candidate.archive_path.exists()


def test_failed_recovery_keeps_blank_document_and_archive(editor, monkeypatch):
    candidate = _candidate(editor)
    candidate.archive_path.write_bytes(b"corrupt recovery archive")
    original_id = editor.document_controller.document_id
    errors = []
    monkeypatch.setattr(editor, "_ask_recovery_candidate", lambda _candidate: "recover")
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_args: errors.append(_args[-1]))

    editor._offer_recovery_candidates()

    assert editor.document_controller.document_id == original_id
    assert not editor.document_controller.dirty
    assert candidate.archive_path.read_bytes() == b"corrupt recovery archive"
    assert len(errors) == 1
    assert editor._window_registry.windows() == (editor,)


def test_native_python_native_switches_keep_identity_history_and_scene_isolated(editor, tmp_path, monkeypatch):
    _edit(editor)
    editor.canvas.add_guide("vertical", 100.0)
    editor.canvas.set_bitmap_assets((ProjectAsset("old.svg", b"<svg/>", "image/svg+xml"),))
    manager = editor.canvas.layer_manager()
    assert manager.set_layer_locked(manager.layers()[0].id, True)
    original = tmp_path / "native.drawsvg"
    assert editor._save_document_to(original)
    native_state = editor.canvas._serialize_scene_state()
    native_id = editor.document_controller.document_id
    editor.canvas.set_connector_creation_enabled(True)
    editor.canvas._connector_start = QtCore.QPointF(10, 10)
    source = tmp_path / "exchange.py"
    source.write_text(
        "d = draw.Drawing(200, 100)\n"
        "_rect = draw.Rectangle(50, 50, 20, 10, fill='blue')\n"
        "d.append(_rect)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: "discard")

    assert editor._open_python_document(source).name == "OPENED"

    controller = editor.document_controller
    assert controller.document_id != native_id
    assert controller.path is None
    assert controller.dirty and controller.revision == 1
    assert editor.canvas.guides() == ()
    assert editor.canvas.bitmap_assets() == ()
    assert all(not layer.locked for layer in editor.canvas.layer_manager().layers())
    assert not editor.canvas.connector_creation_enabled()
    assert editor.canvas._connector_start is None
    assert not editor.canvas.history().can_undo()
    assert not editor.canvas.history().can_redo()
    assert len(editor.canvas._serialize_scene_state()["items"]) == 1
    assert editor._window_registry.windows() == (editor,)

    assert editor._open_project_path(original).name == "OPENED"

    assert controller.document_id == native_id
    assert controller.path == original.resolve()
    assert not controller.dirty and controller.revision == 0
    assert editor.canvas._serialize_scene_state() == native_state
    assert [asset.name for asset in editor.canvas.bitmap_assets()] == ["old.svg"]
    assert not editor.canvas.history().can_undo()
    assert not editor.canvas.history().can_redo()
    assert editor._window_registry.windows() == (editor,)


@pytest.mark.parametrize("enabled", [False, True])
def test_startup_recovery_switch_controls_offer_and_timer(editor, tmp_path, monkeypatch, application, enabled):
    candidate = _candidate(editor)
    offered = []
    monkeypatch.setattr(MainWindow, "_ask_recovery_candidate", lambda _self, item: offered.append(item.document_id) or "recover")
    registry = DocumentWindowRegistry()
    startup = MainWindow(
        recent_files_path=tmp_path / "startup-recent.json",
        window_registry=registry,
        recovery_store=editor._recovery_store,
        recovery_enabled=enabled,
        check_startup_recovery=True,
    )
    try:
        application.processEvents()
        assert offered == ([candidate.document_id] if enabled else [])
        assert registry.windows() == (startup,)
        assert startup.document_controller._recovery_timer.isActive() is enabled
        if enabled:
            assert startup.document_controller.document_id == candidate.document_id
            assert startup.document_controller.dirty
        else:
            _edit(startup)
            assert not startup.document_controller.write_recovery_if_needed()
            assert len(editor._recovery_store.candidates()) == 1
    finally:
        startup._force_close = True
        startup.close()


def test_open_project_owned_by_another_window_keeps_current_document(editor, tmp_path, monkeypatch):
    other = MainWindow(
        recent_files_path=tmp_path / "recent.json",
        window_registry=editor._window_registry,
        recovery_enabled=False,
        check_startup_recovery=False,
    )
    target = tmp_path / "owned.drawsvg"
    assert other._save_document_to(target)
    _edit(editor)
    before = editor.canvas._serialize_scene_state()
    monkeypatch.setattr(editor, "_ask_unsaved_changes", lambda: pytest.fail("Focus prompted to replace"))

    result = editor._open_project_path(target)

    assert result.name == "OPENED"
    assert editor.canvas._serialize_scene_state() == before
    assert editor.document_controller.path is None
    assert editor._window_registry.windows() == (editor, other)
