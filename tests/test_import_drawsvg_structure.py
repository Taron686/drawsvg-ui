from PySide6 import QtWidgets

from import_drawsvg import import_drawsvg_py


def test_blank_line_discards_pending_arrow_metadata(application, tmp_path):
    path = tmp_path / "drawing.py"
    path.write_text(
        "d = draw.Drawing(100, 100)\n"
        "_line = draw.Line(0, 0, 50, 50)\n"
        "\n"
        "# Arrowheads: start=true, end=true\n",
        encoding="utf-8",
    )
    scene = QtWidgets.QGraphicsScene()

    assert import_drawsvg_py(scene, path=path) == path.resolve()
    assert [item.data(0) for item in scene.items() if item.parentItem() is None] == [
        "Line"
    ]
