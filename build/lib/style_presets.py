"""Versioned per-item visual styles and built-in presets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets


STYLE_VERSION = 1
KEY_STYLE = 1104

PRESETS: dict[str, dict[str, Any]] = {
    "default": {"label": "Default", "fill": "#ffffff", "stroke": "#000000"},
    "ocean": {"label": "Ocean", "gradient": ("#d7f0ff", "#2686c2"), "stroke": "#17658f"},
    "sunset": {"label": "Sunset", "gradient": ("#ffe2bf", "#e36c54"), "stroke": "#a64638"},
    "soft-shadow": {
        "label": "Soft shadow",
        "fill": "#ffffff",
        "stroke": "#4b5563",
        "shadow": {"offset_x": 3.0, "offset_y": 3.0, "blur_radius": 5.0, "color": "#66000000"},
    },
}


def preset_choices() -> tuple[tuple[str, str], ...]:
    return tuple((preset_id, str(data["label"])) for preset_id, data in PRESETS.items())


def style_data(item: QtWidgets.QGraphicsItem) -> dict[str, Any] | None:
    value = item.data(KEY_STYLE)
    return dict(value) if isinstance(value, Mapping) else None


def _color(value: object, fallback: str = "#00000000") -> QtGui.QColor:
    color = QtGui.QColor(str(value))
    return color if color.isValid() else QtGui.QColor(fallback)


def _shadow_effect(data: Mapping[str, Any] | None) -> QtWidgets.QGraphicsDropShadowEffect | None:
    if not data:
        return None
    effect = QtWidgets.QGraphicsDropShadowEffect()
    effect.setOffset(float(data.get("offset_x", 0.0)), float(data.get("offset_y", 0.0)))
    effect.setBlurRadius(max(0.0, float(data.get("blur_radius", 0.0))))
    effect.setColor(_color(data.get("color")))
    return effect


def apply_style_data(item: QtWidgets.QGraphicsItem, data: Mapping[str, Any] | None) -> None:
    """Restore metadata and the corresponding editor shadow without touching colors."""

    if not data:
        item.setData(KEY_STYLE, None)
        item.setGraphicsEffect(None)
        return
    restored = migrate_style_data(data)
    item.setData(KEY_STYLE, restored)
    shadow = restored.get("shadow")
    item.setGraphicsEffect(_shadow_effect(shadow if isinstance(shadow, Mapping) else None))


def migrate_style_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Accept old preset records and retain unknown IDs with their inline styling."""

    result = dict(data)
    version = result.get("version", 0)
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        version = 0
    result["version"] = STYLE_VERSION
    preset_id = result.get("preset_id")
    if isinstance(preset_id, str) and preset_id not in PRESETS:
        result["unresolved_preset"] = preset_id
        result.pop("preset_id", None)
    return result


def apply_preset(item: QtWidgets.QGraphicsItem, preset_id: str) -> bool:
    preset = PRESETS.get(preset_id)
    if preset is None:
        return False
    if hasattr(item, "brush") and hasattr(item, "setBrush"):
        if "gradient" in preset:
            start, end = preset["gradient"]
            gradient = QtGui.QLinearGradient(0.0, 0.0, 1.0, 1.0)
            gradient.setCoordinateMode(QtGui.QGradient.CoordinateMode.ObjectBoundingMode)
            gradient.setColorAt(0.0, _color(start))
            gradient.setColorAt(1.0, _color(end))
            item.setBrush(QtGui.QBrush(gradient))
        else:
            item.setBrush(QtGui.QBrush(_color(preset["fill"])))
    if hasattr(item, "pen") and hasattr(item, "setPen"):
        pen = QtGui.QPen(item.pen())
        pen.setColor(_color(preset["stroke"]))
        item.setPen(pen)
    apply_style_data(
        item,
        {
            "version": STYLE_VERSION,
            "preset_id": preset_id,
            "shadow": dict(preset.get("shadow", {})),
        },
    )
    item.update()
    return True
