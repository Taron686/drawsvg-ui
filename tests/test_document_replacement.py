from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtCore, QtTest

from document_controller import DocumentController
from document_format import ProjectAsset, ProjectDocument
from recovery import RecoveryStore


@pytest.fixture
def controller(canvas_view, tmp_path):
    result = DocumentController(
        canvas_view, recovery_store=RecoveryStore(tmp_path / "recovery")
    )
    yield result
    result._dirty_timer.stop()
    result._recovery_timer.stop()
    canvas_view.history()._timer.stop()


@pytest.mark.parametrize(
    ("baseline", "dirty", "revision"),
    [("saved", False, 0), ("blank", False, 0), ("unsaved", True, 1),
     ("recovered", True, 7)],
)
def test_replacement_establishes_identity_assets_and_single_history_baseline(
    controller, canvas_view, tmp_path, application, baseline, dirty, revision
):
    # Missing history suppression would retain a previous document in Undo.
    canvas_view.add_shape_at_view_center("Rectangle")
    canvas_view.history().capture_now()
    controller.refresh_dirty_state()
    assert controller.write_recovery_if_needed()
    old_id = controller.document_id
    asset = ProjectAsset("attachment.bin", b"target asset")
    document = ProjectDocument(
        scene={"items": [], "grid_visible": False}, assets=(asset,)
    )
    source = tmp_path / "target.drawsvg" if baseline in {"saved", "recovered"} else None

    controller.replace_document(
        document, source_path=source, baseline=baseline, recovery_revision=7
    )
    application.processEvents()
    QtTest.QTest.qWait(280)

    assert controller.document_id == document.document_id != old_id
    assert controller.path == source
    assert controller.dirty is dirty
    assert controller.revision == revision
    assert canvas_view.bitmap_assets() == (asset,)
    assert canvas_view._serialize_scene_state()["items"] == []
    assert not canvas_view._serialize_scene_state()["grid_visible"]
    history = canvas_view.history()
    assert history._index == 0
    assert len(history._states) == 1
    assert not history.can_undo() and not history.can_redo()
    assert controller.recovery_store.candidates() == ()


def test_failed_replacement_restores_scene_view_metadata_and_redo(
    controller, canvas_view, tmp_path, monkeypatch, application
):
    # A restore that records clear_canvas destroys the existing Redo branch.
    canvas_view.add_shape_at_view_center("Rectangle")
    canvas_view.history().capture_now()
    canvas_view.add_shape("Ellipse", QtCore.QPointF(300, 100))
    canvas_view.history().capture_now()
    canvas_view.undo()
    canvas_view.set_bitmap_assets((ProjectAsset("old.bin", b"original"),))
    controller.save(tmp_path / "original.drawsvg")
    canvas_view.scale(1.7, 1.7)
    selected = next(item for item in canvas_view.scene().items()
                    if canvas_view._is_serializable_item(item))
    selected.setSelected(True)
    before = controller.project_document()
    history = canvas_view.history()
    history_before = (list(history._states), history._index, history.history_bytes)
    transform = canvas_view.transform()
    scroll = (canvas_view.horizontalScrollBar().value(), canvas_view.verticalScrollBar().value())
    metadata = (controller.path, controller.document_id, controller.dirty, controller.revision)
    original_restore = canvas_view._restore_scene_state

    def fail_target(state):
        if state.get("grid_visible") is False:
            canvas_view.clear_canvas()
            raise RuntimeError("target restore failed")
        original_restore(state)

    monkeypatch.setattr(canvas_view, "_restore_scene_state", fail_target)
    with pytest.raises(RuntimeError, match="target restore failed"):
        controller.replace_document(
            ProjectDocument(scene={"items": [], "grid_visible": False}),
            source_path=None, baseline="unsaved",
        )
    application.processEvents()
    QtTest.QTest.qWait(280)

    assert controller.project_document() == before
    assert (controller.path, controller.document_id, controller.dirty, controller.revision) == metadata
    assert (history._states, history._index, history.history_bytes) == history_before
    assert history.can_redo()
    assert canvas_view.transform() == transform
    assert (canvas_view.horizontalScrollBar().value(), canvas_view.verticalScrollBar().value()) == scroll
    assert canvas_view.scene().selectedItems() == []
    canvas_view.redo()
    assert len(canvas_view._serialize_scene_state()["items"]) == 2


def test_validation_failure_keeps_existing_item_selection_and_assets(
    controller, canvas_view
):
    # Validation must precede even a rollback, since rollback replaces item identity.
    item = canvas_view.add_shape_at_view_center("Rectangle")
    item.setSelected(True)
    asset = ProjectAsset("old.bin", b"original")
    canvas_view.set_bitmap_assets((asset,))
    with pytest.raises(ValueError, match="Unknown shape"):
        controller.replace_document(
            ProjectDocument(scene={"items": [{"shape": "Unknown Shape"}]}),
            source_path=None, baseline="unsaved",
        )
    assert canvas_view.scene().selectedItems() == [item]
    assert canvas_view.bitmap_assets() == (asset,)


@pytest.mark.parametrize("broken_serialization", [False, True])
def test_double_failure_detaches_and_preserves_original_archives(
    controller, canvas_view, tmp_path, monkeypatch, application, broken_serialization
):
    # Failed rollback must never leave Save or recovery pointing at the original UUID/path.
    from document_controller import DocumentReplacementError

    canvas_view.add_shape_at_view_center("Rectangle")
    original_path = controller.save(tmp_path / "original.drawsvg")
    canvas_view.add_shape_at_view_center("Ellipse")
    assert controller.write_recovery_if_needed()
    original_id = controller.document_id
    candidate = controller.recovery_store.candidates()[0]
    archives = {path: path.read_bytes() for path in (
        original_path, candidate.archive_path, candidate.metadata_path
    )}

    def cannot_serialize():
        raise ValueError("damaged scene cannot serialize")

    def fail_restore(_state):
        canvas_view.clear_canvas()
        if broken_serialization:
            monkeypatch.setattr(canvas_view, "_serialize_scene_state", cannot_serialize)
        raise RuntimeError("restore failed")

    monkeypatch.setattr(canvas_view, "_restore_scene_state", fail_restore)
    with pytest.raises(DocumentReplacementError) as failure:
        controller.replace_document(
            ProjectDocument(scene={"items": []}), source_path=None, baseline="blank"
        )
    assert failure.value.rollback_failed
    assert controller.path is None
    assert controller.document_id != original_id
    controller.refresh_dirty_state()
    assert controller.dirty
    assert controller.revision >= 1
    assert controller._saved_fingerprint is None
    with pytest.raises(ValueError, match="destination"):
        controller.save()
    if broken_serialization:
        application.processEvents()
        QtTest.QTest.qWait(280)
        assert not controller.write_recovery_if_needed()
        with pytest.raises(ValueError, match="cannot serialize"):
            controller.save(tmp_path / "broken.drawsvg")
        assert not (tmp_path / "broken.drawsvg").exists()
    assert all(path.read_bytes() == payload for path, payload in archives.items())


def test_recovery_with_current_uuid_preserves_its_candidate(controller, canvas_view):
    # UUID-equal replacement must not discard the candidate it just restored.
    canvas_view.add_shape_at_view_center("Rectangle")
    assert controller.write_recovery_if_needed()
    candidate = controller.recovery_store.candidates()[0]
    archive = candidate.archive_path.read_bytes()
    controller.restore_recovery(candidate)
    assert controller.dirty
    assert controller.document_id == candidate.document_id
    assert candidate.archive_path.read_bytes() == archive


def test_history_suspension_is_nested_and_stops_pending_capture(canvas_view):
    # Inner exit must not turn recording back on before the outer restore ends.
    history = canvas_view.history()
    before = (list(history._states), history._index, history.history_bytes)
    history.mark_dirty()
    with history.suspended():
        assert not history._timer.isActive()
        canvas_view.add_shape_at_view_center("Rectangle")
        with history.suspended():
            history.capture_now()
        canvas_view.add_shape_at_view_center("Ellipse")
        history.capture_now()
    assert (history._states, history._index, history.history_bytes) == before
    history.capture_initial_state()
    assert history._index == 0 and len(history._states) == 1


def test_repeated_replacement_clears_connector_preview(controller, canvas_view):
    # Transient connector endpoints otherwise retain references to removed items.
    for baseline in ("blank", "unsaved", "blank"):
        canvas_view.set_connector_creation_enabled(True)
        canvas_view._handle_connector_click(QtCore.QPoint(10, 10))
        controller.replace_document(
            ProjectDocument(scene={"items": [], "grid_visible": True}),
            source_path=None, baseline=baseline,
        )
        assert not canvas_view.connector_creation_enabled()
        assert canvas_view._connector_start is None
        assert canvas_view._connector_preview_position is None
        assert not canvas_view.history().can_undo()


def test_public_fit_restores_master_page_zoom(canvas_view):
    # Existing windows need an explicit fit; showEvent only fits their first show.
    canvas_view.resize(1000, 700)
    canvas_view._fit_view_to_page()
    fitted = canvas_view.transform()
    canvas_view.scale(2, 2)
    canvas_view.fit_to_page()
    assert canvas_view.transform() == fitted


@pytest.mark.parametrize(("baseline", "source"), [
    ("saved", None), ("saved", Path("relative.drawsvg")),
    ("blank", Path("unexpected.drawsvg")), ("unsaved", Path("unexpected.drawsvg")),
    ("unknown", None),
])
def test_invalid_baseline_contract_does_not_replace_selection(controller, canvas_view, baseline, source):
    item = canvas_view.add_shape_at_view_center("Rectangle")
    item.setSelected(True)
    with pytest.raises(ValueError):
        controller.replace_document(ProjectDocument(scene={"items": []}), source_path=source, baseline=baseline)
    assert canvas_view.scene().selectedItems() == [item]


def test_history_baseline_serialization_failure_preserves_redo(canvas_view, monkeypatch):
    # A failed initial snapshot must not clear history before it can serialize.
    canvas_view.add_shape_at_view_center("Rectangle")
    canvas_view.add_shape_at_view_center("Ellipse")
    canvas_view.undo()
    history = canvas_view.history()
    before = (list(history._states), history._index, history.history_bytes)

    def fail_snapshot():
        raise ValueError("snapshot failed")

    monkeypatch.setattr(history, "_serialize_state", fail_snapshot)
    with pytest.raises(ValueError, match="snapshot failed"):
        history.capture_initial_state()
    assert (history._states, history._index, history.history_bytes) == before
    assert history.can_redo()


def test_replacement_rolls_back_when_new_history_cannot_serialize(
    controller, canvas_view, monkeypatch
):
    # Errors during history finalization still belong to the replacement transaction.
    canvas_view.add_shape_at_view_center("Rectangle")
    before = controller.project_document()
    history = canvas_view.history()
    old_history = (list(history._states), history._index, history.history_bytes)

    def fail_snapshot():
        raise ValueError("new snapshot failed")

    monkeypatch.setattr(history, "_serialize_state", fail_snapshot)
    with pytest.raises(ValueError, match="new snapshot failed"):
        controller.replace_document(
            ProjectDocument(scene={"items": []}), source_path=None, baseline="blank"
        )
    assert controller.project_document() == before
    assert (history._states, history._index, history.history_bytes) == old_history


def test_suspension_preserves_existing_recording_suppression(canvas_view):
    history = canvas_view.history()
    history._ignore_changes = True
    try:
        with history.suspended():
            pass
        assert history._ignore_changes
    finally:
        history._ignore_changes = False


def test_controller_load_uses_saved_replacement_baseline(controller, canvas_view, tmp_path):
    from document_io import save_project

    canvas_view.add_shape_at_view_center("Rectangle")
    source = tmp_path / "source.drawsvg"
    document = ProjectDocument(scene={"schema_version": 1, "items": [], "grid_visible": True})
    save_project(source, document)
    assert controller.load(source) == source
    assert controller.document_id == document.document_id
    assert controller.path == source
    assert not controller.dirty
    assert controller.revision == 0
    assert not canvas_view.history().can_undo()


def test_invalid_target_assets_preserve_selected_item(controller, canvas_view):
    item = canvas_view.add_shape_at_view_center("Rectangle")
    item.setSelected(True)
    with pytest.raises(ValueError):
        controller.replace_document(
            ProjectDocument(scene={"items": []}, assets=(ProjectAsset("bad.png", b"invalid", "image/png"),)),
            source_path=None, baseline="unsaved",
        )
    assert canvas_view.scene().selectedItems() == [item]
