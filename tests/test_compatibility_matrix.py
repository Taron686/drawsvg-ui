from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PySide6 import QtWidgets

from canvas_view import CanvasView
from document_format import CURRENT_FORMAT_VERSION, PROJECT_JSON_PATH, UnsupportedFormatVersionError
from document_io import load_project, save_project
from import_drawsvg import import_drawsvg_py


FIXTURE_DIRECTORY = Path(__file__).with_name("fixtures") / "compatibility"
SUPPORTED_PROJECT_FIXTURES = (
    "project-v1-baseline.json",
    "project-v1-wave5.json",
)


def _project_payload(name: str) -> dict:
    return json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))


def _write_project_fixture(path: Path, payload: dict) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PROJECT_JSON_PATH, json.dumps(payload))


@pytest.mark.parametrize("fixture_name", SUPPORTED_PROJECT_FIXTURES)
def test_supported_v1_projects_load_and_resave_with_current_writer(
    application: QtWidgets.QApplication, tmp_path: Path, fixture_name: str
) -> None:
    payload = _project_payload(fixture_name)
    source = tmp_path / fixture_name.replace(".json", ".drawsvg")
    upgraded = tmp_path / f"upgraded-{source.name}"
    _write_project_fixture(source, payload)

    loaded = load_project(source)
    canvas = CanvasView()
    canvas._restore_scene_state(loaded.scene)
    save_project(upgraded, loaded)

    with zipfile.ZipFile(upgraded) as archive:
        persisted = json.loads(archive.read(PROJECT_JSON_PATH))
    assert loaded.document_id == payload["document_id"]
    assert loaded.scene == payload["scene"]
    assert any(item.data(0) == payload["scene"]["items"][0]["type_id"] for item in canvas.scene().items())
    assert persisted["format_version"] == CURRENT_FORMAT_VERSION
    assert persisted["scene"] == payload["scene"]


def test_future_project_fixture_has_an_actionable_version_error(tmp_path: Path) -> None:
    source = tmp_path / "project-v2-future.drawsvg"
    _write_project_fixture(source, _project_payload("project-v2-future.json"))

    with pytest.raises(UnsupportedFormatVersionError, match="newer than supported"):
        load_project(source)


def test_legacy_python_fixture_imports_into_the_current_canvas(
    application: QtWidgets.QApplication,
) -> None:
    scene = QtWidgets.QGraphicsScene()

    loaded_path = import_drawsvg_py(
        scene, path=FIXTURE_DIRECTORY / "python-v1-basic.py"
    )

    items = [item for item in scene.items() if item.data(0) == "Rectangle"]
    assert loaded_path == (FIXTURE_DIRECTORY / "python-v1-basic.py").resolve()
    assert len(items) == 1


def test_app_logging_uses_python_310_compatible_utc() -> None:
    import ast

    source = Path(__file__).parents[1] / "src" / "app_logging.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    datetime_imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "datetime"
        for alias in node.names
    }

    assert "timezone" in datetime_imports
    assert "UTC" not in datetime_imports
