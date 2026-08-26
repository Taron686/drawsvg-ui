from __future__ import annotations

from PySide6 import QtCore
from PySide6.QtTest import QTest


def _state_count(canvas_view) -> int:
    return len(canvas_view.history()._states)


def test_separate_shape_actions_capture_immediately(canvas_view) -> None:
    history = canvas_view.history()
    assert _state_count(canvas_view) == 1

    canvas_view.add_shape("Rectangle", QtCore.QPointF(10, 10))
    assert _state_count(canvas_view) == 2

    canvas_view.add_shape("Ellipse", QtCore.QPointF(100, 10))
    assert _state_count(canvas_view) == 3
    assert history.can_undo()


def test_nested_transaction_captures_one_long_action(canvas_view) -> None:
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(10, 10))
    assert item is not None
    before = _state_count(canvas_view)
    history = canvas_view.history()

    with history.transaction():
        item.moveBy(10, 0)
        QTest.qWait(300)
        assert _state_count(canvas_view) == before
        with history.transaction():
            item.moveBy(10, 0)
        assert _state_count(canvas_view) == before

    assert _state_count(canvas_view) == before + 1


def test_timer_remains_a_fallback_without_transaction(canvas_view) -> None:
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(10, 10))
    assert item is not None
    before = _state_count(canvas_view)

    item.moveBy(10, 0)
    QTest.qWait(300)

    assert _state_count(canvas_view) == before + 1
