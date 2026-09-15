"""Atomic persistence for validated native DrawSVG projects."""

from __future__ import annotations

import os
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

from document_format import PROJECT_JSON_PATH, ProjectDocument
from document_validator import (
    DEFAULT_LIMITS,
    ValidationLimits,
    encode_project_json,
    validate_project_archive,
    validate_project_document,
)


def save_project(
    path: str | Path,
    document: ProjectDocument,
    *,
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> None:
    """Validate and atomically replace *path* with a native project archive."""

    destination = Path(path)
    validated = validate_project_document(document, limits=limits)
    project_json = encode_project_json(validated.payload)
    destination.parent.mkdir(parents=False, exist_ok=True)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        _write_archive(temporary_path, project_json, validated)
        with temporary_path.open("r+b") as temporary_file:
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
        _sync_directory(destination.parent)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_project(
    path: str | Path,
    *,
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> ProjectDocument:
    """Return a complete project only after its entire archive has validated."""

    validated = validate_project_archive(path, limits=limits)
    return ProjectDocument(
        scene=deepcopy(validated.payload["scene"]),
        document_id=validated.payload["document_id"],
        assets=validated.assets,
        thumbnail=validated.thumbnail,
    )


def _write_archive(path: Path, project_json: bytes, validated) -> None:
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=False,
    ) as archive:
        archive.writestr(PROJECT_JSON_PATH, project_json)
        for asset in sorted(validated.assets, key=lambda value: value.archive_path):
            archive.writestr(asset.archive_path, asset.data)
        if validated.thumbnail is not None:
            archive.writestr(
                validated.payload["thumbnail"]["path"], validated.thumbnail
            )


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
