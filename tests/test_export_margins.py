from dataclasses import FrozenInstanceError

import pytest
from PySide6 import QtCore


@pytest.mark.parametrize(
    "content, sides, expected",
    [
        ((0, 0, 100, 50), (10, 5, 20, 15), (-10, -5, 130, 70)),
        ((-20.25, -10.5, 100.125, 50.75), (0, 0, 0, 0),
         (-20.25, -10.5, 100.125, 50.75)),
        ((-20.25, -10.5, 100.125, 50.75), (1.25, 2.5, 3.75, 4.125),
         (-21.5, -13, 105.125, 57.375)),
        ((0, 0, 100, 50), (10000, 10000, 10000, 10000),
         (-10000, -10000, 20100, 20050)),
    ],
)
def test_margins_expand_without_rounding_or_mutating_content(content, sides, expected):
    from export_margins import ExportMargins, expand_export_rect

    rect = QtCore.QRectF(*content)
    result = expand_export_rect(rect, ExportMargins(*sides))

    assert result.getRect() == pytest.approx(expected)
    assert rect.getRect() == content
    assert result is not rect


@pytest.mark.parametrize("side", ["left", "top", "right", "bottom"])
@pytest.mark.parametrize("value", [-0.01, 10000.01, float("nan"), float("inf"), -float("inf")])
def test_margins_reject_invalid_values_on_every_side(side, value):
    from export_margins import ExportMargins

    sides = dict(left=5, top=5, right=5, bottom=5)
    sides[side] = value
    with pytest.raises(ValueError, match=side):
        ExportMargins(**sides)


def test_margins_cannot_be_mutated_after_validation():
    from export_margins import ExportMargins

    margins = ExportMargins(1, 2, 3, 4)
    with pytest.raises(FrozenInstanceError):
        margins.left = -1


@pytest.mark.parametrize(
    "content",
    [(0, 0, 0, 10), (0, 0, 10, 0), (0, 0, -1, 10), (0, 0, 10, -1),
     (float("nan"), 0, 10, 10), (0, float("inf"), 10, 10),
     (0, 0, float("inf"), 10), (0, 0, 10, float("nan"))],
)
def test_margins_reject_empty_or_nonfinite_content(content):
    from export_margins import ExportMargins, expand_export_rect

    with pytest.raises(ValueError, match="content"):
        expand_export_rect(QtCore.QRectF(*content), ExportMargins(5, 5, 5, 5))
