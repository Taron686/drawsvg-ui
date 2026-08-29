from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6 import QtGui, QtWidgets

import main_window
from document_controller import DocumentWindowRegistry
from document_format import ProjectDocument
from document_io import load_project, save_project
from items import RectItem
from main_window import MainWindow
from recovery import RecoveryStore


def _window(
    tmp_path: Path,
    *,
    registry: DocumentWindowRegistry | None = None,
    store: RecoveryStore | None = None,
) -> MainWindow:
    return MainWindow(
        recent_files_path=tmp_path / "recent.json",
        window_registry=registry,
        recovery_store=store,
    )


def _dirty(window: MainWindow) -> None:
    assert window.canvas.add_shape_at_view_center("Rectangle") is not None
    window.document_controller.refresh_dirty_state()
    assert window.document_controller.dirty


def _force_close(registry: DocumentWindowRegistry) -> None:
    for window in registry.windows():
        window._force_close = True
        window.close()


def test_file_menu_exposes_native_document_actions_and_shortcuts(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    registry = window._window_registry
    try:
        assert window.windowTitle() == "Untitled — DrawSVG UI"
        assert window.actionNew.shortcut().toString() == "Ctrl+N"
        assert window.actionOpen_project.shortcut().toString() == "Ctrl+O"
        assert window.actionSave_project.shortcut().toString() == "Ctrl+S"
        assert window.actionSave_project_as.shortcut().toString() == "Ctrl+Shift+S"
    finally:
        _force_close(registry)


def test_save_and_undo_track_document_dirty_state_and_title(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    window = _window(tmp_path)
    registry = window._window_registry
    destination = tmp_path / "drawing"
    try:
        _dirty(window)
        assert window.windowTitle() == "Untitled * — DrawSVG UI"
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getSaveFileName",
            lambda *_args, **_kwargs: (str(destination), ""),
        )

        assert window.save_document_as()
        project_path = destination.with_suffix(".drawsvg")
        assert window.document_controller.path == project_path.resolve()
        assert not window.document_controller.dirty
        assert window.windowTitle() == "drawing.drawsvg — DrawSVG UI"
        assert load_project(project_path).document_id == window.document_controller.document_id

        item = next(
            item
            for item in window.canvas.scene().items()
            if isinstance(item, RectItem)
        )
        item.moveBy(25.0, 0.0)
        window.canvas.history().capture_now()
        window.document_controller.refresh_dirty_state()
        assert window.document_controller.dirty

        window.canvas.undo()
        window.document_controller.refresh_dirty_state()
        assert not window.document_controller.dirty
    finally:
        _force_close(registry)


def test_new_windows_keep_uuid_history_and_dirty_state_separate(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    registry = DocumentWindowRegistry()
    store = RecoveryStore(tmp_path / "recovery")
    first = _window(tmp_path, registry=registry, store=store)
    try:
        second = first.new_document_window()
        _dirty(first)

        assert registry.windows() == (first, second)
        assert first.document_controller.document_id != second.document_controller.document_id
        assert first.document_controller.dirty
        assert not second.document_controller.dirty
        assert first.canvas.history().can_undo()
        assert not second.canvas.history().can_undo()
    finally:
        _force_close(registry)


def test_open_uses_a_new_window_and_focuses_an_already_open_project(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    registry = DocumentWindowRegistry()
    store = RecoveryStore(tmp_path / "recovery")
    root = _window(tmp_path, registry=registry, store=store)
    project_path = tmp_path / "existing.drawsvg"
    save_project(
        project_path,
        ProjectDocument(scene=root.canvas._serialize_scene_state()),
    )
    try:
        opened = root._open_project_path(project_path)
        assert opened is not None and opened is not root
        assert len(registry.windows()) == 2
        assert opened.document_controller.path == project_path.resolve()
        assert not opened.document_controller.dirty

        duplicate = root._open_project_path(project_path)
        assert duplicate is opened
        assert len(registry.windows()) == 2
    finally:
        _force_close(registry)


def test_failed_open_keeps_current_document_and_registry_unchanged(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = DocumentWindowRegistry()
    window = _window(tmp_path, registry=registry)
    _dirty(window)
    before = window.canvas._serialize_scene_state()
    broken_path = tmp_path / "broken.drawsvg"
    broken_path.write_bytes(b"not a project")
    errors: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "critical",
        lambda _parent, _title, message: errors.append(message),
    )
    try:
        assert window._open_project_path(broken_path) is None
        assert registry.windows() == (window,)
        assert window.canvas._serialize_scene_state() == before
        assert window.document_controller.path is None
        assert window.document_controller.dirty
        assert errors and "application log" in errors[0]
    finally:
        _force_close(registry)


def test_save_as_rejects_a_path_owned_by_another_window(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = DocumentWindowRegistry()
    first = _window(tmp_path, registry=registry)
    second = first.new_document_window()
    destination = tmp_path / "shared.drawsvg"
    warnings: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    try:
        assert first._save_document_to(destination)
        _dirty(second)
        assert not second._save_document_to(destination)
        assert second.document_controller.path is None
        assert second.document_controller.dirty
        assert warnings == ["This project is already open in another editor window."]
    finally:
        _force_close(registry)


def test_recovery_is_uuid_scoped_and_skips_duplicate_snapshots(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    registry = DocumentWindowRegistry()
    store = RecoveryStore(tmp_path / "recovery")
    first = _window(tmp_path, registry=registry, store=store)
    second = first.new_document_window()
    try:
        _dirty(first)
        _dirty(second)
        assert first.document_controller.write_recovery_if_needed()
        assert second.document_controller.write_recovery_if_needed()
        assert not first.document_controller.write_recovery_if_needed()

        candidates = store.candidates()
        assert {candidate.document_id for candidate in candidates} == {
            first.document_controller.document_id,
            second.document_controller.document_id,
        }
        assert len(tuple((tmp_path / "recovery").glob("*.drawsvg"))) == 2
        assert all(store.load(candidate).document_id == candidate.document_id for candidate in candidates)
    finally:
        _force_close(registry)


def test_recovery_is_only_offered_when_newer_than_its_source(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    registry = DocumentWindowRegistry()
    store = RecoveryStore(tmp_path / "recovery")
    window = _window(tmp_path, registry=registry, store=store)
    project_path = tmp_path / "drawing.drawsvg"
    try:
        assert window._save_document_to(project_path)
        _dirty(window)
        assert window.document_controller.write_recovery_if_needed()
        assert len(store.candidates()) == 1

        future = max(
            candidate.recovered_at_ns for candidate in store.candidates()
        ) + 1_000_000_000
        os.utime(project_path, ns=(future, future))
        assert store.candidates() == ()
    finally:
        _force_close(registry)


def test_recovery_restore_is_dirty_and_preserves_document_identity(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    registry = DocumentWindowRegistry()
    store = RecoveryStore(tmp_path / "recovery")
    source = _window(tmp_path, registry=registry, store=store)
    try:
        _dirty(source)
        state = source.canvas._serialize_scene_state()
        document_id = source.document_controller.document_id
        assert source.document_controller.write_recovery_if_needed()
        candidate = store.candidates()[0]

        restored = source.new_document_window()
        restored.document_controller.restore_recovery(candidate)
        assert restored.document_controller.document_id == document_id
        assert restored.document_controller.dirty
        assert restored.document_controller.path is None
        assert restored.canvas._serialize_scene_state() == state
    finally:
        _force_close(registry)


def test_startup_recovery_offers_every_candidate(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    writer_registry = DocumentWindowRegistry()
    first = _window(tmp_path, registry=writer_registry, store=store)
    second = first.new_document_window()
    _dirty(first)
    _dirty(second)
    assert first.document_controller.write_recovery_if_needed()
    assert second.document_controller.write_recovery_if_needed()
    _force_close(writer_registry)

    registry = DocumentWindowRegistry()
    startup = _window(tmp_path, registry=registry, store=store)
    offered: list[str] = []
    monkeypatch.setattr(
        startup,
        "_ask_recovery_candidate",
        lambda candidate: offered.append(candidate.document_id) or "recover",
    )
    try:
        startup._offer_recovery_candidates()
        assert set(offered) == {
            first.document_controller.document_id,
            second.document_controller.document_id,
        }
        assert len(registry.windows()) == 2
        assert all(window.document_controller.dirty for window in registry.windows())
    finally:
        _force_close(registry)


def test_close_cancel_keeps_window_and_discard_removes_its_recovery(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = DocumentWindowRegistry()
    store = RecoveryStore(tmp_path / "recovery")
    window = _window(tmp_path, registry=registry, store=store)
    _dirty(window)
    assert window.document_controller.write_recovery_if_needed()
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda: "cancel")

    assert not window.close()
    assert registry.windows() == (window,)
    assert len(store.candidates()) == 1

    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda: "discard")
    assert window.close()
    assert registry.windows() == ()
    assert store.candidates() == ()


def test_close_save_uses_native_save_as_and_clears_recovery(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = DocumentWindowRegistry()
    store = RecoveryStore(tmp_path / "recovery")
    window = _window(tmp_path, registry=registry, store=store)
    destination = tmp_path / "saved.drawsvg"
    _dirty(window)
    assert window.document_controller.write_recovery_if_needed()
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda: "save")
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(destination), ""),
    )

    assert window.close()
    assert destination.is_file()
    assert registry.windows() == ()
    assert store.candidates() == ()


def test_quit_cancel_closes_none_of_the_document_windows(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = DocumentWindowRegistry()
    first = _window(tmp_path, registry=registry)
    second = first.new_document_window()
    _dirty(first)
    _dirty(second)
    monkeypatch.setattr(first, "_ask_unsaved_changes", lambda: "discard")
    monkeypatch.setattr(second, "_ask_unsaved_changes", lambda: "cancel")
    try:
        assert not first._request_quit()
        assert registry.windows() == (first, second)
    finally:
        _force_close(registry)


def test_quit_discard_closes_all_document_windows(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = DocumentWindowRegistry()
    first = _window(tmp_path, registry=registry)
    second = first.new_document_window()
    _dirty(first)
    _dirty(second)
    monkeypatch.setattr(first, "_ask_unsaved_changes", lambda: "discard")
    monkeypatch.setattr(second, "_ask_unsaved_changes", lambda: "discard")

    assert first._request_quit()
    assert registry.windows() == ()


def test_python_import_opens_an_unsaved_dirty_document_window(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = DocumentWindowRegistry()
    root = _window(tmp_path, registry=registry)
    source = tmp_path / "legacy.py"

    def import_fixture(scene, _parent, _path=None):
        scene.addItem(RectItem(0.0, 0.0, 20.0, 10.0))
        return source.resolve()

    monkeypatch.setattr(main_window, "import_drawsvg_py", import_fixture)
    try:
        assert root._open_python_document(source) == source.resolve()
        imported = registry.windows()[-1]
        assert imported is not root
        assert imported.document_controller.path is None
        assert imported.document_controller.dirty
        assert imported.windowTitle() == "Untitled * — DrawSVG UI"
    finally:
        _force_close(registry)
