from __future__ import annotations

import os
import shutil
from importlib import metadata
from pathlib import Path

import export_test_tools
import pytest
from export_test_tools import (
    ToolVerificationError,
    UnsupportedReferencePlatform,
    assert_within_locked_tolerance,
    compare_rgba_images,
    installed_pypdfium2_version,
    load_tool_lock,
    pdfium_scale,
    sha256_file,
    verify_pypdfium2_version,
    verify_pypdfium2_wheel,
    verify_resvg_archive,
    verify_resvg_executable,
    verify_resvg_identity,
)
from PySide6 import QtGui


def _rgba_image(width: int, height: int) -> QtGui.QImage:
    image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGBA8888)
    image.fill(QtGui.QColor(0, 0, 0, 0))
    return image


def test_lock_defines_reference_environment_and_exact_tool_pins() -> None:
    tool_lock = load_tool_lock()
    reference = tool_lock["reference_environment"]
    resvg_platform = tool_lock["resvg"]["platforms"]["windows-x86_64"]

    assert reference["platform"] == "windows-x86_64"
    assert reference["dpi"] == 144
    assert reference["pixel_format"] == "RGBA8888"
    assert reference["color_space"] == "sRGB"
    assert reference["component_connectivity"] == 8
    assert tool_lock["resvg"]["version"] == "0.47.0"
    assert len(resvg_platform["archive_sha256"]) == 64
    assert len(resvg_platform["binary_sha256"]) == 64
    assert tool_lock["pypdfium2"]["version"] == "5.13.0"
    assert len(tool_lock["pypdfium2"]["platforms"]["windows-x86_64"]["sha256"]) == 64
    assert pdfium_scale(tool_lock) == 2.0


@pytest.mark.parametrize(
    ("version", "digest"),
    [
        ("0.46.0", "a" * 64),
        ("0.47.0", "b" * 64),
    ],
)
def test_resvg_identity_rejects_version_or_hash_mismatch(
    version: str,
    digest: str,
) -> None:
    with pytest.raises(ToolVerificationError):
        verify_resvg_identity(
            actual_version=version,
            actual_binary_sha256=digest,
            expected_version="0.47.0",
            expected_binary_sha256="a" * 64,
        )


def test_resvg_archive_rejects_hash_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "resvg-win64.zip"
    archive.write_bytes(b"unexpected archive contents")
    tool_lock = load_tool_lock()

    with pytest.raises(ToolVerificationError, match="archive SHA-256 mismatch"):
        verify_resvg_archive(
            archive,
            tool_lock,
            platform_key="windows-x86_64",
        )


def test_resvg_archive_accepts_the_locked_digest(tmp_path: Path) -> None:
    archive = tmp_path / "resvg-win64.zip"
    archive.write_bytes(b"locked archive contents")
    tool_lock = load_tool_lock()
    tool_lock["resvg"]["platforms"]["windows-x86_64"]["archive_sha256"] = sha256_file(
        archive
    )

    verify_resvg_archive(archive, tool_lock, platform_key="windows-x86_64")


def test_resvg_executable_hashes_before_launching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "resvg.exe"
    executable.write_bytes(b"untrusted executable")
    monkeypatch.setattr(export_test_tools, "sha256_file", lambda _: "0" * 64)

    def must_not_execute(*args, **kwargs) -> None:
        pytest.fail("an executable with a mismatched hash must not be launched")

    monkeypatch.setattr(export_test_tools.subprocess, "run", must_not_execute)

    with pytest.raises(ToolVerificationError, match="binary SHA-256 mismatch"):
        verify_resvg_executable(
            executable,
            load_tool_lock(),
            platform_key="windows-x86_64",
        )


def test_pypdfium2_wheel_rejects_hash_mismatch(tmp_path: Path) -> None:
    wheel = tmp_path / "pypdfium2.whl"
    wheel.write_bytes(b"unexpected wheel contents")

    with pytest.raises(ToolVerificationError, match="wheel SHA-256 mismatch"):
        verify_pypdfium2_wheel(
            wheel,
            load_tool_lock(),
            platform_key="windows-x86_64",
        )


def test_pypdfium2_wheel_accepts_the_locked_digest(tmp_path: Path) -> None:
    wheel = tmp_path / "pypdfium2.whl"
    wheel.write_bytes(b"locked wheel contents")
    tool_lock = load_tool_lock()
    tool_lock["pypdfium2"]["platforms"]["windows-x86_64"]["sha256"] = sha256_file(wheel)

    verify_pypdfium2_wheel(wheel, tool_lock, platform_key="windows-x86_64")


def test_pypdfium2_identity_rejects_version_mismatch() -> None:
    with pytest.raises(ToolVerificationError):
        verify_pypdfium2_version("5.12.1", load_tool_lock())


def test_identical_rgba_images_have_zero_error() -> None:
    image = _rgba_image(4, 3)

    comparison = compare_rgba_images(image, image.copy())

    assert comparison.mean_channel_difference == 0
    assert comparison.different_pixels == 0
    assert comparison.different_pixel_ratio == 0
    assert comparison.largest_component == 0
    assert comparison.largest_component_ratio == 0
    assert_within_locked_tolerance(comparison, load_tool_lock())


def test_rgba_metrics_use_channel_threshold_and_eight_connectivity() -> None:
    reference = _rgba_image(4, 3)
    actual = reference.copy()
    actual.setPixelColor(0, 0, QtGui.QColor(13, 0, 0, 0))
    actual.setPixelColor(1, 1, QtGui.QColor(0, 13, 0, 0))
    actual.setPixelColor(3, 2, QtGui.QColor(0, 0, 12, 0))

    comparison = compare_rgba_images(reference, actual, channel_threshold=12)

    assert comparison.mean_channel_difference == pytest.approx(38 / (4 * 3 * 4))
    assert comparison.different_pixels == 2
    assert comparison.different_pixel_ratio == pytest.approx(2 / 12)
    assert comparison.largest_component == 2
    assert comparison.largest_component_ratio == pytest.approx(2 / 12)


def test_rgba_comparison_rejects_different_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions differ"):
        compare_rgba_images(_rgba_image(2, 2), _rgba_image(3, 2))


def test_locked_resvg_if_provisioned() -> None:
    executable_name = "resvg.exe" if os.name == "nt" else "resvg"
    executable = os.environ.get("RESVG") or shutil.which(executable_name)
    if executable is None:
        pytest.skip("resvg is not provisioned; set RESVG to the locked executable")

    try:
        verify_resvg_executable(Path(executable), load_tool_lock())
    except UnsupportedReferencePlatform as error:
        pytest.skip(str(error))


def test_locked_pypdfium2_if_installed() -> None:
    try:
        actual_version = installed_pypdfium2_version()
    except metadata.PackageNotFoundError:
        pytest.skip("pypdfium2 is not installed in this isolated test environment")

    verify_pypdfium2_version(actual_version, load_tool_lock())
