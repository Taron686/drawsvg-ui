"""Bound and free scene connectors with bounded orthogonal routing."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import UUID, uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from scene_codec import KEY_ITEM_ID, KEY_TRANSIENT

CONNECTOR_TYPE_ID = "Connector"
MAX_DIRTY_REGIONS = 32
MAX_OBSTACLES = 64
ROUTE_MARGIN = 16.0

AnchorName = Literal["auto", "north", "east", "south", "west", "center"]
EndpointRole = Literal["start", "end"]
VALID_ANCHORS = frozenset({"auto", "north", "east", "south", "west", "center"})


@dataclass(frozen=True, slots=True)
class ConnectorEndpoint:
    """A connector endpoint, optionally bound to an item and anchor."""

    position: QtCore.QPointF
    target_id: str | None = None
    anchor: AnchorName = "auto"

    @classmethod
    def free(cls, position: QtCore.QPointF) -> ConnectorEndpoint:
        return cls(QtCore.QPointF(position))

    def to_data(self) -> dict[str, Any]:
        return {
            "position": [float(self.position.x()), float(self.position.y())],
            "target_id": self.target_id,
            "anchor": self.anchor,
        }

    @classmethod
    def from_data(cls, value: Any) -> ConnectorEndpoint:
        if not isinstance(value, Mapping):
            return cls.free(QtCore.QPointF())
        raw_position = value.get("position")
        position = _point_from_data(raw_position)
        target_id = _normalized_uuid(value.get("target_id"))
        raw_anchor = value.get("anchor")
        anchor: AnchorName = (
            raw_anchor
            if isinstance(raw_anchor, str) and raw_anchor in VALID_ANCHORS
            else "auto"
        )
        return cls(position, target_id, anchor)


class ConnectorItem(QtWidgets.QGraphicsPathItem):
    """Selectable connector whose geometry is owned by :class:`ConnectorManager`."""

    def __init__(
        self,
        start: ConnectorEndpoint,
        end: ConnectorEndpoint,
        *,
        pen: QtGui.QPen | None = None,
    ) -> None:
        super().__init__()
        self.start_endpoint = start
        self.end_endpoint = end
        self._route_points: tuple[QtCore.QPointF, ...] = ()
        self._hidden_by_target = False
        self.setData(0, CONNECTOR_TYPE_ID)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPen(pen or QtGui.QPen(QtGui.QColor("#303030"), 2.0))
        self.setZValue(-0.25)

    def route_points(self) -> tuple[QtCore.QPointF, ...]:
        return tuple(QtCore.QPointF(point) for point in self._route_points)

    def set_route_points(self, points: Iterable[QtCore.QPointF]) -> None:
        route = tuple(QtCore.QPointF(point) for point in points)
        if len(route) < 2:
            return
        if route == self._route_points:
            return
        self._route_points = route
        path = QtGui.QPainterPath(route[0])
        for point in route[1:]:
            path.lineTo(point)
        self.setPath(path)

    def to_data(self) -> dict[str, Any]:
        pen = self.pen()
        color = pen.color()
        return {
            "shape": CONNECTOR_TYPE_ID,
            "class": self.__class__.__name__,
            "pos": [0.0, 0.0],
            "rotation": 0.0,
            "scale": 1.0,
            "z": float(self.zValue()),
            "connector": {
                "start": self.start_endpoint.to_data(),
                "end": self.end_endpoint.to_data(),
                "routing": "orthogonal",
            },
            "pen": {
                "color": color.name(QtGui.QColor.NameFormat.HexArgb),
                "width": float(pen.widthF()),
            },
        }

    @classmethod
    def from_data(cls, value: Mapping[str, Any]) -> ConnectorItem:
        connector = value.get("connector")
        payload = connector if isinstance(connector, Mapping) else {}
        pen = _pen_from_data(value.get("pen"))
        item = cls(
            ConnectorEndpoint.from_data(payload.get("start")),
            ConnectorEndpoint.from_data(payload.get("end")),
            pen=pen,
        )
        z_value = value.get("z")
        if _is_number(z_value):
            item.setZValue(float(z_value))
        return item


class ConnectorManager(QtCore.QObject):
    """Resolve bindings and reroute only connectors affected by geometry changes."""

    def __init__(
        self, scene: QtWidgets.QGraphicsScene, parent: QtCore.QObject | None = None
    ):
        super().__init__(parent)
        self._scene = scene
        self._connectors: set[ConnectorItem] = set()
        self._items_by_id: dict[str, QtWidgets.QGraphicsItem] = {}
        self._bindings: dict[str, set[ConnectorItem]] = defaultdict(set)
        self._updating = False
        self._reroute_count = 0
        self._last_reroute_count = 0
        self._last_obstacle_count = 0
        scene.changed.connect(self._on_scene_changed)
        item_removed = getattr(scene, "itemRemoved", None)
        if item_removed is not None:
            item_removed.connect(self.item_removed)

    def connectors(self) -> tuple[ConnectorItem, ...]:
        return tuple(self._connectors)

    def routing_stats(self) -> dict[str, int]:
        return {
            "reroute_count": self._reroute_count,
            "last_reroute_count": self._last_reroute_count,
            "last_obstacle_count": self._last_obstacle_count,
            "max_obstacles": MAX_OBSTACLES,
        }

    def reset_routing_stats(self) -> None:
        self._reroute_count = 0
        self._last_reroute_count = 0
        self._last_obstacle_count = 0

    def endpoint_for(
        self,
        value: QtCore.QPointF | QtWidgets.QGraphicsItem,
        *,
        anchor: AnchorName = "auto",
    ) -> ConnectorEndpoint:
        if isinstance(value, QtWidgets.QGraphicsItem):
            item_id = _ensure_item_id(value)
            self._items_by_id[item_id] = value
            return ConnectorEndpoint(
                value.sceneBoundingRect().center(), item_id, anchor
            )
        return ConnectorEndpoint.free(QtCore.QPointF(value))

    def create_connector(
        self,
        start: ConnectorEndpoint,
        end: ConnectorEndpoint,
        *,
        pen: QtGui.QPen | None = None,
    ) -> ConnectorItem:
        item = ConnectorItem(start, end, pen=pen)
        self._scene.addItem(item)
        self.register_connector(item)
        return item

    def register_connector(self, connector: ConnectorItem) -> None:
        self._connectors.add(connector)
        self._register_binding(connector, connector.start_endpoint.target_id)
        self._register_binding(connector, connector.end_endpoint.target_id)
        self.update_connector(connector)

    def unregister_connector(self, connector: ConnectorItem) -> None:
        self._connectors.discard(connector)
        for connectors in self._bindings.values():
            connectors.discard(connector)
        self._bindings = defaultdict(
            set,
            {item_id: items for item_id, items in self._bindings.items() if items},
        )

    def reset(self) -> None:
        self._connectors.clear()
        self._items_by_id.clear()
        self._bindings.clear()
        self.reset_routing_stats()

    def rebuild_item_index(self) -> None:
        self._items_by_id.clear()
        for item in self._scene.items():
            if isinstance(item, ConnectorItem):
                continue
            item_id = _normalized_uuid(item.data(KEY_ITEM_ID))
            if item_id is not None:
                self._items_by_id[item_id] = item

    def resolve_bindings(self) -> None:
        self.rebuild_item_index()
        self._bindings.clear()
        for connector in tuple(self._connectors):
            self._detach_missing_target(connector, "start")
            self._detach_missing_target(connector, "end")
            self._register_binding(connector, connector.start_endpoint.target_id)
            self._register_binding(connector, connector.end_endpoint.target_id)
            self.update_connector(connector)

    def bind_endpoint(
        self,
        connector: ConnectorItem,
        role: EndpointRole,
        target: QtWidgets.QGraphicsItem,
        *,
        anchor: AnchorName = "auto",
    ) -> None:
        endpoint = self.endpoint_for(target, anchor=anchor)
        self._set_endpoint(connector, role, endpoint)
        self.update_connector(connector)

    def set_free_endpoint(
        self,
        connector: ConnectorItem,
        role: EndpointRole,
        position: QtCore.QPointF,
    ) -> None:
        self._set_endpoint(connector, role, ConnectorEndpoint.free(position))
        self.update_connector(connector)

    def notify_item_geometry_changed(self, item: QtWidgets.QGraphicsItem) -> None:
        affected: set[ConnectorItem] = set()
        pending = [item]
        while pending:
            current = pending.pop()
            item_id = _normalized_uuid(current.data(KEY_ITEM_ID))
            if item_id is not None:
                self._items_by_id[item_id] = current
                affected.update(self._bindings.get(item_id, ()))
            pending.extend(current.childItems())
        self._reroute(affected)

    def item_removed(self, item: QtWidgets.QGraphicsItem) -> None:
        if isinstance(item, ConnectorItem):
            self.unregister_connector(item)
            return
        target_ids: set[str] = set()
        pending = [item]
        while pending:
            current = pending.pop()
            item_id = _normalized_uuid(current.data(KEY_ITEM_ID))
            if item_id is not None:
                target_ids.add(item_id)
            pending.extend(current.childItems())
        affected = {
            connector
            for item_id in target_ids
            for connector in self._bindings.get(item_id, ())
        }
        for connector in tuple(affected):
            if connector.start_endpoint.target_id in target_ids:
                self._set_endpoint(
                    connector,
                    "start",
                    ConnectorEndpoint.free(connector.start_endpoint.position),
                )
            if connector.end_endpoint.target_id in target_ids:
                self._set_endpoint(
                    connector,
                    "end",
                    ConnectorEndpoint.free(connector.end_endpoint.position),
                )
        for item_id in target_ids:
            self._items_by_id.pop(item_id, None)
        self._reroute(affected)

    def update_connector(self, connector: ConnectorItem) -> None:
        if connector not in self._connectors:
            return
        self._detach_missing_target(connector, "start")
        self._detach_missing_target(connector, "end")
        self._sync_visibility(connector)
        start, end = self._resolved_points(connector)
        if (
            connector.start_endpoint.target_id is not None
            and connector.start_endpoint.target_id == connector.end_endpoint.target_id
        ):
            target = self._items_by_id.get(connector.start_endpoint.target_id)
            points = self._self_loop_points(start, end, target)
            obstacle_count = 0
        else:
            points, obstacle_count = self._orthogonal_route(connector, start, end)
        connector.start_endpoint = replace(connector.start_endpoint, position=start)
        connector.end_endpoint = replace(connector.end_endpoint, position=end)
        connector.set_route_points(points)
        self._last_obstacle_count = obstacle_count
        self._reroute_count += 1

    def _sync_visibility(self, connector: ConnectorItem) -> None:
        targets = (
            self._target_for(connector.start_endpoint),
            self._target_for(connector.end_endpoint),
        )
        target_hidden = any(
            target is not None and not target.isVisible() for target in targets
        )
        if target_hidden:
            if connector.isVisible():
                connector._hidden_by_target = True
                connector.setVisible(False)
        elif connector._hidden_by_target:
            connector._hidden_by_target = False
            if self._is_visible_in_layers(connector):
                connector.setVisible(True)

    def _is_visible_in_layers(self, connector: ConnectorItem) -> bool:
        canvas = self.parent()
        layer_manager = getattr(canvas, "layer_manager", None)
        if not callable(layer_manager):
            return True
        manager = layer_manager()
        return (
            manager.layer_for_item(connector).visible
            and manager.item_visible(connector)
        )

    def refresh_visibility(self) -> None:
        for connector in self._connectors:
            self._sync_visibility(connector)

    def _set_endpoint(
        self,
        connector: ConnectorItem,
        role: EndpointRole,
        endpoint: ConnectorEndpoint,
    ) -> None:
        old_endpoint = (
            connector.start_endpoint if role == "start" else connector.end_endpoint
        )
        self._unregister_binding(connector, old_endpoint.target_id)
        if role == "start":
            connector.start_endpoint = endpoint
        else:
            connector.end_endpoint = endpoint
        self._register_binding(connector, endpoint.target_id)

    def _register_binding(
        self, connector: ConnectorItem, target_id: str | None
    ) -> None:
        if target_id is not None:
            self._bindings[target_id].add(connector)

    def _unregister_binding(
        self, connector: ConnectorItem, target_id: str | None
    ) -> None:
        if target_id is None:
            return
        connectors = self._bindings.get(target_id)
        if connectors is None:
            return
        connectors.discard(connector)
        if not connectors:
            self._bindings.pop(target_id, None)

    def _detach_missing_target(
        self, connector: ConnectorItem, role: EndpointRole
    ) -> None:
        endpoint = (
            connector.start_endpoint if role == "start" else connector.end_endpoint
        )
        target_id = endpoint.target_id
        if target_id is None:
            return
        target = self._items_by_id.get(target_id)
        if target is not None and target.scene() is self._scene:
            return
        self._set_endpoint(
            connector, role, replace(endpoint, target_id=None, anchor="auto")
        )

    def _resolved_points(
        self, connector: ConnectorItem
    ) -> tuple[QtCore.QPointF, QtCore.QPointF]:
        start_target = self._target_for(connector.start_endpoint)
        end_target = self._target_for(connector.end_endpoint)
        start_hint = (
            start_target.sceneBoundingRect().center()
            if start_target is not None
            else connector.start_endpoint.position
        )
        end_hint = (
            end_target.sceneBoundingRect().center()
            if end_target is not None
            else connector.end_endpoint.position
        )
        same_target = start_target is not None and start_target is end_target
        start_anchor = connector.start_endpoint.anchor
        end_anchor = connector.end_endpoint.anchor
        if same_target and start_anchor == "auto" and end_anchor == "auto":
            start_anchor, end_anchor = "east", "south"
        start = self._endpoint_position(
            connector.start_endpoint, end_hint, anchor=start_anchor
        )
        end = self._endpoint_position(
            connector.end_endpoint, start_hint, anchor=end_anchor
        )
        return start, end

    def _endpoint_position(
        self,
        endpoint: ConnectorEndpoint,
        toward: QtCore.QPointF,
        *,
        anchor: AnchorName,
    ) -> QtCore.QPointF:
        target = self._target_for(endpoint)
        if target is None:
            return QtCore.QPointF(endpoint.position)
        rect = _content_rect(target)
        if anchor == "auto":
            center = target.mapToScene(rect.center())
            delta = toward - center
            if abs(delta.x()) >= abs(delta.y()):
                anchor = "east" if delta.x() >= 0.0 else "west"
            else:
                anchor = "south" if delta.y() >= 0.0 else "north"
        local = {
            "north": QtCore.QPointF(rect.center().x(), rect.top()),
            "east": QtCore.QPointF(rect.right(), rect.center().y()),
            "south": QtCore.QPointF(rect.center().x(), rect.bottom()),
            "west": QtCore.QPointF(rect.left(), rect.center().y()),
            "center": rect.center(),
        }[anchor]
        return target.mapToScene(local)

    def _target_for(
        self, endpoint: ConnectorEndpoint
    ) -> QtWidgets.QGraphicsItem | None:
        if endpoint.target_id is None:
            return None
        target = self._items_by_id.get(endpoint.target_id)
        return target if target is not None and target.scene() is self._scene else None

    def _self_loop_points(
        self,
        start: QtCore.QPointF,
        end: QtCore.QPointF,
        target: QtWidgets.QGraphicsItem | None,
    ) -> tuple[QtCore.QPointF, ...]:
        rect = (
            target.sceneBoundingRect()
            if target is not None
            else QtCore.QRectF(start, end)
        )
        right = rect.right() + ROUTE_MARGIN * 2.0
        bottom = rect.bottom() + ROUTE_MARGIN * 2.0
        return (
            start,
            QtCore.QPointF(right, start.y()),
            QtCore.QPointF(right, bottom),
            QtCore.QPointF(end.x(), bottom),
            end,
        )

    def _orthogonal_route(
        self,
        connector: ConnectorItem,
        start: QtCore.QPointF,
        end: QtCore.QPointF,
    ) -> tuple[tuple[QtCore.QPointF, ...], int]:
        obstacles = self._obstacles(connector, start, end)
        candidates = _route_candidates(start, end, obstacles)
        valid = [
            points
            for points in candidates
            if not any(_polyline_intersects_rect(points, rect) for rect in obstacles)
        ]
        route = min(valid or candidates[:1], key=_route_score)
        return _deduplicate_points(route), len(obstacles)

    def _obstacles(
        self,
        connector: ConnectorItem,
        start: QtCore.QPointF,
        end: QtCore.QPointF,
    ) -> tuple[QtCore.QRectF, ...]:
        corridor = (
            QtCore.QRectF(start, end)
            .normalized()
            .adjusted(
                -ROUTE_MARGIN * 4.0,
                -ROUTE_MARGIN * 4.0,
                ROUTE_MARGIN * 4.0,
                ROUTE_MARGIN * 4.0,
            )
        )
        excluded: set[QtWidgets.QGraphicsItem] = {connector}
        for endpoint in (connector.start_endpoint, connector.end_endpoint):
            target = self._target_for(endpoint)
            while target is not None:
                excluded.add(target)
                target = target.parentItem()
        obstacles: list[QtCore.QRectF] = []
        for item in self._scene.items(corridor):
            if len(obstacles) >= MAX_OBSTACLES:
                break
            if (
                item in excluded
                or isinstance(item, ConnectorItem)
                or not item.isVisible()
            ):
                continue
            if item.parentItem() is not None or bool(item.data(KEY_TRANSIENT)):
                continue
            name = item.__class__.__name__
            if name == "A4PageItem" or name.endswith("Handle"):
                continue
            rect = item.sceneBoundingRect().adjusted(
                -ROUTE_MARGIN, -ROUTE_MARGIN, ROUTE_MARGIN, ROUTE_MARGIN
            )
            if not rect.isNull():
                obstacles.append(rect)
        return tuple(obstacles)

    @QtCore.Slot(list)
    def _on_scene_changed(self, regions: list[QtCore.QRectF]) -> None:
        if self._updating or not self._connectors:
            return
        if len(regions) > MAX_DIRTY_REGIONS:
            self._reroute(self._connectors)
            return
        affected: set[ConnectorItem] = set()
        for region in regions:
            query = region.adjusted(-1.0, -1.0, 1.0, 1.0)
            for item in self._scene.items(query):
                item_id = _normalized_uuid(item.data(KEY_ITEM_ID))
                if item_id is not None:
                    affected.update(self._bindings.get(item_id, ()))
            for connector in self._connectors:
                route_bounds = connector.sceneBoundingRect().adjusted(
                    -ROUTE_MARGIN, -ROUTE_MARGIN, ROUTE_MARGIN, ROUTE_MARGIN
                )
                if route_bounds.intersects(query):
                    affected.add(connector)
        self._reroute(affected)

    def _reroute(self, connectors: Iterable[ConnectorItem]) -> None:
        active = tuple(
            connector
            for connector in set(connectors)
            if connector in self._connectors and connector.scene() is self._scene
        )
        self._last_reroute_count = len(active)
        if not active:
            return
        self._updating = True
        try:
            for connector in active:
                self.update_connector(connector)
        finally:
            self._updating = False


def is_connector_data(value: Mapping[str, Any]) -> bool:
    return (
        value.get("shape") == CONNECTOR_TYPE_ID
        or value.get("type_id") == CONNECTOR_TYPE_ID
    )


def _route_candidates(
    start: QtCore.QPointF,
    end: QtCore.QPointF,
    obstacles: tuple[QtCore.QRectF, ...],
) -> tuple[tuple[QtCore.QPointF, ...], ...]:
    candidates: list[tuple[QtCore.QPointF, ...]] = [
        (start, QtCore.QPointF(end.x(), start.y()), end),
        (start, QtCore.QPointF(start.x(), end.y()), end),
    ]
    if obstacles:
        top = min(rect.top() for rect in obstacles) - ROUTE_MARGIN
        bottom = max(rect.bottom() for rect in obstacles) + ROUTE_MARGIN
        left = min(rect.left() for rect in obstacles) - ROUTE_MARGIN
        right = max(rect.right() for rect in obstacles) + ROUTE_MARGIN
        candidates.extend(
            (
                start,
                QtCore.QPointF(start.x(), y),
                QtCore.QPointF(end.x(), y),
                end,
            )
            for y in (top, bottom)
        )
        candidates.extend(
            (
                start,
                QtCore.QPointF(x, start.y()),
                QtCore.QPointF(x, end.y()),
                end,
            )
            for x in (left, right)
        )
    return tuple(_deduplicate_points(points) for points in candidates)


def _route_score(points: tuple[QtCore.QPointF, ...]) -> tuple[float, int]:
    length = sum(
        abs(second.x() - first.x()) + abs(second.y() - first.y())
        for first, second in zip(points, points[1:])
    )
    return length, len(points)


def _deduplicate_points(
    points: Iterable[QtCore.QPointF],
) -> tuple[QtCore.QPointF, ...]:
    result: list[QtCore.QPointF] = []
    for point in points:
        if not result or point != result[-1]:
            result.append(QtCore.QPointF(point))
    return tuple(result)


def _polyline_intersects_rect(
    points: tuple[QtCore.QPointF, ...], rect: QtCore.QRectF
) -> bool:
    return any(
        _segment_intersects_rect(first, second, rect)
        for first, second in zip(points, points[1:])
    )


def _segment_intersects_rect(
    first: QtCore.QPointF, second: QtCore.QPointF, rect: QtCore.QRectF
) -> bool:
    if rect.contains(first) or rect.contains(second):
        return True
    line = QtCore.QLineF(first, second)
    edges = (
        QtCore.QLineF(rect.topLeft(), rect.topRight()),
        QtCore.QLineF(rect.topRight(), rect.bottomRight()),
        QtCore.QLineF(rect.bottomRight(), rect.bottomLeft()),
        QtCore.QLineF(rect.bottomLeft(), rect.topLeft()),
    )
    return any(
        line.intersects(edge)[0] == QtCore.QLineF.IntersectionType.BoundedIntersection
        for edge in edges
    )


def _content_rect(item: QtWidgets.QGraphicsItem) -> QtCore.QRectF:
    content_rect = getattr(item, "_contentRect", None)
    if callable(content_rect):
        rect = content_rect()
        if isinstance(rect, QtCore.QRectF) and not rect.isNull():
            return rect
    return item.boundingRect()


def _ensure_item_id(item: QtWidgets.QGraphicsItem) -> str:
    item_id = _normalized_uuid(item.data(KEY_ITEM_ID))
    if item_id is None:
        item_id = str(uuid4())
        item.setData(KEY_ITEM_ID, item_id)
    return item_id


def _normalized_uuid(value: Any) -> str | None:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        return None


def _point_from_data(value: Any) -> QtCore.QPointF:
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and _is_number(value[0])
        and _is_number(value[1])
    ):
        return QtCore.QPointF(float(value[0]), float(value[1]))
    return QtCore.QPointF()


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _pen_from_data(value: Any) -> QtGui.QPen:
    pen = QtGui.QPen(QtGui.QColor("#303030"), 2.0)
    if not isinstance(value, Mapping):
        return pen
    color = value.get("color")
    if isinstance(color, str):
        candidate = QtGui.QColor(color)
        if candidate.isValid():
            pen.setColor(candidate)
    width = value.get("width")
    if _is_number(width) and float(width) > 0.0:
        pen.setWidthF(float(width))
    return pen


__all__ = [
    "CONNECTOR_TYPE_ID",
    "ConnectorEndpoint",
    "ConnectorItem",
    "ConnectorManager",
    "is_connector_data",
]
