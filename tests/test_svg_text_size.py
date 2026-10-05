from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from export_renderer import ExportArea, ExportRenderer, ExportRequest, TextStrategy
from items import TextItem


@pytest.fixture(scope="module", autouse=True)
def text_font(application):
    # The Windows offscreen plugin needs an explicit font for real glyph metrics.
    path = Path("C:/Windows/Fonts/arial.ttf")
    font_id = QtGui.QFontDatabase.addApplicationFont(str(path)) if path.exists() else -1
    if path.exists():
        assert font_id >= 0
    yield
    if font_id >= 0:
        QtGui.QFontDatabase.removeApplicationFont(font_id)


def _ink_bounds(image: QtGui.QImage) -> QtCore.QRect:
    pixels = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).red() < 128
    ]
    assert pixels, "The comparison must contain visible glyphs"
    xs, ys = zip(*pixels)
    return QtCore.QRect(
        QtCore.QPoint(min(xs), min(ys)), QtCore.QPoint(max(xs), max(ys))
    )


@pytest.mark.parametrize("font_unit", ["pt", "px"])
@pytest.mark.parametrize("strategy", list(TextStrategy))
@pytest.mark.parametrize("scale", [1, 2])
def test_svg_text_size_matches_editor(application, tmp_path, font_unit, strategy, scale):
    scene = QtWidgets.QGraphicsScene()
    item = TextItem(10, 10, 200, 50)
    item.setPlainText("Service Not Seen")
    font = QtGui.QFont("Arial")
    if font_unit == "pt":
        font.setPointSizeF(9)
    else:
        font.setPixelSize(12)
    item.setFont(font)
    scene.addItem(item)
    source = QtCore.QRectF(0, 0, 220, 60)
    size = QtCore.QSize(220 * scale, 60 * scale)
    target = QtCore.QRectF(0, 0, size.width(), size.height())

    reference = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32)
    reference.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(reference)
    scene.render(painter, target, source)
    painter.end()

    path = ExportRenderer(scene).export_svg(
        tmp_path / "text.svg",
        ExportRequest(
            area=ExportArea.CURRENT_PAGE,
            current_page=source,
            scale=scale,
            text_strategy=strategy,
        ),
    )[0]
    renderer = QtSvg.QSvgRenderer(str(path))
    assert renderer.isValid()
    exported = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32)
    exported.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(exported)
    renderer.render(painter, target)
    painter.end()

    expected, actual = _ink_bounds(reference), _ink_bounds(exported)
    assert expected.width() > 50 * scale
    # Glyph outlines and hinted raster text can differ by a few edge pixels.
    assert abs(actual.width() - expected.width()) <= 2 * scale, (expected, actual)
    assert abs(actual.height() - expected.height()) <= scale, (expected, actual)
    assert abs(actual.top() - expected.top()) <= scale, (expected, actual)


@pytest.mark.parametrize("layout_dpi", [96, 144])
@pytest.mark.parametrize("strategy", list(TextStrategy))
@pytest.mark.parametrize("scale", [1, 2])
def test_svg_page_size_is_independent_of_font_dpi(
    application, tmp_path, monkeypatch, layout_dpi, strategy, scale
):
    # Windows ignores QT_FONT_DPI. Use real Qt metrics from a controlled device.
    device = QtGui.QImage(96, 96, QtGui.QImage.Format.Format_ARGB32)
    device.setDotsPerMeterX(round(layout_dpi / 0.0254))
    device.setDotsPerMeterY(round(layout_dpi / 0.0254))
    metrics = QtGui.QFontMetricsF
    monkeypatch.setattr(QtGui, "QFontMetricsF", lambda font: metrics(font, device))

    scene = QtWidgets.QGraphicsScene()
    scene.addRect(0, 0, 96, 96)
    path = ExportRenderer(scene).export_svg(
        tmp_path / "page.svg",
        ExportRequest(
            area=ExportArea.CURRENT_PAGE,
            current_page=QtCore.QRectF(0, 0, 96, 96),
            scale=scale,
            text_strategy=strategy,
        ),
    )[0]
    root = ElementTree.parse(path).getroot()
    # A 96-unit page is one inch regardless of the font's device DPI.
    for dimension in ("width", "height"):
        value = root.attrib[dimension]
        assert value.endswith("mm")
        assert float(value[:-2]) == pytest.approx(25.4 * scale, abs=0.001)
