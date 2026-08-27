from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from uuid import UUID

import pytest

from clipboard_service import (
    CLIPBOARD_FORMAT,
    CLIPBOARD_MIME_TYPE,
    CLIPBOARD_VERSION,
    ClipboardLimits,
    ClipboardService,
    ClipboardValidationError,
)
from document_format import ProjectAsset

DOCUMENT_ID = "d95db7f0-b07b-4d00-954e-ab478779f69c"
GROUP_ID = "09269fe9-6d47-4fc4-a71c-37584fbf8e43"
CHILD_ID = "2d9468ec-1b30-4075-9f17-3d82149bb36b"
EXTERNAL_ID = "c2895bb2-9f01-42ca-bbcc-b74c14b9867d"
NEW_GROUP_ID = "d1e83a63-bb3e-42fb-a6d3-2aab7d4d8bd3"
NEW_CHILD_ID = "ef6897b1-1de9-441e-8b0d-f44e39952c89"


def _items() -> list[dict]:
    return [
        {
            "id": GROUP_ID,
            "type_id": "Group",
            "shape": "Group",
            "references": {
                "selected_child": CHILD_ID,
                "outside_selection": EXTERNAL_ID,
            },
            "children": [
                {
                    "id": CHILD_ID,
                    "type_id": "Rectangle",
                    "shape": "Rectangle",
                    "parent_id": GROUP_ID,
                    "target_id": EXTERNAL_ID,
                }
            ],
        }
    ]


def _raw_payload(
    *, items: list[dict] | None = None, assets: list[dict] | None = None
) -> bytes:
    return json.dumps(
        {
            "format": CLIPBOARD_FORMAT,
            "version": CLIPBOARD_VERSION,
            "source_document_id": DOCUMENT_ID,
            "items": _items() if items is None else items,
            "assets": [] if assets is None else assets,
        },
        separators=(",", ":"),
    ).encode()


def _ids(*values: str):
    iterator = iter(values)
    return lambda: next(iterator)


def test_versioned_roundtrip_remaps_group_and_detaches_external_references() -> None:
    original = _items()
    unchanged = deepcopy(original)

    encoded = ClipboardService.encode(
        original,
        source_document_id=DOCUMENT_ID,
    )
    paste = ClipboardService.prepare_paste(
        encoded,
        id_factory=_ids(NEW_GROUP_ID, NEW_CHILD_ID),
    )

    assert CLIPBOARD_MIME_TYPE.endswith(";version=1")
    assert json.loads(encoded)["version"] == CLIPBOARD_VERSION
    assert paste.source_document_id == DOCUMENT_ID
    assert paste.item_id_map == {
        GROUP_ID: NEW_GROUP_ID,
        CHILD_ID: NEW_CHILD_ID,
    }
    group = paste.items[0]
    child = group["children"][0]
    assert group["id"] == NEW_GROUP_ID
    assert child["id"] == NEW_CHILD_ID
    assert child["parent_id"] == NEW_GROUP_ID
    assert child["target_id"] is None
    assert group["references"] == {
        "selected_child": NEW_CHILD_ID,
        "outside_selection": None,
    }
    assert original == unchanged


def test_generated_ids_are_new_and_do_not_collide_with_destination() -> None:
    collision = "80869cec-00a5-467d-b45e-6f3240741303"
    final_id = "42fedbc7-5a3a-4c68-b495-111919eadfe2"
    item = {"id": GROUP_ID, "type_id": "Rectangle"}
    payload = ClipboardService.encode([item])

    paste = ClipboardService.prepare_paste(
        payload,
        existing_item_ids=[collision],
        id_factory=_ids(collision, GROUP_ID, final_id),
    )

    assert paste.items[0]["id"] == final_id
    assert paste.items[0]["id"] not in {collision, GROUP_ID}
    UUID(paste.items[0]["id"])


def test_assets_are_deduplicated_and_name_conflicts_are_remapped() -> None:
    same_data = b"already-present"
    new_data = b"different-data"
    items = [
        {
            "id": GROUP_ID,
            "type_id": "Bitmap",
            "asset_name": "source.png",
            "preview": {"asset_name": "shared.bin"},
        }
    ]
    encoded = ClipboardService.encode(
        items,
        assets=(
            ProjectAsset("source.png", same_data, "image/png"),
            ProjectAsset("shared.bin", new_data),
        ),
    )

    paste = ClipboardService.prepare_paste(
        encoded,
        existing_assets=(
            ProjectAsset("kept.png", same_data, "image/png"),
            ProjectAsset("shared.bin", b"destination-data"),
        ),
        id_factory=_ids(NEW_GROUP_ID),
    )

    expected_name = f"shared-{sha256(new_data).hexdigest()[:8]}.bin"
    assert paste.asset_name_map == {
        "source.png": "kept.png",
        "shared.bin": expected_name,
    }
    assert paste.items[0]["asset_name"] == "kept.png"
    assert paste.items[0]["preview"]["asset_name"] == expected_name
    assert paste.assets_to_add == (ProjectAsset(expected_name, new_data),)


def test_asset_references_are_rewritten_case_insensitively() -> None:
    encoded = ClipboardService.encode(
        [{"id": GROUP_ID, "type_id": "Bitmap", "asset_name": "foo.png"}],
        assets=(ProjectAsset("Foo.PNG", b"image-data", "image/png"),),
    )

    paste = ClipboardService.prepare_paste(encoded, id_factory=_ids(NEW_GROUP_ID))

    assert paste.items[0]["asset_name"] == "Foo.PNG"
    assert paste.asset_name_map == {"Foo.PNG": "Foo.PNG"}


def test_duplicate_asset_content_inside_payload_is_added_once() -> None:
    data = b"one-copy"
    encoded = ClipboardService.encode(
        [{"id": GROUP_ID, "type_id": "Bitmap", "asset_name": "first.bin"}],
        assets=(ProjectAsset("first.bin", data), ProjectAsset("second.bin", data)),
    )

    paste = ClipboardService.prepare_paste(
        encoded,
        id_factory=_ids(NEW_GROUP_ID),
    )

    assert paste.assets_to_add == (ProjectAsset("first.bin", data),)
    assert paste.asset_name_map == {
        "first.bin": "first.bin",
        "second.bin": "first.bin",
    }


def test_conflicting_maximum_length_asset_name_stays_within_contract() -> None:
    long_name = f"a.{('x' * 125)}"
    encoded = ClipboardService.encode(
        [{"id": GROUP_ID, "type_id": "Bitmap", "asset_name": long_name}],
        assets=(ProjectAsset(long_name, b"new"),),
    )

    paste = ClipboardService.prepare_paste(
        encoded,
        existing_assets=(ProjectAsset(long_name, b"old"),),
        id_factory=_ids(NEW_GROUP_ID),
    )

    remapped_name = paste.asset_name_map[long_name]
    assert len(remapped_name) <= 128
    assert paste.assets_to_add[0].name == remapped_name


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"{broken", "UTF-8 JSON"),
        (
            b"".join(
                (
                    b'{"format":"a","format":"b","version":1,',
                    b'"source_document_id":null,"items":[],"assets":[]}',
                )
            ),
            "Duplicate JSON key",
        ),
        (_raw_payload().replace(b'"version":1', b'"version":2'), "version"),
        (
            _raw_payload().replace(b'"items":', b'"unknown":true,"items":'),
            "top-level shape",
        ),
        (
            _raw_payload(items=[{"id": "not-a-uuid", "type_id": "Rectangle"}]),
            "item ID",
        ),
        (
            _raw_payload(
                items=[
                    {"id": GROUP_ID, "type_id": "Rectangle"},
                    {"id": GROUP_ID, "type_id": "Ellipse"},
                ]
            ),
            "duplicate item IDs",
        ),
        (
            _raw_payload(
                items=[
                    {
                        "id": GROUP_ID,
                        "type_id": "Rectangle",
                        "target_id": "invalid",
                    }
                ]
            ),
            "reference target_id",
        ),
        (
            _raw_payload(
                items=[
                    {
                        "id": GROUP_ID,
                        "type_id": "Bitmap",
                        "asset_name": "missing.bin",
                    }
                ]
            ),
            "undeclared asset",
        ),
    ],
)
def test_malformed_or_manipulated_payload_is_rejected(raw: bytes, message: str) -> None:
    with pytest.raises(ClipboardValidationError, match=message):
        ClipboardService.prepare_paste(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("data", "%%%", "encoding"),
        ("size", 99, "size does not match"),
        ("sha256", "0" * 64, "checksum does not match"),
        ("name", "../escape.bin", "asset name"),
    ],
)
def test_manipulated_assets_are_rejected(
    field: str,
    value: object,
    message: str,
) -> None:
    encoded = ClipboardService.encode(
        [{"id": GROUP_ID, "type_id": "Bitmap", "asset_name": "asset.bin"}],
        assets=(ProjectAsset("asset.bin", b"data"),),
    )
    payload = json.loads(encoded)
    payload["assets"][0][field] = value

    with pytest.raises(ClipboardValidationError, match=message):
        ClipboardService.prepare_paste(json.dumps(payload).encode())


def test_limits_reject_payload_before_any_result_is_returned() -> None:
    raw = _raw_payload(items=[{"id": GROUP_ID, "type_id": "Rectangle"}])

    with pytest.raises(ClipboardValidationError, match="size limit"):
        ClipboardService.prepare_paste(
            raw,
            limits=ClipboardLimits(max_payload_bytes=len(raw) - 1),
        )
    with pytest.raises(ClipboardValidationError, match="too many items"):
        ClipboardService.prepare_paste(
            raw,
            limits=ClipboardLimits(max_items=0),
        )


def test_reference_lists_keep_only_internal_targets() -> None:
    item = {
        "id": GROUP_ID,
        "type_id": "Group",
        "member_ids": [CHILD_ID, EXTERNAL_ID],
        "children": [{"id": CHILD_ID, "type_id": "Rectangle"}],
    }
    encoded = ClipboardService.encode([item])

    paste = ClipboardService.prepare_paste(
        encoded,
        id_factory=_ids(NEW_GROUP_ID, NEW_CHILD_ID),
    )

    assert paste.items[0]["member_ids"] == [NEW_CHILD_ID]
