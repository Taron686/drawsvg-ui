"""Pure test support for reproducible export-image comparisons.

This module intentionally lives under ``tests``. It verifies externally provisioned
renderers and compares already-rasterized images; it is not part of the application
export runtime and never downloads tools.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from importlib import metadata
from pathlib import Path
from typing import Any

from PySide6 import QtGui

LOCK_PATH = Path(__file__).with_name("export-tools.lock")


class ToolVerificationError(RuntimeError):
    """Raised when a provisioned test renderer does not match the lock."""


class UnsupportedReferencePlatform(RuntimeError):
    """Raised when no reference-renderer binary is locked for this platform."""


@dataclass(frozen=True)
class ImageComparison:
    width: int
    height: int
    channel_threshold: int
    mean_channel_difference: float
    different_pixels: int
    different_pixel_ratio: float
    largest_component: int
    largest_component_ratio: float


def load_tool_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reference_dpi(tool_lock: dict[str, Any]) -> int:
    return int(tool_lock["reference_environment"]["dpi"])


def pdfium_scale(tool_lock: dict[str, Any]) -> float:
    """Return the PDF point-to-pixel scale for the locked reference DPI."""

    return reference_dpi(tool_lock) / 72.0


def current_platform_key() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        architecture = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        architecture = "aarch64"
    else:
        architecture = machine or "unknown"

    if sys.platform == "win32":
        operating_system = "windows"
    elif sys.platform == "darwin":
        operating_system = "macos"
    elif sys.platform.startswith("linux"):
        operating_system = "linux"
    else:
        operating_system = sys.platform
    return f"{operating_system}-{architecture}"


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_resvg_identity(
    *,
    actual_version: str,
    actual_binary_sha256: str,
    expected_version: str,
    expected_binary_sha256: str,
) -> None:
    if actual_version != expected_version:
        raise ToolVerificationError(
            f"resvg version mismatch: expected {expected_version}, "
            f"got {actual_version}"
        )
    if actual_binary_sha256.lower() != expected_binary_sha256.lower():
        raise ToolVerificationError(
            "resvg binary SHA-256 mismatch: "
            f"expected {expected_binary_sha256}, got {actual_binary_sha256}"
        )


def verify_resvg_executable(
    executable: Path,
    tool_lock: dict[str, Any],
    *,
    platform_key: str | None = None,
) -> None:
    selected_platform = platform_key or current_platform_key()
    platform_lock = tool_lock["resvg"]["platforms"].get(selected_platform)
    if platform_lock is None:
        raise UnsupportedReferencePlatform(
            f"no resvg reference binary is locked for {selected_platform}"
        )
    if not executable.is_file():
        raise ToolVerificationError(f"resvg executable not found: {executable}")

    result = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    version = result.stdout.strip()
    if version.startswith("resvg "):
        version = version.removeprefix("resvg ")
    verify_resvg_identity(
        actual_version=version,
        actual_binary_sha256=sha256_file(executable),
        expected_version=tool_lock["resvg"]["version"],
        expected_binary_sha256=platform_lock["binary_sha256"],
    )


def verify_pypdfium2_version(
    actual_version: str,
    tool_lock: dict[str, Any],
) -> None:
    expected_version = tool_lock["pypdfium2"]["version"]
    if actual_version != expected_version:
        raise ToolVerificationError(
            f"pypdfium2 version mismatch: expected {expected_version}, "
            f"got {actual_version}"
        )


def installed_pypdfium2_version() -> str:
    return metadata.version("pypdfium2")


def load_rgba_image(path: Path) -> QtGui.QImage:
    image = QtGui.QImage(str(path))
    if image.isNull():
        raise ValueError(f"could not load image: {path}")
    return image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)


def compare_rgba_images(
    reference: QtGui.QImage,
    actual: QtGui.QImage,
    *,
    channel_threshold: int = 12,
) -> ImageComparison:
    if not 0 <= channel_threshold <= 255:
        raise ValueError("channel_threshold must be between 0 and 255")
    if reference.size() != actual.size():
        raise ValueError(
            "RGBA image dimensions differ: "
            f"reference={reference.width()}x{reference.height()}, "
            f"actual={actual.width()}x{actual.height()}"
        )

    reference_rgba = reference.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    actual_rgba = actual.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    width = reference_rgba.width()
    height = reference_rgba.height()
    pixel_count = width * height
    if pixel_count == 0:
        raise ValueError("RGBA images must contain at least one pixel")

    total_channel_difference = 0
    difference_mask = bytearray(pixel_count)
    for y in range(height):
        reference_row = reference_rgba.constScanLine(y)
        actual_row = actual_rgba.constScanLine(y)
        for x in range(width):
            offset = x * 4
            channel_differences = (
                abs(reference_row[offset + channel] - actual_row[offset + channel])
                for channel in range(4)
            )
            maximum = 0
            for difference in channel_differences:
                total_channel_difference += difference
                maximum = max(maximum, difference)
            if maximum > channel_threshold:
                difference_mask[y * width + x] = 1

    different_pixels = sum(difference_mask)
    largest_component = _largest_eight_connected_component(
        difference_mask,
        width,
        height,
    )
    return ImageComparison(
        width=width,
        height=height,
        channel_threshold=channel_threshold,
        mean_channel_difference=total_channel_difference / (pixel_count * 4),
        different_pixels=different_pixels,
        different_pixel_ratio=different_pixels / pixel_count,
        largest_component=largest_component,
        largest_component_ratio=largest_component / pixel_count,
    )


def _largest_eight_connected_component(
    mask: bytearray,
    width: int,
    height: int,
) -> int:
    largest = 0
    for seed in range(width * height):
        if not mask[seed]:
            continue
        mask[seed] = 0
        queue = deque([seed])
        component_size = 0
        while queue:
            current = queue.popleft()
            component_size += 1
            x = current % width
            y = current // width
            for neighbor_y in range(max(0, y - 1), min(height, y + 2)):
                for neighbor_x in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = neighbor_y * width + neighbor_x
                    if mask[neighbor]:
                        mask[neighbor] = 0
                        queue.append(neighbor)
        largest = max(largest, component_size)
    return largest


def assert_within_locked_tolerance(
    comparison: ImageComparison,
    tool_lock: dict[str, Any],
) -> None:
    reference = tool_lock["reference_environment"]
    failures = []
    if comparison.mean_channel_difference > reference["max_mean_channel_difference"]:
        failures.append(
            "mean channel difference "
            f"{comparison.mean_channel_difference:.6f} > "
            f"{reference['max_mean_channel_difference']}"
        )
    if comparison.different_pixel_ratio > reference["max_different_pixel_ratio"]:
        failures.append(
            f"different pixel ratio {comparison.different_pixel_ratio:.6%} > "
            f"{reference['max_different_pixel_ratio']:.6%}"
        )
    if (
        comparison.largest_component_ratio
        > reference["max_largest_component_ratio"]
    ):
        failures.append(
            "largest component ratio "
            f"{comparison.largest_component_ratio:.6%} > "
            f"{reference['max_largest_component_ratio']:.6%}"
        )
    if failures:
        raise AssertionError("; ".join(failures))
