from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from export_renderer import ExportArea, ExportRenderer, ExportRequest
from shape_registry import SHAPE_REGISTRY
from style_presets import apply_preset, style_data


def test_gradient_preset_and_shadow_survive_registry_roundtrip(application) -> None:
    item = SHAPE_REGISTRY.create("Rectangle", 10.0, 20.0)
    assert item is not None
    assert apply_preset(item, "soft-shadow")
    serialized = SHAPE_REGISTRY.serialize(item)
    assert serialized is not None
    assert serialized["item_style"]["preset_id"] == "soft-shadow"

    restored = SHAPE_REGISTRY.restore(serialized)
    assert restored is not None
    assert style_data(restored) == style_data(item)
    assert restored.graphicsEffect() is not None

    assert apply_preset(restored, "ocean")
    assert isinstance(restored.brush().gradient(), QtGui.QLinearGradient)
    serialized = SHAPE_REGISTRY.serialize(restored)
    assert serialized is not None
    restored_again = SHAPE_REGISTRY.restore(serialized)
    assert restored_again is not None
    assert isinstance(restored_again.brush().gradient(), QtGui.QLinearGradient)


def test_unknown_preset_is_preserved_as_unresolved_inline_style(application) -> None:
    item = SHAPE_REGISTRY.create("Rectangle", 0.0, 0.0)
    assert item is not None
    serialized = SHAPE_REGISTRY.serialize(item)
    assert serialized is not None
    serialized["item_style"] = {"version": 99, "preset_id": "future-preset"}

    restored = SHAPE_REGISTRY.restore(serialized)
    assert restored is not None
    assert style_data(restored) == {"version": 1, "unresolved_preset": "future-preset"}


def test_styled_item_exports_in_all_formats(application, tmp_path: Path) -> None:
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create("Rectangle", 10.0, 10.0)
    assert item is not None
    assert apply_preset(item, "soft-shadow")
    scene.addItem(item)
    request = ExportRequest(
        area=ExportArea.CURRENT_PAGE,
        current_page=QtCore.QRectF(0.0, 0.0, 200.0, 120.0),
    )
    renderer = ExportRenderer(scene)
    assert renderer.export_svg(tmp_path / "styled.svg", request)[0].exists()
    assert renderer.export_png(tmp_path / "styled.png", request)[0].exists()
    assert renderer.export_pdf(tmp_path / "styled.pdf", request).exists()
