import json

from PySide6 import QtCore


def _snapshot(canvas_view) -> str:
    return json.dumps(
        canvas_view.serialize_scene_state(), sort_keys=True, separators=(",", ":")
    )


def test_undo_of_moved_group_restores_the_exact_snapshot(canvas_view, application):
    history = canvas_view.history()
    items = [
        canvas_view.add_shape(
            shape, QtCore.QPointF(100 + index * 150, 100), snap_to_grid=False
        )
        for index, shape in enumerate(("Rectangle", "Ellipse", "Diamond"))
    ]
    canvas_view.scene().clearSelection()
    for item in items:
        item.setSelected(True)
    canvas_view._group_selected_items()
    history.capture_now()
    grouped = _snapshot(canvas_view)

    group = canvas_view.scene().selectedItems()[0]
    for _ in range(2):
        group.moveBy(50, 40)
        history.capture_now()
    states = len(history._states)
    index = history._index

    history.undo()
    history.undo()
    assert _snapshot(canvas_view) == grouped

    # A later capture must recognise the restored scene instead of appending it.
    history.capture_now()
    assert len(history._states) == states
    assert history._index == index - 2
    assert history.can_redo()
