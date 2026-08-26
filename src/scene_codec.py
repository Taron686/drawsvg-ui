"""Canonical scene metadata used by history and future document formats."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
from uuid import UUID, uuid4

from PySide6 import QtWidgets

SCHEMA_VERSION = 1
DEFAULT_LAYER_ID = "layer-1"

# QGraphicsItem data key 0 is the legacy palette shape identifier.
KEY_TRANSIENT = 1001
KEY_ITEM_ID = 1002
KEY_LAYER_ID = 1003


class SceneCodec:
    """Add stable scene metadata around the existing shape serializers."""

    @staticmethod
    def is_transient(item: QtWidgets.QGraphicsItem) -> bool:
        return bool(item.data(KEY_TRANSIENT))

    @classmethod
    def serialize_state(
        cls,
        items: Iterable[QtWidgets.QGraphicsItem],
        serialize_item: Callable[[QtWidgets.QGraphicsItem], dict[str, Any]],
        *,
        grid_visible: bool,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "items": cls.serialize_items(items, serialize_item),
            "grid_visible": grid_visible,
        }

    @classmethod
    def serialize_items(
        cls,
        items: Iterable[QtWidgets.QGraphicsItem],
        serialize_item: Callable[[QtWidgets.QGraphicsItem], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for item in items:
            if cls.is_transient(item):
                continue
            data = serialize_item(item)
            data["id"] = cls._item_id(item)
            data["type_id"] = str(data["shape"])
            data["layer_id"] = cls._layer_id(item)
            data["stack_order"] = len(serialized)
            serialized.append(data)
        return serialized

    @classmethod
    def normalize_state(cls, state: Mapping[str, Any]) -> dict[str, Any]:
        """Accept legacy snapshots while restoring their explicit item order."""
        payload = dict(state)
        items = state.get("items")
        payload["items"] = cls._ordered_items(items if isinstance(items, list) else [])
        payload["schema_version"] = SCHEMA_VERSION
        return payload

    @classmethod
    def restore_item_metadata(
        cls,
        item: QtWidgets.QGraphicsItem,
        data: Mapping[str, Any],
    ) -> None:
        item_id = data.get("id")
        if cls._is_uuid(item_id):
            item.setData(KEY_ITEM_ID, str(UUID(str(item_id))))
        else:
            cls._item_id(item)

        layer_id = data.get("layer_id")
        item.setData(
            KEY_LAYER_ID,
            str(layer_id) if isinstance(layer_id, str) and layer_id else DEFAULT_LAYER_ID,
        )

    @classmethod
    def _ordered_items(cls, items: list[Any]) -> list[dict[str, Any]]:
        indexed_items = [
            (index, dict(item))
            for index, item in enumerate(items)
            if isinstance(item, Mapping)
        ]
        indexed_items.sort(key=cls._stack_sort_key)
        ordered: list[dict[str, Any]] = []
        for _index, item in indexed_items:
            children = item.get("children")
            if isinstance(children, list):
                item["children"] = cls._ordered_items(children)
            ordered.append(item)
        return ordered

    @staticmethod
    def _stack_sort_key(entry: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        index, item = entry
        stack_order = item.get("stack_order")
        if isinstance(stack_order, int) and not isinstance(stack_order, bool):
            return (stack_order, index)
        return (index, index)

    @staticmethod
    def _is_uuid(value: Any) -> bool:
        try:
            UUID(str(value))
        except (AttributeError, TypeError, ValueError):
            return False
        return True

    @classmethod
    def _item_id(cls, item: QtWidgets.QGraphicsItem) -> str:
        item_id = item.data(KEY_ITEM_ID)
        if cls._is_uuid(item_id):
            return str(UUID(str(item_id)))
        item_id = str(uuid4())
        item.setData(KEY_ITEM_ID, item_id)
        return item_id

    @staticmethod
    def _layer_id(item: QtWidgets.QGraphicsItem) -> str:
        layer_id = item.data(KEY_LAYER_ID)
        return str(layer_id) if isinstance(layer_id, str) and layer_id else DEFAULT_LAYER_ID
