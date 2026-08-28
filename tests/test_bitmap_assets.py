from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from asset_service import BitmapAssetError, BitmapAssetLimits, BitmapAssetService
from bitmap_item import (
    BitmapItem,
    bitmap_assets_for_items,
    restore_bitmap_item,
    serialize_bitmap_item,
)
from clipboard_service import ClipboardService
from document_format import ProjectAsset, ProjectDocument
from document_io import load_project, save_project
from export_renderer import ExportRenderer, ExportRequest


def _image_bytes(format_name: str, color: str = "#e14b4b") -> bytes:
    image = QtGui.QImage(12, 8, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(color))
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    assert buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, format_name)
    buffer.close()
    return bytes(data)


@pytest.mark.parametrize(
    ("format_name", "media_type", "suffix"),
    [
        ("PNG", "image/png", ".png"),
        ("JPEG", "image/jpeg", ".jpg"),
        ("WEBP", "image/webp", ".webp"),
    ],
)
def test_imported_bitmaps_are_validated_and_content_addressed(
    application: QtWidgets.QApplication, format_name: str, media_type: str, suffix: str
) -> None:
    data = _image_bytes(format_name)
    imported = BitmapAssetService().import_bytes(data, media_type=media_type)
    assert imported.added
    assert imported.asset.name == f"bitmap-{sha256(data).hexdigest()[:16]}{suffix}"
    assert imported.image.size() == QtCore.QSize(12, 8)


def test_rejected_import_never_mutates_assets(
    application: QtWidgets.QApplication,
) -> None:
    data = _image_bytes("PNG")
    service = BitmapAssetService(limits=BitmapAssetLimits(max_asset_bytes=len(data)))
    valid = service.import_bytes(data)
    with pytest.raises(BitmapAssetError, match="MIME"):
        service.import_bytes(data, media_type="image/jpeg")
    with pytest.raises(BitmapAssetError, match="size limit"):
        service.import_bytes(data + b"x")
    with pytest.raises(BitmapAssetError, match="supported"):
        service.import_bytes(b"not an image")
    assert service.assets() == (valid.asset,)


def test_duplicate_content_and_project_asset_limits(
    application: QtWidgets.QApplication,
) -> None:
    first = _image_bytes("PNG", "#e14b4b")
    second = _image_bytes("PNG", "#4b7ee1")
    service = BitmapAssetService(limits=BitmapAssetLimits(max_assets=1))
    stored = service.import_bytes(first)
    assert not service.import_bytes(first).added
    with pytest.raises(BitmapAssetError, match="too many"):
        service.import_bytes(second)
    assert service.assets() == (stored.asset,)


def test_service_preserves_unrelated_project_assets(
    application: QtWidgets.QApplication,
) -> None:
    unrelated = ProjectAsset("embedded.svg", b"<svg/>", "image/svg+xml")
    service = BitmapAssetService((unrelated,))
    imported = service.import_bytes(_image_bytes("PNG"))
    assert service.assets() == (unrelated, imported.asset)


def test_replacement_keeps_display_transformation(
    application: QtWidgets.QApplication,
) -> None:
    service = BitmapAssetService()
    first, second = (
        service.import_bytes(_image_bytes("PNG")),
        service.import_bytes(_image_bytes("PNG", "#4b7ee1")),
    )
    item = BitmapItem(first.asset, 10, 20, 120, 60)
    item.setRotation(17)
    item.setScale(1.25)
    before = item.pos(), item.rotation(), item.scale(), item.item_size()
    item.replace_asset(second.asset)
    assert (item.pos(), item.rotation(), item.scale(), item.item_size()) == before


def test_project_clipboard_and_export_roundtrip(
    application: QtWidgets.QApplication, tmp_path: Path
) -> None:
    service = BitmapAssetService()
    imported = service.import_bytes(_image_bytes("PNG"))
    original = BitmapItem(imported.asset, width=36, height=24)
    record = serialize_bitmap_item(original)
    record["id"] = str(uuid4())
    document_path = tmp_path / "bitmap.drawsvg"
    save_project(
        document_path,
        ProjectDocument(
            scene={"schema_version": 1, "grid_visible": False, "items": [record]},
            assets=service.assets(),
        ),
    )
    loaded = load_project(document_path)
    restored = restore_bitmap_item(loaded.scene["items"][0], loaded.assets)
    encoded = ClipboardService.encode(
        [record], assets=bitmap_assets_for_items((original,), loaded.assets)
    )
    pasted = ClipboardService.prepare_paste(encoded)
    assert (
        restore_bitmap_item(pasted.items[0], pasted.assets_to_add).asset_sha256
        == restored.asset_sha256
    )
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(restored)
    output = tmp_path / "bitmap.svg"
    ExportRenderer(scene).export_svg(output, ExportRequest(background=None))
    root = ElementTree.fromstring(output.read_bytes())
    assert len([node for node in root.iter() if node.tag.endswith("image")]) == 1


def test_tampered_reference_or_unsafe_size_is_rejected(
    application: QtWidgets.QApplication,
) -> None:
    imported = BitmapAssetService().import_bytes(_image_bytes("PNG"))
    record = serialize_bitmap_item(BitmapItem(imported.asset))
    record["asset_sha256"] = "0" * 64
    with pytest.raises(BitmapAssetError, match="does not match"):
        restore_bitmap_item(record, (imported.asset,))
    record["asset_sha256"] = sha256(imported.asset.data).hexdigest()
    record["size"] = [20_000, 8]
    with pytest.raises(BitmapAssetError, match="dimensions"):
        restore_bitmap_item(record, (imported.asset,))


def test_canvas_persists_bitmap_items_through_undo_redo_and_restore(
    canvas_view,
) -> None:
    service = BitmapAssetService()
    imported = service.import_bytes(_image_bytes("PNG"))
    canvas_view.set_bitmap_assets(service.assets())
    item = canvas_view.add_bitmap_item(imported.asset, QtCore.QPointF(10, 20), 36, 24)
    item.setRotation(17)
    item.setScale(1.25)
    canvas_view.history().capture_now()

    state = canvas_view._serialize_scene_state()
    record = state["items"][0]
    assert record["type_id"] == "Bitmap"
    assert record["asset_sha256"] == item.asset_sha256

    clone = canvas_view._clone_item(item)
    assert isinstance(clone, BitmapItem)
    assert clone.item_size() == item.item_size()
    assert clone.asset_sha256 == item.asset_sha256

    canvas_view.undo()
    unrotated = next(
        scene_item
        for scene_item in canvas_view.scene().items()
        if isinstance(scene_item, BitmapItem)
    )
    assert unrotated.asset_sha256 == item.asset_sha256
    assert unrotated.rotation() == pytest.approx(0)
    assert unrotated.scale() == pytest.approx(1)

    canvas_view.redo()
    restored = next(
        scene_item
        for scene_item in canvas_view.scene().items()
        if isinstance(scene_item, BitmapItem)
    )
    assert restored.asset_sha256 == item.asset_sha256
    assert restored.rotation() == pytest.approx(17)
    assert restored.scale() == pytest.approx(1.25)
