import pytest
from PySide6 import QtCore

from document_format import ProjectDocument
from document_io import save_project
from main_window import MainWindow, OpenResult


@pytest.mark.parametrize("action", ["python", "template", "blank_template", "native"])
def test_document_preparation_preserves_grid_preference_except_native_state(
    application, tmp_path, action
):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    settings.setValue("view/settings_version", 1)
    settings.setValue("view/grid", False)
    window = MainWindow(recent_files_path=tmp_path / "recent.json", settings=settings,
                        recovery_enabled=False)
    try:
        if action == "python":
            source = tmp_path / "drawing.py"
            source.write_text("d = draw.Drawing(100, 100)\n_rect = draw.Rectangle(1, 2, 30, 40)\nd.append(_rect)\n")
            result = window._open_python_document(source)
        elif action == "native":
            source = tmp_path / "drawing.drawsvg"
            state = window.canvas._serialize_scene_state()
            state["grid_visible"] = True
            save_project(source, ProjectDocument(scene=state))
            result = window._open_project_path(source)
        else:
            result = window.new_document_from_template("Blank" if action == "blank_template" else "Flowchart")
        assert result is OpenResult.OPENED
        expected_grid = action == "native"
        assert window.canvas._serialize_scene_state()["grid_visible"] is expected_grid
        assert settings.value("view/grid", None, bool) is expected_grid
    finally:
        window._force_close = True
        window.close()
