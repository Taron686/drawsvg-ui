# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from PySide6 import QtCore

if TYPE_CHECKING:
    from canvas_view import CanvasView


class UndoTransactionManager:
    """Run one callback when the outermost undo transaction completes."""

    def __init__(
        self,
        on_outer_begin: Callable[[], None],
        on_outer_end: Callable[[], None],
    ) -> None:
        self._depth = 0
        self._on_outer_begin = on_outer_begin
        self._on_outer_end = on_outer_end

    def begin(self) -> None:
        if self._depth == 0:
            self._on_outer_begin()
        self._depth += 1

    def end(self) -> None:
        if self._depth == 0:
            raise RuntimeError("Undo transaction ended without a matching begin")
        self._depth -= 1
        if self._depth == 0:
            self._on_outer_end()

    @property
    def active(self) -> bool:
        return self._depth > 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.begin()
        try:
            yield
        finally:
            self.end()


class SceneHistory(QtCore.QObject):
    historyChanged = QtCore.Signal(bool, bool)
    snapshotSerialized = QtCore.Signal(str)

    def __init__(
        self,
        view: CanvasView,
        *,
        max_states: int = 50,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._max_states = max(1, int(max_states))
        self._max_bytes = max(1, int(max_bytes))
        self._states: list[str] = []
        self._history_bytes = 0
        self._index = -1
        self._ignore_changes = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._capture_snapshot)
        self._transactions = UndoTransactionManager(
            self._begin_transaction,
            self._end_transaction,
        )
        scene = view.scene()
        if scene is not None:
            scene.changed.connect(self._on_scene_changed)

    def capture_initial_state(self) -> None:
        if self._ignore_changes:
            return
        # Serialize before replacing history so a failure retains Undo and Redo.
        state_str = self._serialize_state()
        state_bytes = len(state_str.encode("utf-8"))
        self._timer.stop()
        self._states = [state_str] if state_bytes <= self._max_bytes else []
        self._history_bytes = state_bytes if self._states else 0
        self._index = len(self._states) - 1
        self._notify()

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Pause recording across scene replacement and any necessary rollback."""
        previous = self._ignore_changes
        self._ignore_changes = True
        self._timer.stop()
        try:
            yield
        finally:
            self._ignore_changes = previous

    @property
    def history_bytes(self) -> int:
        """Current UTF-8 size of retained serialized history snapshots."""
        return self._history_bytes

    def mark_dirty(self) -> None:
        if self._ignore_changes:
            return
        if self.transaction_active:
            return
        self._timer.start()

    def capture_now(self) -> None:
        self._capture_snapshot()

    def begin_transaction(self) -> None:
        self._transactions.begin()

    def end_transaction(self) -> None:
        self._transactions.end()

    @property
    def transaction_active(self) -> bool:
        return self._transactions.active

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._transactions.transaction():
            yield

    def undo(self) -> None:
        # Only capture at the tip. Capturing an older state would discard redo.
        if (
            not self._ignore_changes
            and not self.transaction_active
            and self._timer.isActive()
            and self._index == len(self._states) - 1
        ):
            self._timer.stop()
            self._capture_snapshot()
        if not self.can_undo():
            return
        self._index -= 1
        self._apply_current_state()
        self._notify()

    def redo(self) -> None:
        if not self.can_redo():
            return
        self._index += 1
        self._apply_current_state()
        self._notify()

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return 0 <= self._index < len(self._states) - 1

    def _notify(self) -> None:
        self.historyChanged.emit(self.can_undo(), self.can_redo())

    def _on_scene_changed(self, _region: list[QtCore.QRectF]) -> None:  # type: ignore[override]
        if self._ignore_changes:
            return
        if self.transaction_active:
            return
        self._timer.start()

    def _begin_transaction(self) -> None:
        if self._ignore_changes:
            return
        if self._timer.isActive():
            self._timer.stop()
            self._capture_snapshot()

    def _end_transaction(self) -> None:
        if self._ignore_changes:
            return
        self._timer.stop()
        self._capture_snapshot()

    def _serialize_state(self) -> str:
        state = self._view.serialize_scene_state()
        return json.dumps(state, sort_keys=True, separators=(",", ":"))

    def _capture_snapshot(self, force: bool = False) -> None:
        if self._ignore_changes:
            return
        try:
            state_str = self._serialize_state()
        except Exception:
            logging.getLogger("canvas_view").exception(
                "Could not capture scene history"
            )
            return
        self.snapshotSerialized.emit(state_str)
        if not force and self._index >= 0 and self._states[self._index] == state_str:
            return
        state_bytes = len(state_str.encode("utf-8"))
        if state_bytes > self._max_bytes:
            return
        if self._index < len(self._states) - 1:
            self._history_bytes -= sum(
                len(snapshot.encode("utf-8"))
                for snapshot in self._states[self._index + 1 :]
            )
            self._states = self._states[: self._index + 1]
        self._states.append(state_str)
        self._history_bytes += state_bytes
        if len(self._states) > self._max_states:
            overflow = len(self._states) - self._max_states
            self._history_bytes -= sum(
                len(snapshot.encode("utf-8")) for snapshot in self._states[:overflow]
            )
            self._states = self._states[overflow:]
            self._index = len(self._states) - 1
        while self._history_bytes > self._max_bytes and len(self._states) > 1:
            self._history_bytes -= len(self._states[0].encode("utf-8"))
            self._states.pop(0)
        self._index = len(self._states) - 1
        self._notify()

    def _apply_current_state(self) -> None:
        if not (0 <= self._index < len(self._states)):
            return
        state_str = self._states[self._index]
        state = json.loads(state_str)
        self._ignore_changes = True
        self._timer.stop()
        try:
            self._view.restore_scene_state(state)
        finally:
            self._ignore_changes = False
