from __future__ import annotations

import re
from pathlib import Path


def test_all_top_level_runtime_modules_are_packaged() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"py-modules\s*=\s*\[(.*?)\]", pyproject, flags=re.DOTALL)
    assert match is not None

    declared = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', match.group(1)))
    runtime_modules = {
        path.stem
        for path in (project_root / "src").glob("*.py")
        if path.stem != "__init__"
    }

    assert declared == runtime_modules
