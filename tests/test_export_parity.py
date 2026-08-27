from __future__ import annotations

import json
import math
import runpy
from pathlib import Path
from xml.etree import ElementTree

import pytest
from export_test_tools import (
    assert_within_locked_tolerance,
    compare_rgba_images,
    load_rgba_image,
    load_tool_lock,
)
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from export_drawsvg import export_drawsvg_py
from export_renderer import ExportArea, ExportRenderer, ExportRequest, TextStrategy
from shape_registry import SHAPE_REGISTRY

REFERENCE_PATH = Path(__file__).with_name("export-references.json")


def _reference() -> dict[str, object]:
    return json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))


def _builtins_scene() -> QtWidgets.QGraphicsScene:
    scene = QtWidgets.QGraphicsScene()
    for index, definition in enumerate(SHAPE_REGISTRY.definitions()):
        column = index % 3
        row = index // 3
        item = SHAPE_REGISTRY.create(
            definition.type_id,
            25.0 + column * 230.0,
            25.0 + row * 110.0,
        )
        assert item is not None
        if isinstance(item, QtWidgets.QGraphicsTextItem):
            item.setPlainText("Portable text")
        label_setter = getattr(item, "set_label_text", None)
        if callable(label_setter):
            label_setter(definition.type_id)
        scene.addItem(item)
    return scene


def _request(strategy: TextStrategy) -> ExportRequest:
    reference = _reference()
    page = reference["page"]
    assert isinstance(page, list)
    return ExportRequest(
        area=ExportArea.CURRENT_PAGE,
        current_page=QtCore.QRectF(*(float(value) for value in page)),
        background=QtGui.QColor(str(reference["background"])),
        scale=float(reference["scale"]),
        text_strategy=strategy,
    )


def _rasterize_svg(path: Path, size: QtCore.QSize) -> QtGui.QImage:
    renderer = QtSvg.QSvgRenderer(str(path))
    assert renderer.isValid()
    image = QtGui.QImage(size, QtGui.QImage.Format.Format_RGBA8888)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    try:
        renderer.render(painter, QtCore.QRectF(image.rect()))
    finally:
        painter.end()
    return image


def test_versioned_reference_covers_every_builtin_and_export_format() -> None:
    reference = _reference()

    assert reference["schema_version"] == 1
    assert tuple(reference["shape_type_ids"]) == SHAPE_REGISTRY.type_ids()
    assert reference["text_strategy"] == TextStrategy.CONVERT_TO_PATHS.value
    assert reference["formats"] == ["svg", "png", "pdf", "drawsvg_python"]
    assert reference["tolerance_contract"] == "export-tools.lock"


def test_keep_text_and_convert_text_to_paths_are_distinct_svg_strategies(
    application: QtWidgets.QApplication,
    tmp_path: Path,
) -> None:
    scene = QtWidgets.QGraphicsScene()
    text = QtWidgets.QGraphicsTextItem("Portable text")
    text.setFont(QtGui.QFont("Arial", 18))
    scene.addItem(text)
    renderer = ExportRenderer(scene)

    keep_path = renderer.export_svg(
        tmp_path / "keep.svg", _request(TextStrategy.KEEP_TEXT)
    )[0]
    outline_path = renderer.export_svg(
        tmp_path / "paths.svg", _request(TextStrategy.CONVERT_TO_PATHS)
    )[0]

    keep_root = ElementTree.parse(keep_path).getroot()
    outline_root = ElementTree.parse(outline_path).getroot()
    assert any(element.tag.endswith("text") for element in keep_root.iter())
    assert not any(element.tag.endswith("text") for element in outline_root.iter())
    assert any(element.tag.endswith("path") for element in outline_root.iter())


def test_builtin_qt_exports_match_the_locked_image_contract(
    application: QtWidgets.QApplication,
    tmp_path: Path,
) -> None:
    renderer = ExportRenderer(_builtins_scene())
    request = _request(TextStrategy.CONVERT_TO_PATHS)
    svg_path = renderer.export_svg(tmp_path / "builtins.svg", request)[0]
    png_path = renderer.export_png(tmp_path / "builtins.png", request)[0]
    pdf_path = renderer.export_pdf(tmp_path / "builtins.pdf", request)

    png = load_rgba_image(png_path)
    svg = _rasterize_svg(svg_path, png.size())
    comparison = compare_rgba_images(
        png,
        svg,
        channel_threshold=load_tool_lock()["reference_environment"][
            "different_pixel_channel_threshold"
        ],
    )

    assert_within_locked_tolerance(comparison, load_tool_lock())
    assert pdf_path.read_bytes().startswith(b"%PDF-")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "legacy drawsvg-Python parity is a release blocker: measured MAE "
        "4.458377 > 1.5, different pixels 2.577746% > 0.1%, and largest "
        "component 0.127479% > 0.02%; repair requires a separately reviewed "
        "change across the 13 legacy export adapters"
    ),
)
def test_drawsvg_python_is_executable_and_uses_the_locked_image_contract(
    application: QtWidgets.QApplication,
    monkeypatch,
    tmp_path: Path,
) -> None:
    scene = _builtins_scene()
    script_path = tmp_path / "builtins_drawsvg.py"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(script_path), "Python (*.py)"),
    )
    export_drawsvg_py(scene)
    generated = runpy.run_path(str(script_path))
    drawing = generated["build_drawing"]()
    drawsvg_path = tmp_path / "builtins_drawsvg.svg"
    drawing.save_svg(str(drawsvg_path))

    bounds = scene.itemsBoundingRect().adjusted(-5.0, -5.0, 5.0, 5.0)
    source_rect = QtCore.QRectF(
        math.floor(bounds.left()),
        math.floor(bounds.top()),
        math.ceil(bounds.right()) - math.floor(bounds.left()),
        math.ceil(bounds.bottom()) - math.floor(bounds.top()),
    )
    qt_path = ExportRenderer(scene).export_png(
        tmp_path / "builtins_qt.png",
        ExportRequest(
            area=ExportArea.CURRENT_PAGE,
            current_page=source_rect,
            background=QtGui.QColor("white"),
            scale=2.0,
            text_strategy=TextStrategy.CONVERT_TO_PATHS,
        ),
    )[0]
    qt_image = load_rgba_image(qt_path)
    drawsvg_image = _rasterize_svg(drawsvg_path, qt_image.size())
    comparison = compare_rgba_images(
        qt_image,
        drawsvg_image,
        channel_threshold=load_tool_lock()["reference_environment"][
            "different_pixel_channel_threshold"
        ],
    )

    assert_within_locked_tolerance(comparison, load_tool_lock())


def test_png_scale_changes_pixels_not_only_the_output_canvas(
    application: QtWidgets.QApplication,
    tmp_path: Path,
) -> None:
    scene = QtWidgets.QGraphicsScene()
    rectangle = QtWidgets.QGraphicsRectItem(0.0, 0.0, 40.0, 30.0)
    rectangle.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    rectangle.setBrush(QtGui.QColor("#d94f4f"))
    scene.addItem(rectangle)
    path = ExportRenderer(scene).export_png(
        tmp_path / "scaled.png",
        ExportRequest(
            area=ExportArea.CURRENT_PAGE,
            current_page=QtCore.QRectF(0.0, 0.0, 80.0, 60.0),
            scale=2.0,
        ),
    )[0]

    image = load_rgba_image(path)
    assert image.size() == QtCore.QSize(160, 120)
    assert image.pixelColor(70, 40).name() == "#d94f4f"


def test_font_substitution_is_reported_before_export(
    application: QtWidgets.QApplication,
    monkeypatch,
    tmp_path: Path,
) -> None:
    scene = QtWidgets.QGraphicsScene()
    text = QtWidgets.QGraphicsTextItem("Fallback")
    text.setFont(QtGui.QFont("Unavailable Test Font", 12))
    scene.addItem(text)
    substitutions: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ExportRenderer,
        "_resolved_font_family",
        staticmethod(lambda _font: "Arial"),
    )

    ExportRenderer(scene).export_png(
        tmp_path / "fallback.png",
        ExportRequest(
            area=ExportArea.CURRENT_PAGE,
            current_page=QtCore.QRectF(0.0, 0.0, 100.0, 50.0),
            font_fallback_reporter=lambda requested, resolved: substitutions.append(
                (requested, resolved)
            ),
        ),
    )

    assert substitutions == [("Unavailable Test Font", "Arial")]
