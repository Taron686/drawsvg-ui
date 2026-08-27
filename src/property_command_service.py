"""Typed, undo-aware property edits for one or more graphics items.

The service deliberately owns no canvas or widget references.  Callers provide the
selected items and a history object with a ``transaction()`` context manager.  This
makes the command boundary usable by the properties panel now and by future canvas
integration without coupling it to SceneCodec or CanvasView.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Protocol

from PySide6 import QtWidgets


class TransactionalHistory(Protocol):
    """Minimal history contract used to create one undo step per command."""

    def transaction(self) -> AbstractContextManager[None]: ...


Validator = Callable[[Any], bool]
Getter = Callable[[QtWidgets.QGraphicsItem], Any]
Setter = Callable[[QtWidgets.QGraphicsItem, Any], bool]


@dataclass(frozen=True)
class PropertyDescriptor:
    """A typed, item-local property that can be changed by a command."""

    key: str
    value_type: type[Any] | tuple[type[Any], ...]
    getter: Getter
    setter: Setter
    validator: Validator | None = None

    def accepts(self, value: Any) -> bool:
        if not isinstance(value, self.value_type):
            return False
        return self.validator(value) if self.validator is not None else True


class PropertyRegistry:
    """Maps graphics-item types to descriptors available for their properties."""

    def __init__(self) -> None:
        self._descriptors: dict[
            type[QtWidgets.QGraphicsItem], tuple[PropertyDescriptor, ...]
        ] = {}

    def register(
        self,
        item_type: type[QtWidgets.QGraphicsItem],
        *descriptors: PropertyDescriptor,
    ) -> None:
        self._descriptors[item_type] = tuple(descriptors)

    def descriptors_for(
        self, item: QtWidgets.QGraphicsItem
    ) -> tuple[PropertyDescriptor, ...]:
        descriptors: dict[str, PropertyDescriptor] = {}
        for item_type in reversed(type(item).__mro__):
            for descriptor in self._descriptors.get(item_type, ()):
                descriptors[descriptor.key] = descriptor
        return tuple(descriptors.values())

    def descriptor_for(
        self, item: QtWidgets.QGraphicsItem, key: str
    ) -> PropertyDescriptor | None:
        return next(
            (
                descriptor
                for descriptor in self.descriptors_for(item)
                if descriptor.key == key
            ),
            None,
        )


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _set_x(item: QtWidgets.QGraphicsItem, value: Any) -> bool:
    target = float(value)
    if math.isclose(item.x(), target, abs_tol=0.1):
        return False
    item.setX(target)
    return True


def _set_y(item: QtWidgets.QGraphicsItem, value: Any) -> bool:
    target = float(value)
    if math.isclose(item.y(), target, abs_tol=0.1):
        return False
    item.setY(target)
    return True


def _set_rotation(item: QtWidgets.QGraphicsItem, value: Any) -> bool:
    target = float(value)
    if math.isclose(item.rotation(), target, abs_tol=0.1):
        return False
    item.setRotation(target)
    return True


def _set_scale(item: QtWidgets.QGraphicsItem, value: Any) -> bool:
    target = float(value)
    if target <= 0.0 or math.isclose(item.scale(), target, rel_tol=1e-3, abs_tol=1e-3):
        return False
    item.setScale(target)
    return True


def _set_z_value(item: QtWidgets.QGraphicsItem, value: Any) -> bool:
    target = float(value)
    if math.isclose(item.zValue(), target, abs_tol=0.01):
        return False
    item.setZValue(target)
    return True


def default_property_registry() -> PropertyRegistry:
    """Return descriptors that every ``QGraphicsItem`` supports."""

    registry = PropertyRegistry()
    registry.register(
        QtWidgets.QGraphicsItem,
        PropertyDescriptor(
            "position_x",
            (int, float),
            lambda item: float(item.x()),
            _set_x,
            _is_finite_number,
        ),
        PropertyDescriptor(
            "position_y",
            (int, float),
            lambda item: float(item.y()),
            _set_y,
            _is_finite_number,
        ),
        PropertyDescriptor(
            "rotation",
            (int, float),
            lambda item: float(item.rotation()),
            _set_rotation,
            _is_finite_number,
        ),
        PropertyDescriptor(
            "scale",
            (int, float),
            lambda item: float(item.scale()),
            _set_scale,
            lambda value: _is_finite_number(value) and float(value) > 0.0,
        ),
        PropertyDescriptor(
            "z_value",
            (int, float),
            lambda item: float(item.zValue()),
            _set_z_value,
            _is_finite_number,
        ),
    )
    return registry


class PropertyCommandService:
    """Validate and apply a property command as one history transaction.

    ``locked`` is intentionally a duck-typed item attribute.  T-024 will own the
    persisted layer lock model; this boundary already makes items exposing that
    attribute read-only and safely skips them in mixed selections.
    """

    def __init__(
        self,
        history: TransactionalHistory | None = None,
        *,
        registry: PropertyRegistry | None = None,
        is_locked: Callable[[QtWidgets.QGraphicsItem], bool] | None = None,
    ) -> None:
        self._history = history
        self._registry = registry or default_property_registry()
        self._is_locked = is_locked or self._default_is_locked

    @staticmethod
    def _default_is_locked(item: QtWidgets.QGraphicsItem) -> bool:
        value = getattr(item, "locked", False)
        return bool(value() if callable(value) else value)

    def descriptors_for(
        self, items: Iterable[QtWidgets.QGraphicsItem]
    ) -> tuple[PropertyDescriptor, ...]:
        selected = tuple(items)
        if not selected:
            return ()
        first = self._registry.descriptors_for(selected[0])
        return tuple(
            descriptor
            for descriptor in first
            if all(
                self._registry.descriptor_for(item, descriptor.key) is not None
                for item in selected[1:]
            )
        )

    def common_value(
        self, items: Iterable[QtWidgets.QGraphicsItem], key: str
    ) -> Any | None:
        selected = tuple(items)
        if not selected:
            return None
        descriptor = self._registry.descriptor_for(selected[0], key)
        if descriptor is None:
            return None
        value = descriptor.getter(selected[0])
        for item in selected[1:]:
            candidate = self._registry.descriptor_for(item, key)
            if candidate is None or candidate.getter(item) != value:
                return None
        return value

    def can_write(self, items: Iterable[QtWidgets.QGraphicsItem]) -> bool:
        return any(not self._is_locked(item) for item in items)

    def apply(
        self, items: Iterable[QtWidgets.QGraphicsItem], key: str, value: Any
    ) -> bool:
        """Apply ``key=value`` to every writable compatible item in one undo step."""

        selected = tuple(items)
        if not selected:
            return False
        descriptors = [
            (item, self._registry.descriptor_for(item, key)) for item in selected
        ]
        if any(descriptor is None for _, descriptor in descriptors):
            raise KeyError(f"Property '{key}' is not available for every selected item")
        if not all(
            descriptor is not None and descriptor.accepts(value)
            for _, descriptor in descriptors
        ):
            raise ValueError(f"Invalid value for property '{key}'")

        writable = [
            (item, item_descriptor)
            for item, item_descriptor in descriptors
            if not self._is_locked(item)
        ]
        if not writable:
            return False
        if all(
            item_descriptor.getter(item) == value
            for item, item_descriptor in writable
            if item_descriptor is not None
        ):
            return False
        transaction = (
            self._history.transaction() if self._history is not None else nullcontext()
        )
        with transaction:
            changed = False
            for item, item_descriptor in writable:
                if item_descriptor is not None:
                    changed = item_descriptor.setter(item, value) or changed
            return changed
