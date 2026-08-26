from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from PySide6 import QtCore, QtGui, QtWidgets

from export_renderer import ExportArea, ExportRenderer, ExportRequest
from items import RectItem


def _rectangle(x: float, y: float, width: float, height: float, color: str) -> RectItem:
    item = RectItem(x, y, width, height)
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    item.setBrush(QtGui.QColor(color))
    return item


def test_exports_valid_svg_png_and_pdf_from_one_scene(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_rectangle(0.0, 0.0, 40.0, 30.0, "#d94f4f"))
    renderer = ExportRenderer(scene)
    request = ExportRequest(
        area=ExportArea.CURRENT_PAGE,
        current_page=QtCore.QRectF(0.0, 0.0, 80.0, 60.0),
    )

    svg = renderer.export_svg(tmp_path / "scene.svg", request)
    png = renderer.export_png(tmp_path / "scene.png", request)
    pdf = renderer.export_pdf(tmp_path / "scene.pdf", request)

    assert svg == (tmp_path / "scene.svg",)
    assert png == (tmp_path / "scene.png",)
    assert ElementTree.parse(svg[0]).getroot().tag.endswith("svg")
    assert QtGui.QImageReader(str(png[0])).read().size() == QtCore.QSize(80, 60)
    assert pdf.read_bytes().startswith(b"%PDF-")


def test_all_pages_uses_numbered_svg_and_png_files(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_rectangle(0.0, 0.0, 10.0, 10.0, "#d94f4f"))
    request = ExportRequest(
        area=ExportArea.ALL_PAGES,
        pages=(QtCore.QRectF(0.0, 0.0, 20.0, 20.0), QtCore.QRectF(30.0, 0.0, 20.0, 20.0)),
    )
    renderer = ExportRenderer(scene)

    assert renderer.export_svg(tmp_path / "pages.svg", request) == (
        tmp_path / "pages_p001.svg",
        tmp_path / "pages_p002.svg",
    )
    assert renderer.export_png(tmp_path / "pages.png", request) == (
        tmp_path / "pages_p001.png",
        tmp_path / "pages_p002.png",
    )
    pdf = renderer.export_pdf(tmp_path / "pages.pdf", request)
    assert pdf.read_bytes().count(b"/Type /Page") >= 2


def test_export_restores_selection_visibility_and_canvas_history(
    canvas_view, tmp_path: Path
) -> None:
    scene = canvas_view.scene()
    item = _rectangle(10.0, 10.0, 40.0, 30.0, "#d94f4f")
    scene.addItem(item)
    item.setSelected(True)
    history = canvas_view.history()
    history._timer.stop()
    states_before = list(history._states)
    index_before = history._index
    page = canvas_view._page_item
    assert page is not None
    page_rect = page.mapRectToScene(page.rect())

    ExportRenderer(scene).export_png(
        tmp_path / "selection.png",
        ExportRequest(
            area=ExportArea.SELECTION,
            hidden_items=(page,),
            background=QtGui.QColor("white"),
        ),
    )

    assert item.isSelected()
    assert page.isVisible()
    assert list(history._states) == states_before
    assert history._index == index_before
    assert scene.selectedItems() == [item]
    assert page_rect.contains(item.sceneBoundingRect())
