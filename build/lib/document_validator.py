"""Strict validation for native DrawSVG project JSON and ZIP containers."""

from __future__ import annotations

import json
import math
import re
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from PySide6 import QtGui

from document_format import (
    CURRENT_FORMAT_VERSION,
    PROJECT_FORMAT,
    PROJECT_JSON_PATH,
    THUMBNAIL_PATH,
    DocumentFormatError,
    ProjectAsset,
    ProjectDocument,
    migrate_project_payload,
)


class DocumentValidationError(DocumentFormatError):
    """Raised when project content violates the native format contract."""


@dataclass(frozen=True)
class ValidationLimits:
    max_archive_bytes: int = 128 * 1024 * 1024
    max_members: int = 260
    max_total_uncompressed_bytes: int = 100 * 1024 * 1024
    max_project_json_bytes: int = 8 * 1024 * 1024
    max_assets: int = 256
    max_asset_bytes: int = 25 * 1024 * 1024
    max_thumbnail_bytes: int = 2 * 1024 * 1024
    max_thumbnail_dimension: int = 4096
    max_json_depth: int = 64
    max_json_nodes: int = 250_000
    max_scene_items: int = 50_000


DEFAULT_LIMITS = ValidationLimits()


@dataclass(frozen=True)
class ValidatedProject:
    payload: dict[str, Any]
    assets: tuple[ProjectAsset, ...]
    thumbnail: bytes | None


_ASSET_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MEDIA_TYPE_RE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\Z"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_project_archive(
    path: str | Path,
    *,
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> ValidatedProject:
    """Read and validate an archive without extracting anything to disk."""

    archive_path = Path(path)
    try:
        archive_size = archive_path.stat().st_size
    except OSError as error:
        raise DocumentValidationError(f"Cannot read project file: {error}") from error
    if archive_size > limits.max_archive_bytes:
        raise DocumentValidationError("Project archive exceeds the size limit")

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            return _validate_open_archive(archive, limits)
    except DocumentFormatError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise DocumentValidationError("Invalid project ZIP archive") from error


def validate_project_document(
    document: ProjectDocument,
    *,
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> ValidatedProject:
    """Validate an in-memory project before it is written."""

    assets = tuple(document.assets)
    asset_descriptors = [_asset_descriptor(asset) for asset in assets]
    thumbnail_descriptor = (
        _binary_descriptor(THUMBNAIL_PATH, "image/png", document.thumbnail)
        if document.thumbnail is not None
        else None
    )
    payload: dict[str, Any] = {
        "format": PROJECT_FORMAT,
        "format_version": CURRENT_FORMAT_VERSION,
        "document_id": document.document_id,
        "scene": dict(document.scene),
        "assets": asset_descriptors,
        "thumbnail": thumbnail_descriptor,
    }
    member_names = {PROJECT_JSON_PATH, *(asset.archive_path for asset in assets)}
    member_data = {asset.archive_path: asset.data for asset in assets}
    if document.thumbnail is not None:
        member_names.add(THUMBNAIL_PATH)
        member_data[THUMBNAIL_PATH] = document.thumbnail

    migrated = _validate_payload(payload, member_names, limits)
    validated_assets, thumbnail = _validate_binary_members(
        migrated, member_data, limits
    )
    try:
        encoded = _encode_project_json(migrated)
    except (TypeError, ValueError, RecursionError) as error:
        raise DocumentValidationError("Project data is not valid JSON") from error
    if len(encoded) > limits.max_project_json_bytes:
        raise DocumentValidationError("project.json exceeds the size limit")
    if len(encoded) + sum(len(data) for data in member_data.values()) > (
        limits.max_total_uncompressed_bytes
    ):
        raise DocumentValidationError("Project exceeds the uncompressed size limit")
    return ValidatedProject(migrated, validated_assets, thumbnail)


def encode_project_json(payload: Mapping[str, Any]) -> bytes:
    """Encode validated project metadata in a deterministic representation."""

    return _encode_project_json(payload)


def _validate_open_archive(
    archive: zipfile.ZipFile,
    limits: ValidationLimits,
) -> ValidatedProject:
    infos = archive.infolist()
    if len(infos) > limits.max_members:
        raise DocumentValidationError("Project archive contains too many members")

    members: dict[str, zipfile.ZipInfo] = {}
    casefolded_names: set[str] = set()
    total_size = 0
    for info in infos:
        _validate_member(info)
        folded = info.filename.casefold()
        if info.filename in members or folded in casefolded_names:
            raise DocumentValidationError("Project archive contains duplicate members")
        members[info.filename] = info
        casefolded_names.add(folded)
        total_size += info.file_size
        if total_size > limits.max_total_uncompressed_bytes:
            raise DocumentValidationError("Project exceeds the uncompressed size limit")

    project_info = members.get(PROJECT_JSON_PATH)
    if project_info is None:
        raise DocumentValidationError("Project archive is missing project.json")
    if project_info.file_size > limits.max_project_json_bytes:
        raise DocumentValidationError("project.json exceeds the size limit")

    project_bytes = _read_member(archive, project_info, limits.max_project_json_bytes)
    payload = _decode_project_json(project_bytes, limits)
    migrated = _validate_payload(
        payload,
        set(members),
        limits,
        discard_invalid_thumbnail=True,
    )

    binary_members: dict[str, bytes] = {}
    for member_name in set(members) - {PROJECT_JSON_PATH}:
        if member_name == THUMBNAIL_PATH and migrated["thumbnail"] is None:
            continue
        limit = (
            limits.max_thumbnail_bytes
            if member_name == THUMBNAIL_PATH
            else limits.max_asset_bytes
        )
        try:
            binary_members[member_name] = _read_member(
                archive, members[member_name], limit
            )
        except DocumentValidationError:
            if member_name != THUMBNAIL_PATH:
                raise
            migrated["thumbnail"] = None
    assets, thumbnail = _validate_binary_members(
        migrated,
        binary_members,
        limits,
        discard_invalid_thumbnail=True,
    )
    if thumbnail is None:
        migrated["thumbnail"] = None
    return ValidatedProject(migrated, assets, thumbnail)


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if not name or "\x00" in name or "\\" in name:
        raise DocumentValidationError("Project archive contains an unsafe member path")
    parts = name.split("/")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or any(":" in part for part in parts)
        or info.is_dir()
    ):
        raise DocumentValidationError("Project archive contains an unsafe member path")
    unix_type = (info.external_attr >> 16) & 0o170000
    if unix_type == stat.S_IFLNK:
        raise DocumentValidationError("Project archive contains a symbolic link")
    if info.flag_bits & 0x1:
        raise DocumentValidationError("Encrypted project members are not supported")
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise DocumentValidationError("Unsupported ZIP compression method")


def _decode_project_json(raw: bytes, limits: ValidationLimits) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
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
        raise DocumentValidationError("project.json is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise DocumentValidationError("project.json must contain a JSON object")
    _validate_json_tree(payload, limits)
    return migrate_project_payload(payload)


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number is not finite")
    return parsed


def _validate_json_tree(value: Any, limits: ValidationLimits) -> None:
    nodes = 0
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_json_nodes:
            raise DocumentValidationError("project.json contains too many values")
        if depth > limits.max_json_depth:
            raise DocumentValidationError("project.json is nested too deeply")
        if isinstance(current, dict):
            if not all(isinstance(key, str) for key in current):
                raise DocumentValidationError("JSON object keys must be strings")
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, float) and not math.isfinite(current):
            raise DocumentValidationError("JSON numbers must be finite")
        elif not isinstance(current, (str, int, float, bool, type(None))):
            raise DocumentValidationError("Project contains a non-JSON value")


def _validate_payload(
    payload: Mapping[str, Any],
    member_names: set[str],
    limits: ValidationLimits,
    *,
    discard_invalid_thumbnail: bool = False,
) -> dict[str, Any]:
    migrated = migrate_project_payload(payload)
    required = {
        "format",
        "format_version",
        "document_id",
        "scene",
        "assets",
        "thumbnail",
    }
    if not required.issubset(migrated):
        raise DocumentValidationError("project.json has an invalid top-level shape")
    if migrated["format"] != PROJECT_FORMAT:
        raise DocumentValidationError("Not a DrawSVG project")
    if migrated["format_version"] != CURRENT_FORMAT_VERSION:
        raise DocumentValidationError(
            "Project migration did not reach the current version"
        )
    try:
        migrated["document_id"] = str(UUID(migrated["document_id"]))
    except (AttributeError, TypeError, ValueError) as error:
        raise DocumentValidationError("Invalid document UUID") from error
    _validate_scene(migrated["scene"], limits)
    _validate_json_tree(migrated, limits)

    raw_assets = migrated["assets"]
    if not isinstance(raw_assets, list) or len(raw_assets) > limits.max_assets:
        raise DocumentValidationError("Project asset manifest is invalid")

    expected_members = {PROJECT_JSON_PATH}
    seen_names: set[str] = set()
    total_asset_size = 0
    for descriptor in raw_assets:
        _validate_asset_descriptor(descriptor, limits)
        name = descriptor["name"]
        if name.casefold() in seen_names:
            raise DocumentValidationError("Project contains duplicate asset names")
        seen_names.add(name.casefold())
        expected_members.add(descriptor["path"])
        total_asset_size += descriptor["size"]
    if total_asset_size > limits.max_total_uncompressed_bytes:
        raise DocumentValidationError("Project assets exceed the total size limit")

    thumbnail = migrated["thumbnail"]
    if thumbnail is not None:
        try:
            _validate_thumbnail_descriptor(thumbnail, limits)
        except DocumentValidationError:
            if not discard_invalid_thumbnail:
                raise
            migrated["thumbnail"] = None
        else:
            expected_members.add(THUMBNAIL_PATH)

    if discard_invalid_thumbnail:
        if THUMBNAIL_PATH not in member_names:
            migrated["thumbnail"] = None
        member_names = member_names - {THUMBNAIL_PATH}
        expected_members = expected_members - {THUMBNAIL_PATH}
    if member_names != expected_members:
        raise DocumentValidationError(
            "Project archive members do not match the asset manifest"
        )
    return dict(migrated)


def _validate_scene(scene: Any, limits: ValidationLimits) -> None:
    if not isinstance(scene, dict):
        raise DocumentValidationError("Project scene must be a JSON object")
    schema_version = scene.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise DocumentValidationError("Project scene has an invalid schema version")
    if "grid_visible" in scene and not isinstance(scene["grid_visible"], bool):
        raise DocumentValidationError("Project scene has an invalid grid flag")
    items = scene.get("items")
    if not isinstance(items, list):
        raise DocumentValidationError("Project scene items must be a list")

    count = 0
    pending = list(items)
    while pending:
        item = pending.pop()
        if not isinstance(item, dict):
            raise DocumentValidationError("Project scene contains an invalid item")
        count += 1
        if count > limits.max_scene_items:
            raise DocumentValidationError("Project scene contains too many items")
        children = item.get("children")
        if children is not None:
            if not isinstance(children, list):
                raise DocumentValidationError("Project item children must be a list")
            pending.extend(children)


def _validate_asset_descriptor(
    descriptor: Any,
    limits: ValidationLimits,
) -> None:
    required = {"name", "path", "media_type", "size", "sha256"}
    if not isinstance(descriptor, dict) or set(descriptor) != required:
        raise DocumentValidationError("Invalid asset descriptor")
    name = descriptor["name"]
    if not isinstance(name, str) or not _ASSET_NAME_RE.fullmatch(name):
        raise DocumentValidationError("Invalid asset name")
    if descriptor["path"] != f"assets/{name}":
        raise DocumentValidationError("Asset path does not match its name")
    _validate_binary_descriptor(descriptor, limits.max_asset_bytes)


def _validate_thumbnail_descriptor(
    descriptor: Any,
    limits: ValidationLimits,
) -> None:
    required = {"path", "media_type", "size", "sha256"}
    if not isinstance(descriptor, dict) or set(descriptor) != required:
        raise DocumentValidationError("Invalid thumbnail descriptor")
    if descriptor["path"] != THUMBNAIL_PATH:
        raise DocumentValidationError("Invalid thumbnail path")
    if descriptor["media_type"] != "image/png":
        raise DocumentValidationError("Project thumbnail must be a PNG image")
    _validate_binary_descriptor(descriptor, limits.max_thumbnail_bytes)


def _validate_binary_descriptor(descriptor: Mapping[str, Any], limit: int) -> None:
    media_type = descriptor["media_type"]
    size = descriptor["size"]
    digest = descriptor["sha256"]
    if not isinstance(media_type, str) or not _MEDIA_TYPE_RE.fullmatch(media_type):
        raise DocumentValidationError("Invalid asset media type")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= limit:
        raise DocumentValidationError("Invalid asset size")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise DocumentValidationError("Invalid asset checksum")


def _validate_binary_members(
    payload: Mapping[str, Any],
    member_data: Mapping[str, bytes],
    limits: ValidationLimits,
    *,
    discard_invalid_thumbnail: bool = False,
) -> tuple[tuple[ProjectAsset, ...], bytes | None]:
    assets: list[ProjectAsset] = []
    for descriptor in payload["assets"]:
        data = member_data[descriptor["path"]]
        _verify_binary(data, descriptor)
        assets.append(ProjectAsset(descriptor["name"], data, descriptor["media_type"]))

    thumbnail_descriptor = payload["thumbnail"]
    thumbnail = None
    if thumbnail_descriptor is not None:
        try:
            thumbnail = member_data[THUMBNAIL_PATH]
            _verify_binary(thumbnail, thumbnail_descriptor)
            _validate_png_thumbnail(thumbnail, limits)
        except (DocumentValidationError, KeyError):
            if not discard_invalid_thumbnail:
                raise
            thumbnail = None
    return tuple(assets), thumbnail


def _verify_binary(data: bytes, descriptor: Mapping[str, Any]) -> None:
    if not isinstance(data, bytes):
        raise DocumentValidationError("Project binary members must be bytes")
    if len(data) != descriptor["size"]:
        raise DocumentValidationError("Asset size does not match its descriptor")
    if sha256(data).hexdigest() != descriptor["sha256"]:
        raise DocumentValidationError("Asset checksum does not match its descriptor")


def _validate_png_thumbnail(data: bytes, limits: ValidationLimits) -> None:
    if (
        len(data) < 24
        or not data.startswith(_PNG_SIGNATURE)
        or data[8:12] != b"\x00\x00\x00\r"
        or data[12:16] != b"IHDR"
    ):
        raise DocumentValidationError("Project thumbnail is not a valid PNG header")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if (
        width < 1
        or height < 1
        or width > limits.max_thumbnail_dimension
        or height > limits.max_thumbnail_dimension
    ):
        raise DocumentValidationError("Project thumbnail dimensions are invalid")
    image = QtGui.QImage.fromData(data, "PNG")
    if image.isNull() or image.width() != width or image.height() != height:
        raise DocumentValidationError("Project thumbnail cannot be decoded")


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    limit: int,
) -> bytes:
    if info.file_size > limit:
        raise DocumentValidationError(f"Archive member {info.filename!r} is too large")
    try:
        with archive.open(info, "r") as member:
            data = member.read(limit + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise DocumentValidationError(
            f"Cannot read archive member {info.filename!r}"
        ) from error
    if len(data) > limit or len(data) != info.file_size:
        raise DocumentValidationError(f"Archive member {info.filename!r} is invalid")
    return data


def _asset_descriptor(asset: ProjectAsset) -> dict[str, Any]:
    return {
        "name": asset.name,
        "path": asset.archive_path,
        "media_type": asset.media_type,
        "size": len(asset.data),
        "sha256": sha256(asset.data).hexdigest(),
    }


def _binary_descriptor(path: str, media_type: str, data: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "media_type": media_type,
        "size": len(data),
        "sha256": sha256(data).hexdigest(),
    }


def _encode_project_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
