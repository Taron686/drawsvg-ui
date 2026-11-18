from PySide6 import QtTest

from document_controller import DocumentController
from recovery import RecoveryStore


def test_dirty_refresh_coalesces_scene_changes(
    canvas_view, tmp_path, monkeypatch, application
):
    controller = DocumentController(
        canvas_view, recovery_store=RecoveryStore(tmp_path), recovery_enabled=False
    )
    application.processEvents()
    controller._dirty_timer.stop()
    canvas_view.history()._timer.stop()
    calls = 0
    original = controller._fingerprint

    def fingerprint():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(controller, "_fingerprint", fingerprint)
    for _ in range(4):
        controller._schedule_dirty_refresh()
        QtTest.QTest.qWait(20)
    assert calls == 0
    QtTest.QTest.qWait(300)
    assert calls == 1


def test_history_snapshot_supplies_pending_dirty_refresh(
    canvas_view, tmp_path, monkeypatch, application
):
    controller = DocumentController(
        canvas_view, recovery_store=RecoveryStore(tmp_path), recovery_enabled=False
    )
    application.processEvents()
    controller._dirty_timer.stop()
    canvas_view.history()._timer.stop()
    calls = 0
    original = canvas_view._serialize_scene_state

    def serialize():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(canvas_view, "_serialize_scene_state", serialize)
    controller._schedule_dirty_refresh()
    canvas_view.history().capture_now()
    QtTest.QTest.qWait(300)
    assert calls == 1
