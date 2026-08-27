from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from layer_manager import DEFAULT_LAYER_ID
from scene_codec import KEY_ITEM_ID, KEY_LAYER_ID


def _add(canvas_view, shape: str, x: float):
    item = canvas_view.add_shape(
        shape, QtCore.QPointF(x, 25.0), snap_to_grid=False
    )
    assert item is not None
    return item


def test_legacy_snapshot_restores_a_visible_unlocked_default_layer(canvas_view) -> None:
    item = _add(canvas_view, "Rectangle", 10.0)
    item_id = item.data(KEY_ITEM_ID)
    legacy = canvas_view._serialize_scene_state()
    legacy.pop("layers")
    legacy["items"][0].pop("visible")
    legacy["items"][0].pop("locked")

    canvas_view._restore_scene_state(legacy)

    manager = canvas_view.layer_manager()
    assert [(layer.id, layer.visible, layer.locked) for layer in manager.layers()] == [
        (DEFAULT_LAYER_ID, True, False)
    ]
    restored = next(
        scene_item
        for scene_item in canvas_view.scene().items()
        if scene_item.data(KEY_ITEM_ID) == item_id
    )
    assert restored.data(KEY_LAYER_ID) == DEFAULT_LAYER_ID


def test_layer_state_roundtrips_and_undo_restores_visibility_and_lock(canvas_view) -> None:
    first = _add(canvas_view, "Rectangle", 10.0)
    second = _add(canvas_view, "Ellipse", 180.0)
    manager = canvas_view.layer_manager()
    with canvas_view.history().transaction():
        layer = manager.add_layer("Annotations")
        assert manager.assign_item(second, layer.id)
        canvas_view.history().mark_dirty()
    layer_id = layer.id

    with canvas_view.history().transaction():
        assert manager.set_layer_visible(layer_id, False)
        assert manager.set_layer_locked(layer_id, True)
        canvas_view.history().mark_dirty()

    state = canvas_view._serialize_scene_state()
    assert state["layers"][1] == {
        "id": layer_id,
        "name": "Annotations",
        "visible": False,
        "locked": True,
    }
    assert not second.isVisible()
    assert second.locked

    canvas_view.undo()

    restored_layer = next(item for item in manager.layers() if item.id == layer_id)
    assert restored_layer.visible
    assert not restored_layer.locked
    restored_second = next(
        item
        for item in canvas_view.scene().items()
        if item.data(KEY_ITEM_ID) == second.data(KEY_ITEM_ID)
    )
    assert restored_second.isVisible()
    assert not restored_second.locked
    assert first.data(KEY_ITEM_ID)


def test_reordering_preserves_item_ids_and_geometry(canvas_view) -> None:
    first = _add(canvas_view, "Rectangle", 10.0)
    second = _add(canvas_view, "Ellipse", 180.0)
    manager = canvas_view.layer_manager()
    before = {
        item.data(KEY_ITEM_ID): (item.pos().x(), item.pos().y())
        for item in (first, second)
    }

    with canvas_view.history().transaction():
        assert manager.move_item(second, -1)
        canvas_view.history().mark_dirty()

    state = canvas_view._serialize_scene_state()
    assert [entry["id"] for entry in state["items"]] == [
        second.data(KEY_ITEM_ID),
        first.data(KEY_ITEM_ID),
    ]
    after = {
        item.data(KEY_ITEM_ID): (item.pos().x(), item.pos().y())
        for item in (first, second)
    }
    assert after == before


def test_layer_lock_disables_direct_item_interaction(canvas_view) -> None:
    item = _add(canvas_view, "Rectangle", 10.0)
    manager = canvas_view.layer_manager()

    assert manager.set_item_locked(item, True)

    assert item.locked
    assert not item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    assert not item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
