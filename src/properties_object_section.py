# SPDX-License-Identifier: GPL-2.0-or-later

"""Object-property section builders used by the properties panel."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from connectors import ConnectorItem
from items import (
    BlockArrowItem,
    CurvyBracketItem,
    LineItem,
    RectItem,
    SplitRoundedRectItem,
    TextItem,
)
from style_presets import style_data


class ObjectSectionBuilder:
    """Build object controls using the host panel binding methods."""

    def _build_transform_and_size(
        self, item: QtWidgets.QGraphicsItem, object_data: dict[str, Any]
    ) -> None:
        self._group_transform.show()
        self._bind_double_spin(
            self._spin_pos_x,
            lambda: float(item.pos().x()),
            lambda value: self._set_item_pos(item, x=value),
        )
        self._bind_double_spin(
            self._spin_pos_y,
            lambda: float(item.pos().y()),
            lambda value: self._set_item_pos(item, y=value),
        )
        self._bind_double_spin(
            self._spin_rotation,
            lambda: float(item.rotation()),
            lambda value: self._set_item_rotation(item, value),
        )
        self._bind_double_spin(
            self._spin_scale,
            lambda: float(item.scale()),
            lambda value: self._set_item_scale(item, value),
        )
        self._bind_double_spin(
            self._spin_z_value,
            lambda: float(item.zValue()),
            lambda value: self._set_item_z(item, value),
        )

        size_value = object_data.get("size")
        if isinstance(size_value, (list, tuple)) and len(size_value) == 2:
            self._group_size.show()
            self._bind_double_spin(
                self._spin_width,
                lambda item=item: float(self._item_dimensions(item)[0]),
                lambda value: self._set_item_size(item, width=value),
            )
            self._bind_double_spin(
                self._spin_height,
                lambda item=item: float(self._item_dimensions(item)[1]),
                lambda value: self._set_item_size(item, height=value),
            )

    def _build_rounded_and_split(
        self, item: QtWidgets.QGraphicsItem, object_data: dict[str, Any]
    ) -> None:
        if isinstance(item, (RectItem, SplitRoundedRectItem)) or hasattr(item, "rx"):
            self._group_rounded.show()
            self._bind_double_spin(
                self._spin_radius_x,
                lambda: float(getattr(item, "rx", 0.0)),
                lambda value: self._set_corner_radius(item, "rx", value),
            )
            self._bind_double_spin(
                self._spin_radius_y,
                lambda: float(getattr(item, "ry", getattr(item, "rx", 0.0))),
                lambda value: self._set_corner_radius(item, "ry", value),
            )

        if isinstance(item, SplitRoundedRectItem):
            self._group_sections.show()
            self._bind_color_field(
                self._color_top_fill,
                lambda: item.topBrush().color(),
                lambda color: self._set_split_brush_color(item, "top", color),
            )
            self._bind_color_field(
                self._color_bottom_fill,
                lambda: item.bottomBrush().color(),
                lambda color: self._set_split_brush_color(item, "bottom", color),
            )
            self._bind_double_spin(
                self._spin_divider_ratio,
                lambda: float(item.divider_ratio()),
                lambda value: self._set_split_ratio(item, value),
            )

    def _build_stroke_fill_and_style(
        self, item: QtWidgets.QGraphicsItem, object_data: dict[str, Any]
    ) -> None:
        if hasattr(item, "pen") and not isinstance(item, TextItem):
            self._group_stroke.show()
            self._bind_color_field(
                self._color_stroke,
                lambda: item.pen().color(),
                lambda color: self._set_pen_color(item, color),
            )
            self._bind_double_spin(
                self._spin_stroke_width,
                lambda: float(item.pen().widthF()),
                lambda value: self._set_pen_width(item, value),
            )
            # Connector data stores only pen color and width, so a line style
            # set here would be lost on save.
            style_supported = not isinstance(item, ConnectorItem)
            self._combo_stroke_style.setEnabled(style_supported)
            if style_supported:
                self._bind_combobox(
                    self._combo_stroke_style,
                    lambda: self._pen_style_value(item),
                    lambda value: self._set_pen_style(item, value),
                )

        if hasattr(item, "brush") and not isinstance(item, LineItem):
            self._group_fill.show()
            self._bind_color_field(
                self._color_fill,
                lambda: item.brush().color(),
                lambda color: self._set_brush_color(item, color),
            )

        if hasattr(item, "setGraphicsEffect"):
            self._group_style_preset.show()
            data = style_data(item) or {}
            shadow = data.get("shadow") if isinstance(data.get("shadow"), dict) else {}
            with QtCore.QSignalBlocker(self._combo_style_preset):
                preset_id = data.get("preset_id")
                index = self._combo_style_preset.findData(preset_id)
                self._combo_style_preset.setCurrentIndex(max(0, index))
            with QtCore.QSignalBlocker(self._check_style_shadow):
                self._check_style_shadow.setChecked(bool(shadow))
            for spin, key in (
                (self._spin_shadow_x, "offset_x"),
                (self._spin_shadow_y, "offset_y"),
                (self._spin_shadow_blur, "blur_radius"),
            ):
                with QtCore.QSignalBlocker(spin):
                    spin.setValue(float(shadow.get(key, 0.0)))
            with QtCore.QSignalBlocker(self._color_shadow):
                self._color_shadow.setColor(str(shadow.get("color", "#66000000")))

    def _build_shape_specific_controls(
        self, item: QtWidgets.QGraphicsItem, object_data: dict[str, Any]
    ) -> None:
        if isinstance(item, BlockArrowItem):
            self._group_arrow_shape.show()
            self._bind_double_spin(
                self._spin_head_ratio,
                item.head_ratio,
                lambda value: self._set_block_arrow_ratio(item, "head", value),
            )
            self._bind_double_spin(
                self._spin_shaft_ratio,
                item.shaft_ratio,
                lambda value: self._set_block_arrow_ratio(item, "shaft", value),
            )

        if isinstance(item, CurvyBracketItem):
            self._group_bracket.show()
            self._bind_ratio_slider(
                self._slider_hook_depth,
                self._spin_hook_depth,
                item.hook_ratio,
                lambda value: self._set_bracket_hook_ratio(item, value),
            )

        if isinstance(item, LineItem):
            self._group_line_arrows.show()
            self._bind_checkbox(
                self._check_arrow_start,
                lambda: bool(item.arrow_start),
                lambda value: self._toggle_line_arrow(item, "start", value),
            )
            self._bind_checkbox(
                self._check_arrow_end,
                lambda: bool(item.arrow_end),
                lambda value: self._toggle_line_arrow(item, "end", value),
            )
            self._bind_double_spin(
                self._spin_arrow_length,
                item.arrow_head_length,
                lambda value: self._set_line_arrow_metric(item, "length", value),
            )
            self._bind_double_spin(
                self._spin_arrow_width,
                item.arrow_head_width,
                lambda value: self._set_line_arrow_metric(item, "width", value),
            )
