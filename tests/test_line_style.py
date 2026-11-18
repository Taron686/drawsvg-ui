from __future__ import annotations

import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

from main_window import MainWindow
from shape_registry import SHAPE_REGISTRY

DASH = QtCore.Qt.PenStyle.DashLine
DOT = QtCore.Qt.PenStyle.DotLine
SHAPES = (
    "Rectangle",
    "Rounded Rectangle",
    "Ellipse",
    "Circle",
    "Triangle",
    "Diamond",
    "Block Arrow",
    "Line",
    "Arrow",
)


@pytest.fixture
def window(application, tmp_path):
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    window = MainWindow(recent_files_path=tmp_path / "recent.json", settings=settings)
    window.show()
    application.processEvents()
    yield window
    window.canvas.scene().clearSelection()
    window._force_close = True
    window.close()


def _style_action(view, item, label):
    menu = QtWidgets.QMenu()
    callbacks = view._create_shape_style_actions(menu, item)
    for action, callback in callbacks.items():
        parent = action.parent()
        if action.text() == label and getattr(parent, "title", lambda: "")() == (
            "Line style"
        ):
            return callback
    raise AssertionError(f"no 'Line style > {label}' action for {type(item)}")


def _select(window, item):
    window.canvas.scene().clearSelection()
    item.setSelected(True)
    QTest.qWait(50)


@pytest.mark.parametrize("shape", SHAPES)
def test_context_menu_sets_line_style_for_every_shape(canvas_view, shape):
    item = canvas_view.add_shape(shape, QtCore.QPointF(100, 100))
    _style_action(canvas_view, item, "Dashed")()
    assert item.pen().style() == DASH
    _style_action(canvas_view, item, "Dotted")()
    assert item.pen().style() == DOT
    canvas_view.scene().clearSelection()


@pytest.mark.parametrize("shape", SHAPES)
def test_properties_panel_sets_line_style(window, shape):
    item = window.canvas.add_shape(shape, QtCore.QPointF(100, 100))
    _select(window, item)
    combo = window.properties_panel._combo_stroke_style
    assert combo.isEnabled()
    assert combo.currentData() == int(QtCore.Qt.PenStyle.SolidLine.value)

    combo.setCurrentIndex(combo.findData(int(DASH.value)))
    assert item.pen().style() == DASH

    combo.setCurrentIndex(combo.findData(int(DOT.value)))
    assert item.pen().style() == DOT


def test_properties_panel_reflects_existing_style(window):
    item = window.canvas.add_shape("Ellipse", QtCore.QPointF(100, 100))
    pen = item.pen()
    pen.setStyle(DASH)
    item.setPen(pen)
    _select(window, item)
    combo = window.properties_panel._combo_stroke_style
    assert combo.currentText() == "Dashed"


def test_custom_entry_is_hidden_from_popup_but_shown_for_custom_patterns(window):
    combo = window.properties_panel._combo_stroke_style
    custom_row = combo.findData(-1)
    assert combo.view().isRowHidden(custom_row)

    item = window.canvas.add_shape("Rectangle", QtCore.QPointF(100, 100))
    pen = item.pen()
    pen.setDashPattern([6.0, 2.0, 1.0, 2.0])
    item.setPen(pen)
    _select(window, item)
    assert combo.currentText() == "Custom"
    assert combo.view().isRowHidden(custom_row)


@pytest.mark.parametrize("style", (DASH, DOT))
@pytest.mark.parametrize("shape", ("Rectangle", "Ellipse", "Triangle", "Arrow"))
def test_line_style_survives_serialization(canvas_view, shape, style):
    item = canvas_view.add_shape(shape, QtCore.QPointF(100, 100))
    _style_action(
        canvas_view, item, "Dashed" if style == DASH else "Dotted"
    )()
    restored = SHAPE_REGISTRY.restore(SHAPE_REGISTRY.serialize(item))
    assert restored.pen().style() == style
    canvas_view.scene().clearSelection()


def test_custom_dash_pattern_survives_serialization(canvas_view):
    item = canvas_view.add_shape("Rectangle", QtCore.QPointF(100, 100))
    pen = item.pen()
    pen.setDashPattern([6.0, 2.0, 1.0, 2.0])
    item.setPen(pen)
    restored = SHAPE_REGISTRY.restore(SHAPE_REGISTRY.serialize(item))
    assert restored.pen().style() == QtCore.Qt.PenStyle.CustomDashLine
    assert restored.pen().dashPattern() == [6.0, 2.0, 1.0, 2.0]
    canvas_view.scene().clearSelection()


def test_line_shape_cache_follows_geometry_and_pen(canvas_view):
    item = canvas_view.add_shape("Arrow", QtCore.QPointF(100, 100))
    before = item.boundingRect()
    assert item.boundingRect() == before

    pen = item.pen()
    pen.setWidthF(30.0)
    item.setPen(pen)
    wider = item.boundingRect()
    assert wider.height() > before.height()

    item._points[-1] = item._points[-1] + QtCore.QPointF(200.0, 0.0)
    item._update_path()
    assert item.boundingRect().width() > wider.width()

    with_head = item.shape().boundingRect()
    item.set_arrow_head_width(120.0)
    assert item.shape().boundingRect().height() > with_head.height()
    canvas_view.scene().clearSelection()
