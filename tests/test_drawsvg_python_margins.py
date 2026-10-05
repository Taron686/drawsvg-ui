import runpy
from xml.etree import ElementTree as ET

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from export_drawsvg import export_drawsvg_py
from export_margins import ExportMargins
from import_drawsvg import import_drawsvg_py
from items import RectItem


@pytest.fixture
def rectangle_scene(application):
    scene = QtWidgets.QGraphicsScene()
    item = RectItem(0, 0, 100.25, 50.75)
    item.setData(0, "Rectangle")
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    item.setBrush(QtGui.QColor("#e02020"))
    item.setPos(-20.25, -10.5)
    scene.addItem(item)
    item.setSelected(True)
    return scene, item


@pytest.mark.parametrize(
    "margins, expected",
    [(None, (-26, -16, 111, 62)),
     (ExportMargins(0, 0, 0, 0), (-20.25, -10.5, 100.25, 50.75)),
     (ExportMargins(1.25, 2.5, 3.75, 4.125), (-21.5, -13, 105.25, 57.375))],
    ids=["legacy", "explicit-zero", "fractional-asymmetric"],
)
def test_python_output_executes_with_exact_margins_and_preserves_coordinates(
    rectangle_scene, monkeypatch, tmp_path, margins, expected
):
    scene, item = rectangle_scene
    before = (item.pos(), item.rect(), item.sceneTransform(), scene.sceneRect(), item.isSelected())
    output = tmp_path / "margins.py"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **kw: (str(output), ""))
    export_drawsvg_py(scene, margins=margins)

    drawing = runpy.run_path(str(output))["build_drawing"]()
    root = ET.fromstring(drawing.as_svg())
    assert tuple(map(float, root.attrib["viewBox"].split())) == pytest.approx(expected)
    assert (float(root.attrib["width"]), float(root.attrib["height"])) == pytest.approx(expected[2:])
    rectangles = root.findall("{http://www.w3.org/2000/svg}rect")
    background = rectangles[0]
    assert tuple(float(background.attrib[k]) for k in ("x", "y", "width", "height")) == pytest.approx(expected)
    assert background.attrib["fill"] == "white"
    assert tuple(float(rectangles[1].attrib[k]) for k in ("x", "y", "width", "height")) == pytest.approx((0, 0, 100.25, 50.75))
    assert (item.pos(), item.rect(), item.sceneTransform(), scene.sceneRect(), item.isSelected()) == before

    restored = QtWidgets.QGraphicsScene()
    import_drawsvg_py(restored, path=str(output))
    restored_items = [candidate for candidate in restored.items() if candidate.data(0) == "Rectangle"]
    assert len(restored_items) == 1
    assert restored_items[0].sceneBoundingRect().getRect() == pytest.approx((-20.25, -10.5, 100.25, 50.75))
    assert restored.sceneRect().getRect() == pytest.approx(expected)


def test_legacy_python_empty_scene_keeps_existing_padding(application, monkeypatch, tmp_path):
    output = tmp_path / "empty.py"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **kw: (str(output), ""))

    export_drawsvg_py(QtWidgets.QGraphicsScene())

    root = ET.fromstring(runpy.run_path(str(output))["build_drawing"]().as_svg())
    assert tuple(map(float, root.attrib["viewBox"].split())) == (-5, -5, 10, 10)


def test_custom_python_margins_reject_empty_scene(application):
    with pytest.raises(ValueError, match="empty"):
        export_drawsvg_py(QtWidgets.QGraphicsScene(), margins=ExportMargins(5, 5, 5, 5))
