from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from export_renderer import (
    ExportArea,
    ExportRenderer,
    ExportRequest,
    ExportShadow,
    ShadowStyle,
    TextStrategy,
)
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


def test_shadow_uses_raster_shadow_with_vector_svg_content(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_rectangle(10.0, 10.0, 20.0, 20.0, "#d94f4f"))
    request = ExportRequest(
        area=ExportArea.CURRENT_PAGE,
        current_page=QtCore.QRectF(0.0, 0.0, 60.0, 60.0),
        shadow=ExportShadow(offset_x=4.0, offset_y=4.0, blur_radius=3.0),
    )

    svg = ExportRenderer(scene).export_svg(tmp_path / "shadow.svg", request)[0]
    png = ExportRenderer(scene).export_png(tmp_path / "shadow.png", request)[0]
    pdf = ExportRenderer(scene).export_pdf(tmp_path / "shadow.pdf", request)

    root = ElementTree.parse(svg).getroot()
    image_element = next(element for element in root if element.tag.endswith("image"))
    assert image_element.attrib["href"].startswith("data:image/png;base64,")
    assert not any(element.tag.endswith("filter") for element in root.iter())
    image = QtGui.QImage(str(png)).convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    assert image.pixelColor(34, 34).lightness() < 255
    assert b"/Image" in pdf.read_bytes()


@pytest.mark.parametrize("text_strategy", list(TextStrategy))
def test_soft_shadow_is_cropped_scaled_and_keeps_transparent_background(
    application: QtWidgets.QApplication, tmp_path: Path, text_strategy: TextStrategy
) -> None:
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_rectangle(20.0, 20.0, 10.0, 10.0, "#d94f4f"))
    scene.addText("Shadow")
    request = ExportRequest(
        area=ExportArea.CURRENT_PAGE,
        current_page=QtCore.QRectF(0.0, 0.0, 100.0, 80.0),
        background=None,
        scale=2.0,
        text_strategy=text_strategy,
        shadow=ExportShadow(offset_x=3.0, offset_y=4.0, blur_radius=2.0),
    )
    renderer = ExportRenderer(scene)

    svg = renderer.export_svg(tmp_path / f"crop-{text_strategy.value}.svg", request)[0]
    png = renderer.export_png(tmp_path / f"crop-{text_strategy.value}.png", request)[0]
    pdf = renderer.export_pdf(tmp_path / f"crop-{text_strategy.value}.pdf", request)

    root = ElementTree.parse(svg).getroot()
    shadow_image = next(element for element in root if element.tag.endswith("image"))
    assert float(shadow_image.attrib["width"]) < 100.0
    assert float(shadow_image.attrib["height"]) < 80.0
    assert float(shadow_image.attrib["x"]) > 0.0
    assert not any(element.attrib.get("id") == "export-background" for element in root)
    image = QtGui.QImage(str(png)).convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    assert image.size() == QtCore.QSize(200, 160)
    assert image.pixelColor(190, 150).alpha() == 0
    assert b"/Image" in pdf.read_bytes()


def test_hard_shadow_stays_vector_when_soft_shadow_exceeds_budget(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_rectangle(0.0, 0.0, 5_000.0, 4_000.0, "#d94f4f"))
    renderer = ExportRenderer(scene)
    request = ExportRequest(
        area=ExportArea.CURRENT_PAGE,
        current_page=QtCore.QRectF(0.0, 0.0, 5_000.0, 4_000.0),
        shadow=ExportShadow(blur_radius=0.0),
    )

    with pytest.raises(ValueError, match="16 megapixel"):
        renderer.export_svg(tmp_path / "soft-too-large.svg", request)

    hard_svg = renderer.export_svg(
        tmp_path / "hard.svg",
        ExportRequest(
            area=request.area,
            current_page=request.current_page,
            shadow=ExportShadow(style=ShadowStyle.HARD_VECTOR),
        ),
    )[0]
    contents = hard_svg.read_bytes()
    root = ElementTree.parse(hard_svg).getroot()
    assert b"data:image" not in contents
    assert any(
        element.attrib.get("transform", "").startswith("translate(")
        for element in root.iter()
    )


def test_hard_shadow_uses_the_vector_path_for_png_and_pdf(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_rectangle(10.0, 10.0, 20.0, 20.0, "#d94f4f"))
    request = ExportRequest(
        area=ExportArea.CURRENT_PAGE,
        current_page=QtCore.QRectF(0.0, 0.0, 60.0, 60.0),
        shadow=ExportShadow(
            offset_x=4.0,
            offset_y=4.0,
            style=ShadowStyle.HARD_VECTOR,
        ),
    )
    renderer = ExportRenderer(scene)

    png = renderer.export_png(tmp_path / "hard.png", request)[0]
    pdf = renderer.export_pdf(tmp_path / "hard.pdf", request)

    image = QtGui.QImage(str(png)).convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    shadow_pixel = image.pixelColor(32, 32)
    assert shadow_pixel.red() == shadow_pixel.green() == shadow_pixel.blue()
    assert 140 < shadow_pixel.red() < 170
    assert b"/Subtype /Image" not in pdf.read_bytes()


def test_page_budget_and_request_positional_arguments_are_preserved(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    reporter = lambda _requested, _resolved: None
    request = ExportRequest(
        ExportArea.CURRENT_PAGE,
        QtCore.QRectF(0.0, 0.0, 8_001.0, 8_000.0),
        (),
        (),
        QtGui.QColor("white"),
        1.0,
        TextStrategy.KEEP_TEXT,
        reporter,
    )
    assert request.font_fallback_reporter is reporter

    scene = QtWidgets.QGraphicsScene()
    scene.addItem(_rectangle(0.0, 0.0, 1.0, 1.0, "#d94f4f"))
    with pytest.raises(ValueError, match="64 megapixel"):
        ExportRenderer(scene).export_png(tmp_path / "too-large.png", request)
