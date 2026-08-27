from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui

from items import RectItem


@pytest.mark.parametrize("zoom", (0.25, 1.0, 4.0))
def test_manual_guide_threshold_is_six_screen_pixels(canvas_view, zoom: float) -> None:
    canvas_view.add_guide("vertical", 100.0)
    canvas_view.setTransform(QtGui.QTransform.fromScale(zoom, zoom))

    inside, inside_guides = canvas_view.snap_scene_position(
        QtCore.QPointF(100.0 + 6.0 / zoom, 31.0)
    )
    outside, outside_guides = canvas_view.snap_scene_position(
        QtCore.QPointF(100.0 + 7.0 / zoom, 31.0)
    )

    assert inside.x() == pytest.approx(100.0)
    assert inside_guides == {"vertical": 100.0}
    assert outside_guides == {}
    assert outside.x() != pytest.approx(100.0)


def test_manual_guides_take_priority_over_smart_guides_and_grid(canvas_view) -> None:
    other = RectItem(100.0, 40.0, 20.0, 20.0)
    other.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(other)
    canvas_view.add_guide("vertical", 103.0)

    snapped, active_guides = canvas_view.snap_scene_position(
        QtCore.QPointF(100.5, 40.0), QtCore.QSizeF(20.0, 20.0)
    )

    assert snapped.x() == pytest.approx(103.0)
    assert active_guides["vertical"] == pytest.approx(103.0)


def test_smart_guides_precede_grid_when_no_manual_guide_exists(canvas_view) -> None:
    other = RectItem(100.0, 40.0, 20.0, 20.0)
    other.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(other)

    snapped, active_guides = canvas_view.snap_scene_position(
        QtCore.QPointF(104.0, 40.0), QtCore.QSizeF(20.0, 20.0)
    )

    assert snapped.x() == pytest.approx(100.0)
    assert active_guides["vertical"] == pytest.approx(100.0)


def test_dragging_selected_item_uses_manual_guide_before_grid(canvas_view) -> None:
    item = RectItem(100.0, 40.0, 20.0, 20.0)
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    canvas_view.scene().addItem(item)
    item.setSelected(True)
    canvas_view.add_guide("vertical", 103.0)

    canvas_view._snap_selected_items()

    assert item.sceneBoundingRect().left() == pytest.approx(103.0)
    assert canvas_view._active_snap_guides["vertical"] == pytest.approx(103.0)


def test_owner_page_is_deterministic_and_oversized_item_creates_every_touched_page(
    canvas_view,
) -> None:
    item = RectItem(-900.0, -900.0, 1800.0, 1800.0)
    canvas_view.scene().addItem(item)
    owner = canvas_view._ensure_page_for_item(item, QtCore.QPointF(100.0, -100.0))

    assert canvas_view._owner_page_index(item) == owner.index
    expected_indices = canvas_view._page_indices_for_rect(item.sceneBoundingRect())
    assert expected_indices <= set(canvas_view._pages)
    assert canvas_view.scene().sceneRect().contains(item.sceneBoundingRect())


def test_moving_item_reassigns_owner_page_by_reference_point(canvas_view) -> None:
    item = RectItem(0.0, 0.0, 40.0, 40.0)
    canvas_view.scene().addItem(item)
    first = canvas_view._ensure_page_for_item(item, QtCore.QPointF(0.0, 0.0)).index
    item.setPos(2000.0, 0.0)
    second = canvas_view._ensure_page_for_item(item, QtCore.QPointF(2000.0, 0.0)).index

    assert first != second
    assert canvas_view._owner_page_index(item) == second
    assert second in canvas_view._pages


def test_guides_and_owner_page_survive_scene_state_restore(canvas_view) -> None:
    canvas_view.add_guide("horizontal", 80.0)
    item = canvas_view.add_shape(
        "Rectangle", QtCore.QPointF(1200.0, 20.0), snap_to_grid=False
    )
    assert item is not None
    owner_before = canvas_view._owner_page_index(item)
    state = canvas_view._serialize_scene_state()

    canvas_view._restore_scene_state(state)
    restored = next(
        item for item in canvas_view.scene().items() if isinstance(item, RectItem)
    )

    assert canvas_view.guides() == (("horizontal", 80.0),)
    assert canvas_view._owner_page_index(restored) == owner_before


def test_ruler_ticks_are_expressed_in_millimetres(canvas_view) -> None:
    ticks = canvas_view.ruler_ticks(0.0, 100.0, major_mm=10.0)

    assert ticks[0] == pytest.approx((0.0, 0.0))
    assert ticks[1][1] == pytest.approx(10.0)
