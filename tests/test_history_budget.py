from __future__ import annotations

from canvas_view import CanvasView, SceneHistory


def test_scene_history_evicts_oldest_states_at_state_limit(application) -> None:
    view = CanvasView()
    view.history()._timer.stop()
    history = SceneHistory(view, max_states=3, max_bytes=1024)
    snapshots = iter(["state-0", "state-1", "state-2", "state-3"])
    history._serialize_state = lambda: next(snapshots)  # type: ignore[method-assign]

    history.capture_initial_state()
    for _ in range(3):
        history.capture_now()

    assert history._states == ["state-1", "state-2", "state-3"]
    assert history.history_bytes == sum(len(state) for state in history._states)
    view.close()


def test_scene_history_evicts_oldest_states_at_byte_limit(application) -> None:
    view = CanvasView()
    view.history()._timer.stop()
    history = SceneHistory(view, max_states=50, max_bytes=12)
    snapshots = iter(["initial", "second", "third", "fourth"])
    history._serialize_state = lambda: next(snapshots)  # type: ignore[method-assign]

    history.capture_initial_state()
    history.capture_now()
    history.capture_now()
    history.capture_now()

    assert history._states == ["third", "fourth"]
    assert history.history_bytes == len("third") + len("fourth")
    assert history.history_bytes <= 12
    view.close()


def test_scene_history_rejects_snapshot_larger_than_byte_limit(application) -> None:
    view = CanvasView()
    view.history()._timer.stop()
    history = SceneHistory(view, max_states=50, max_bytes=4)
    history._serialize_state = lambda: "oversized"  # type: ignore[method-assign]

    history.capture_initial_state()

    assert history._states == []
    assert history.history_bytes == 0
    view.close()
