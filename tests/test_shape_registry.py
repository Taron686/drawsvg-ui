from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from constants import SHAPES
from export_drawsvg import export_drawsvg_py
from items import build_curvy_bracket_path
from palette import PaletteList, _build_shape_icon
from shape_registry import SHAPE_REGISTRY


def test_registry_has_one_stable_definition_for_each_existing_shape() -> None:
    definitions = SHAPE_REGISTRY.definitions()

    assert SHAPE_REGISTRY.type_ids() == SHAPES
    all_definitions = definitions + SHAPE_REGISTRY.extension_definitions()
    assert len({definition.type_id for definition in all_definitions}) == len(all_definitions)
    assert all(definition.python_export_adapter for definition in definitions)


def test_registry_creates_and_serializes_each_existing_shape(
    application: QtWidgets.QApplication,
) -> None:
    for definition in SHAPE_REGISTRY.definitions():
        item = SHAPE_REGISTRY.create(definition.type_id, 10.0, 20.0)

        assert item is not None
        assert item.data(0) == definition.type_id
        data = SHAPE_REGISTRY.serialize(item)
        assert data is not None
        assert data["type_id"] == definition.type_id
        assert data["shape"] == definition.palette_label


def test_registry_restores_by_type_id_with_legacy_shape_fallback(
    application: QtWidgets.QApplication,
) -> None:
    current = SHAPE_REGISTRY.restore(
        {"type_id": "Rectangle", "shape": "Unknown", "size": [40.0, 30.0]}
    )
    legacy = SHAPE_REGISTRY.restore({"shape": "Circle", "size": [25.0, 25.0]})

    assert current is not None
    assert current.data(0) == "Rectangle"
    assert legacy is not None
    assert legacy.data(0) == "Circle"


@pytest.mark.parametrize("type_id", ["Ellipse", "Circle"])
def test_registry_roundtrip_preserves_ellipse_labels(
    application: QtWidgets.QApplication,
    type_id: str,
) -> None:
    item = SHAPE_REGISTRY.create(type_id, 0.0, 0.0)

    assert item is not None
    item.set_label_text(f"{type_id} label")  # type: ignore[attr-defined]
    restored = SHAPE_REGISTRY.restore(SHAPE_REGISTRY.serialize(item) or {})

    assert restored is not None
    assert restored.label_item().toPlainText() == f"{type_id} label"  # type: ignore[attr-defined]


def test_registry_rejects_unknown_type_id() -> None:
    assert SHAPE_REGISTRY.create("Unknown", 0.0, 0.0) is None
    assert SHAPE_REGISTRY.restore({"type_id": "Unknown", "shape": "Rectangle"}) is None


def test_registry_factory_preserves_default_line_geometry(
    application: QtWidgets.QApplication,
) -> None:
    line = SHAPE_REGISTRY.create("Line", 5.0, 7.0)
    arrow = SHAPE_REGISTRY.create("Arrow", 5.0, 7.0)

    assert line is not None
    assert arrow is not None
    assert line.pos() == QtCore.QPointF(5.0, 7.0)
    assert arrow.pos() == QtCore.QPointF(5.0, 7.0)
    assert not line.arrow_end  # type: ignore[attr-defined]
    assert arrow.arrow_end  # type: ignore[attr-defined]


def test_curvy_bracket_has_long_stems_and_a_compact_center_notch() -> None:
    path = build_curvy_bracket_path(80.0, 160.0, 48.0)
    elements = [path.elementAt(index) for index in range(path.elementCount())]
    line_ends = [
        element
        for element in elements
        if element.type == QtGui.QPainterPath.ElementType.LineToElement
    ]

    assert elements[0].x > 60.0
    assert elements[-1].x > 60.0
    assert min(element.x for element in elements) < 16.0
    assert len(line_ends) == 2
    assert line_ends[0].y < 70.0
    assert line_ends[1].y > 90.0


def test_hook_depth_moves_the_center_notch_horizontally() -> None:
    shallow = build_curvy_bracket_path(80.0, 160.0, 160.0 * 0.08)
    deep = build_curvy_bracket_path(80.0, 160.0, 160.0 * 0.45)

    shallow_notch_x = shallow.elementAt(7).x
    deep_notch_x = deep.elementAt(7).x

    assert shallow_notch_x - deep_notch_x > 15.0


def test_curvy_bracket_uses_rounded_stroke_ends(
    application: QtWidgets.QApplication,
) -> None:
    item = SHAPE_REGISTRY.create("Curvy Right Bracket", 0.0, 0.0)

    assert item is not None
    assert item.pen().capStyle() == QtCore.Qt.PenCapStyle.RoundCap
    assert item.pen().joinStyle() == QtCore.Qt.PenJoinStyle.RoundJoin


def test_curvy_left_bracket_stays_rotated_through_registry_roundtrip(
    application: QtWidgets.QApplication,
) -> None:
    item = SHAPE_REGISTRY.create("Curvy Left Bracket", 0.0, 0.0)

    assert item is not None
    assert item.rotation() == pytest.approx(180.0)

    restored = SHAPE_REGISTRY.restore(SHAPE_REGISTRY.serialize(item) or {})

    assert restored is not None
    assert restored.data(0) == "Curvy Left Bracket"
    assert restored.rotation() == pytest.approx(180.0)


def test_curvy_bracket_palette_icons_show_both_orientations(
    application: QtWidgets.QApplication,
) -> None:
    size = QtCore.QSize(56, 56)
    right = _build_shape_icon("Curvy Right Bracket", size).toImage()
    left = _build_shape_icon("Curvy Left Bracket", size).toImage()
    rotated_right = right.flipped(
        QtCore.Qt.Orientation.Horizontal | QtCore.Qt.Orientation.Vertical
    )
    channel_differences = [
        abs(left_channel - right_channel)
        for left_channel, right_channel in zip(
            bytes(left.bits()), bytes(rotated_right.bits())
        )
    ]

    assert max(channel_differences) <= 2


def test_curvy_bracket_python_export_keeps_rounded_stroke(
    application: QtWidgets.QApplication,
    monkeypatch,
    tmp_path: Path,
) -> None:
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create("Curvy Right Bracket", 0.0, 0.0)
    assert item is not None
    scene.addItem(item)
    output = tmp_path / "curvy_bracket.py"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "Python (*.py)"),
    )

    export_drawsvg_py(scene)

    code = output.read_text(encoding="utf-8")
    assert "stroke_linecap='round'" in code
    assert "stroke_linejoin='round'" in code


def test_palette_uses_registry_order(application: QtWidgets.QApplication) -> None:
    palette = PaletteList()
    try:
        assert [
            palette.item(index).data(QtCore.Qt.ItemDataRole.UserRole)
            for index in range(palette.count())
        ] == [definition.type_id for definition in SHAPE_REGISTRY.palette_definitions()]
    finally:
        palette.close()


def test_new_palette_elements_have_distinct_shape_previews(
    application: QtWidgets.QApplication,
) -> None:
    preview_types = (
        "Hexagon",
        "Parallelogram",
        "Database",
        "Document",
        "Multiple Document",
        "Cloud",
        "Callout",
        "Table",
        "Swimlane",
        "Free Polyline",
        "Free Polygon",
        "Bezier Path",
    )
    size = QtCore.QSize(56, 56)

    def pixels(type_id: str) -> bytes:
        image = _build_shape_icon(type_id, size).toImage()
        return bytes(image.bits())

    fallback = pixels("Unknown Shape")
    previews = [pixels(type_id) for type_id in preview_types]

    assert all(preview != fallback for preview in previews)
    assert len(set(previews)) == len(preview_types)


def test_python_export_dispatches_all_registered_adapters(
    application: QtWidgets.QApplication,
    monkeypatch,
    tmp_path: Path,
) -> None:
    scene = QtWidgets.QGraphicsScene()
    for index, definition in enumerate(SHAPE_REGISTRY.definitions()):
        item = SHAPE_REGISTRY.create(definition.type_id, index * 250.0, index * 100.0)
        assert item is not None
        scene.addItem(item)

    output = tmp_path / "all_shapes.py"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "Python (*.py)"),
    )

    export_drawsvg_py(scene)

    code = output.read_text(encoding="utf-8")
    compile(code, str(output), "exec")
    assert "def build_drawing():" in code
