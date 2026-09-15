from __future__ import annotations

from PySide6 import QtWidgets

from property_command_service import PropertyDescriptor, PropertyRegistry


def test_subclass_descriptor_overrides_a_base_descriptor(application) -> None:
    registry = PropertyRegistry()
    base = PropertyDescriptor("value", int, lambda item: 1, lambda item, value: True)
    specialized = PropertyDescriptor(
        "value", str, lambda item: "rect", lambda item, value: True
    )
    registry.register(QtWidgets.QGraphicsItem, base)
    registry.register(QtWidgets.QGraphicsRectItem, specialized)

    descriptor = registry.descriptor_for(QtWidgets.QGraphicsRectItem(), "value")

    assert descriptor is specialized
