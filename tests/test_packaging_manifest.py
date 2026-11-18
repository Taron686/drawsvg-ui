from __future__ import annotations

from pathlib import Path


def test_runtime_modules_are_discovered_instead_of_listed() -> None:
    """A hand-kept module list once dropped new modules from the wheel.

    setuptools' src-layout discovery packages every top-level module under
    ``src``; an explicit list or finder would silently switch that off.
    """
    project_root = Path(__file__).resolve().parents[1]
    pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")

    assert "py-modules" not in pyproject
    assert "[tool.setuptools.packages" not in pyproject
    assert (project_root / "src" / "main.py").is_file()
