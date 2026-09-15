import pytest
from PySide6 import QtCore

from import_drawsvg import import_drawsvg_py
from items.labels import ShapeLabelMixin


@pytest.mark.parametrize("font_px", (10, 12, 24))
def test_imported_box_labels_keep_position_through_undo(
    application, canvas_view, tmp_path, font_px
):
    lines = ["import drawsvg as draw", "d = draw.Drawing(1200, 1000)"]
    for index in range(20):
        lines.extend([
            f"_rect = draw.Rectangle({index % 5 * 200}, {index // 5 * 150}, "
            f"160, 100, data_label_id='label{index}')",
            f"_label = draw.Text('First line\\nSecond line\\nThird line\\nFourth line\\nFifth line', "
            f"{font_px}, 0, 0, data_shape_label='true', data_label_id='label{index}', "
            f"data_label_h='center', data_label_v='middle', data_font_px={font_px})",
        ])
    lines.append("_text = draw.Text('Standalone', 16, 100, 800)")
    path = tmp_path / "legacy_labels.py"
    path.write_text("\n".join(lines), encoding="utf-8")
    assert import_drawsvg_py(canvas_view.scene(), path=path) == path

    def label_state():
        return sorted(
            (
                item.pos().x(), item.pos().y(), item.label_alignment(),
                item.label_text(), item.label_item().font().toString(),
                item.label_item().pos().x(), item.label_item().pos().y(),
            )
            for item in canvas_view.scene().items()
            if isinstance(item, ShapeLabelMixin) and item.has_label()
        )

    before = label_state()
    assert len(before) == 20
    canvas_view.add_shape("Rectangle", QtCore.QPointF(900, 900), snap_to_grid=False)
    canvas_view.history().undo()
    application.processEvents()
    assert label_state() == before
    canvas_view.history().redo()
    application.processEvents()
    assert label_state() == before
