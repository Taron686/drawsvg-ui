from PySide6 import QtCore, QtTest


def test_scene_changes_inside_existing_rect_rescan_once_after_a_pause(
    canvas_view, monkeypatch
):
    calls = []
    monkeypatch.setattr(canvas_view, "_update_scene_rect", lambda: calls.append(1))
    rect = canvas_view.scene().sceneRect()
    for _ in range(10):
        canvas_view._on_scene_rect_changed(
            [QtCore.QRectF(rect.center(), QtCore.QSizeF(1, 1))]
        )
    assert calls == []
    QtTest.QTest.qWait(canvas_view._scene_rect_timer.interval() + 100)
    assert calls == [1]

    canvas_view._on_scene_rect_changed([QtCore.QRectF(rect.right() + 1, 0, 10, 10)])
    assert calls == [1, 1]
    assert not canvas_view._scene_rect_timer.isActive()


def test_moving_item_beyond_scene_rect_expands_it(canvas_view, application):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    application.processEvents()
    item.setPos(10000, 10000)
    application.processEvents()
    assert canvas_view.scene().sceneRect().contains(item.sceneBoundingRect())


def test_scene_rect_shrinks_after_item_returns_inside(canvas_view, application):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(0, 0), snap_to_grid=False)
    application.processEvents()
    QtTest.QTest.qWait(canvas_view._scene_rect_timer.interval() + 100)
    compact = canvas_view.scene().sceneRect()

    item.setPos(10000, 10000)
    application.processEvents()
    expanded = canvas_view.scene().sceneRect()
    assert expanded.width() > compact.width()

    item.setPos(0, 0)
    application.processEvents()
    QtTest.QTest.qWait(canvas_view._scene_rect_timer.interval() + 100)
    assert canvas_view.scene().sceneRect().width() < expanded.width()
