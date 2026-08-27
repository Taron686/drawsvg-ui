from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_runtime_logging_module(tmp_path: Path) -> None:
    """The GUI entry point's logging dependency must ship in the wheel."""
    wheel_dir = tmp_path / "wheelhouse"
    wheel_dir.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(PROJECT_ROOT),
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        assert "app_logging.py" in archive.namelist()
