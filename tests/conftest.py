from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import pytest
from PySide6 import QtWidgets

from canvas_view import CanvasView


@pytest.fixture(scope="session")
def application() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas_view(application: QtWidgets.QApplication) -> Iterator[CanvasView]:
    view = CanvasView()
    yield view
    view.close()
