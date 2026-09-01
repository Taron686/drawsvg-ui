"""A resizable graphics item backed by a validated embedded bitmap."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from asset_service import (
    DEFAULT_BITMAP_LIMITS,
    BitmapAssetError,
    BitmapAssetLimits,
    decode_bitmap_asset,
)
from constants import PEN_SELECTED
from document_format import ProjectAsset
from items.base import ResizableItem, _should_draw_selection

BITMAP_TYPE_ID = "Bitmap"


class BitmapItem(ResizableItem, QtWidgets.QGraphicsItem):
    """A scene item whose intrinsic size may differ from the decoded image."""

    def __init__(
        self,
        asset: ProjectAsset,
        x: float = 0.0,
        y: float = 0.0,
        width: float | None = None,
        height: float | None = None,
        *,
        limits: BitmapAssetLimits = DEFAULT_BITMAP_LIMITS,
    ) -> None:
        decoded = decode_bitmap_asset(asset, limits=limits)
        QtWidgets.QGraphicsItem.__init__(self)
        ResizableItem.__init__(self)
        self._limits = limits
        self._asset = asset
        self._asset_name = asset.name
        self._asset_sha256 = decoded.sha256
        self._asset_media_type = asset.media_type
        self._image = decoded.image.copy()
        self._size = _valid_size(
            decoded.image.width() if width is None else width,
            decoded.image.height() if height is None else height,
            limits,
        )
        self.setPos(float(x), float(y))
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setData(0, BITMAP_TYPE_ID)
        self.setTransformOriginPoint(self.boundingRect().center())

    @property
    def asset_name(self) -> str:
        return self._asset_name

    @property
    def asset_sha256(self) -> str:
        return self._asset_sha256

    @property
    def asset_media_type(self) -> str:
        return self._asset_media_type

    @property
    def asset(self) -> ProjectAsset:
        return self._asset

    def boundingRect(self) -> QtCore.QRectF:
        return QtCore.QRectF(0, 0, self._size.width(), self._size.height())

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        del option, widget
        painter.drawImage(self.boundingRect(), self._image)
        if _should_draw_selection(self):
            painter.save()
            painter.setPen(PEN_SELECTED)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.restore()

    def item_size(self) -> QtCore.QSizeF:
        return QtCore.QSizeF(self._size)

    def set_size(self, width: float, height: float, adjust_origin: bool = True) -> None:
        self.prepareGeometryChange()
        self._size = _valid_size(width, height, self._limits)
        if adjust_origin:
            self.setTransformOriginPoint(self.boundingRect().center())
        if self.isSelected():
            self.update_handles()
        self.update()

    def replace_asset(self, asset: ProjectAsset) -> None:
        decoded = decode_bitmap_asset(asset, limits=self._limits)
        self._asset_name, self._asset_sha256, self._asset_media_type, self._image = (
            asset.name,
            decoded.sha256,
            asset.media_type,
            decoded.image.copy(),
        )
        self._asset = asset
        self.update()


def serialize_bitmap_item(item: BitmapItem) -> dict[str, Any]:
    size = item.item_size()
    return {
        "type_id": BITMAP_TYPE_ID,
        "shape": BITMAP_TYPE_ID,
        "asset_name": item.asset_name,
        "asset_sha256": item.asset_sha256,
        "asset_media_type": item.asset_media_type,
        "size": [size.width(), size.height()],
    }


def restore_bitmap_item(
    data: Mapping[str, Any],
    assets: Iterable[ProjectAsset],
    *,
    limits: BitmapAssetLimits = DEFAULT_BITMAP_LIMITS,
) -> BitmapItem:
    if data.get("type_id") != BITMAP_TYPE_ID:
        raise BitmapAssetError("Bitmap payload has an invalid type ID")
    name, digest, media_type = (
        data.get("asset_name"),
        data.get("asset_sha256"),
        data.get("asset_media_type"),
    )
    if (
        not isinstance(name, str)
        or not isinstance(digest, str)
        or not isinstance(media_type, str)
    ):
        raise BitmapAssetError("Bitmap payload is missing its asset reference")
    asset = next(
        (
            candidate
            for candidate in assets
            if candidate.name.casefold() == name.casefold()
        ),
        None,
    )
    if (
        asset is None
        or asset.media_type != media_type
        or sha256(asset.data).hexdigest() != digest
    ):
        raise BitmapAssetError(
            "Bitmap payload asset reference does not match its asset"
        )
    size = data.get("size")
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        raise BitmapAssetError("Bitmap payload has an invalid size")
    return BitmapItem(asset, width=size[0], height=size[1], limits=limits)


def bitmap_assets_for_items(
    items: Iterable[QtWidgets.QGraphicsItem], assets: Iterable[ProjectAsset]
) -> tuple[ProjectAsset, ...]:
    available = {asset.name.casefold(): asset for asset in assets}
    result: list[ProjectAsset] = []
    seen: set[str] = set()
    pending = list(items)
    while pending:
        item = pending.pop()
        pending.extend(item.childItems())
        if isinstance(item, BitmapItem) and item.asset_name.casefold() not in seen:
            asset = available.get(item.asset_name.casefold())
            if asset is None or sha256(asset.data).hexdigest() != item.asset_sha256:
                raise BitmapAssetError(
                    "Bitmap item references a missing or changed asset"
                )
            result.append(asset)
            seen.add(item.asset_name.casefold())
    return tuple(result)


def _valid_size(width: Any, height: Any, limits: BitmapAssetLimits) -> QtCore.QSizeF:
    try:
        values = (float(width), float(height))
    except (TypeError, ValueError) as error:
        raise BitmapAssetError(
            "Bitmap dimensions must be finite positive numbers"
        ) from error
    if (
        any(not math.isfinite(value) or value <= 0 for value in values)
        or values[0] > limits.max_dimension
        or values[1] > limits.max_dimension
        or values[0] * values[1] > limits.max_pixels
    ):
        raise BitmapAssetError("Bitmap dimensions exceed the size limit")
    return QtCore.QSizeF(*values)
