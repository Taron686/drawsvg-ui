import pytest
from PySide6 import QtCore, QtGui

from document_format import ProjectDocument
from document_io import load_project, save_project
from items import GroupItem
from scene_codec import KEY_ITEM_ID


@pytest.fixture(autouse=True)
def _clear_selection(canvas_view):
    yield
    canvas_view.scene().clearSelection()


def _rectangle(view, x, y, width=30, height=20):
    item = view.add_shape(
        "Rectangle", QtCore.QPointF(x, y), snap_to_grid=False
    )
    item.setRect(0, 0, width, height)
    item.update_handles()
    return item


def _nested_group(view, depth):
    view._grid_size_min = 0
    first = _rectangle(view, 100, 100)
    second = _rectangle(view, 105, 105)
    first.setSelected(True)
    second.setSelected(True)
    view._group_selected_items()
    group = first.parentItem()
    for _ in range(depth):
        extra = _rectangle(view, 100, 100, 10, 10)
        group.setSelected(True)
        extra.setSelected(True)
        view._group_selected_items()
        group = extra.parentItem()
    return group, first, second


def _assert_rect(actual, expected):
    assert (actual.x(), actual.y(), actual.width(), actual.height()) == pytest.approx(
        (expected.x(), expected.y(), expected.width(), expected.height())
    )


def _assert_selection(group, expected):
    _assert_rect(group.mapRectToScene(group._handle_rect()), expected)
    # The resize grips must follow the same content edges, not the Qt group cache.
    group.update_handles()
    handle = next(h for h in group._handles if h._direction == "top_left")
    _assert_rect(
        QtCore.QRectF(handle.scenePos(), QtCore.QSizeF()),
        QtCore.QRectF(expected.topLeft() - QtCore.QPointF(10, 10), QtCore.QSizeF()),
    )


@pytest.mark.parametrize("depth", (0, 1, 5, 10))
def test_nested_group_selection_stays_tight(canvas_view, depth):
    group, _, _ = _nested_group(canvas_view, depth)
    _assert_selection(group, QtCore.QRectF(99, 99, 37, 27))


def test_nested_selection_uses_current_child_geometry(canvas_view):
    group, first, second = _nested_group(canvas_view, 1)
    first.setRect(0, 0, 12, 8)
    second.setRect(0, 0, 12, 8)
    second.moveBy(20, 10)
    _assert_selection(group, QtCore.QRectF(99, 99, 39, 25))


def test_nested_rotations_do_not_accumulate_empty_bounding_corners(canvas_view):
    group, first, second = _nested_group(canvas_view, 1)
    inner = first.parentItem()
    # Opposite rotations cancel. Bounding each intermediate group would inflate
    # the result even after helper handles are excluded.
    inner.setTransformOriginPoint(0, 0)
    group.setTransformOriginPoint(0, 0)
    inner.setRotation(45)
    group.setRotation(-45)
    inverse, invertible = group.sceneTransform().inverted()
    assert invertible
    content = QtCore.QRectF()
    for item in (first, second, *[
        child for child in group.childItems() if child.data(0) == "Rectangle"
    ]):
        transform = item.sceneTransform() * inverse
        rect = transform.mapRect(item.boundingRect())
        content = content.united(rect)
    _assert_rect(group._handle_rect(), content)


@pytest.mark.parametrize("operation", ("restore", "undo_redo", "load"))
def test_restored_nested_selection_stays_tight(canvas_view, tmp_path, operation):
    view = canvas_view
    group, _, _ = _nested_group(view, 5)
    group_id = group.data(KEY_ITEM_ID)
    if operation == "undo_redo":
        view.undo()
        view.redo()
    else:
        state = view._serialize_scene_state()
        if operation == "load":
            path = tmp_path / "nested.drawsvg"
            save_project(path, ProjectDocument(scene=state))
            state = load_project(path).scene
        view._restore_scene_state(state)
    restored = next(
        item for item in view.scene().items()
        if isinstance(item, GroupItem) and item.data(KEY_ITEM_ID) == group_id
    )
    restored.setSelected(True)
    _assert_selection(restored, QtCore.QRectF(99, 99, 37, 27))


def test_moved_scaled_group_selection_preserves_local_content(canvas_view):
    group, _, _ = _nested_group(canvas_view, 5)
    expected = QtCore.QRectF(99 - group.x(), 99 - group.y(), 37, 27)
    group.setPos(900, 600)
    group.setScale(0.25)
    group.setRotation(30)
    group.setTransform(QtGui.QTransform().shear(0.1, 0.05))
    _assert_rect(group._handle_rect(), expected)
