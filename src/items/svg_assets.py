"""Validation and transport helpers for embedded SVG assets.

The parser deliberately accepts only self-contained SVG.  It performs all
validation before callers create a graphics item or mutate a scene.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SVG_MEDIA_TYPE = "image/svg+xml"
SVG_CLIPBOARD_FORMAT = "application/x-drawsvg-svg-asset+json"
SVG_CLIPBOARD_VERSION = 1

_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_FORBIDDEN_DECLARATION_RE = re.compile(
    br"<!\s*(?:DOCTYPE|ENTITY)\b|<\?\s*xml-stylesheet\b", re.IGNORECASE
)
_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_DATA_IMAGE_RE = re.compile(
    r"data:image/(?:png|jpeg|webp);base64,[a-z0-9+/=\s]+\Z", re.IGNORECASE
)
_FORBIDDEN_ELEMENTS = {
    "audio",
    "embed",
    "foreignObject",
    "iframe",
    "object",
    "script",
    "video",
}


class SvgAssetError(ValueError):
    """Raised when an SVG asset violates the sandbox contract."""


@dataclass(frozen=True, slots=True)
class SvgLimits:
    """Resource limits applied before an SVG reaches Qt's renderer."""

    max_bytes: int = 2 * 1024 * 1024
    max_elements: int = 10_000
    max_depth: int = 64
    max_attributes_per_element: int = 128
    max_attribute_chars: int = 256_000
    max_use_expansions: int = 20_000
    max_use_chain: int = 32

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class SvgAsset:
    """A validated, immutable SVG payload identified by its SHA-256 digest."""

    data: bytes
    digest: str

    @property
    def asset_id(self) -> str:
        return f"sha256:{self.digest}"

    @property
    def media_type(self) -> str:
        return SVG_MEDIA_TYPE

    def storage_record(self) -> dict[str, Any]:
        """Return manifest metadata; binary data remains a separate asset entry."""

        return {
            "asset_id": self.asset_id,
            "media_type": self.media_type,
            "byte_length": len(self.data),
        }

    def clipboard_payload(self) -> dict[str, Any]:
        """Return a versioned, self-contained payload for clipboard transport."""

        return {
            "format": SVG_CLIPBOARD_FORMAT,
            "version": SVG_CLIPBOARD_VERSION,
            **self.storage_record(),
            "data": base64.b64encode(self.data).decode("ascii"),
        }


class SvgAssetParser:
    """Parse self-contained SVG with bounded structure and ``use`` expansion."""

    def __init__(self, limits: SvgLimits | None = None):
        self.limits = limits or SvgLimits()

    def parse(self, source: bytes | bytearray | memoryview | str) -> SvgAsset:
        data = self._coerce_source(source)
        if not data:
            raise SvgAssetError("SVG asset is empty")
        if len(data) > self.limits.max_bytes:
            raise SvgAssetError("SVG asset exceeds the byte limit")
        if b"\x00" in data:
            raise SvgAssetError("SVG asset contains a NUL byte")
        if _FORBIDDEN_DECLARATION_RE.search(data):
            raise SvgAssetError("DTD, entity, and external stylesheet declarations are forbidden")

        root = self._parse_bounded_tree(data)
        if _split_name(root.tag) != (_SVG_NAMESPACE, "svg") and _split_name(root.tag) != (
            "",
            "svg",
        ):
            raise SvgAssetError("Root element must be svg")

        id_map, uses, local_urls = self._validate_elements(root)
        for reference in local_urls:
            if reference not in id_map:
                raise SvgAssetError(f"Reference targets unknown id: {reference}")
        self._validate_use_expansion(uses, id_map)

        digest = hashlib.sha256(data).hexdigest()
        return SvgAsset(data=data, digest=digest)

    def parse_file(self, path: str | Path) -> SvgAsset:
        asset_path = Path(path)
        try:
            size = asset_path.stat().st_size
        except OSError as exc:
            raise SvgAssetError(f"Cannot read SVG asset: {exc}") from exc
        if size > self.limits.max_bytes:
            raise SvgAssetError("SVG asset exceeds the byte limit")
        try:
            return self.parse(asset_path.read_bytes())
        except OSError as exc:
            raise SvgAssetError(f"Cannot read SVG asset: {exc}") from exc

    def restore(
        self, record: Mapping[str, Any], data: bytes | bytearray | memoryview
    ) -> SvgAsset:
        """Validate a project asset entry and its manifest metadata."""

        asset = self.parse(data)
        _validate_metadata(record, asset)
        return asset

    def from_clipboard(self, payload: Mapping[str, Any]) -> SvgAsset:
        """Decode and revalidate a versioned clipboard payload."""

        if payload.get("format") != SVG_CLIPBOARD_FORMAT:
            raise SvgAssetError("Unsupported SVG clipboard format")
        if payload.get("version") != SVG_CLIPBOARD_VERSION:
            raise SvgAssetError("Unsupported SVG clipboard version")
        encoded = payload.get("data")
        if not isinstance(encoded, str):
            raise SvgAssetError("SVG clipboard data is missing")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SvgAssetError("SVG clipboard data is not valid base64") from exc
        asset = self.parse(data)
        _validate_metadata(payload, asset)
        return asset

    def _coerce_source(
        self, source: bytes | bytearray | memoryview | str
    ) -> bytes:
        if isinstance(source, str):
            return source.encode("utf-8")
        if isinstance(source, (bytes, bytearray, memoryview)):
            return bytes(source)
        raise TypeError("SVG source must be bytes or text")

    def _parse_bounded_tree(self, data: bytes) -> ET.Element:
        parser = ET.XMLPullParser(events=("start", "end"))
        depth = 0
        elements = 0
        root: ET.Element | None = None
        try:
            parser.feed(data)
            for event, element in parser.read_events():
                if event == "start":
                    if root is None:
                        root = element
                    depth += 1
                    elements += 1
                    if depth > self.limits.max_depth:
                        raise SvgAssetError("SVG nesting depth exceeds the limit")
                    if elements > self.limits.max_elements:
                        raise SvgAssetError("SVG element count exceeds the limit")
                else:
                    depth -= 1
            parser.close()
        except ET.ParseError as exc:
            raise SvgAssetError(f"Malformed SVG XML: {exc}") from exc
        if root is None:
            raise SvgAssetError("SVG asset has no root element")
        return root

    def _validate_elements(
        self, root: ET.Element
    ) -> tuple[dict[str, ET.Element], list[ET.Element], set[str]]:
        id_map: dict[str, ET.Element] = {}
        uses: list[ET.Element] = []
        local_urls: set[str] = set()

        for element in root.iter():
            namespace, local_name = _split_name(element.tag)
            if namespace not in ("", _SVG_NAMESPACE):
                raise SvgAssetError(f"Foreign element namespace is forbidden: {namespace}")
            if local_name in _FORBIDDEN_ELEMENTS:
                raise SvgAssetError(f"Forbidden SVG element: {local_name}")
            if len(element.attrib) > self.limits.max_attributes_per_element:
                raise SvgAssetError("SVG element has too many attributes")

            element_id = element.attrib.get("id")
            if element_id:
                if element_id in id_map:
                    raise SvgAssetError(f"Duplicate SVG id: {element_id}")
                id_map[element_id] = element

            for raw_name, value in element.attrib.items():
                attr_namespace, attr_name = _split_name(raw_name)
                if attr_namespace not in ("", _XLINK_NAMESPACE, _XML_NAMESPACE):
                    raise SvgAssetError(
                        f"Foreign attribute namespace is forbidden: {attr_namespace}"
                    )
                if attr_namespace == _XML_NAMESPACE and attr_name == "base":
                    raise SvgAssetError("xml:base is forbidden in embedded SVG")
                if len(value) > self.limits.max_attribute_chars:
                    raise SvgAssetError("SVG attribute exceeds the character limit")
                if attr_name.lower().startswith("on"):
                    raise SvgAssetError("SVG event handler attributes are forbidden")
                if attr_name in ("href", "src"):
                    self._validate_href(local_name, value)
                local_urls.update(_local_url_references(value))
                if _has_external_url(value):
                    raise SvgAssetError("External URL references are forbidden")

            if local_name == "style":
                css = element.text or ""
                if re.search(r"@import\b", css, re.IGNORECASE):
                    raise SvgAssetError("CSS imports are forbidden")
                local_urls.update(_local_url_references(css))
                if _has_external_url(css):
                    raise SvgAssetError("External CSS URL references are forbidden")
            if local_name == "use":
                uses.append(element)

        return id_map, uses, local_urls

    def _validate_href(self, element_name: str, value: str) -> None:
        value = value.strip()
        if element_name == "use" and value.startswith("#") and len(value) > 1:
            return
        if element_name == "image" and _DATA_IMAGE_RE.fullmatch(value):
            return
        raise SvgAssetError("Only local use references and embedded raster images are allowed")

    def _validate_use_expansion(
        self, uses: list[ET.Element], id_map: Mapping[str, ET.Element]
    ) -> None:
        expansion_count = 0

        def count_expansion(element: ET.Element, stack: tuple[str, ...]) -> None:
            nonlocal expansion_count
            expansion_count += 1
            if expansion_count > self.limits.max_use_expansions:
                raise SvgAssetError("use expansion exceeds the limit")
            if _local_name(element.tag) == "use":
                target_id = _href_value(element).removeprefix("#")
                if not target_id or target_id not in id_map:
                    raise SvgAssetError(f"use targets unknown id: {target_id}")
                if target_id in stack:
                    raise SvgAssetError("Cyclic use reference is forbidden")
                if len(stack) >= self.limits.max_use_chain:
                    raise SvgAssetError("use reference chain exceeds the limit")
                count_expansion(id_map[target_id], (*stack, target_id))
            for child in element:
                count_expansion(child, stack)

        for use in uses:
            target_id = _href_value(use).removeprefix("#")
            if not target_id or target_id not in id_map:
                raise SvgAssetError(f"use targets unknown id: {target_id}")
            count_expansion(id_map[target_id], (target_id,))


def _validate_metadata(record: Mapping[str, Any], asset: SvgAsset) -> None:
    if record.get("asset_id") != asset.asset_id:
        raise SvgAssetError("SVG asset digest does not match its metadata")
    if record.get("media_type") != SVG_MEDIA_TYPE:
        raise SvgAssetError("SVG asset media type is invalid")
    byte_length = record.get("byte_length")
    if isinstance(byte_length, bool) or not isinstance(byte_length, int):
        raise SvgAssetError("SVG asset byte length is invalid")
    if byte_length != len(asset.data):
        raise SvgAssetError("SVG asset byte length does not match its metadata")


def _split_name(name: str) -> tuple[str, str]:
    if name.startswith("{") and "}" in name:
        namespace, local_name = name[1:].split("}", 1)
        return namespace, local_name
    return "", name


def _local_name(name: str) -> str:
    return _split_name(name)[1]


def _href_value(element: ET.Element) -> str:
    return (
        element.attrib.get("href")
        or element.attrib.get(f"{{{_XLINK_NAMESPACE}}}href")
        or ""
    ).strip()


def _local_url_references(value: str) -> set[str]:
    references: set[str] = set()
    for match in _URL_RE.finditer(value):
        reference = match.group(2).strip()
        if reference.startswith("#") and len(reference) > 1:
            references.add(reference[1:])
    return references


def _has_external_url(value: str) -> bool:
    for match in _URL_RE.finditer(value):
        reference = match.group(2).strip()
        if not reference.startswith("#"):
            return True
    return False


__all__ = [
    "SVG_CLIPBOARD_FORMAT",
    "SVG_CLIPBOARD_VERSION",
    "SVG_MEDIA_TYPE",
    "SvgAsset",
    "SvgAssetError",
    "SvgAssetParser",
    "SvgLimits",
]
