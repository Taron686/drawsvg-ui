"""Persistent layer state shared by the canvas and the layers sidebar."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtWidgets

from scene_codec import DEFAULT_LAYER_ID, KEY_LAYER_ID, SceneCodec

# Kept separate from SceneCodec's structural metadata so old scenes retain their
# existing payload shape until they opt in to layers.
KEY_ITEM_VISIBLE = 1004
KEY_ITEM_LOCKED = 1005


@dataclass
class Layer:
    id: str
    name: str
    visible: bool = True
    locked: bool = False


class LayerManager(QtCore.QObject):
    """Own layer and item presentation state without changing item geometry."""

    changed = QtCore.Signal()

    def __init__(self, canvas: Any) -> None:
        super().__init__(canvas)
        self._canvas = canvas
        self._layers: list[Layer] = [Layer(DEFAULT_LAYER_ID, "Layer 1")]

    def layers(self) -> tuple[Layer, ...]:
        return tuple(self._layers)

    def layer_for_item(self, item: QtWidgets.QGraphicsItem) -> Layer:
        layer_id = item.data(KEY_LAYER_ID)
        if not isinstance(layer_id, str) or not self._find_layer(layer_id):
            item.setData(KEY_LAYER_ID, DEFAULT_LAYER_ID)
            return self._layers[0]
        return self._find_layer(layer_id)  # type: ignore[return-value]

    def items_for_layer(self, layer_id: str) -> list[QtWidgets.QGraphicsItem]:
        scene = self._canvas.scene()
        if scene is None:
            return []
        items = [
            item
            for item in scene.items(QtCore.Qt.SortOrder.AscendingOrder)
            if self._is_top_level_item(item)
            and self.layer_for_item(item).id == layer_id
        ]
        return items

    def serialize_state(self) -> list[dict[str, Any]]:
        return [
            {
                "id": layer.id,
                "name": layer.name,
                "visible": layer.visible,
                "locked": layer.locked,
            }
            for layer in self._layers
        ]

    def restore_state(self, payload: object) -> None:
        restored: list[Layer] = []
        if isinstance(payload, list):
            known_ids: set[str] = set()
            for index, entry in enumerate(payload, start=1):
                if not isinstance(entry, Mapping):
                    continue
                layer_id = entry.get("id")
                name = entry.get("name")
                if not isinstance(layer_id, str) or not layer_id or layer_id in known_ids:
                    continue
                known_ids.add(layer_id)
                restored.append(
                    Layer(
                        layer_id,
                        name if isinstance(name, str) and name else f"Layer {index}",
                        bool(entry.get("visible", True)),
                        bool(entry.get("locked", False)),
                    )
                )
        self._layers = restored or [Layer(DEFAULT_LAYER_ID, "Layer 1")]
        if not self._find_layer(DEFAULT_LAYER_ID):
            self._layers.insert(0, Layer(DEFAULT_LAYER_ID, "Layer 1"))
        self.sync_items()

    def item_metadata(self, item: QtWidgets.QGraphicsItem) -> dict[str, Any]:
        layer = self.layer_for_item(item)
        return {
            "layer_id": layer.id,
            "visible": self.item_visible(item),
            "locked": self.item_locked(item),
        }

    def restore_item_state(
        self,
        item: QtWidgets.QGraphicsItem,
        data: Mapping[str, Any],
    ) -> None:
        layer_id = data.get("layer_id")
        item.setData(
            KEY_LAYER_ID,
            layer_id if isinstance(layer_id, str) and self._find_layer(layer_id) else DEFAULT_LAYER_ID,
        )
        item.setData(KEY_ITEM_VISIBLE, bool(data.get("visible", True)))
        item.setData(KEY_ITEM_LOCKED, bool(data.get("locked", False)))
        self._apply_item_state(item)

    def register_item(self, item: QtWidgets.QGraphicsItem) -> None:
        if not self._is_top_level_item(item):
            return
        self.layer_for_item(item)
        if item.data(KEY_ITEM_VISIBLE) is None:
            item.setData(KEY_ITEM_VISIBLE, True)
        if item.data(KEY_ITEM_LOCKED) is None:
            item.setData(KEY_ITEM_LOCKED, False)
        self._apply_item_state(item)

    def sync_items(self) -> None:
        scene = self._canvas.scene()
        if scene is None:
            return
        for item in scene.items(QtCore.Qt.SortOrder.AscendingOrder):
            if self._is_top_level_item(item):
                self.register_item(item)
        self.changed.emit()

    def item_visible(self, item: QtWidgets.QGraphicsItem) -> bool:
        return item.data(KEY_ITEM_VISIBLE) is not False

    def item_locked(self, item: QtWidgets.QGraphicsItem) -> bool:
        return bool(item.data(KEY_ITEM_LOCKED))

    def set_layer_visible(self, layer_id: str, visible: bool) -> bool:
        layer = self._find_layer(layer_id)
        if layer is None or layer.visible == visible:
            return False
        layer.visible = visible
        self._apply_layer(layer)
        self.changed.emit()
        return True

    def set_layer_locked(self, layer_id: str, locked: bool) -> bool:
        layer = self._find_layer(layer_id)
        if layer is None or layer.locked == locked:
            return False
        layer.locked = locked
        self._apply_layer(layer)
        self.changed.emit()
        return True

    def set_item_visible(self, item: QtWidgets.QGraphicsItem, visible: bool) -> bool:
        if self.item_visible(item) == visible:
            return False
        item.setData(KEY_ITEM_VISIBLE, visible)
        self._apply_item_state(item)
        self.changed.emit()
        return True

    def set_item_locked(self, item: QtWidgets.QGraphicsItem, locked: bool) -> bool:
        if self.item_locked(item) == locked:
            return False
        item.setData(KEY_ITEM_LOCKED, locked)
        self._apply_item_state(item)
        self.changed.emit()
        return True

    def assign_item(self, item: QtWidgets.QGraphicsItem, layer_id: str) -> bool:
        if not self._is_top_level_item(item) or self._find_layer(layer_id) is None:
            return False
        if self.layer_for_item(item).id == layer_id:
            return False
        item.setData(KEY_LAYER_ID, layer_id)
        self._apply_item_state(item)
        self.changed.emit()
        return True

    def add_layer(self, name: str | None = None) -> Layer:
        existing = {layer.id for layer in self._layers}
        number = 1
        while f"layer-{number}" in existing:
            number += 1
        layer = Layer(f"layer-{number}", name or f"Layer {number}")
        self._layers.append(layer)
        self.changed.emit()
        return layer

    def remove_layer(self, layer_id: str) -> bool:
        layer = self._find_layer(layer_id)
        if layer is None or len(self._layers) == 1:
            return False
        fallback = next(item for item in self._layers if item.id != layer_id)
        for item in self.items_for_layer(layer_id):
            item.setData(KEY_LAYER_ID, fallback.id)
            self._apply_item_state(item)
        self._layers.remove(layer)
        self.changed.emit()
        return True

    def move_item(self, item: QtWidgets.QGraphicsItem, offset: int) -> bool:
        layer = self.layer_for_item(item)
        ordered = self.items_for_layer(layer.id)
        try:
            index = ordered.index(item)
        except ValueError:
            return False
        target = max(0, min(len(ordered) - 1, index + offset))
        if target == index:
            return False
        ordered[index], ordered[target] = ordered[target], ordered[index]
        self._apply_global_order(layer.id, ordered)
        self.changed.emit()
        return True

    def _apply_global_order(
        self,
        layer_id: str,
        layer_items: list[QtWidgets.QGraphicsItem],
    ) -> None:
        scene = self._canvas.scene()
        if scene is None:
            return
        ordered = [
            item
            for item in scene.items(QtCore.Qt.SortOrder.AscendingOrder)
            if self._is_top_level_item(item)
        ]
        iterator = iter(layer_items)
        ordered = [next(iterator) if self.layer_for_item(item).id == layer_id else item for item in ordered]
        for z_value, ordered_item in enumerate(ordered):
            ordered_item.setZValue(float(z_value))

    def _apply_layer(self, layer: Layer) -> None:
        for item in self.items_for_layer(layer.id):
            self._apply_item_state(item)

    def _apply_item_state(self, item: QtWidgets.QGraphicsItem) -> None:
        layer = self.layer_for_item(item)
        item.setVisible(layer.visible and self.item_visible(item))
        locked = layer.locked or self.item_locked(item)
        item.locked = locked
        if item.parentItem() is None:
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not locked)
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not locked)
        if locked:
            item.setSelected(False)

    def _is_top_level_item(self, item: QtWidgets.QGraphicsItem) -> bool:
        return bool(
            item.parentItem() is None
            and self._canvas._is_serializable_item(item)
            and not SceneCodec.is_transient(item)
        )

    def _find_layer(self, layer_id: str) -> Layer | None:
        return next((layer for layer in self._layers if layer.id == layer_id), None)
