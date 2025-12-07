# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Optional

PACKAGE_NAME = "drawsvg-ui"
GITHUB_URL = "https://github.com/Taron686/UI_drawsvg"


def get_version() -> str:
    """
    Resolve the application version from installed metadata when available.
    Falls back to reading pyproject.toml so running from a checkout still shows a version.
    """
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        pass

    version = _read_version_from_pyproject()
    return version or "0.0.0"


def _read_version_from_pyproject() -> Optional[str]:
    """Best-effort lookup of the version field in pyproject.toml when running from source."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject_path.is_file():
        return None

    try:
        content = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Prefer tomllib when available (Python 3.11+ or backport)
    try:
        import tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None

    if tomllib is not None:
        try:
            data = tomllib.loads(content)
            project = data.get("project", {})
            version = project.get("version")
            if version:
                return str(version)
        except Exception:
            pass

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("version"):
            continue
        _, _, remainder = stripped.partition("=")
        candidate = remainder.strip().strip('"').strip("'")
        if candidate:
            return candidate

    return None
