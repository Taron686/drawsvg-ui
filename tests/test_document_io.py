from __future__ import annotations

import json
import struct
import zipfile
import zlib
from hashlib import sha256
from pathlib import Path

import pytest

import document_io
from document_format import (
    CURRENT_FORMAT_VERSION,
    PROJECT_FORMAT,
    PROJECT_JSON_PATH,
    ProjectAsset,
    ProjectDocument,
    UnsupportedFormatVersionError,
)
from document_io import load_project, save_project
from document_validator import (
    DocumentValidationError,
    ValidationLimits,
    _validate_member,
)

DOCUMENT_ID = "d95db7f0-b07b-4d00-954e-ab478779f69c"


def _png_header(width: int = 16, height: int = 12) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = b"".join(b"\0" + b"\0\0\0\0" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def _payload(
    *,
    assets: list[dict] | None = None,
    thumbnail: dict | None = None,
    version: int = CURRENT_FORMAT_VERSION,
) -> dict:
    return {
        "format": PROJECT_FORMAT,
        "format_version": version,
        "document_id": DOCUMENT_ID,
        "scene": {
            "schema_version": 1,
            "grid_visible": False,
            "items": [{"type_id": "Rectangle", "stack_order": 0}],
        },
        "assets": assets or [],
        "thumbnail": thumbnail,
    }


def _descriptor(name: str, data: bytes) -> dict:
    return {
        "name": name,
        "path": f"assets/{name}",
        "media_type": "application/octet-stream",
        "size": len(data),
        "sha256": sha256(data).hexdigest(),
    }


def _write_zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(name, data)


def test_project_roundtrip_preserves_scene_assets_and_thumbnail(tmp_path: Path) -> None:
    scene = {
        "schema_version": 1,
        "grid_visible": True,
        "items": [
            {
                "id": "f253083a-4188-452b-8480-452c513195dc",
                "type_id": "Rectangle",
                "layer_id": "layer-1",
                "stack_order": 0,
                "position": [12.5, -4.0],
            }
        ],
    }
    project = ProjectDocument(
        scene=scene,
        document_id=DOCUMENT_ID,
        assets=(ProjectAsset("sample.bin", b"asset-data"),),
        thumbnail=_png_header(),
    )
    path = tmp_path / "drawing.drawsvg"

    save_project(path, project)
    loaded = load_project(path)

    assert loaded == project
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            PROJECT_JSON_PATH,
            "assets/sample.bin",
            "thumbnail.png",
        }
        payload = json.loads(archive.read(PROJECT_JSON_PATH))
    assert payload["format_version"] == CURRENT_FORMAT_VERSION
    assert payload["format"] == "drawsvg-ui-project"
    assert payload["document_id"] == DOCUMENT_ID
    assert payload["assets"][0]["sha256"] == sha256(b"asset-data").hexdigest()


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape", "/absolute", "C:/drive", "a/../b"],
)
def test_zip_slip_paths_are_rejected(tmp_path: Path, unsafe_name: str) -> None:
    path = tmp_path / "unsafe.drawsvg"
    _write_zip(
        path,
        [
            (PROJECT_JSON_PATH, json.dumps(_payload()).encode()),
            (unsafe_name, b"content"),
        ],
    )

    with pytest.raises(DocumentValidationError, match="unsafe member path"):
        load_project(path)


def test_backslash_member_is_rejected_before_platform_normalization() -> None:
    info = zipfile.ZipInfo("placeholder")
    info.filename = "assets\\backslash.bin"

    with pytest.raises(DocumentValidationError, match="unsafe member path"):
        _validate_member(info)


def test_unlisted_asset_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unlisted.drawsvg"
    _write_zip(
        path,
        [
            (PROJECT_JSON_PATH, json.dumps(_payload()).encode()),
            ("assets/unlisted.bin", b"content"),
        ],
    )

    with pytest.raises(DocumentValidationError, match="do not match"):
        load_project(path)


def test_missing_or_modified_asset_is_rejected(tmp_path: Path) -> None:
    original = b"original"
    descriptor = _descriptor("sample.bin", original)
    path = tmp_path / "modified.drawsvg"
    _write_zip(
        path,
        [
            (PROJECT_JSON_PATH, json.dumps(_payload(assets=[descriptor])).encode()),
            ("assets/sample.bin", b"modified"),
        ],
    )

    with pytest.raises(DocumentValidationError, match="checksum"):
        load_project(path)


def test_invalid_thumbnail_is_discarded(tmp_path: Path) -> None:
    thumbnail = b"not-a-png"
    descriptor = {
        "path": "thumbnail.png",
        "media_type": "image/png",
        "size": len(thumbnail),
        "sha256": sha256(thumbnail).hexdigest(),
    }
    path = tmp_path / "thumbnail.drawsvg"
    _write_zip(
        path,
        [
            (PROJECT_JSON_PATH, json.dumps(_payload(thumbnail=descriptor)).encode()),
            ("thumbnail.png", thumbnail),
        ],
    )

    loaded = load_project(path)

    assert loaded.thumbnail is None


def test_unknown_top_level_fields_are_accepted(tmp_path: Path) -> None:
    path = tmp_path / "future-field.drawsvg"
    payload = _payload()
    payload["future_metadata"] = {"supported_later": True}
    _write_zip(path, [(PROJECT_JSON_PATH, json.dumps(payload).encode())])

    loaded = load_project(path)

    assert loaded.document_id == DOCUMENT_ID


def test_invalid_document_uuid_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad-id.drawsvg"
    payload = _payload()
    payload["document_id"] = "not-a-uuid"
    _write_zip(path, [(PROJECT_JSON_PATH, json.dumps(payload).encode())])

    with pytest.raises(DocumentValidationError, match="document UUID"):
        load_project(path)


def test_scene_item_limit_includes_nested_groups(tmp_path: Path) -> None:
    path = tmp_path / "too-many-items.drawsvg"
    payload = _payload()
    payload["scene"]["items"] = [{"children": [{}, {}]}]
    _write_zip(path, [(PROJECT_JSON_PATH, json.dumps(payload).encode())])

    with pytest.raises(DocumentValidationError, match="too many items"):
        load_project(path, limits=ValidationLimits(max_scene_items=2))


def test_configured_size_limits_are_enforced_before_loading(tmp_path: Path) -> None:
    data = b"12345"
    descriptor = _descriptor("large.bin", data)
    path = tmp_path / "large.drawsvg"
    _write_zip(
        path,
        [
            (PROJECT_JSON_PATH, json.dumps(_payload(assets=[descriptor])).encode()),
            ("assets/large.bin", data),
        ],
    )
    limits = ValidationLimits(
        max_asset_bytes=4,
        max_total_uncompressed_bytes=1024 * 1024,
    )

    with pytest.raises(DocumentValidationError, match="asset size"):
        load_project(path, limits=limits)


def test_invalid_load_never_returns_a_partial_document(tmp_path: Path) -> None:
    path = tmp_path / "broken.drawsvg"
    _write_zip(path, [(PROJECT_JSON_PATH, b"{broken")])
    open_document = ProjectDocument(scene={"items": ["keep-me"]})

    with pytest.raises(DocumentValidationError):
        replacement = load_project(path)
        open_document = replacement

    assert open_document.scene == {"items": ["keep-me"]}


def test_future_format_version_has_a_clear_migration_error(tmp_path: Path) -> None:
    path = tmp_path / "future.drawsvg"
    payload = _payload(version=CURRENT_FORMAT_VERSION + 1)
    _write_zip(path, [(PROJECT_JSON_PATH, json.dumps(payload).encode())])

    with pytest.raises(UnsupportedFormatVersionError, match="newer than supported"):
        load_project(path)


def test_atomic_save_preserves_destination_when_writing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "drawing.drawsvg"
    path.write_bytes(b"existing-project")

    def fail_write(*_args, **_kwargs) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(document_io, "_write_archive", fail_write)

    with pytest.raises(OSError, match="disk failure"):
        save_project(
            path,
            ProjectDocument(
                scene={"schema_version": 1, "grid_visible": False, "items": []}
            ),
        )

    assert path.read_bytes() == b"existing-project"
    assert list(tmp_path.glob(".drawing.drawsvg.*.tmp")) == []
