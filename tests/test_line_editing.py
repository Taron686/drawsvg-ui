from __future__ import annotations

import json

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from items import LineItem
from main_window import MainWindow


@pytest.fixture
def rotation_window(application, tmp_path):
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    window = MainWindow(recent_files_path=tmp_path / "recent.json", settings=settings)
    window.resize(1200, 850)
    arrow = window.canvas.add_shape("Arrow", QtCore.QPointF(), snap_to_grid=False)
    assert isinstance(arrow, LineItem)
    arrow.set_arrow_start(True)
    arrow.set_arrow_end(False)
    arrow._points = [
        QtCore.QPointF(60, 360), QtCore.QPointF(120, 255), QtCore.QPointF(410, 225)
    ]
    arrow._update_path()
    arrow.update_handles()
    window.canvas.scene().clearSelection()
    arrow.setSelected(True)
    window.show()
    application.processEvents()
    window.canvas.centerOn(arrow.sceneBoundingRect().center())
    yield window, arrow
    window.canvas.scene().clearSelection()
    window._force_close = True
    window.close()


def _scene_points(arrow):
    return [arrow.mapToScene(point) for point in arrow._points]


def _assert_points_equal(actual, expected):
    assert len(actual) == len(expected)
    for point, reference in zip(actual, expected):
        assert point.x() == pytest.approx(reference.x())
        assert point.y() == pytest.approx(reference.y())


def _drag_handle(window, arrow, handle, vertex, original, *, snap=False):
    view = window.canvas
    position = QtCore.QPointF(arrow.pos())
    start = view.mapFromScene(handle.scenePos())
    modifiers = (
        QtCore.Qt.KeyboardModifier.NoModifier
        if snap else QtCore.Qt.KeyboardModifier.AltModifier
    )
    QTest.mousePress(view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, start)
    assert arrow._moving_index == vertex
    for delta in (QtCore.QPoint(12, 8), QtCore.QPoint(25, 20)):
        end = start + delta
        target = view.mapToScene(end)
        if snap:
            spacing = view._grid_size_min
            origin = view._master_origin
            target = QtCore.QPointF(
                origin.x() + round((target.x() - origin.x()) / spacing) * spacing,
                origin.y() + round((target.y() - origin.y()) / spacing) * spacing,
            )
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove, QtCore.QPointF(end),
            QtCore.QPointF(view.viewport().mapToGlobal(end)),
            QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton, modifiers,
        )
        QtWidgets.QApplication.sendEvent(view.viewport(), event)
        expected = list(original)
        expected[vertex] = target
        _assert_points_equal(_scene_points(arrow), expected)
        assert arrow.pos() == position
    QTest.mouseRelease(view.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers, end)
    return _scene_points(arrow)


@pytest.mark.parametrize("rotation", (0.0, 35.0, 90.0))
@pytest.mark.parametrize("scale", (1.0, 1.6))
@pytest.mark.parametrize("vertex", (0, 1, 2), ids=("tip", "corner", "end"))
def test_rotation_property_then_vertex_drag_keeps_untouched_points_fixed(
    rotation_window, rotation, scale, vertex
):
    window, arrow = rotation_window
    window.properties_panel._spin_rotation.setValue(rotation)
    window.properties_panel._spin_scale.setValue(scale)
    assert arrow.rotation() == rotation
    assert arrow.scale() == scale
    original = _scene_points(arrow)
    history = window.canvas.history()
    history.capture_initial_state()

    moved = _drag_handle(window, arrow, arrow._handles[vertex], vertex, original)

    assert history.can_undo()
    history.undo()
    restored = next(it for it in window.canvas.scene().items() if isinstance(it, LineItem))
    _assert_points_equal(_scene_points(restored), original)
    history.redo()
    restored = next(it for it in window.canvas.scene().items() if isinstance(it, LineItem))
    _assert_points_equal(_scene_points(restored), moved)
    state = json.loads(json.dumps(window.canvas._serialize_scene_state()))
    window.canvas._restore_scene_state(state)
    restored = next(it for it in window.canvas.scene().items() if isinstance(it, LineItem))
    _assert_points_equal(_scene_points(restored), moved)


@pytest.mark.parametrize("vertex", (0, 1, 2), ids=("tip", "corner", "end"))
def test_rotated_vertex_drag_snaps_only_the_dragged_point(rotation_window, vertex):
    window, arrow = rotation_window
    window.properties_panel._spin_rotation.setValue(90.0)
    _drag_handle(window, arrow, arrow._handles[vertex], vertex, _scene_points(arrow), snap=True)


@pytest.mark.parametrize("rotation", (35.0, 90.0))
@pytest.mark.parametrize("scale", (1.0, 1.6))
def test_rotated_midpoint_drag_inserts_a_vertex_without_moving_existing_points(
    rotation_window, rotation, scale
):
    window, arrow = rotation_window
    window.properties_panel._spin_rotation.setValue(rotation)
    window.properties_panel._spin_scale.setValue(scale)
    original = _scene_points(arrow)
    midpoint = arrow._mid_handles[0]
    inserted = list(original)
    inserted.insert(1, midpoint.scenePos())

    _drag_handle(window, arrow, midpoint, 1, inserted)

    assert len(arrow._points) == 4
