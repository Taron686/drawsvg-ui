"""Validated, content-addressed embedded bitmap assets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from PySide6 import QtCore, QtGui

from document_format import ProjectAsset

_FORMATS: dict[bytes, tuple[str, str]] = {
    b"png": ("image/png", ".png"),
    b"jpeg": ("image/jpeg", ".jpg"),
    b"jpg": ("image/jpeg", ".jpg"),
    b"webp": ("image/webp", ".webp"),
}


class BitmapAssetError(ValueError):
    """The proposed bitmap is malformed or exceeds a resource limit."""


@dataclass(frozen=True)
class BitmapAssetLimits:
    max_asset_bytes: int = 25 * 1024 * 1024
    max_total_asset_bytes: int = 100 * 1024 * 1024
    max_assets: int = 256
    max_dimension: int = 16_384
    max_pixels: int = 64 * 1024 * 1024


DEFAULT_BITMAP_LIMITS = BitmapAssetLimits()


@dataclass(frozen=True)
class DecodedBitmap:
    asset: ProjectAsset
    image: QtGui.QImage
    sha256: str


@dataclass(frozen=True)
class BitmapImport:
    asset: ProjectAsset
    image: QtGui.QImage
    added: bool


class BitmapAssetService:
    """Own validated project assets and import new images atomically."""

    def __init__(
        self,
        assets: Iterable[ProjectAsset] = (),
        *,
        limits: BitmapAssetLimits = DEFAULT_BITMAP_LIMITS,
    ) -> None:
        _validate_limits(limits)
        self._limits = limits
        self._assets: list[ProjectAsset] = []
        self._by_digest: dict[str, ProjectAsset] = {}
        self._by_name: dict[str, ProjectAsset] = {}
        self._total_bytes = 0
        for asset in assets:
            if asset.media_type in {
                media_type for media_type, _suffix in _FORMATS.values()
            }:
                self._add_existing(decode_bitmap_asset(asset, limits=limits))
            else:
                self._add_non_bitmap(asset)

    def assets(self) -> tuple[ProjectAsset, ...]:
        return tuple(self._assets)

    def import_file(
        self, path: str | Path, *, media_type: str | None = None
    ) -> BitmapImport:
        try:
            with Path(path).open("rb") as stream:
                data = stream.read(self._limits.max_asset_bytes + 1)
        except OSError as error:
            raise BitmapAssetError(f"Bitmap file could not be read: {error}") from error
        return self.import_bytes(data, media_type=media_type)

    def import_bytes(
        self, data: bytes, *, media_type: str | None = None
    ) -> BitmapImport:
        """Validate fully before mutating; duplicate content reuses its first asset."""
        decoded = decode_bitmap_bytes(data, media_type=media_type, limits=self._limits)
        existing = self._by_digest.get(decoded.sha256)
        if existing is not None:
            return BitmapImport(existing, decoded.image, False)
        if len(self._assets) >= self._limits.max_assets:
            raise BitmapAssetError("Project contains too many bitmap assets")
        if self._total_bytes + len(data) > self._limits.max_total_asset_bytes:
            raise BitmapAssetError("Bitmap assets exceed the total size limit")
        suffix = decoded.asset.name.rsplit(".", 1)[-1]
        name = f"bitmap-{decoded.sha256[:16]}.{suffix}"
        asset = ProjectAsset(name, data, decoded.asset.media_type)
        self._assets.append(asset)
        self._by_name[name.casefold()] = asset
        self._by_digest[decoded.sha256] = asset
        self._total_bytes += len(data)
        return BitmapImport(asset, decoded.image, True)

    def resolve(self, name: str) -> ProjectAsset:
        asset = self._by_name.get(name.casefold()) if isinstance(name, str) else None
        if asset is None:
            raise BitmapAssetError("Bitmap item references a missing asset")
        return asset

    def ensure(self, asset: ProjectAsset) -> ProjectAsset:
        """Validate and register a bitmap asset, returning its canonical value."""
        decoded = decode_bitmap_asset(asset, limits=self._limits)
        existing = self._by_digest.get(decoded.sha256)
        if existing is not None:
            return existing
        conflicting = self._by_name.get(asset.name.casefold())
        if conflicting is not None:
            raise BitmapAssetError("Project contains a conflicting bitmap asset name")
        self._add_existing(decoded)
        return asset

    def _add_existing(self, decoded: DecodedBitmap) -> None:
        asset = decoded.asset
        if len(self._assets) >= self._limits.max_assets:
            raise BitmapAssetError("Project contains too many bitmap assets")
        if asset.name.casefold() in self._by_name:
            raise BitmapAssetError("Project contains duplicate bitmap asset names")
        if self._total_bytes + len(asset.data) > self._limits.max_total_asset_bytes:
            raise BitmapAssetError("Bitmap assets exceed the total size limit")
        self._assets.append(asset)
        self._by_name[asset.name.casefold()] = asset
        self._by_digest.setdefault(decoded.sha256, asset)
        self._total_bytes += len(asset.data)

    def _add_non_bitmap(self, asset: ProjectAsset) -> None:
        """Keep unrelated project assets available for parallel asset features."""
        if (
            not isinstance(asset, ProjectAsset)
            or not asset.name
            or "/" in asset.name
            or "\\" in asset.name
            or not isinstance(asset.data, bytes)
            or len(asset.data) > self._limits.max_asset_bytes
            or not isinstance(asset.media_type, str)
            or not asset.media_type
        ):
            raise BitmapAssetError("Project asset is invalid")
        if len(self._assets) >= self._limits.max_assets:
            raise BitmapAssetError("Project contains too many bitmap assets")
        if asset.name.casefold() in self._by_name:
            raise BitmapAssetError("Project contains duplicate bitmap asset names")
        if self._total_bytes + len(asset.data) > self._limits.max_total_asset_bytes:
            raise BitmapAssetError("Bitmap assets exceed the total size limit")
        self._assets.append(asset)
        self._by_name[asset.name.casefold()] = asset
        self._total_bytes += len(asset.data)


def decode_bitmap_asset(
    asset: ProjectAsset, *, limits: BitmapAssetLimits = DEFAULT_BITMAP_LIMITS
) -> DecodedBitmap:
    if not isinstance(asset, ProjectAsset):
        raise BitmapAssetError("Bitmap assets must be ProjectAsset values")
    decoded = decode_bitmap_bytes(
        asset.data, media_type=asset.media_type, limits=limits
    )
    if not asset.name or "/" in asset.name or "\\" in asset.name:
        raise BitmapAssetError("Bitmap asset name is invalid")
    return DecodedBitmap(asset, decoded.image, decoded.sha256)


def decode_bitmap_bytes(
    data: bytes,
    *,
    media_type: str | None = None,
    limits: BitmapAssetLimits = DEFAULT_BITMAP_LIMITS,
) -> DecodedBitmap:
    _validate_limits(limits)
    if not isinstance(data, bytes) or not data:
        raise BitmapAssetError("Bitmap data must be non-empty bytes")
    if len(data) > limits.max_asset_bytes:
        raise BitmapAssetError("Bitmap data exceeds the size limit")
    encoded = QtCore.QByteArray(data)
    buffer = QtCore.QBuffer()
    buffer.setData(encoded)
    if not buffer.open(QtCore.QIODevice.OpenModeFlag.ReadOnly):
        raise BitmapAssetError("Bitmap data could not be opened")
    try:
        reader = QtGui.QImageReader(buffer)
        specification = _FORMATS.get(bytes(reader.format()).lower())
        if specification is None:
            raise BitmapAssetError(
                "Only PNG, JPEG, and WebP bitmap assets are supported"
            )
        detected_media_type, extension = specification
        if media_type is not None and media_type != detected_media_type:
            raise BitmapAssetError("Bitmap MIME type does not match its encoded data")
        size = reader.size()
        if (
            size.width() < 1
            or size.height() < 1
            or size.width() > limits.max_dimension
            or size.height() > limits.max_dimension
            or size.width() * size.height() > limits.max_pixels
        ):
            raise BitmapAssetError("Bitmap dimensions exceed the size limit")
        image = reader.read()
        if image.isNull() or image.size() != size:
            raise BitmapAssetError("Bitmap data cannot be decoded")
    finally:
        buffer.close()
    digest = sha256(data).hexdigest()
    return DecodedBitmap(
        ProjectAsset(f"bitmap-{digest[:16]}{extension}", data, detected_media_type),
        image,
        digest,
    )


def _validate_limits(limits: BitmapAssetLimits) -> None:
    values = (
        (
            limits.max_asset_bytes,
            limits.max_total_asset_bytes,
            limits.max_assets,
            limits.max_dimension,
            limits.max_pixels,
        )
        if isinstance(limits, BitmapAssetLimits)
        else ()
    )
    if not values or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in values
    ):
        raise BitmapAssetError("Bitmap limits must be positive integers")
