"""Document-scoped recovery archives for native DrawSVG projects."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from PySide6 import QtCore

from document_format import ProjectDocument
from document_io import load_project, save_project

_METADATA_VERSION = 1


def scene_fingerprint(scene: Any) -> str:
    """Return a stable digest without retaining drawing contents in metadata."""

    payload = json.dumps(scene, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def default_recovery_directory() -> Path:
    data_dir = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data_dir) / "recovery"


@dataclass(frozen=True)
class RecoveryCandidate:
    document_id: str
    archive_path: Path
    metadata_path: Path
    source_path: Path | None
    revision: int
    fingerprint: str
    recovered_at_ns: int

    @property
    def display_name(self) -> str:
        if self.source_path is not None:
            return self.source_path.name
        return f"Untitled ({self.document_id[:8]})"


class RecoveryStore:
    """Persist and discover independent recovery data by document UUID."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_recovery_directory()

    def write(
        self,
        document: ProjectDocument,
        *,
        source_path: str | Path | None,
        revision: int,
        fingerprint: str,
    ) -> RecoveryCandidate:
        document_id = str(UUID(document.document_id))
        archive_path, metadata_path = self._paths(document_id)
        self.root.mkdir(parents=True, exist_ok=True)
        save_project(archive_path, document)
        recovered_at_ns = time.time_ns()
        normalized_source = (
            str(Path(source_path).expanduser().resolve())
            if source_path is not None
            else None
        )
        metadata = {
            "version": _METADATA_VERSION,
            "document_id": document_id,
            "source_path": normalized_source,
            "revision": int(revision),
            "fingerprint": str(fingerprint),
            "recovered_at_ns": recovered_at_ns,
        }
        self._write_metadata(metadata_path, metadata)
        return RecoveryCandidate(
            document_id=document_id,
            archive_path=archive_path,
            metadata_path=metadata_path,
            source_path=Path(normalized_source) if normalized_source is not None else None,
            revision=int(revision),
            fingerprint=str(fingerprint),
            recovered_at_ns=recovered_at_ns,
        )

    def candidates(self) -> tuple[RecoveryCandidate, ...]:
        try:
            metadata_paths = tuple(self.root.glob("*.json"))
        except OSError:
            return ()
        candidates = [
            candidate
            for metadata_path in metadata_paths
            if (candidate := self._read_candidate(metadata_path)) is not None
            and self._is_newer_or_orphaned(candidate)
        ]
        candidates.sort(key=lambda value: value.recovered_at_ns, reverse=True)
        return tuple(candidates)

    def load(self, candidate: RecoveryCandidate) -> ProjectDocument:
        document = load_project(candidate.archive_path)
        if document.document_id != candidate.document_id:
            raise ValueError("Recovery document UUID does not match its metadata")
        if scene_fingerprint(document.scene) != candidate.fingerprint:
            raise ValueError("Recovery contents do not match their metadata")
        return document

    def discard(self, document_id: str) -> None:
        archive_path, metadata_path = self._paths(str(UUID(document_id)))
        for path in (archive_path, metadata_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _paths(self, document_id: str) -> tuple[Path, Path]:
        safe_id = str(UUID(document_id))
        return self.root / f"{safe_id}.drawsvg", self.root / f"{safe_id}.json"

    @staticmethod
    def _write_metadata(path: Path, metadata: dict[str, object]) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                json.dump(metadata, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, path)
        except BaseException:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def _read_candidate(self, metadata_path: Path) -> RecoveryCandidate | None:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict) or metadata.get("version") != 1:
                return None
            document_id = str(UUID(str(metadata["document_id"])))
            revision = metadata["revision"]
            fingerprint = metadata["fingerprint"]
            recovered_at_ns = metadata["recovered_at_ns"]
            source_value = metadata.get("source_path")
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 0
                or not isinstance(fingerprint, str)
                or len(fingerprint) != 64
                or isinstance(recovered_at_ns, bool)
                or not isinstance(recovered_at_ns, int)
                or recovered_at_ns < 0
                or source_value is not None
                and not isinstance(source_value, str)
            ):
                return None
            archive_path, expected_metadata_path = self._paths(document_id)
            if metadata_path.resolve() != expected_metadata_path.resolve():
                return None
            if not archive_path.is_file():
                return None
            return RecoveryCandidate(
                document_id=document_id,
                archive_path=archive_path,
                metadata_path=metadata_path,
                source_path=Path(source_value) if source_value is not None else None,
                revision=revision,
                fingerprint=fingerprint,
                recovered_at_ns=recovered_at_ns,
            )
        except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _is_newer_or_orphaned(candidate: RecoveryCandidate) -> bool:
        source_path = candidate.source_path
        if source_path is None:
            return True
        try:
            return candidate.recovered_at_ns > source_path.stat().st_mtime_ns
        except OSError:
            return True
