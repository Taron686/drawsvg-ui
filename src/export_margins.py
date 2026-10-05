# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Validated drawing-unit margins shared by all export formats."""

from dataclasses import dataclass
import math

from PySide6 import QtCore


@dataclass(frozen=True)
class ExportMargins:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        for side in ("left", "top", "right", "bottom"):
            value = getattr(self, side)
            if not math.isfinite(value) or not 0 <= value <= 10000:
                raise ValueError(f"{side} margin must be finite and between 0 and 10000")


def expand_export_rect(
    content_rect: QtCore.QRectF, margins: ExportMargins
) -> QtCore.QRectF:
    """Add margins without changing content coordinates or rounding its bounds."""
    if content_rect.isEmpty() or not all(
        math.isfinite(value)
        for value in (*content_rect.getRect(), content_rect.right(), content_rect.bottom())
    ):
        raise ValueError("Export content rectangle must be finite with positive width and height")
    return content_rect.adjusted(-margins.left, -margins.top, margins.right, margins.bottom)
