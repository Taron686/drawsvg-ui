from __future__ import annotations

from PySide6 import QtCore

from items import TextItem
from properties_panel import PropertiesPanel


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
