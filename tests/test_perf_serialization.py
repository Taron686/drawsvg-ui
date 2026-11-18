from PySide6 import QtCore, QtWidgets


def test_serialization_skips_classification_of_child_items(canvas_view, monkeypatch):
    parent = canvas_view.add_shape(
        "Rectangle", QtCore.QPointF(20, 20), snap_to_grid=False
    )
    child = QtWidgets.QGraphicsRectItem(0, 0, 10, 10, parent)
    classified = []
    original = canvas_view._is_serializable_item

    def classify(item):
        classified.append(item)
        return original(item)

    monkeypatch.setattr(canvas_view, "_is_serializable_item", classify)
    canvas_view._serialize_scene_state()
    assert child not in classified
