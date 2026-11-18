# SPDX-License-Identifier: GPL-2.0-or-later

from collections.abc import Iterable

from PySide6 import QtWidgets

from connectors import ConnectorItem


def align_items(
    items: Iterable[QtWidgets.QGraphicsItem], mode: str, grid_size: float
) -> None:
    items = [item for item in items if not isinstance(item, ConnectorItem)]
    if not items:
        return
    bounds = [item.sceneBoundingRect() for item in items]
    if mode == "grid":
        for item, rect in zip(items, bounds):
            x = round(rect.left() / grid_size) * grid_size
            y = round(rect.top() / grid_size) * grid_size
            item.moveBy(x - rect.left(), y - rect.top())
        return
    if mode in ("left", "hcenter", "right"):
        values = {
            "left": [rect.left() for rect in bounds],
            "hcenter": [rect.center().x() for rect in bounds],
            "right": [rect.right() for rect in bounds],
        }[mode]
        target = (
            min(values)
            if mode == "left"
            else max(values)
            if mode == "right"
            else sum(values) / len(values)
        )
        for item, value in zip(items, values):
            item.moveBy(target - value, 0)
    elif mode in ("top", "vcenter", "bottom"):
        values = {
            "top": [rect.top() for rect in bounds],
            "vcenter": [rect.center().y() for rect in bounds],
            "bottom": [rect.bottom() for rect in bounds],
        }[mode]
        target = (
            min(values)
            if mode == "top"
            else max(values)
            if mode == "bottom"
            else sum(values) / len(values)
        )
        for item, value in zip(items, values):
            item.moveBy(0, target - value)
