from __future__ import annotations

import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

from connectors import (
    MAX_OBSTACLES,
    ROUTE_MARGIN,
    ConnectorEndpoint,
    ConnectorItem,
    _polyline_intersects_rect,
)
from items import GroupItem
from scene_codec import KEY_ITEM_ID


def _shape(canvas_view, x: float, y: float = 20.0):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(x, y), snap_to_grid=False)
    assert item is not None
    return item


def _connectors(canvas_view) -> list[ConnectorItem]:
    return [
        item for item in canvas_view.scene().items() if isinstance(item, ConnectorItem)
    ]


def _east_anchor(item: QtWidgets.QGraphicsItem) -> QtCore.QPointF:
    bounds = item.boundingRect()
    return item.mapToScene(QtCore.QPointF(bounds.right(), bounds.center().y()))


def _click_scene(
    canvas_view, scene_position: QtCore.QPointF, application
) -> QtCore.QPointF:
    canvas_view.resize(800, 600)
    canvas_view.show()
    application.processEvents()
    view_position = canvas_view.mapFromScene(scene_position)
    clicked_position = canvas_view.mapToScene(view_position)
    QTest.mouseClick(
        canvas_view.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=view_position,
    )
    return clicked_position


def test_connector_creation_mode_binds_two_clicked_items_in_one_undo_step(
    canvas_view, application
) -> None:
    start = _shape(canvas_view, 40.0)
    end = _shape(canvas_view, 360.0)
    history = canvas_view.history()
    states_before = len(history._states)

    canvas_view.set_connector_creation_enabled(True)
    _click_scene(canvas_view, start.sceneBoundingRect().center(), application)
    _click_scene(canvas_view, end.sceneBoundingRect().center(), application)

    connector = _connectors(canvas_view)[0]
    assert connector.start_endpoint.target_id == start.data(KEY_ITEM_ID)
    assert connector.end_endpoint.target_id == end.data(KEY_ITEM_ID)
    assert len(history._states) == states_before + 1

    canvas_view.undo()
    assert not _connectors(canvas_view)
    canvas_view.redo()
    restored = _connectors(canvas_view)[0]
    assert restored.start_endpoint.target_id == start.data(KEY_ITEM_ID)
    assert restored.end_endpoint.target_id == end.data(KEY_ITEM_ID)


def test_connector_creation_mode_uses_free_points_and_escape_cancels(
    canvas_view, application
) -> None:
    history = canvas_view.history()
    states_before = len(history._states)
    start = QtCore.QPointF(-200.0, -100.0)
    end = QtCore.QPointF(-80.0, -100.0)

    canvas_view.set_connector_creation_enabled(True)
    _click_scene(canvas_view, start, application)
    QTest.keyClick(canvas_view, QtCore.Qt.Key.Key_Escape)

    assert not canvas_view.connector_creation_enabled()
    assert not _connectors(canvas_view)
    assert len(history._states) == states_before

    canvas_view.set_connector_creation_enabled(True)
    clicked_start = _click_scene(canvas_view, start, application)
    clicked_end = _click_scene(canvas_view, end, application)

    connector = _connectors(canvas_view)[0]
    assert connector.start_endpoint.target_id is None
    assert connector.end_endpoint.target_id is None
    assert connector.route_points()[0] == clicked_start
    assert connector.route_points()[-1] == clicked_end


def test_bound_and_free_endpoints_serialize_with_stable_references(canvas_view) -> None:
    target = _shape(canvas_view, 40.0)
    connector = canvas_view.add_connector(
        target,
        QtCore.QPointF(360.0, 140.0),
        start_anchor="east",
    )

    state = canvas_view._serialize_scene_state()
    data = next(item for item in state["items"] if item["type_id"] == "Connector")

    assert data["connector"]["start"]["target_id"] == target.data(KEY_ITEM_ID)
    assert data["connector"]["start"]["anchor"] == "east"
    assert data["connector"]["end"] == {
        "position": [360.0, 140.0],
        "target_id": None,
        "anchor": "auto",
    }
    assert connector.route_points()[-1] == QtCore.QPointF(360.0, 140.0)


def test_connector_follows_position_and_rotation_geometry_events(
    canvas_view, application
) -> None:
    target = _shape(canvas_view, 40.0)
    connector = canvas_view.add_connector(
        target,
        QtCore.QPointF(420.0, 100.0),
        start_anchor="east",
    )
    before = connector.route_points()[0]

    target.moveBy(50.0, 30.0)
    target.setRotation(90.0)
    application.processEvents()

    expected = target.mapToScene(
        QtCore.QPointF(
            target.boundingRect().right(), target.boundingRect().center().y()
        )
    )
    assert connector.route_points()[0].x() == pytest.approx(expected.x())
    assert connector.route_points()[0].y() == pytest.approx(expected.y())
    assert connector.route_points()[0] != before


def test_self_connector_builds_an_external_loop(canvas_view) -> None:
    target = _shape(canvas_view, 100.0)
    connector = canvas_view.add_connector(target, target)
    points = connector.route_points()
    bounds = target.sceneBoundingRect()

    assert len(points) == 5
    assert max(point.x() for point in points) > bounds.right()
    assert max(point.y() for point in points) > bounds.bottom()
    assert connector.start_endpoint.target_id == connector.end_endpoint.target_id


def test_obstacle_routing_is_orthogonal_and_avoids_padded_bounds(canvas_view) -> None:
    obstacle = _shape(canvas_view, 90.0, -20.0)
    connector = canvas_view.add_connector(
        QtCore.QPointF(0.0, 20.0), QtCore.QPointF(360.0, 20.0)
    )
    points = connector.route_points()
    padded = obstacle.sceneBoundingRect().adjusted(
        -ROUTE_MARGIN, -ROUTE_MARGIN, ROUTE_MARGIN, ROUTE_MARGIN
    )

    assert len(points) >= 4
    assert all(
        first.x() == pytest.approx(second.x()) or first.y() == pytest.approx(second.y())
        for first, second in zip(points, points[1:])
    )
    assert not _polyline_intersects_rect(points, padded)


def test_route_reacts_to_new_obstacle_on_existing_free_path(canvas_view, application) -> None:
    connector = canvas_view.add_connector(
        QtCore.QPointF(0.0, 20.0), QtCore.QPointF(360.0, 20.0)
    )
    obstacle = _shape(canvas_view, 140.0, -20.0)
    application.processEvents()

    padded = obstacle.sceneBoundingRect().adjusted(
        -ROUTE_MARGIN, -ROUTE_MARGIN, ROUTE_MARGIN, ROUTE_MARGIN
    )
    assert not _polyline_intersects_rect(connector.route_points(), padded)


def test_alignment_does_not_move_connector_item(canvas_view) -> None:
    shape = _shape(canvas_view, 40.0)
    connector = canvas_view.add_connector(
        QtCore.QPointF(0.0, 20.0), QtCore.QPointF(360.0, 20.0)
    )
    before = connector.route_points()

    canvas_view._align_items([shape, connector], "right")

    assert connector.route_points() == before


def test_connector_bound_to_group_child_follows_group_transform(canvas_view) -> None:
    child = _shape(canvas_view, 40.0)
    sibling = _shape(canvas_view, 220.0)
    connector = canvas_view.add_connector(
        child,
        QtCore.QPointF(500.0, 80.0),
        start_anchor="east",
    )
    connector.setSelected(False)
    canvas_view.scene().clearSelection()
    child.setSelected(True)
    sibling.setSelected(True)
    canvas_view._group_selected_items()
    group = next(
        item for item in canvas_view.scene().items() if isinstance(item, GroupItem)
    )
    before = connector.route_points()[0]

    group.moveBy(80.0, 40.0)
    canvas_view.connector_manager().notify_item_geometry_changed(group)

    assert connector.route_points()[0] == _east_anchor(child)
    assert connector.route_points()[0] != before


def test_connector_itself_is_not_absorbed_by_grouping(canvas_view) -> None:
    first = _shape(canvas_view, 40.0)
    second = _shape(canvas_view, 220.0)
    connector = canvas_view.add_connector(first, second)
    canvas_view.scene().clearSelection()
    for item in (first, second, connector):
        item.setSelected(True)

    canvas_view._group_selected_items()

    group = next(
        item for item in canvas_view.scene().items() if isinstance(item, GroupItem)
    )
    assert connector.parentItem() is None
    assert first.parentItem() is group
    assert second.parentItem() is group


def test_removing_group_detaches_connector_bound_to_child(canvas_view) -> None:
    child = _shape(canvas_view, 40.0)
    sibling = _shape(canvas_view, 220.0)
    canvas_view.scene().clearSelection()
    child.setSelected(True)
    sibling.setSelected(True)
    canvas_view._group_selected_items()
    group = next(
        item for item in canvas_view.scene().items() if isinstance(item, GroupItem)
    )
    connector = canvas_view.add_connector(
        child,
        QtCore.QPointF(500.0, 80.0),
        start_anchor="east",
    )
    last_position = QtCore.QPointF(connector.route_points()[0])

    canvas_view.scene().removeItem(group)

    assert connector.start_endpoint.target_id is None
    assert connector.route_points()[0] == last_position


def test_restore_resolves_connectors_after_nested_targets(canvas_view) -> None:
    child = _shape(canvas_view, 40.0)
    sibling = _shape(canvas_view, 220.0)
    canvas_view.scene().clearSelection()
    child.setSelected(True)
    sibling.setSelected(True)
    canvas_view._group_selected_items()
    group = next(
        item for item in canvas_view.scene().items() if isinstance(item, GroupItem)
    )
    child_id = child.data(KEY_ITEM_ID)
    connector = canvas_view.add_connector(
        child,
        QtCore.QPointF(520.0, 100.0),
        start_anchor="east",
    )
    connector.setSelected(False)
    group.setSelected(False)
    state = canvas_view._serialize_scene_state()

    canvas_view._restore_scene_state(state)

    restored_connector = _connectors(canvas_view)[0]
    restored_child = next(
        item
        for item in canvas_view.scene().items()
        if item.data(KEY_ITEM_ID) == child_id
    )
    expected = restored_child.mapToScene(
        QtCore.QPointF(
            restored_child.boundingRect().right(),
            restored_child.boundingRect().center().y(),
        )
    )
    assert restored_connector.start_endpoint.target_id == child_id
    assert restored_connector.route_points()[0].x() == pytest.approx(expected.x())
    assert restored_connector.route_points()[0].y() == pytest.approx(expected.y())


def test_missing_restore_target_detaches_without_losing_last_position(
    canvas_view,
) -> None:
    connector = canvas_view.add_connector(
        QtCore.QPointF(30.0, 40.0), QtCore.QPointF(300.0, 40.0)
    )
    state = canvas_view._serialize_scene_state()
    data = next(item for item in state["items"] if item["type_id"] == "Connector")
    data["connector"]["start"]["target_id"] = "a5d7247d-71e7-465a-a91b-158c00a17f22"

    canvas_view._restore_scene_state(state)

    restored = _connectors(canvas_view)[0]
    assert restored.start_endpoint.target_id is None
    assert restored.route_points()[0] == QtCore.QPointF(30.0, 40.0)
    assert connector.scene() is None


def test_removing_target_detaches_bound_endpoint(canvas_view) -> None:
    target = _shape(canvas_view, 40.0)
    connector = canvas_view.add_connector(
        target,
        QtCore.QPointF(400.0, 80.0),
        start_anchor="east",
    )
    last_position = QtCore.QPointF(connector.route_points()[0])

    canvas_view.scene().removeItem(target)

    assert connector.start_endpoint.target_id is None
    assert connector.route_points()[0] == last_position


def test_bound_connector_survives_transform_undo_and_redo(canvas_view) -> None:
    target = _shape(canvas_view, 40.0)
    target_id = target.data(KEY_ITEM_ID)
    canvas_view.add_connector(
        target,
        QtCore.QPointF(420.0, 100.0),
        start_anchor="east",
    )
    original = _connectors(canvas_view)[0].route_points()[0]

    with canvas_view.history().transaction():
        target.moveBy(80.0, 20.0)
        canvas_view.connector_manager().notify_item_geometry_changed(target)
        canvas_view.history().mark_dirty()
    moved = _connectors(canvas_view)[0].route_points()[0]
    assert moved != original

    canvas_view.undo()
    undone = _connectors(canvas_view)[0]
    undone_target = next(
        item
        for item in canvas_view.scene().items()
        if item.data(KEY_ITEM_ID) == target_id
    )
    assert undone.route_points()[0] == _east_anchor(undone_target)
    assert undone.route_points()[0] != moved

    canvas_view.redo()
    redone = _connectors(canvas_view)[0]
    restored_target = next(
        item
        for item in canvas_view.scene().items()
        if item.data(KEY_ITEM_ID) == target_id
    )
    assert redone.start_endpoint.target_id == target_id
    assert redone.route_points()[0] == _east_anchor(restored_target)
    assert redone.route_points()[0] != undone.route_points()[0]


def test_rerouting_is_limited_to_bound_degree_and_capped_obstacles(canvas_view) -> None:
    manager = canvas_view.connector_manager()
    targets: list[QtWidgets.QGraphicsRectItem] = []
    for index in range(MAX_OBSTACLES + 20):
        item = QtWidgets.QGraphicsRectItem(index * 5.0, -30.0, 4.0, 60.0)
        canvas_view.scene().addItem(item)
        targets.append(item)
    primary = targets[0]
    connector = manager.create_connector(
        manager.endpoint_for(primary, anchor="east"),
        ConnectorEndpoint.free(QtCore.QPointF(600.0, 0.0)),
    )
    for index in range(1, 12):
        target = targets[index]
        manager.create_connector(
            manager.endpoint_for(target, anchor="south"),
            ConnectorEndpoint.free(QtCore.QPointF(index * 20.0, 180.0)),
        )
    manager.reset_routing_stats()

    primary.moveBy(0.0, 20.0)
    manager.notify_item_geometry_changed(primary)
    stats = manager.routing_stats()

    assert connector.route_points()[0].y() == pytest.approx(20.0)
    assert stats["last_reroute_count"] == 1
    assert stats["reroute_count"] == 1
    assert stats["last_obstacle_count"] <= MAX_OBSTACLES
