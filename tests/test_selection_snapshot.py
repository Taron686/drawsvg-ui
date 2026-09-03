from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from items import CurvyBracketItem, TextItem
from properties_panel import PlainTextEditor, PropertiesPanel


def test_single_selection_snapshot_keeps_raw_panel_data_without_formatted_lists(
    canvas_view,
) -> None:
    item = canvas_view.add_shape(
        "Text", QtCore.QPointF(10.0, 10.0), snap_to_grid=False
    )
    assert isinstance(item, TextItem)
    item.setPlainText("Raw text")
    item.setSelected(True)

    snapshot = canvas_view._build_selection_snapshot()

    assert snapshot["selection_type"] == "single"
    assert "properties" not in snapshot
    assert "text_properties" not in snapshot
    assert snapshot["object_data"]["shape"] == "Text"
    assert snapshot["text_data"]["text"] == "Raw text"

    panel = PropertiesPanel()
    panel.update_snapshot(snapshot)

    assert panel._latest_object_data == snapshot["object_data"]
    assert panel._latest_text_data == snapshot["text_data"]
    panel.close()


def test_shape_label_uses_a_multiline_text_editor(canvas_view) -> None:
    item = canvas_view.add_shape(
        "Rectangle", QtCore.QPointF(10.0, 10.0), snap_to_grid=False
    )
    assert item is not None
    panel = PropertiesPanel()
    panel.update_snapshot(canvas_view._build_selection_snapshot())

    editor = panel.findChild(PlainTextEditor, "plainLabelText")

    assert isinstance(editor, PlainTextEditor)
    editor.setPlainText("First line\nSecond line")
    editor.editingFinished.emit()
    assert item.label_text() == "First line\nSecond line"
    panel.close()


def test_hook_depth_slider_updates_value_and_bracket_geometry(canvas_view) -> None:
    item = canvas_view.add_shape(
        "Curvy Right Bracket", QtCore.QPointF(10.0, 10.0), snap_to_grid=False
    )
    assert isinstance(item, CurvyBracketItem)
    item.setSelected(True)
    panel = PropertiesPanel(canvas_view)
    panel.update_snapshot(canvas_view._build_selection_snapshot())

    slider = panel.findChild(QtWidgets.QSlider, "sliderHookDepth")

    assert slider is not None
    assert (slider.minimum(), slider.maximum()) == (8, 45)
    slider.setValue(45)
    assert item.hook_ratio() == 0.45
    assert panel._spin_hook_depth.isReadOnly()
    assert panel._spin_hook_depth.value() == 0.45
    panel.close()
