"""Versioned data contract for native ``.drawsvg`` project files."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

PROJECT_FORMAT = "drawsvg-ui-project"
CURRENT_FORMAT_VERSION = 1
PROJECT_JSON_PATH = "project.json"
ASSET_DIRECTORY = "assets"
THUMBNAIL_PATH = "thumbnail.png"


class DocumentFormatError(ValueError):
    """Base error for malformed or unsupported project data."""


class UnsupportedFormatVersionError(DocumentFormatError):
    """Raised when a project has no supported migration path."""


@dataclass(frozen=True)
class ProjectAsset:
    """One named binary asset stored below ``assets/`` in the archive."""

    name: str
    data: bytes
    media_type: str = "application/octet-stream"

    @property
    def archive_path(self) -> str:
        return f"{ASSET_DIRECTORY}/{self.name}"


@dataclass(frozen=True)
class ProjectDocument:
    """A fully loaded project that is safe to publish to the UI."""

    scene: Mapping[str, Any]
    document_id: str = field(default_factory=lambda: str(uuid4()))
    assets: tuple[ProjectAsset, ...] = ()
    thumbnail: bytes | None = None

    def __post_init__(self) -> None:
        try:
            normalized_id = str(UUID(self.document_id))
        except (AttributeError, TypeError, ValueError) as error:
            raise DocumentFormatError("Invalid document UUID") from error
        object.__setattr__(self, "document_id", normalized_id)


Migration = Callable[[dict[str, Any]], dict[str, Any]]

# Add migrations as ``old_version: migrate_to_next_version``. There was no native
# project format before version 1, so the initial registry is intentionally empty.
_MIGRATIONS: dict[int, Migration] = {}


def migrate_project_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a current-version copy of *payload* or reject unsupported versions."""

    migrated = deepcopy(dict(payload))
    version = migrated.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise UnsupportedFormatVersionError("Invalid project format version")
    if version > CURRENT_FORMAT_VERSION:
        raise UnsupportedFormatVersionError(
            f"Project format version {version} is newer than supported version "
            f"{CURRENT_FORMAT_VERSION}"
        )

    while version < CURRENT_FORMAT_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            raise UnsupportedFormatVersionError(
                f"No migration path from project format version {version}"
            )
        migrated = migration(migrated)
        next_version = migrated.get("format_version")
        if next_version != version + 1:
            raise DocumentFormatError(
                f"Migration from version {version} did not advance exactly one version"
            )
        version = next_version

    return migrated
