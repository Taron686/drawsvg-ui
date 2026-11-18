import random

from PySide6 import QtCore, QtTest, QtWidgets

import canvas_view as canvas_module


def test_drag_snap_matches_uncached_after_scene_edits(canvas_view, application):
    scene = canvas_view.scene()
    items = []
    for i in range(240):
        x, y = (i % 20) * 51, (i // 20) * 47
        if i % 3 == 0:
            item = QtWidgets.QGraphicsRectItem(x, y, 30, 20)
        elif i % 3 == 1:
            item = QtWidgets.QGraphicsEllipseItem(x, y, 30, 20)
        else:
            item = QtWidgets.QGraphicsLineItem(x, y, x + 30, y + 20)
        scene.addItem(item)
        items.append(item)
    canvas_view.set_grid_snap_enabled(False)
    randomizer = random.Random(143)
    probes = [
        QtCore.QPointF(randomizer.uniform(0, 1100), randomizer.uniform(0, 650))
        for _ in range(120)
    ]
    # Include equal-distance and duplicate candidate cases as well as random probes.
    probes += [QtCore.QPointF(25.5, 23.5), QtCore.QPointF(51, 47)]
    for phase in range(3):
        if phase == 1:
            items[0].moveBy(23, 31)
            scene.removeItem(items.pop(1))
            added = QtWidgets.QGraphicsRectItem(111, 222, 33, 44)
            scene.addItem(added)
            items.append(added)
        if phase == 2:
            items[-1].hide()
        application.processEvents()
        exclude = (items[0],)
        expected = [
            canvas_view.snap_scene_position(p, QtCore.QSizeF(20, 15), exclude=exclude)
            for p in probes
        ]
        canvas_view._begin_snap_drag()
        actual = [
            canvas_view.snap_scene_position(p, QtCore.QSizeF(20, 15), exclude=exclude)
            for p in probes
        ]
        canvas_view._end_snap_drag()
        assert actual == expected


def test_drag_reuses_snap_bounds(canvas_view, monkeypatch):
    for i in range(100):
        canvas_view.scene().addRect(i * 40, 0, 20, 20)
    original = canvas_module.item_snap_bounds
    calls = 0

    def bounds(item, view):
        nonlocal calls
        calls += 1
        return original(item, view)

    monkeypatch.setattr(canvas_module, "item_snap_bounds", bounds)
    canvas_view._begin_snap_drag()
    canvas_view.snap_scene_position(QtCore.QPointF(20, 20))
    initial = calls
    for i in range(20):
        canvas_view.snap_scene_position(QtCore.QPointF(i * 3, 20))
    canvas_view._end_snap_drag()
    assert initial >= 100
    assert calls == initial


def test_sorted_lookup_keeps_original_ties(canvas_view):
    randomizer = random.Random(52)
    for _ in range(500):
        values = tuple(float(randomizer.randrange(-5, 6)) for _ in range(3))
        candidates = tuple(float(randomizer.randrange(-8, 9)) for _ in range(30))
        ordered = sorted((value, index) for index, value in enumerate(candidates))
        assert canvas_view._nearest_sorted_snap(values, ordered, 4) == (
            canvas_view._nearest_snap(values, candidates, 4)
        )


def test_mouse_press_and_release_bound_cache_lifetime(canvas_view, application):
    canvas_view.show()
    application.processEvents()
    QtTest.QTest.mousePress(canvas_view.viewport(), QtCore.Qt.MouseButton.LeftButton)
    assert canvas_view._snap_drag_cache == {}
    QtTest.QTest.mouseRelease(canvas_view.viewport(), QtCore.Qt.MouseButton.LeftButton)
    assert canvas_view._snap_drag_cache is None
