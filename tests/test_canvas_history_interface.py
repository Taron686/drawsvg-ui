from canvas_view import CanvasView, SceneHistory


def test_history_uses_public_scene_state_interface(application, monkeypatch):
    view = CanvasView()
    view.history()._timer.stop()
    state = {"value": 1}
    restored = []
    monkeypatch.setattr(view, "serialize_scene_state", lambda: dict(state))
    monkeypatch.setattr(view, "restore_scene_state", lambda data: restored.append(data))
    history = SceneHistory(view)
    history.capture_initial_state()
    state["value"] = 2
    history.capture_now()
    history.undo()
    assert restored == [{"value": 1}]
    view.close()
