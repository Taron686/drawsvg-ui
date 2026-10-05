from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from document_controller import DocumentWindowRegistry
from export_renderer import ExportRenderer, ExportRequest
import main_window
from main_window import MainWindow


def _window(tmp_path, registry, settings):
    return MainWindow(
        recent_files_path=tmp_path / "recent.json",
        window_registry=registry,
        settings=settings,
    )


@pytest.mark.parametrize("grid,alignment", [(False, False), (False, True), (True, False), (True, True)])
def test_snap_actions_persist_independently_of_display_and_theme(application, tmp_path, grid, alignment):
    registry = DocumentWindowRegistry()
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = _window(tmp_path, registry, settings)
    try:
        actions = {action.text(): action for action in window.menuView.actions()}
        assert "Snap to grid" in actions
        assert "Snap to guides and objects" in actions
        grid_action = actions["Snap to grid"]
        alignment_action = actions["Snap to guides and objects"]
        assert grid_action.isCheckable() and grid_action.isChecked()
        assert alignment_action.isCheckable() and alignment_action.isChecked()
        item = window.canvas.add_shape("Rectangle", QtCore.QPointF(103, 107), snap_to_grid=False)
        window._set_theme("dark")
        window.canvas.history().capture_initial_state()
        before = window.canvas._serialize_scene_state()
        grid_action.setChecked(grid)
        alignment_action.setChecked(alignment)
        assert window.canvas.grid_snap_enabled() is grid
        assert window.canvas.alignment_snap_enabled() is alignment
        assert window.canvas._serialize_scene_state() == before
        assert item.pos() == QtCore.QPointF(103, 107)
        assert not window.canvas.history().can_undo()
        assert window.actionShow_grid.isChecked()
        assert window.actionShow_guides.isChecked()
        window._save_view_settings()
        settings.sync()
        assert settings.value("view/snap_grid", None, bool) is grid
        assert settings.value("view/snap_alignment", None, bool) is alignment
        restored = _window(tmp_path, registry, settings)
        assert restored.canvas.grid_snap_enabled() is grid
        assert restored.canvas.alignment_snap_enabled() is alignment
        assert restored.actionSnap_grid.isChecked() is grid
        assert restored.actionSnap_alignment.isChecked() is alignment
        assert settings.value("view/theme", "light", str) == "dark"
        assert restored.canvas.backgroundBrush().color() == QtGui.QColor("#2d2d30")
        window.actionShow_grid.setChecked(False)
        window.actionShow_guides.setChecked(False)
        assert window.canvas.grid_snap_enabled() is grid
        assert window.canvas.alignment_snap_enabled() is alignment
    finally:
        for candidate in registry.windows():
            candidate._force_close = True
            candidate.close()


def test_old_view_settings_default_missing_snap_keys_to_enabled(application, tmp_path):
    registry = DocumentWindowRegistry()
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    settings.setValue("view/settings_version", 1)
    settings.setValue("view/grid", False)
    settings.setValue("view/guides", False)
    settings.setValue("view/theme", "dark")
    window = _window(tmp_path, registry, settings)
    try:
        assert window.canvas.grid_snap_enabled()
        assert window.canvas.alignment_snap_enabled()
        assert window.actionSnap_grid.isChecked()
        assert window.actionSnap_alignment.isChecked()
        assert not window.actionShow_grid.isChecked()
        assert not window.actionShow_guides.isChecked()
        assert settings.value("view/theme", "light", str) == "dark"
    finally:
        window._force_close = True
        window.close()


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
        document_id = window.document_controller.document_id
        window._set_theme("dark")
        window.actionSnap_grid.setChecked(False)
        window.actionShow_guides.setChecked(False)
        result = window.new_document_from_template("Flowchart")
        assert registry.windows() == (window,)
        assert result is main_window.OpenResult.OPENED
        assert window.document_controller.path is None
        assert window.document_controller.document_id != document_id
        assert window.document_controller.dirty
        assert window.document_controller.revision == 1
        assert len(window.canvas.scene().items()) > 1
        assert not window.canvas.history().can_undo()
        assert not window.canvas.history().can_redo()
        assert not window.actionSnap_grid.isChecked()
        assert not window.actionShow_guides.isChecked()
        assert window.canvas.backgroundBrush().color() == QtGui.QColor("#2d2d30")
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
            surface_color = "#1e1e1e" if isinstance(widget, QtWidgets.QAbstractItemView) else "#252526"
            assert palette.color(QtGui.QPalette.ColorRole.Window).name() == surface_color
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
        for widget in themed_widgets:
            palette = QtWidgets.QWidget.palette(widget)
            assert palette.color(QtGui.QPalette.ColorRole.Window).lightness() > 180
            assert palette.color(QtGui.QPalette.ColorRole.WindowText).lightness() < 80
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


def test_light_theme_stays_light_with_a_dark_standard_palette(application, tmp_path) -> None:
    class DarkSystemStyle(QtWidgets.QProxyStyle):
        def standardPalette(self):
            palette = super().standardPalette()
            for role in (
                QtGui.QPalette.ColorRole.Window,
                QtGui.QPalette.ColorRole.Base,
                QtGui.QPalette.ColorRole.Button,
            ):
                palette.setColor(role, QtGui.QColor("#242424"))
            for role in (
                QtGui.QPalette.ColorRole.WindowText,
                QtGui.QPalette.ColorRole.Text,
                QtGui.QPalette.ColorRole.ButtonText,
            ):
                palette.setColor(role, QtGui.QColor("#f0f0f0"))
            return palette

    previous_style = application.style().objectName()
    previous_palette = QtGui.QPalette(application.palette())
    window = None
    try:
        application.setStyle(DarkSystemStyle("Fusion"))
        assert application.style().standardPalette().color(
            QtGui.QPalette.ColorRole.Window
        ).lightness() < 80
        settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
        window = _window(tmp_path, DocumentWindowRegistry(), settings)
        for theme in ("light", "dark", "light"):
            window._set_theme(theme)
            application.processEvents()
            if theme == "dark":
                continue
            for widget in (window.centralWidget(), window.properties_panel):
                palette = QtWidgets.QWidget.palette(widget)
                for group in (QtGui.QPalette.ColorGroup.Active, QtGui.QPalette.ColorGroup.Inactive):
                    for role in (
                        QtGui.QPalette.ColorRole.Window,
                        QtGui.QPalette.ColorRole.Base,
                        QtGui.QPalette.ColorRole.Button,
                    ):
                        assert palette.color(group, role).lightness() > 180
                    for role in (
                        QtGui.QPalette.ColorRole.WindowText,
                        QtGui.QPalette.ColorRole.Text,
                        QtGui.QPalette.ColorRole.ButtonText,
                    ):
                        assert palette.color(group, role).lightness() < 80
    finally:
        if window is not None:
            window._force_close = True
            window.close()
        application.setStyle(previous_style)
        application.setPalette(previous_palette)


@pytest.mark.parametrize("spin_type", [QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox])
def test_dark_fusion_spinbox_arrows_are_visible_and_receive_clicks(application, tmp_path, spin_type) -> None:
    previous_style = application.style().objectName()
    previous_palette = QtGui.QPalette(application.palette())
    window = None
    try:
        application.setStyle("Fusion")
        settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
        window = _window(tmp_path, DocumentWindowRegistry(), settings)
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        spin = spin_type(window)
        spin.setRange(-1000, 1000)
        spin.setGeometry(5, 5, 220, 27)
        window._set_theme("dark")
        window.show()
        application.processEvents()
        spin.clearFocus()
        image = spin.grab().toImage()
        option = QtWidgets.QStyleOptionSpinBox()
        spin.initStyleOption(option)
        for subcontrol, direction in (
            (QtWidgets.QStyle.SubControl.SC_SpinBoxUp, 1),
            (QtWidgets.QStyle.SubControl.SC_SpinBoxDown, -1),
        ):
            button = spin.style().subControlRect(
                QtWidgets.QStyle.ComplexControl.CC_SpinBox, option, subcontrol, spin
            )
            assert not button.intersects(spin.lineEdit().geometry())
            interior = button.adjusted(3, 2, -3, -2)
            scale = image.devicePixelRatio()
            assert any(
                image.pixelColor(x, y).lightness() > 150
                for x in range(round(interior.left() * scale), round((interior.right() + 1) * scale))
                for y in range(round(interior.top() * scale), round((interior.bottom() + 1) * scale))
            ), "No visible arrow inside the spin button"
            target = spin.childAt(button.center()) or spin
            spin.setValue(0)
            QtTest.QTest.mouseClick(
                target, QtCore.Qt.MouseButton.LeftButton,
                pos=target.mapFrom(spin, button.center()),
            )
            assert spin.value() == direction * spin.singleStep()
    finally:
        if window is not None:
            window._force_close = True
            window.close()
        application.setStyle(previous_style)
        application.setPalette(previous_palette)


@pytest.mark.parametrize("surface", ["menus", "scrollbars", "tabs", "panels", "inputs"])
def test_fusion_chrome_follows_window_theme_with_dark_application_palette(
    application, tmp_path, surface
) -> None:
    previous_style = application.style().objectName()
    previous_palette = QtGui.QPalette(application.palette())
    window = None
    try:
        application.setStyle("Fusion")
        system_palette = QtGui.QPalette(application.palette())
        for role, color in (
            (QtGui.QPalette.ColorRole.Window, "#1e1e1e"),
            (QtGui.QPalette.ColorRole.Base, "#2d2d2d"),
            (QtGui.QPalette.ColorRole.Button, "#3c3c3c"),
            (QtGui.QPalette.ColorRole.WindowText, "#ffffff"),
            (QtGui.QPalette.ColorRole.Text, "#ffffff"),
            (QtGui.QPalette.ColorRole.ButtonText, "#ffffff"),
        ):
            system_palette.setColor(role, QtGui.QColor(color))
        application.setPalette(system_palette)
        settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
        window = _window(tmp_path, DocumentWindowRegistry(), settings)
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.resize(1200, 800)
        window.canvas.add_shape("Rectangle", QtCore.QPointF(0, 0))
        window.canvas.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        window.canvas.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        window.canvas.scene().setSceneRect(-2000, -2000, 4000, 4000)
        window.show()
        # Context menus created after startup must also inherit the window's theme.
        context_menu = QtWidgets.QMenu(window.canvas)
        context_menu.addAction("Context action")
        if surface == "menus":
            widgets = window.findChildren(QtWidgets.QMenu)
        elif surface == "scrollbars":
            widgets = [window.canvas.horizontalScrollBar(), window.canvas.verticalScrollBar()]
        elif surface == "tabs":
            widgets = window.findChildren(QtWidgets.QTabBar)
        elif surface == "panels":
            widgets = [window.palette.viewport(), window.properties_panel, window.menuBar(), window.statusBar()]
        else:
            spin = window.properties_panel.findChild(QtWidgets.QDoubleSpinBox, "spinZValue")
            widgets = [spin.lineEdit()]
        assert widgets
        for theme in ("light", "dark", "light"):
            window._set_theme(theme)
            application.processEvents()
            for widget in widgets:
                widget.ensurePolished()
                image = widget.grab().toImage()
                scale = image.devicePixelRatio()
                if surface == "menus":
                    point = QtCore.QPoint(widget.width() - 5, 5)
                elif surface == "scrollbars":
                    option = QtWidgets.QStyleOptionSlider()
                    widget.initStyleOption(option)
                    thumb = widget.style().subControlRect(
                        QtWidgets.QStyle.ComplexControl.CC_ScrollBar, option,
                        QtWidgets.QStyle.SubControl.SC_ScrollBarSlider, widget,
                    )
                    # Sample the thumb surface, away from Fusion's dark grip marks.
                    point = thumb.topLeft() + QtCore.QPoint(5, 5)
                elif surface == "tabs":
                    point = widget.tabRect(0).topLeft() + QtCore.QPoint(5, 5)
                else:
                    point = QtCore.QPoint(widget.width() - 20, 5)
                pixel = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
                assert pixel.lightness() > 180 if theme == "light" else pixel.lightness() < 128, (
                    surface, theme, widget.objectName(), pixel.name()
                )
                if surface == "menus":
                    text_color = widget.palette().color(QtGui.QPalette.ColorRole.WindowText)
                    minimum_contrast = 100 if widget.isEnabled() else 70
                    assert abs(pixel.lightness() - text_color.lightness()) > minimum_contrast
            assert application.palette() == system_palette
    finally:
        if window is not None:
            window._force_close = True
            window.close()
        application.setStyle(previous_style)
        application.setPalette(previous_palette)


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


@pytest.mark.parametrize("startup_theme", [None, "light", "dark"])
@pytest.mark.parametrize("shape", ["Text", "Rectangle"])
def test_theme_switch_preserves_widget_geometry_and_page_position(
    application, tmp_path, startup_theme, shape
) -> None:
    previous_style = application.style().objectName()
    previous_palette = QtGui.QPalette(application.palette())
    window = None
    try:
        application.setStyle("Fusion")
        settings = QtCore.QSettings(
            str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
        )
        if startup_theme is not None:
            settings.setValue("view/settings_version", 1)
            settings.setValue("view/theme", startup_theme)
        window = _window(tmp_path, DocumentWindowRegistry(), settings)
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.resize(1198, 808)
        window.show()
        window.mainSplitter.setSizes([220, 598, 380])
        item = window.canvas.add_shape(shape, QtCore.QPointF(80.0, 80.0))
        for _ in range(4):
            application.processEvents()

        panel = window.properties_panel
        widgets = [
            window.menuBar(), window.statusBar(), window.mainSplitter,
            window.right_panel_tabs, panel, window.canvas.viewport(),
            window.canvas.horizontalScrollBar(), window.canvas.verticalScrollBar(),
            *[widget for widget in panel.findChildren(QtWidgets.QWidget)
              if widget.objectName() and widget.isVisible()],
        ]
        geometry = [
            (widget.mapTo(window, QtCore.QPoint()), widget.size(), widget.sizeHint())
            for widget in widgets
        ]
        page_origin = window.canvas.mapFromScene(
            window.canvas._page_item.sceneBoundingRect().topLeft()
        )
        item_transform = item.sceneTransform()
        for theme in ("dark", "light", "dark", "light"):
            window._set_theme(theme)
            for _ in range(4):
                application.processEvents()
            for widget, expected in zip(widgets, geometry):
                actual = (
                    widget.mapTo(window, QtCore.QPoint()), widget.size(), widget.sizeHint()
                )
                assert actual == expected, f"{theme}: {widget.objectName()} changed geometry"
            assert window.canvas.mapFromScene(
                window.canvas._page_item.sceneBoundingRect().topLeft()
            ) == page_origin
            assert item.sceneTransform() == item_transform
    finally:
        if window is not None:
            window._force_close = True
            window.close()
        application.setStyle(previous_style)
        application.setPalette(previous_palette)
