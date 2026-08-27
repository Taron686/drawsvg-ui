"""Validated, versioned clipboard payloads for scene items.

The service is deliberately independent from Qt and the canvas.  A caller may
publish the encoded bytes under :data:`CLIPBOARD_MIME_TYPE` and only add the
returned items/assets to a document after :meth:`ClipboardService.prepare_paste`
has completed successfully.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from document_format import ProjectAsset

CLIPBOARD_MIME_TYPE = "application/vnd.drawsvg-ui.items+json;version=1"
CLIPBOARD_FORMAT = "drawsvg-ui-clipboard"
CLIPBOARD_VERSION = 1

_TOP_LEVEL_KEYS = {
    "format",
    "version",
    "source_document_id",
    "items",
    "assets",
}
_ASSET_KEYS = {"name", "media_type", "size", "sha256", "data"}
_REFERENCE_KEYS = {
    "attached_to_id",
    "end_item_id",
    "owner_id",
    "parent_id",
    "source_id",
    "source_item_id",
    "start_item_id",
    "target_id",
    "target_item_id",
}
_REFERENCE_LIST_KEYS = {"item_ids", "linked_item_ids", "member_ids"}
_ASSET_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MEDIA_TYPE_RE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\Z"
)
_ROLE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ClipboardValidationError(ValueError):
    """Raised when clipboard content is malformed or exceeds safe limits."""


@dataclass(frozen=True)
class ClipboardLimits:
    """Resource limits applied before a payload can reach the scene."""

    max_payload_bytes: int = 40 * 1024 * 1024
    max_items: int = 10_000
    max_assets: int = 256
    max_asset_bytes: int = 25 * 1024 * 1024
    max_total_asset_bytes: int = 32 * 1024 * 1024
    max_json_depth: int = 64
    max_json_nodes: int = 250_000


DEFAULT_LIMITS = ClipboardLimits()


@dataclass(frozen=True)
class ClipboardPaste:
    """A fully validated paste operation that is safe to publish atomically."""

    items: tuple[dict[str, Any], ...]
    assets_to_add: tuple[ProjectAsset, ...]
    item_id_map: Mapping[str, str]
    asset_name_map: Mapping[str, str]
    source_document_id: str | None


class ClipboardService:
    """Encode selections and prepare collision-free paste operations."""

    @staticmethod
    def encode(
        items: Iterable[Mapping[str, Any]],
        *,
        assets: Iterable[ProjectAsset] = (),
        source_document_id: str | None = None,
        limits: ClipboardLimits = DEFAULT_LIMITS,
    ) -> bytes:
        """Return deterministic JSON bytes suitable for the custom MIME type."""

        copied_items = [deepcopy(dict(item)) for item in items]
        copied_assets = tuple(assets)
        payload = {
            "format": CLIPBOARD_FORMAT,
            "version": CLIPBOARD_VERSION,
            "source_document_id": source_document_id,
            "items": copied_items,
            "assets": [_encode_asset(asset, limits) for asset in copied_assets],
        }
        _validate_payload(payload, limits)
        try:
            encoded = json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as error:
            raise ClipboardValidationError(
                "Clipboard content is not valid JSON"
            ) from error
        if len(encoded) > limits.max_payload_bytes:
            raise ClipboardValidationError("Clipboard payload exceeds the size limit")
        return encoded

    @staticmethod
    def prepare_paste(
        raw: bytes | bytearray | memoryview,
        *,
        existing_item_ids: Iterable[str] = (),
        existing_assets: Iterable[ProjectAsset] = (),
        id_factory: Callable[[], object] = uuid4,
        limits: ClipboardLimits = DEFAULT_LIMITS,
    ) -> ClipboardPaste:
        """Validate *raw*, remap IDs/references and deduplicate its assets.

        References to copied items are redirected to their new IDs.  References
        to objects outside the copied selection are detached as ``None`` so a
        paste cannot accidentally bind to an unrelated destination object.
        """

        payload, source_assets = _decode_payload(raw, limits)
        items = deepcopy(payload["items"])
        old_ids = _scene_item_ids(items)
        used_ids = {
            _normalize_uuid(value, "existing item ID") for value in existing_item_ids
        }
        used_ids.update(old_ids)

        id_map: dict[str, str] = {}
        for old_id in old_ids:
            new_id = _new_unique_id(id_factory, used_ids)
            id_map[old_id] = new_id
            used_ids.add(new_id)

        assets_to_add, asset_map = _deduplicate_assets(
            source_assets,
            tuple(existing_assets),
            limits,
        )
        for item in _iter_scene_items(items):
            old_id = _normalize_uuid(item["id"], "item ID")
            item["id"] = id_map[old_id]

        for item in items:
            _rewrite_embedded_references(item, id_map, asset_map)

        return ClipboardPaste(
            items=tuple(items),
            assets_to_add=assets_to_add,
            item_id_map=id_map,
            asset_name_map=asset_map,
            source_document_id=payload["source_document_id"],
        )


def _encode_asset(asset: ProjectAsset, limits: ClipboardLimits) -> dict[str, Any]:
    name, data, media_type = _validate_project_asset(asset, limits)
    return {
        "name": name,
        "media_type": media_type,
        "size": len(data),
        "sha256": sha256(data).hexdigest(),
        "data": base64.b64encode(data).decode("ascii"),
    }


def _decode_payload(
    raw: bytes | bytearray | memoryview,
    limits: ClipboardLimits,
) -> tuple[dict[str, Any], tuple[ProjectAsset, ...]]:
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ClipboardValidationError("Clipboard payload must be bytes")
    encoded = bytes(raw)
    if len(encoded) > limits.max_payload_bytes:
        raise ClipboardValidationError("Clipboard payload exceeds the size limit")
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_float=_finite_float,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"Invalid JSON number: {value}")
            ),
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as error:
        if isinstance(error, ClipboardValidationError):
            raise
        raise ClipboardValidationError(
            "Clipboard payload is not valid UTF-8 JSON"
        ) from error

    _validate_payload(payload, limits)
    assets = tuple(_decode_asset(value, limits) for value in payload["assets"])
    return payload, assets


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClipboardValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number is not finite")
    return parsed


def _validate_payload(payload: Any, limits: ClipboardLimits) -> None:
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise ClipboardValidationError(
            "Clipboard payload has an invalid top-level shape"
        )
    if payload["format"] != CLIPBOARD_FORMAT:
        raise ClipboardValidationError("Not a DrawSVG clipboard payload")
    version = payload["version"]
    if version != CLIPBOARD_VERSION or isinstance(version, bool):
        raise ClipboardValidationError("Unsupported clipboard payload version")

    source_document_id = payload["source_document_id"]
    if source_document_id is not None:
        payload["source_document_id"] = _normalize_uuid(
            source_document_id,
            "source document ID",
        )

    _validate_json_tree(payload, limits)
    assets = payload["assets"]
    if not isinstance(assets, list) or len(assets) > limits.max_assets:
        raise ClipboardValidationError("Clipboard asset manifest is invalid")

    asset_names: set[str] = set()
    total_asset_bytes = 0
    for descriptor in assets:
        data = _decode_asset_data(descriptor, limits)
        folded_name = descriptor["name"].casefold()
        if folded_name in asset_names:
            raise ClipboardValidationError("Clipboard contains duplicate asset names")
        asset_names.add(folded_name)
        total_asset_bytes += len(data)
        if total_asset_bytes > limits.max_total_asset_bytes:
            raise ClipboardValidationError(
                "Clipboard assets exceed the total size limit"
            )

    items = payload["items"]
    if not isinstance(items, list):
        raise ClipboardValidationError("Clipboard items must be a list")
    _validate_scene_items(items, asset_names, limits)


def _validate_json_tree(value: Any, limits: ClipboardLimits) -> None:
    nodes = 0
    pending = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > limits.max_json_nodes:
            raise ClipboardValidationError("Clipboard JSON contains too many values")
        if depth > limits.max_json_depth:
            raise ClipboardValidationError("Clipboard JSON is nested too deeply")
        if isinstance(current, dict):
            if not all(isinstance(key, str) for key in current):
                raise ClipboardValidationError("Clipboard object keys must be strings")
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)
        elif isinstance(current, float) and not math.isfinite(current):
            raise ClipboardValidationError("Clipboard numbers must be finite")
        elif not isinstance(current, (str, int, float, bool, type(None))):
            raise ClipboardValidationError("Clipboard contains a non-JSON value")


def _validate_scene_items(
    items: list[Any],
    asset_names: set[str],
    limits: ClipboardLimits,
) -> None:
    seen_ids: set[str] = set()
    count = 0
    pending = list(items)
    while pending:
        item = pending.pop()
        if not isinstance(item, dict):
            raise ClipboardValidationError("Clipboard contains an invalid item")
        count += 1
        if count > limits.max_items:
            raise ClipboardValidationError("Clipboard contains too many items")

        item_id = _normalize_uuid(item.get("id"), "item ID")
        if item_id in seen_ids:
            raise ClipboardValidationError("Clipboard contains duplicate item IDs")
        seen_ids.add(item_id)
        type_id = item.get("type_id")
        if not isinstance(type_id, str) or not type_id or len(type_id) > 128:
            raise ClipboardValidationError("Clipboard item has an invalid type ID")

        children = item.get("children")
        if children is not None:
            if not isinstance(children, list):
                raise ClipboardValidationError("Clipboard item children must be a list")
            pending.extend(children)
        _validate_embedded_references(item, asset_names)


def _validate_embedded_references(value: Any, asset_names: set[str]) -> None:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                if key in _REFERENCE_KEYS:
                    if child is not None:
                        _normalize_uuid(child, f"reference {key}")
                elif key in _REFERENCE_LIST_KEYS:
                    if not isinstance(child, list):
                        raise ClipboardValidationError(
                            f"Clipboard reference list {key} is invalid"
                        )
                    for reference in child:
                        _normalize_uuid(reference, f"reference {key}")
                elif key == "references":
                    _validate_reference_map(child)
                elif key == "asset_name":
                    if (
                        not isinstance(child, str)
                        or child.casefold() not in asset_names
                    ):
                        raise ClipboardValidationError(
                            "Clipboard item references an undeclared asset"
                        )
                else:
                    pending.append(child)
        elif isinstance(current, list):
            pending.extend(current)


def _validate_reference_map(value: Any) -> None:
    if not isinstance(value, dict):
        raise ClipboardValidationError("Clipboard references must be an object")
    for role, item_id in value.items():
        if not isinstance(role, str) or not _ROLE_RE.fullmatch(role):
            raise ClipboardValidationError("Clipboard reference role is invalid")
        if item_id is not None:
            _normalize_uuid(item_id, f"reference {role}")


def _decode_asset(descriptor: Any, limits: ClipboardLimits) -> ProjectAsset:
    data = _decode_asset_data(descriptor, limits)
    return ProjectAsset(descriptor["name"], data, descriptor["media_type"])


def _decode_asset_data(descriptor: Any, limits: ClipboardLimits) -> bytes:
    if not isinstance(descriptor, dict) or set(descriptor) != _ASSET_KEYS:
        raise ClipboardValidationError("Invalid clipboard asset descriptor")
    name = descriptor["name"]
    media_type = descriptor["media_type"]
    size = descriptor["size"]
    digest = descriptor["sha256"]
    encoded = descriptor["data"]
    if not isinstance(name, str) or not _ASSET_NAME_RE.fullmatch(name):
        raise ClipboardValidationError("Invalid clipboard asset name")
    if not isinstance(media_type, str) or not _MEDIA_TYPE_RE.fullmatch(media_type):
        raise ClipboardValidationError("Invalid clipboard asset media type")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 <= size <= limits.max_asset_bytes
    ):
        raise ClipboardValidationError("Invalid clipboard asset size")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ClipboardValidationError("Invalid clipboard asset checksum")
    if not isinstance(encoded, str):
        raise ClipboardValidationError("Invalid clipboard asset encoding")
    try:
        data = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise ClipboardValidationError("Invalid clipboard asset encoding") from error
    if len(data) != size:
        raise ClipboardValidationError("Clipboard asset size does not match its data")
    if sha256(data).hexdigest() != digest:
        raise ClipboardValidationError(
            "Clipboard asset checksum does not match its data"
        )
    return data


def _validate_project_asset(
    asset: ProjectAsset,
    limits: ClipboardLimits,
) -> tuple[str, bytes, str]:
    if not isinstance(asset, ProjectAsset):
        raise ClipboardValidationError("Clipboard assets must be ProjectAsset values")
    name = asset.name
    media_type = asset.media_type
    data = asset.data
    if not isinstance(name, str) or not _ASSET_NAME_RE.fullmatch(name):
        raise ClipboardValidationError("Invalid clipboard asset name")
    if not isinstance(media_type, str) or not _MEDIA_TYPE_RE.fullmatch(media_type):
        raise ClipboardValidationError("Invalid clipboard asset media type")
    if not isinstance(data, bytes) or len(data) > limits.max_asset_bytes:
        raise ClipboardValidationError("Invalid clipboard asset data")
    return name, data, media_type


def _scene_item_ids(items: list[dict[str, Any]]) -> list[str]:
    return [_normalize_uuid(item["id"], "item ID") for item in _iter_scene_items(items)]


def _iter_scene_items(items: list[dict[str, Any]]):
    pending = list(reversed(items))
    while pending:
        item = pending.pop()
        yield item
        children = item.get("children")
        if isinstance(children, list):
            pending.extend(reversed(children))


def _new_unique_id(
    id_factory: Callable[[], object],
    used_ids: set[str],
) -> str:
    for _attempt in range(100):
        try:
            candidate = _normalize_uuid(id_factory(), "generated item ID")
        except Exception as error:
            if isinstance(error, ClipboardValidationError):
                raise
            raise ClipboardValidationError("Item ID generator failed") from error
        if candidate not in used_ids:
            return candidate
    raise ClipboardValidationError("Item ID generator did not produce a unique UUID")


def _normalize_uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise ClipboardValidationError(f"Invalid {label}") from error


def _rewrite_embedded_references(
    value: Any,
    id_map: Mapping[str, str],
    asset_map: Mapping[str, str],
) -> None:
    folded_asset_map = {name.casefold(): target for name, target in asset_map.items()}
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, child in list(current.items()):
                if key in _REFERENCE_KEYS:
                    current[key] = _remap_reference(child, id_map)
                elif key in _REFERENCE_LIST_KEYS:
                    current[key] = [
                        id_map[normalized]
                        for reference in child
                        if (
                            normalized := _normalize_uuid(reference, f"reference {key}")
                        )
                        in id_map
                    ]
                elif key == "references":
                    current[key] = {
                        role: _remap_reference(reference, id_map)
                        for role, reference in child.items()
                    }
                elif key == "asset_name":
                    current[key] = folded_asset_map[child.casefold()]
                else:
                    pending.append(child)
        elif isinstance(current, list):
            pending.extend(current)


def _remap_reference(value: Any, id_map: Mapping[str, str]) -> str | None:
    if value is None:
        return None
    return id_map.get(_normalize_uuid(value, "item reference"))


def _deduplicate_assets(
    source_assets: tuple[ProjectAsset, ...],
    existing_assets: tuple[ProjectAsset, ...],
    limits: ClipboardLimits,
) -> tuple[tuple[ProjectAsset, ...], dict[str, str]]:
    by_name: dict[str, ProjectAsset] = {}
    by_content: dict[tuple[str, str], ProjectAsset] = {}
    for asset in existing_assets:
        name, data, media_type = _validate_project_asset(asset, limits)
        folded_name = name.casefold()
        if folded_name in by_name:
            raise ClipboardValidationError("Destination contains duplicate asset names")
        by_name[folded_name] = asset
        by_content[(sha256(data).hexdigest(), media_type)] = asset

    additions: list[ProjectAsset] = []
    name_map: dict[str, str] = {}
    for source in source_assets:
        name, data, media_type = _validate_project_asset(source, limits)
        digest = sha256(data).hexdigest()
        content_key = (digest, media_type)
        matching = by_content.get(content_key)
        if matching is not None:
            name_map[name] = matching.name
            continue

        target_name = name
        if target_name.casefold() in by_name:
            target_name = _unique_asset_name(name, digest, set(by_name))
        added = ProjectAsset(target_name, data, media_type)
        additions.append(added)
        by_name[target_name.casefold()] = added
        by_content[content_key] = added
        name_map[name] = target_name
    return tuple(additions), name_map


def _unique_asset_name(name: str, digest: str, used_names: set[str]) -> str:
    dot = name.rfind(".")
    if dot > 0:
        stem, suffix = name[:dot], name[dot:]
    else:
        stem, suffix = name, ""

    for digest_length in range(8, 65, 4):
        token = digest[:digest_length]
        suffix_limit = 128 - len(token) - 2
        safe_suffix = suffix[:suffix_limit]
        stem_limit = 128 - len(safe_suffix) - len(token) - 1
        candidate = f"{stem[:stem_limit]}-{token}{safe_suffix}"
        if candidate.casefold() not in used_names:
            return candidate
    raise ClipboardValidationError("Could not allocate a unique asset name")
