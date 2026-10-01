import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items import GroupItem
from scene_codec import KEY_ITEM_ID


def _make_group(view, x=100.0):
    view.scene().clearSelection()
    arrow = view.add_shape(
        "Arrow", QtCore.QPointF(x, 100.0), snap_to_grid=False
    )
    rectangle = view.add_shape(
        "Rectangle", QtCore.QPointF(x, 250.0), snap_to_grid=False
    )
    arrow.setSelected(True)
    rectangle.setSelected(True)
    view._group_selected_items()
    group = arrow.parentItem()
    assert isinstance(group, GroupItem)
    return group, arrow, rectangle


def test_legacy_group_without_saved_pivot_restores_geometry(canvas_view):
    view = canvas_view
    group, arrow, rectangle = _make_group(view)
    group.setRotation(35.0)
    group.setScale(1.2)
    expected = {
        obj.data(KEY_ITEM_ID): obj.mapToScene(QtCore.QPointF())
        for obj in (arrow, rectangle)
    }
    state = view._serialize_scene_state()
    for data in state["items"]:
        data.pop("transform_origin", None)

    view._restore_scene_state(state)

    restored = {
        obj.data(KEY_ITEM_ID): obj
        for obj in view.scene().items() if obj.data(KEY_ITEM_ID)
    }
    for item_id, point in expected.items():
        actual = restored[item_id].mapToScene(QtCore.QPointF())
        assert actual.x() == pytest.approx(point.x())
        assert actual.y() == pytest.approx(point.y())


def test_ungroup_releases_multiple_selected_group_trees(canvas_view):
    view = canvas_view
    first, first_arrow, first_rectangle = _make_group(view)
    second, second_arrow, second_rectangle = _make_group(view, 500.0)
    extra = view.add_shape(
        "Rectangle", QtCore.QPointF(800.0, 300.0), snap_to_grid=False
    )
    second.setSelected(True)
    view._group_selected_items()
    outer = extra.parentItem()
    assert isinstance(outer, GroupItem)
    first.setSelected(True)

    view._ungroup_selected_items()

    assert not any(isinstance(obj, GroupItem) for obj in view.scene().items())
    for obj in (first_arrow, first_rectangle, second_arrow, second_rectangle, extra):
        assert obj.scene() is view.scene()
        assert obj.parentItem() is None
    view.scene().clearSelection()


def _open_menu(view, item, monkeypatch, action_text=None):
    menus = []

    class TestMenu(QtWidgets.QMenu):
        def exec(self, _position):
            menus.append(self)
            return next(
                (action for action in self.actions() if action.text() == action_text),
                None,
            )

    # Keep the real menu and actions, replacing only the blocking popup.
    monkeypatch.setattr(QtWidgets, "QMenu", TestMenu)
    view.resize(900, 700)
    view.centerOn(item.sceneBoundingRect().center())
    point = view.mapFromScene(item.mapToScene(item.boundingRect().center()))
    assert view.itemAt(point) is not None
    event = QtGui.QContextMenuEvent(
        QtGui.QContextMenuEvent.Reason.Mouse,
        point,
        view.viewport().mapToGlobal(point),
    )
    view.contextMenuEvent(event)
    assert menus
    return {action.text() for action in menus[0].actions()}


@pytest.mark.parametrize(
    "extra, can_group", ((None, False), ("Rectangle", True), ("Group", True))
)
def test_group_context_menu_counts_independent_objects(
    canvas_view, monkeypatch, extra, can_group
):
    view = canvas_view
    if extra == "Group":
        other, _, _ = _make_group(view, 400.0)
    elif extra:
        other = view.add_shape(
            extra, QtCore.QPointF(400.0, 250.0), snap_to_grid=False
        )
    group, _, rectangle = _make_group(view)
    if extra:
        other.setSelected(True)

    actions = _open_menu(view, rectangle, monkeypatch)
    assert ("Group" in actions) is can_group
    assert ("Align" in actions) is can_group
    assert "Ungroup" in actions
    view.scene().clearSelection()


def test_grouping_single_group_does_not_create_another_group(canvas_view):
    view = canvas_view
    group, arrow, rectangle = _make_group(view)
    before = view._serialize_scene_state()

    view._group_selected_items()

    assert group.parentItem() is None
    assert arrow.parentItem() is group
    assert rectangle.parentItem() is group
    assert view._serialize_scene_state() == before
    view.scene().clearSelection()


@pytest.mark.parametrize("extra", ("Rectangle", "Group"))
def test_context_menu_grouping_preserves_existing_group_children(
    canvas_view, monkeypatch, extra
):
    view = canvas_view
    if extra == "Group":
        other, other_arrow, other_rectangle = _make_group(view, 400.0)
    else:
        other = view.add_shape(
            extra, QtCore.QPointF(400.0, 250.0), snap_to_grid=False
        )
    group, arrow, rectangle = _make_group(view)
    other.setSelected(True)
    items = [arrow, rectangle, other]
    before = [item.mapToScene(QtCore.QPointF()) for item in items]

    _open_menu(view, rectangle, monkeypatch, "Group")

    outer = group.parentItem()
    assert isinstance(outer, GroupItem)
    assert other.parentItem() is outer
    assert arrow.parentItem() is group
    assert rectangle.parentItem() is group
    if extra == "Group":
        assert other_arrow.parentItem() is other
        assert other_rectangle.parentItem() is other
    for item, point in zip(items, before):
        after = item.mapToScene(QtCore.QPointF())
        assert after.x() == pytest.approx(point.x())
        assert after.y() == pytest.approx(point.y())
    view.scene().clearSelection()


@pytest.mark.parametrize("depth", (1, 2, 4))
@pytest.mark.parametrize("transformed", (False, True))
@pytest.mark.parametrize("command", ("menu", "shortcut"))
def test_ungrouping_releases_all_nested_objects(
    canvas_view, monkeypatch, depth, transformed, command
):
    view = canvas_view
    unrelated, unrelated_arrow, unrelated_rectangle = _make_group(view, 600.0)
    group, arrow, rectangle = _make_group(view)
    objects = [arrow, rectangle]
    for level in range(depth):
        if transformed:
            group.setRotation(25.0 + level * 10.0)
            group.setScale(1.2)
            group.setTransform(QtGui.QTransform().shear(0.1, 0.05))
        if level < depth - 1:
            other = view.add_shape(
                "Rectangle", QtCore.QPointF(300.0 + level * 150.0, 300.0),
                snap_to_grid=False,
            )
            objects.append(other)
            group.setSelected(True)
            view._group_selected_items()
            group = other.parentItem()
            assert isinstance(group, GroupItem)
    view.layer_manager().set_item_locked(arrow, True)
    group.setSelected(True)
    sample_points = (QtCore.QPointF(), QtCore.QPointF(30, 5), QtCore.QPointF(0, 20))
    positions = [[obj.mapToScene(point) for point in sample_points] for obj in objects]
    view.history().capture_now()
    original_parents = {obj.data(KEY_ITEM_ID): obj.parentItem().data(KEY_ITEM_ID) for obj in objects}
    history_count = len(view.history()._states)

    if command == "menu":
        _open_menu(view, rectangle, monkeypatch, "Ungroup")
    else:
        event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_G,
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.ShiftModifier,
        )
        view.keyPressEvent(event)

    for obj, expected_points in zip(objects, positions):
        assert obj.scene() is view.scene()
        assert obj.parentItem() is None
        for point, expected in zip(sample_points, expected_points):
            actual = obj.mapToScene(point)
            assert actual.x() == pytest.approx(expected.x())
            assert actual.y() == pytest.approx(expected.y())
        assert bool(obj.flags() & QtWidgets.QGraphicsItem.ItemIsSelectable) is (obj is not arrow)
        assert bool(obj.flags() & QtWidgets.QGraphicsItem.ItemIsMovable) is (obj is not arrow)
    assert {obj for obj in view.scene().items() if isinstance(obj, GroupItem)} == {unrelated}
    assert unrelated_arrow.parentItem() is unrelated
    assert unrelated_rectangle.parentItem() is unrelated
    assert not view.scene().selectedItems()
    assert len(view.history()._states) == history_count + 1
    view.undo()
    assert sum(isinstance(obj, GroupItem) for obj in view.scene().items()) == depth + 1
    restored = {obj.data(KEY_ITEM_ID): obj for obj in view.scene().items() if obj.data(KEY_ITEM_ID)}
    for original, expected_points in zip(objects, positions):
        obj = restored[original.data(KEY_ITEM_ID)]
        assert obj.parentItem().data(KEY_ITEM_ID) == original_parents[original.data(KEY_ITEM_ID)]
        for point, expected in zip(sample_points, expected_points):
            actual = obj.mapToScene(point)
            assert actual.x() == pytest.approx(expected.x())
            assert actual.y() == pytest.approx(expected.y())
    view.redo()
    assert sum(isinstance(obj, GroupItem) for obj in view.scene().items()) == 1
    restored = {obj.data(KEY_ITEM_ID): obj for obj in view.scene().items() if obj.data(KEY_ITEM_ID)}
    for original, expected_points in zip(objects, positions):
        obj = restored[original.data(KEY_ITEM_ID)]
        assert obj.parentItem() is None
        for point, expected in zip(sample_points, expected_points):
            actual = obj.mapToScene(point)
            assert actual.x() == pytest.approx(expected.x())
            assert actual.y() == pytest.approx(expected.y())
    view.scene().clearSelection()
