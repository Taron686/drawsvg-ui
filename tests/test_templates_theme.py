from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from document_controller import DocumentWindowRegistry
from export_renderer import ExportRenderer, ExportRequest
from main_window import MainWindow


def _window(tmp_path, registry, settings):
    return MainWindow(
        recent_files_path=tmp_path / "recent.json",
        window_registry=registry,
        settings=settings,
    )


def test_template_opens_an_unsaved_document(application, tmp_path) -> None:
    registry = DocumentWindowRegistry()
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = _window(tmp_path, registry, settings)
    try:
        template = window.new_document_from_template("Flowchart")
        assert template.document_controller.path is None
        assert template.document_controller.dirty
        assert len(template.canvas.scene().items()) > 1
    finally:
        for candidate in registry.windows():
            candidate._force_close = True
            candidate.close()


def test_theme_and_view_settings_are_restored_after_restart(application, tmp_path) -> None:
    registry = DocumentWindowRegistry()
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = _window(tmp_path, registry, settings)
    try:
        window.actionShow_grid.setChecked(False)
        window.actionShow_guides.setChecked(False)
        window._set_theme("dark")
        settings.sync()
        assert settings.value("view/grid", True, bool) is False
        assert settings.value("view/guides", True, bool) is False
        assert settings.value("view/theme", "light", str) == "dark"

        restored = _window(tmp_path, registry, settings)
        assert restored.actionShow_grid.isChecked() is False
        assert restored.actionShow_guides.isChecked() is False
        assert "#252526" in restored.styleSheet()
    finally:
        for candidate in registry.windows():
            candidate._force_close = True
            candidate.close()


def test_theme_does_not_change_export(application, tmp_path) -> None:
    registry = DocumentWindowRegistry()
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = _window(tmp_path, registry, settings)
    try:
        window.canvas.add_shape("Rectangle", QtCore.QPointF(80.0, 80.0))
        before = ExportRenderer(window.canvas.scene()).export_png(
            tmp_path / "before.png", ExportRequest()
        )[0]
        window._set_theme("dark")
        after = ExportRenderer(window.canvas.scene()).export_png(
            tmp_path / "after.png", ExportRequest()
        )[0]
        assert before.read_bytes() == after.read_bytes()
    finally:
        for candidate in registry.windows():
            candidate._force_close = True
            candidate.close()
