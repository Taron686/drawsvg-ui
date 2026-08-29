from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items import BlockArrowItem, RectItem
from main_window import MainWindow
from ruler_widget import RulerWidget


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


def _mouse_event(
    event_type: QtCore.QEvent.Type,
    point: QtCore.QPoint,
    button: QtCore.Qt.MouseButton,
    buttons: QtCore.Qt.MouseButton,
) -> QtGui.QMouseEvent:
    return QtGui.QMouseEvent(
        event_type,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        button,
        buttons,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def _send_viewport_mouse_event(
    view,
    event_type: QtCore.QEvent.Type,
    point: QtCore.QPoint,
    button: QtCore.Qt.MouseButton,
    buttons: QtCore.Qt.MouseButton,
) -> None:
    global_point = view.viewport().mapToGlobal(point)
    event = QtGui.QMouseEvent(
        event_type,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        QtCore.QPointF(global_point),
        button,
        buttons,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(view.viewport(), event)


def test_corner_resize_does_not_snap_the_selected_arrow_to_a_guide(
    canvas_view, application
) -> None:
    canvas_view.resize(800, 600)
    canvas_view.show()
    origin = canvas_view._master_origin
    arrow = BlockArrowItem(origin.x() + 200.0, origin.y() + 200.0, 50.0, 50.0)
    canvas_view.scene().addItem(arrow)
    arrow.setSelected(True)
    application.processEvents()

    assert arrow._head_handle is not None
    assert arrow._body_handle is not None
    assert arrow._head_handle.isVisible()
    assert arrow._body_handle.isVisible()
    before_position = QtCore.QPointF(arrow.pos())
    canvas_view.add_guide("vertical", arrow.sceneBoundingRect().left() + 3.0)
    resize_handle = next(
        handle for handle in arrow._handles if handle._direction == "bottom_right"
    )
    start = canvas_view.mapFromScene(resize_handle.scenePos())
    end = start + QtCore.QPoint(30, 30)

    _send_viewport_mouse_event(
        canvas_view,
        QtCore.QEvent.Type.MouseButtonPress,
        start,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
    )
    _send_viewport_mouse_event(
        canvas_view,
        QtCore.QEvent.Type.MouseMove,
        end,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.LeftButton,
    )
    _send_viewport_mouse_event(
        canvas_view,
        QtCore.QEvent.Type.MouseButtonRelease,
        end,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.NoButton,
    )

    assert arrow.pos() == before_position
    assert arrow.scale() > 1.0
    assert arrow._head_handle.isVisible()
    assert arrow._body_handle.isVisible()
    assert canvas_view._active_snap_guides == {}


def test_horizontal_ruler_creates_moves_and_deletes_a_vertical_guide(
    canvas_view, application
) -> None:
    canvas_view.resize(400, 300)
    canvas_view.show()
    ruler = RulerWidget(QtCore.Qt.Orientation.Horizontal, canvas_view)
    ruler.resize(400, 22)
    ruler.show()
    application.processEvents()
    start = QtCore.QPoint(80, 11)
    end = QtCore.QPoint(120, 11)

    ruler.mousePressEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonPress,
            start,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
        )
    )
    ruler.mouseMoveEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseMove,
            end,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
        )
    )
    ruler.mouseReleaseEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonRelease,
            end,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
        )
    )

    expected = ruler._scene_position(QtCore.QPointF(end))
    assert canvas_view.guides() == (("vertical", expected),)
    ruler.mousePressEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonPress,
            end,
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.MouseButton.RightButton,
        )
    )
    assert canvas_view.guides() == ()
    ruler.close()


def test_view_action_toggles_visible_rulers_and_guides(application) -> None:
    window = MainWindow()
    window.show()
    application.processEvents()

    assert window.horizontal_ruler.isVisible()
    assert window.vertical_ruler.isVisible()
    window.actionShow_guides.setChecked(False)

    assert not window.canvas.guides_visible()
    assert window.horizontal_ruler.isHidden()
    assert window.vertical_ruler.isHidden()
    window.close()


def test_tools_action_toggles_connector_creation_mode(application) -> None:
    window = MainWindow()
    window.show()
    application.processEvents()

    assert window.actionCreate_connector in window.menuTools.actions()
    window.actionCreate_connector.setChecked(True)
    assert window.canvas.connector_creation_enabled()
    window.canvas.set_connector_creation_enabled(False)
    assert not window.actionCreate_connector.isChecked()
    window.close()


def test_guide_inside_an_a4_page_is_painted_in_the_foreground(
    canvas_view, application
) -> None:
    canvas_view.resize(600, 500)
    canvas_view.show()
    application.processEvents()
    page = canvas_view._page_item
    assert page is not None
    guide_position = 0.0
    page_rect = page.mapRectToScene(page.rect())
    assert page_rect.contains(QtCore.QPointF(guide_position, 0.0))
    canvas_view.add_guide("vertical", guide_position)
    application.processEvents()

    image = canvas_view.viewport().grab().toImage()
    guide_x = canvas_view.mapFromScene(QtCore.QPointF(guide_position, 0.0)).x()
    top = canvas_view.mapFromScene(
        QtCore.QPointF(guide_position, page_rect.top() + 8.0)
    ).y()
    bottom = canvas_view.mapFromScene(
        QtCore.QPointF(guide_position, page_rect.bottom() - 8.0)
    ).y()

    assert any(
        (color := image.pixelColor(guide_x, y)).green() - color.red() > 40
        and color.blue() - color.red() > 40
        for y in range(max(0, top), min(image.height(), bottom + 1))
    )
