from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from document_controller import DocumentWindowRegistry
from export_renderer import ExportRenderer, ExportRequest
from main_window import MainWindow


def _window(tmp_path, registry, settings):
    return MainWindow(
        recent_files_path=tmp_path / "recent.json",
        window_registry=registry,
        settings=settings,
    )


def test_about_menu_is_last_in_menu_bar(application, tmp_path) -> None:
    registry = DocumentWindowRegistry()
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    window = _window(tmp_path, registry, settings)
    try:
        about_menu = window.menuBar().findChild(QtWidgets.QMenu, "menuAbout")
        assert about_menu is not None
        assert window.menuBar().actions()[-1].menu() is about_menu
    finally:
        window._force_close = True
        window.close()


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
        restored_palette = QtWidgets.QWidget.palette(restored.centralWidget())
        assert restored_palette.color(QtGui.QPalette.ColorRole.Window).name() == "#252526"
    finally:
        for candidate in registry.windows():
            candidate._force_close = True
            candidate.close()


def test_dark_and_light_themes_update_the_complete_window_chrome(
    application, tmp_path
) -> None:
    registry = DocumentWindowRegistry()
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    window = _window(tmp_path, registry, settings)
    try:
        themed_widgets = (
            window.centralWidget(),
            window.paletteContainer,
            window.canvasContainer,
            window.propertiesContainer,
            window.palette,
        )

        window._set_theme("dark")
        application.processEvents()
        for widget in themed_widgets:
            palette = QtWidgets.QWidget.palette(widget)
            assert palette.color(QtGui.QPalette.ColorRole.Window).name() == "#252526"
            assert palette.color(QtGui.QPalette.ColorRole.WindowText).name() == "#f0f0f0"
        assert "background-color: #1e1e1e" in window.styleSheet()
        assert "alternate-background-color: #2d2d30" in window.styleSheet()
        assert window.canvas.backgroundBrush().color() == QtGui.QColor("#2d2d30")
        assert window.canvas._page_item.brush().color() == QtGui.QColor("white")
        line_item = next(
            window.palette.item(index)
            for index in range(window.palette.count())
            if window.palette._shape_from_item(window.palette.item(index)) == "Line"
        )
        line_image = line_item.icon().pixmap(window.palette.iconSize()).toImage()
        dark_line_pixels = (
            line_image.pixelColor(x, y)
            for y in range(line_image.height())
            for x in range(line_image.width())
            if line_image.pixelColor(x, y).alpha() > 0
        )
        assert max(color.lightness() for color in dark_line_pixels) > 180

        window._set_theme("light")
        application.processEvents()
        assert window.canvas.backgroundBrush().color() == QtGui.QColor("#f0f0f0")
        light_palette = window.style().standardPalette()
        for widget in themed_widgets:
            palette = QtWidgets.QWidget.palette(widget)
            assert palette.color(QtGui.QPalette.ColorRole.Window) == light_palette.color(
                QtGui.QPalette.ColorRole.Window
            )
            assert palette.color(QtGui.QPalette.ColorRole.WindowText) == light_palette.color(
                QtGui.QPalette.ColorRole.WindowText
            )
        line_image = line_item.icon().pixmap(window.palette.iconSize()).toImage()
        light_line_pixels = (
            line_image.pixelColor(x, y)
            for y in range(line_image.height())
            for x in range(line_image.width())
            if line_image.pixelColor(x, y).alpha() > 0
        )
        assert min(color.lightness() for color in light_line_pixels) < 80
    finally:
        window._force_close = True
        window.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native style regression")
def test_dark_theme_renders_native_windows_menubar_with_contrast() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = """
import tempfile
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from document_controller import DocumentWindowRegistry
from main_window import MainWindow

app = QtWidgets.QApplication([])
directory = Path(tempfile.mkdtemp())
window = MainWindow(
    recent_files_path=directory / "recent.json",
    window_registry=DocumentWindowRegistry(),
    settings=QtCore.QSettings(
        str(directory / "settings.ini"), QtCore.QSettings.Format.IniFormat
    ),
)
window.resize(1198, 808)
window.move(-10000, -10000)
window._set_theme("dark")
window.show()
app.processEvents()
menu_bar = window.menuBar()
image = menu_bar.grab().toImage()
background = image.pixelColor(image.width() - 20, image.height() // 2)
foreground = menu_bar.palette().color(QtGui.QPalette.ColorRole.WindowText)
surface_colors = []
for widget in (window.palette.viewport(), window.properties_panel):
    surface = widget.grab().toImage()
    surface_colors.append(
        surface.pixelColor(surface.width() - 20, surface.height() - 20)
    )
canvas = window.canvas
canvas_image = canvas.viewport().grab().toImage()
page = canvas._page_item
page_sample = canvas.mapFromScene(page.mapToScene(page.rect().center())) + QtCore.QPoint(3, 4)
canvas_outside = canvas_image.pixelColor(10, 10)
canvas_page = canvas_image.pixelColor(page_sample)
window._force_close = True
window.close()
contrast = abs(background.lightness() - foreground.lightness())
print(
    background.name(),
    foreground.name(),
    contrast,
    [color.name() for color in surface_colors],
    canvas_outside.name(),
    canvas_page.name(),
)
valid = (
    background.lightness() < 128
    and contrast > 80
    and all(color.lightness() < 128 for color in surface_colors)
    and canvas_outside.lightness() < 128
    and canvas_page.lightness() > 180
)
raise SystemExit(0 if valid else 1)
"""
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    environment["PYTHONPATH"] = str(project_root / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


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
