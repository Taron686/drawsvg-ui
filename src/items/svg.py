"""Graphics item for a validated embedded SVG asset."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from .svg_assets import SvgAsset, SvgAssetError, SvgAssetParser


SVG_ITEM_TYPE_ID = "asset.svg"
SVG_ITEM_PAYLOAD_VERSION = 1


class SvgItem(QtWidgets.QGraphicsObject):
    """Render an immutable :class:`SvgAsset` in a resizable item rectangle."""

    _MIN_DIMENSION = 1.0

    def __init__(
        self,
        asset: SvgAsset,
        x: float = 0.0,
        y: float = 0.0,
        width: float | None = None,
        height: float | None = None,
        parent: QtWidgets.QGraphicsItem | None = None,
    ):
        super().__init__(parent)
        self._asset = asset
        self._renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(asset.data), self)
        if not self._renderer.isValid():
            raise SvgAssetError("Qt cannot render the validated SVG asset")

        default_size = self._renderer.defaultSize()
        natural_width = float(default_size.width()) if default_size.width() > 0 else 100.0
        natural_height = float(default_size.height()) if default_size.height() > 0 else 100.0
        self._size = QtCore.QSizeF(
            self._validated_dimension(width, natural_width),
            self._validated_dimension(height, natural_height),
        )
        self.setPos(float(x), float(y))
        self.setTransformOriginPoint(self.boundingRect().center())
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )

    @property
    def asset(self) -> SvgAsset:
        return self._asset

    @property
    def asset_id(self) -> str:
        return self._asset.asset_id

    def boundingRect(self) -> QtCore.QRectF:  # type: ignore[override]
        return QtCore.QRectF(0.0, 0.0, self._size.width(), self._size.height())

    def paint(self, painter, option, widget=None):  # type: ignore[override]
        self._renderer.render(painter, self.boundingRect())
        if self.isSelected():
            painter.save()
            pen = QtGui.QPen(QtGui.QColor("#14b5ff"), 1.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()

    def set_size(self, width: float, height: float) -> None:
        new_size = QtCore.QSizeF(
            self._validated_dimension(width), self._validated_dimension(height)
        )
        if new_size == self._size:
            return
        self.prepareGeometryChange()
        self._size = new_size
        self.setTransformOriginPoint(self.boundingRect().center())
        self.update()

    def to_item_payload(self) -> dict[str, Any]:
        """Serialize item state while keeping SVG bytes in the asset store."""

        return {
            "type_id": SVG_ITEM_TYPE_ID,
            "version": SVG_ITEM_PAYLOAD_VERSION,
            "asset_id": self.asset_id,
            "x": self.pos().x(),
            "y": self.pos().y(),
            "width": self._size.width(),
            "height": self._size.height(),
            "rotation": self.rotation(),
            "scale": self.scale(),
            "z_value": self.zValue(),
            "visible": self.isVisible(),
        }

    @classmethod
    def from_item_payload(
        cls, payload: Mapping[str, Any], assets: Mapping[str, SvgAsset]
    ) -> SvgItem:
        if payload.get("type_id") != SVG_ITEM_TYPE_ID:
            raise SvgAssetError("Unsupported SVG item type")
        if payload.get("version") != SVG_ITEM_PAYLOAD_VERSION:
            raise SvgAssetError("Unsupported SVG item version")
        asset_id = payload.get("asset_id")
        if not isinstance(asset_id, str) or asset_id not in assets:
            raise SvgAssetError("SVG item references a missing asset")

        item = cls(
            assets[asset_id],
            x=_number(payload, "x"),
            y=_number(payload, "y"),
            width=_positive_number(payload, "width"),
            height=_positive_number(payload, "height"),
        )
        item.setRotation(_number(payload, "rotation"))
        item.setScale(_positive_number(payload, "scale"))
        item.setZValue(_number(payload, "z_value"))
        visible = payload.get("visible")
        if not isinstance(visible, bool):
            raise SvgAssetError("SVG item visibility must be boolean")
        item.setVisible(visible)
        return item

    @classmethod
    def add_validated_to_scene(
        cls,
        scene: QtWidgets.QGraphicsScene,
        source: bytes | bytearray | memoryview | str,
        *,
        parser: SvgAssetParser | None = None,
        **item_options: Any,
    ) -> SvgItem:
        """Validate and construct fully before performing the scene mutation."""

        asset = (parser or SvgAssetParser()).parse(source)
        item = cls(asset, **item_options)
        scene.addItem(item)
        return item

    @classmethod
    def from_clipboard_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        parser: SvgAssetParser | None = None,
        **item_options: Any,
    ) -> SvgItem:
        asset = (parser or SvgAssetParser()).from_clipboard(payload)
        return cls(asset, **item_options)

    def _validated_dimension(self, value: float | None, fallback: float = 0.0) -> float:
        number = fallback if value is None else float(value)
        if not math.isfinite(number) or number < self._MIN_DIMENSION:
            raise SvgAssetError("SVG item dimensions must be finite and positive")
        return number


def _number(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SvgAssetError(f"SVG item {key} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise SvgAssetError(f"SVG item {key} must be finite")
    return number


def _positive_number(payload: Mapping[str, Any], key: str) -> float:
    value = _number(payload, key)
    if value <= 0.0:
        raise SvgAssetError(f"SVG item {key} must be positive")
    return value


__all__ = ["SVG_ITEM_PAYLOAD_VERSION", "SVG_ITEM_TYPE_ID", "SvgItem"]
