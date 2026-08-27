from __future__ import annotations

import os
import shutil
from importlib import metadata
from pathlib import Path

import pytest
from export_test_tools import (
    ToolVerificationError,
    UnsupportedReferencePlatform,
    assert_within_locked_tolerance,
    compare_rgba_images,
    installed_pypdfium2_version,
    load_tool_lock,
    pdfium_scale,
    verify_pypdfium2_version,
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
    assert (
        len(
            tool_lock["pypdfium2"]["platforms"]["windows-x86_64"]["sha256"]
        )
        == 64
    )
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
