# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Per-window document state and application-wide window registration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import uuid4

from PySide6 import QtCore

from app_logging import hash_path, log_exception
from asset_service import BitmapAssetService
from document_format import ProjectDocument
from document_io import load_project, save_project
from recovery import RecoveryCandidate, RecoveryStore, scene_fingerprint

if TYPE_CHECKING:
    from canvas_view import CanvasView


DocumentBaseline = Literal["saved", "blank", "unsaved", "recovered"]


class DocumentReplacementError(RuntimeError):
    """Replacement and rollback both failed; the remaining scene is detached."""

    def __init__(self, original_error: Exception, rollback_error: Exception) -> None:
        super().__init__("Document replacement and rollback failed; reopen the previous document")
        self.original_error = original_error
        self.rollback_error = rollback_error
        self.rollback_failed = True


def canonical_document_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


class DocumentWindow(Protocol):
    document_controller: "DocumentController"

    def activateWindow(self) -> None: ...

    def raise_(self) -> None: ...


class DocumentWindowRegistry:
    """Keep one live editor window per native project path."""

    def __init__(self) -> None:
        self._windows: list[DocumentWindow] = []
        self.quitting = False
        self.startup_recovery_checked = False

    def register(self, window: DocumentWindow) -> None:
        if window not in self._windows:
            self._windows.append(window)

    def unregister(self, window: DocumentWindow) -> None:
        try:
            self._windows.remove(window)
        except ValueError:
            pass

    def windows(self) -> tuple[DocumentWindow, ...]:
        return tuple(self._windows)

    def window_for_path(self, path: str | Path) -> DocumentWindow | None:
        key = canonical_document_path(path)
        for window in self._windows:
            document_path = window.document_controller.path
            if document_path is not None and canonical_document_path(document_path) == key:
                return window
        return None


class DocumentController(QtCore.QObject):
    """Own one canvas document, its saved baseline, and its recovery timer."""

    dirtyChanged = QtCore.Signal(bool)
    pathChanged = QtCore.Signal(object)
    documentIdChanged = QtCore.Signal(str)

    def __init__(
        self,
        canvas: "CanvasView",
        *,
        recovery_store: RecoveryStore | None = None,
        recovery_interval_ms: int = 30_000,
        recovery_enabled: bool = True,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._recovery_store = recovery_store or RecoveryStore()
        self._recovery_enabled = recovery_enabled
        self._document_id = str(uuid4())
        self._path: Path | None = None
        self._dirty = False
        self._refreshing = False
        self._applying = False
        self._revision = 0
        self._last_observed_fingerprint = self._fingerprint()
        self._saved_fingerprint: str | None = self._last_observed_fingerprint
        self._last_recovery_fingerprint: str | None = None

        self._dirty_timer = QtCore.QTimer(self)
        self._dirty_timer.setSingleShot(True)
        self._dirty_timer.setInterval(0)
        self._dirty_timer.timeout.connect(self.refresh_dirty_state)
        scene = self._canvas.scene()
        if scene is not None:
            scene.changed.connect(self._schedule_dirty_refresh)
        self._canvas.gridVisibilityChanged.connect(self._schedule_dirty_refresh)

        self._recovery_timer = QtCore.QTimer(self)
        self._recovery_timer.setInterval(max(1, int(recovery_interval_ms)))
        self._recovery_timer.timeout.connect(self.write_recovery_if_needed)
        if self._recovery_enabled:
            self._recovery_timer.start()

    @property
    def document_id(self) -> str:
        return self._document_id

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def recovery_store(self) -> RecoveryStore:
        return self._recovery_store

    def project_document(self) -> ProjectDocument:
        return ProjectDocument(
            scene=self._canvas._serialize_scene_state(),
            document_id=self._document_id,
            assets=self._canvas.bitmap_assets(),
        )

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self._path
        if destination is None:
            raise ValueError("A destination is required for an unsaved document")
        destination = destination.expanduser().resolve()
        try:
            self._canvas.history().capture_now()
            document = self.project_document()
            save_project(destination, document)
        except Exception as error:
            log_exception(
                "document.unsaved",
                error,
                component="document",
                path_hash=hash_path(str(destination)),
            )
            raise
        old_path = self._path
        self._path = destination
        fingerprint = scene_fingerprint(document.scene)
        self._saved_fingerprint = fingerprint
        self._last_observed_fingerprint = fingerprint
        self._last_recovery_fingerprint = None
        self._set_dirty(False)
        self._recovery_store.discard(self._document_id)
        if old_path != self._path:
            self.pathChanged.emit(self._path)
        return destination

    def load(self, path: str | Path) -> Path:
        source = Path(path).expanduser().resolve()
        try:
            document = load_project(source)
            self.replace_document(document, source_path=source, baseline="saved")
        except Exception as error:
            log_exception(
                "document.invalid",
                error,
                component="document",
                path_hash=hash_path(str(source)),
            )
            raise
        return source

    def restore_recovery(self, candidate: RecoveryCandidate) -> None:
        try:
            document = self._recovery_store.load(candidate)
            self.replace_document(
                document,
                source_path=candidate.source_path,
                baseline="recovered",
                recovery_revision=candidate.revision,
            )
        except Exception as error:
            log_exception(
                "document.invalid",
                error,
                component="recovery",
                error_code="recovery-load",
            )
            raise

    def mark_imported(self) -> None:
        old_path = self._path
        self._path = None
        self._canvas.history().capture_initial_state()
        fingerprint = self._fingerprint()
        self._last_observed_fingerprint = fingerprint
        self._saved_fingerprint = None
        self._last_recovery_fingerprint = None
        self._revision = max(1, self._revision)
        self._set_dirty(True)
        if old_path is not None:
            self.pathChanged.emit(None)

    def refresh_dirty_state(self, *, force_dirty: bool = False) -> None:
        if self._refreshing or self._applying:
            return
        self._refreshing = True
        try:
            try:
                fingerprint = self._fingerprint()
            except Exception as error:
                self._last_observed_fingerprint = None
                self._set_dirty(True)
                log_exception("document.invalid", error, component="document")
                return
            if fingerprint != self._last_observed_fingerprint:
                self._revision += 1
                self._last_observed_fingerprint = fingerprint
            self._set_dirty(force_dirty or fingerprint != self._saved_fingerprint)
        finally:
            self._refreshing = False

    def write_recovery_if_needed(self) -> bool:
        if not self._recovery_enabled or self._applying:
            return False
        self.refresh_dirty_state()
        fingerprint = self._last_observed_fingerprint
        if fingerprint is None or not self._dirty or fingerprint == self._last_recovery_fingerprint:
            return False
        try:
            self._recovery_store.write(
                self.project_document(),
                source_path=self._path,
                revision=self._revision,
                fingerprint=fingerprint,
            )
        except Exception as error:
            fields = (
                {"path_hash": hash_path(str(self._path))}
                if self._path is not None
                else {}
            )
            log_exception("document.unsaved", error, component="recovery", **fields)
            return False
        self._last_recovery_fingerprint = fingerprint
        return True

    def discard_recovery(self) -> None:
        self._recovery_store.discard(self._document_id)

    def replace_document(
        self,
        document: ProjectDocument,
        *,
        source_path: Path | None,
        baseline: DocumentBaseline,
        recovery_revision: int = 0,
    ) -> None:
        """Adopt a prepared document after the caller has resolved unsaved edits."""
        if baseline not in {"saved", "blank", "unsaved", "recovered"}:
            raise ValueError("Unknown document baseline")
        if baseline == "saved" and (source_path is None or not source_path.is_absolute()):
            raise ValueError("A saved document requires an absolute source path")
        if baseline in {"blank", "unsaved"} and source_path is not None:
            raise ValueError("An unsaved document cannot have a source path")
        self._canvas._validate_scene_state(document.scene)
        BitmapAssetService(document.assets)
        previous = self.project_document()
        transform = self._canvas.transform()
        scroll = (self._canvas.horizontalScrollBar().value(), self._canvas.verticalScrollBar().value())
        history = self._canvas.history()

        def rollback(original_error: Exception) -> None:
            try:
                self._canvas.set_bitmap_assets(previous.assets)
                self._canvas._restore_scene_state(previous.scene)
                self._canvas.setTransform(transform)
                self._canvas.horizontalScrollBar().setValue(scroll[0])
                self._canvas.verticalScrollBar().setValue(scroll[1])
                self._canvas._notify_selection_snapshot()
            except Exception as rollback_error:
                self._detach_failed_replacement()
                log_exception(
                    "document.invalid", rollback_error,
                    component="document", error_code="replacement-rollback",
                )
                raise DocumentReplacementError(original_error, rollback_error) from original_error

        self._applying = True
        self._dirty_timer.stop()
        try:
            with history.suspended():
                try:
                    self._canvas.set_bitmap_assets(document.assets)
                    self._canvas._restore_scene_state(document.scene)
                    fingerprint = self._fingerprint()
                except Exception as error:
                    rollback(error)
                    raise
            try:
                history.capture_initial_state()
            except Exception as error:
                with history.suspended():
                    rollback(error)
                raise
        finally:
            self._applying = False
            self._dirty_timer.stop()
        old_document_id = self._document_id
        old_path = self._path
        self._document_id = document.document_id
        self._path = source_path
        self._last_observed_fingerprint = fingerprint
        self._saved_fingerprint = fingerprint if baseline in {"saved", "blank"} else None
        self._last_recovery_fingerprint = fingerprint if baseline == "recovered" else None
        self._revision = max(1, recovery_revision) if baseline == "recovered" else int(baseline == "unsaved")
        self._set_dirty(baseline in {"unsaved", "recovered"})
        if old_document_id != self._document_id:
            self.documentIdChanged.emit(self._document_id)
            self._recovery_store.discard(old_document_id)
        if old_path != self._path:
            self.pathChanged.emit(self._path)
        self._canvas._notify_selection_snapshot()

    def _detach_failed_replacement(self) -> None:
        """Protect original files even if the remaining scene cannot serialize."""
        self._path = None
        self._document_id = str(uuid4())
        self._saved_fingerprint = None
        self._last_recovery_fingerprint = None
        self._revision = max(1, self._revision + 1)
        try:
            self._last_observed_fingerprint = self._fingerprint()
        except Exception:
            self._last_observed_fingerprint = None
        self._set_dirty(True)
        self.pathChanged.emit(None)
        self.documentIdChanged.emit(self._document_id)
        self._canvas.scene().clearSelection()
        self._canvas._notify_selection_snapshot()

    def _schedule_dirty_refresh(self, *_args: object) -> None:
        if not self._applying:
            self._dirty_timer.start()

    def _fingerprint(self) -> str:
        return scene_fingerprint(self._canvas._serialize_scene_state())

    def _set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self.dirtyChanged.emit(dirty)
