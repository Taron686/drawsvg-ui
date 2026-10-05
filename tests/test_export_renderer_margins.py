from dataclasses import replace
from xml.etree import ElementTree

import pytest
from PySide6 import QtCore, QtGui, QtPdf, QtSvg, QtWidgets

from export_renderer import ExportArea, ExportRenderer, ExportRequest, ExportShadow, ShadowStyle, TextStrategy


def _margins(left=10, top=5, right=20, bottom=15):
    from export_margins import ExportMargins

    return ExportMargins(left, top, right, bottom)


def _rect(scene, x, y, width, height, color="red"):
    item = scene.addRect(
        x, y, width, height, QtGui.QPen(QtCore.Qt.PenStyle.NoPen), QtGui.QBrush(QtGui.QColor(color))
    )
    item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
    return item


def _render(renderer, path, request):
    if path.suffix == ".png":
        return QtGui.QImage(str(renderer.export_png(path, request)[0]))
    if path.suffix == ".pdf":
        document = QtPdf.QPdfDocument()
        assert document.load(str(renderer.export_pdf(path, request))) == QtPdf.QPdfDocument.Error.None_
        try:
            return document.render(0, document.pagePointSize(0).toSize())
        finally:
            document.close()
    svg_path = renderer.export_svg(path, request)[0]
    root = ElementTree.parse(svg_path).getroot()
    _, _, width, height = map(float, root.attrib["viewBox"].split())
    image = QtGui.QImage(int(width), int(height), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    try:
        QtSvg.QSvgRenderer(str(svg_path)).render(painter)
    finally:
        painter.end()
    return image


def test_output_rects_preserve_content_crop_and_expand_negative_origins(application):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, -20, -30, 100, 50)
    renderer = ExportRenderer(scene)
    request = ExportRequest(margins=_margins())
    assert renderer.output_rects(request) == (QtCore.QRectF(-30, -35, 130, 70),)
    assert renderer._source_rects(request) == (QtCore.QRectF(-20, -30, 100, 50),)


@pytest.mark.parametrize("extension", ["png", "svg", "pdf"])
@pytest.mark.parametrize("text_strategy", list(TextStrategy))
def test_asymmetric_margins_preserve_object_size_and_fill_background(
    application, tmp_path, extension, text_strategy
):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 40, 60, 100, 50)
    image = _render(ExportRenderer(scene), tmp_path / f"margins.{extension}", ExportRequest(
        margins=_margins(), text_strategy=text_strategy,
    ))
    assert image.size() == QtCore.QSize(130, 70)
    for point in [(0, 0), (9, 25), (110, 25), (50, 4), (50, 55), (129, 69)]:
        assert image.pixelColor(*point) == QtGui.QColor("white"), point
    for point in [(11, 6), (108, 53), (50, 25)]:
        assert image.pixelColor(*point) == QtGui.QColor("red"), point


def test_png_scales_margins_at_192_dpi_and_retains_transparency(application, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 0, 0, 100, 50)
    image = _render(ExportRenderer(scene), tmp_path / "double.png", ExportRequest(
        margins=_margins(), background=None, scale=2,
    ))
    assert image.size() == QtCore.QSize(260, 140)
    assert image.pixelColor(19, 30).alpha() == 0
    assert image.pixelColor(20, 10) == QtGui.QColor("red")
    assert image.pixelColor(219, 109) == QtGui.QColor("red")
    assert image.pixelColor(220, 30).alpha() == 0
    assert image.pixelColor(50, 110).alpha() == 0


@pytest.mark.parametrize("area", [ExportArea.CURRENT_PAGE, ExportArea.ALL_PAGES, ExportArea.SELECTION])
@pytest.mark.parametrize("extension", ["png", "svg", "pdf"])
def test_added_margins_never_reveal_neighboring_objects(application, tmp_path, area, extension):
    scene = QtWidgets.QGraphicsScene()
    item = _rect(scene, 0, 0, 100, 50)
    item.setSelected(True)
    _rect(scene, 103, 10, 15, 20, "blue")
    request = ExportRequest(
        area=area, current_page=QtCore.QRectF(0, 0, 100, 50),
        pages=(QtCore.QRectF(0, 0, 100, 50),), margins=_margins(),
    )
    image = _render(ExportRenderer(scene), tmp_path / f"neighbor.{extension}", request)
    assert image.size() == QtCore.QSize(130, 70)
    assert image.pixelColor(120, 25) == QtGui.QColor("white")
    assert item.isSelected()


@pytest.mark.parametrize("extension", ["png", "pdf"])
@pytest.mark.parametrize("text_strategy", list(TextStrategy))
def test_objects_crossing_page_boundary_are_clipped_before_margins(
    application, tmp_path, extension, text_strategy
):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 90, 10, 30, 20)
    image = _render(ExportRenderer(scene), tmp_path / f"crossing.{extension}", ExportRequest(
        area=ExportArea.CURRENT_PAGE, current_page=QtCore.QRectF(0, 0, 100, 50),
        margins=_margins(), text_strategy=text_strategy,
    ))
    assert image.pixelColor(105, 25) == QtGui.QColor("red")
    assert image.pixelColor(115, 25) == QtGui.QColor("white")


@pytest.mark.parametrize("extension", ["png", "svg", "pdf"])
def test_zero_margins_match_legacy_render_and_request_positionals(application, tmp_path, extension):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 30, 50, 100, 50)
    reporter = lambda requested, resolved: None
    shadow = ExportShadow(style=ShadowStyle.HARD_VECTOR)
    request = ExportRequest(ExportArea.CANVAS, None, (), (), None, 1, TextStrategy.KEEP_TEXT, reporter, shadow)
    assert request.margins is None
    renderer = ExportRenderer(scene)
    legacy = _render(renderer, tmp_path / f"legacy.{extension}", request)
    custom = _render(renderer, tmp_path / f"zero.{extension}", replace(request, margins=_margins(0, 0, 0, 0)))
    assert custom == legacy


def test_png_budget_includes_margins_before_allocating_image(application, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 0, 0, 1, 1)
    with pytest.raises(ValueError, match="64 megapixel"):
        ExportRenderer(scene).export_png(tmp_path / "huge.png", ExportRequest(
            margins=_margins(4000, 4000, 4000, 4000),
        ))


def test_all_page_dimensions_receive_same_margins(application, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 0, 0, 10, 10)
    request = ExportRequest(area=ExportArea.ALL_PAGES, pages=(
        QtCore.QRectF(0, 0, 100, 50), QtCore.QRectF(200, 0, 50, 100),
    ), margins=_margins())
    renderer = ExportRenderer(scene)
    assert renderer.output_rects(request) == (
        QtCore.QRectF(-10, -5, 130, 70), QtCore.QRectF(190, -5, 80, 120),
    )
    paths = renderer.export_png(tmp_path / "pages.png", request)
    assert [QtGui.QImage(str(path)).size() for path in paths] == [QtCore.QSize(130, 70), QtCore.QSize(80, 120)]
    document = QtPdf.QPdfDocument()
    assert document.load(str(renderer.export_pdf(tmp_path / "pages.pdf", request))) == QtPdf.QPdfDocument.Error.None_
    try:
        assert document.pageCount() == 2
        assert document.pagePointSize(1) == QtCore.QSizeF(80, 120)
    finally:
        document.close()


@pytest.mark.parametrize("shadow_style", list(ShadowStyle))
@pytest.mark.parametrize("extension", ["png", "svg", "pdf"])
def test_shadow_and_text_move_with_content_and_leave_margin_blank(
    application, tmp_path, extension, shadow_style
):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 20, 20, 20, 10)
    scene.addText("A").setPos(60, 10)
    renderer = ExportRenderer(scene)
    request = ExportRequest(
        area=ExportArea.CURRENT_PAGE, current_page=QtCore.QRectF(0, 0, 100, 50),
        margins=_margins(), shadow=ExportShadow(offset_x=4, offset_y=4, blur_radius=0, style=shadow_style),
        text_strategy=TextStrategy.CONVERT_TO_PATHS,
    )
    image = _render(renderer, tmp_path / f"shadow.{extension}", request)
    assert image.pixelColor(51, 37).lightness() < 230
    assert image.pixelColor(30, 25) == QtGui.QColor("red")
    assert image.pixelColor(5, 25) == QtGui.QColor("white")
    if extension == "svg":
        root = ElementTree.parse(tmp_path / "shadow.svg").getroot()
        assert not any(element.tag.endswith("text") for element in root.iter())


def test_svg_preserves_original_viewport_clip_inside_expanded_canvas(application, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 90, 10, 30, 20)
    path = ExportRenderer(scene).export_svg(tmp_path / "clipped.svg", ExportRequest(
        area=ExportArea.CURRENT_PAGE, current_page=QtCore.QRectF(0, 0, 100, 50),
        margins=_margins(), background=None,
    ))[0]
    root = ElementTree.parse(path).getroot()
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    # QSvgRenderer supports SVG Tiny, which omits clipPath. Check the standard
    # SVG viewport contract directly; the PNG/PDF clipping tests exercise Qt.
    clip = root.find(".//svg:clipPath", namespace)
    assert clip is not None
    rect = clip.find("svg:rect", namespace)
    assert rect is not None
    assert tuple(float(rect.attrib[key]) for key in ("x", "y", "width", "height")) == (0, 0, 100, 50)
    content = next(child for child in root if child.attrib.get("clip-path") == f"url(#{clip.attrib['id']})")
    assert content.attrib["transform"] == "translate(10 5)"
    assert not any(element.attrib.get("id") == "export-background" for element in root.iter())


def test_png_rounds_only_total_fractional_output_dimensions(application, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, -20.25, -30.5, 100.25, 50.5)
    request = ExportRequest(margins=_margins(0.1, 0.2, 0.3, 0.4), scale=1.5)
    image = _render(ExportRenderer(scene), tmp_path / "fractional.png", request)
    assert image.size() == QtCore.QSize(151, 77)


@pytest.mark.parametrize("extension", ["png", "svg", "pdf"])
def test_custom_margins_restore_selection_visibility_and_history(canvas_view, tmp_path, extension):
    scene = canvas_view.scene()
    item = _rect(scene, 10, 10, 100, 50)
    item.setSelected(True)
    history = canvas_view.history()
    history._timer.stop()
    states, index = list(history._states), history._index
    page = canvas_view._page_item
    assert page is not None
    position = item.pos()
    _render(ExportRenderer(scene), tmp_path / f"restore.{extension}", ExportRequest(
        area=ExportArea.SELECTION, hidden_items=(page,), margins=_margins(),
    ))
    assert item.isSelected()
    assert item.pos() == position
    assert page.isVisible()
    assert scene.selectedItems() == [item]
    assert list(history._states) == states
    assert history._index == index


def test_custom_margins_restore_scene_state_after_export_failure(application, tmp_path, monkeypatch):
    scene = QtWidgets.QGraphicsScene()
    selected = _rect(scene, 0, 0, 100, 50)
    hidden = _rect(scene, 200, 0, 50, 50)
    selected.setSelected(True)
    renderer = ExportRenderer(scene)

    def fail(*args, **kwargs):
        raise RuntimeError("paint failed")

    monkeypatch.setattr(renderer, "_paint", fail)
    with pytest.raises(RuntimeError, match="paint failed"):
        renderer.export_png(tmp_path / "fail.png", ExportRequest(
            hidden_items=(hidden,), margins=_margins(),
        ))
    assert selected.isSelected()
    assert hidden.isVisible()


@pytest.mark.parametrize("scale", [1, 1.5, 2])
@pytest.mark.parametrize("background", [None, QtGui.QColor("white"), QtGui.QColor(20, 40, 60, 128)])
def test_fractional_png_margin_does_not_stretch_artwork(application, tmp_path, scale, background):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 0, 0, 10, 10)
    image = _render(ExportRenderer(scene), tmp_path / "tiny-margin.png", ExportRequest(
        margins=_margins(0, 0, 0.01, 0), scale=scale, background=background,
    ))
    edge = int(10 * scale)
    assert image.size() == QtCore.QSize(edge + 1, edge)
    assert image.pixelColor(edge - 1, 5) == QtGui.QColor("red")
    expected = background if background is not None else QtGui.QColor(0, 0, 0, 0)
    assert image.pixelColor(edge, 5) == expected


@pytest.mark.parametrize("scale", [1, 2])
def test_fractional_svg_margin_keeps_exact_physical_size(application, tmp_path, scale):
    scene = QtWidgets.QGraphicsScene()
    _rect(scene, 0, 0, 10, 10)
    output = ExportRenderer(scene).export_svg(tmp_path / "tiny-margin.svg", ExportRequest(
        margins=_margins(0, 0, 0.01, 0), scale=scale,
    ))[0]
    root = ElementTree.parse(output).getroot()
    assert float(root.attrib["width"].removesuffix("mm")) == pytest.approx(10.01 * scale * 25.4 / 96, rel=1e-5)
    assert float(root.attrib["height"].removesuffix("mm")) == pytest.approx(10 * scale * 25.4 / 96, rel=1e-5)
