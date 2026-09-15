# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtUiTools import QUiLoader

from app_info import GITHUB_URL, get_version
from canvas_view import CanvasView
from document_controller import DocumentController, DocumentWindowRegistry
from export_drawsvg import export_drawsvg_py
from export_renderer import ExportRenderer, ExportRequest
from import_drawsvg import import_drawsvg_py
from layers_panel import LayersPanel
from palette import PaletteList
from png_export_dialog import PngExportDialog
from properties_panel import PropertiesPanel
from property_command_service import PropertyCommandService
from recovery import RecoveryCandidate, RecoveryStore
from ruler_widget import RulerWidget

_UI_PATH = Path(__file__).resolve().parent / "ui" / "main_window.ui"
_RECENT_FILES_LIMIT = 10
_RECENT_FILES_NAME = "recent_files.json"
_PROJECT_FILTER = "DrawSVG project (*.drawsvg)"
_EXPORT_FORMATS = {
    "svg": ("SVG image (*.svg)", ".svg", "export_svg"),
    "png": ("PNG image (*.png)", ".png", "export_png"),
    "pdf": ("PDF document (*.pdf)", ".pdf", "export_pdf"),
}
_DARK_THEME_STYLESHEET = """
QMainWindow,
QMainWindow QWidget {
    background-color: #252526;
    color: #f0f0f0;
}
QLineEdit,
QTextEdit,
QPlainTextEdit,
QAbstractItemView {
    background-color: #1e1e1e;
    alternate-background-color: #2d2d30;
    color: #f0f0f0;
    selection-background-color: #007acc;
    selection-color: #ffffff;
}
QPushButton,
QToolButton,
QComboBox,
QSpinBox,
QDoubleSpinBox {
    background-color: #333337;
    border: 1px solid #5a5a5f;
    color: #f0f0f0;
    padding: 2px 5px;
}
QPushButton:hover,
QToolButton:hover,
QComboBox:hover,
QSpinBox:hover,
QDoubleSpinBox:hover {
    background-color: #3e3e42;
}
QPushButton:disabled,
QToolButton:disabled,
QComboBox:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {
    color: #858585;
}
QMenuBar,
QMenu,
QStatusBar,
QTabWidget::pane,
QHeaderView::section {
    background-color: #252526;
    color: #f0f0f0;
}
QMenuBar::item {
    background-color: transparent;
    color: #f0f0f0;
}
QMenuBar::item:selected,
QMenu::item:selected,
QTabBar::tab:hover {
    background-color: #3e3e42;
}
QMenu::separator {
    background-color: #4b4b50;
    height: 1px;
    margin: 4px 8px;
}
QTabBar::tab {
    background-color: #2d2d30;
    border: 1px solid #3f3f46;
    color: #d4d4d4;
    padding: 5px 10px;
}
QTabBar::tab:selected {
    background-color: #252526;
    color: #ffffff;
}
QSplitter::handle {
    background-color: #3f3f46;
}
QScrollBar:vertical {
    background-color: #252526;
    margin: 0;
    width: 14px;
}
QScrollBar:horizontal {
    background-color: #252526;
    height: 14px;
    margin: 0;
}
QScrollBar::handle {
    background-color: #5a5a5f;
    border-radius: 3px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:hover {
    background-color: #77777c;
}
QScrollBar::add-line,
QScrollBar::sub-line {
    height: 0;
    width: 0;
}
QScrollBar::add-page,
QScrollBar::sub-page {
    background-color: transparent;
}
QToolTip {
    background-color: #333337;
    border: 1px solid #5a5a5f;
    color: #f0f0f0;
}
""".strip()
_TEMPLATES = {
    "Blank": (),
    "Flowchart": (("Rounded Rectangle", 80.0, 80.0), ("Diamond", 320.0, 80.0), ("Arrow", 190.0, 130.0)),
    "Swimlane": (("Swimlane", 80.0, 80.0),),
}


def _default_recent_files_path() -> Path:
    data_dir = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data_dir) / _RECENT_FILES_NAME


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        recent_files_path: Path | None = None,
        *,
        window_registry: DocumentWindowRegistry | None = None,
        recovery_store: RecoveryStore | None = None,
        settings: QtCore.QSettings | None = None,
        recovery_enabled: bool = True,
        check_startup_recovery: bool = False,
    ):
        super().__init__()

        self._window_registry = window_registry or DocumentWindowRegistry()
        self._recovery_store = recovery_store or RecoveryStore()
        self._recovery_enabled = recovery_enabled
        self._settings_instance = settings
        self._force_close = False

        self._load_ui()

        self._install_custom_widgets()
        self.document_controller = DocumentController(
            self.canvas,
            recovery_store=self._recovery_store,
            recovery_enabled=self._recovery_enabled,
            parent=self,
        )
        layer_manager = self.canvas.layer_manager()
        self._property_command_service = PropertyCommandService(
            self.canvas.history(),
            is_locked=lambda item: layer_manager.layer_for_item(item).locked
            or layer_manager.item_locked(item),
        )
        self._recent_files_path = recent_files_path or _default_recent_files_path()
        self._recent_files = self._load_recent_files()
        self._install_recent_files_menu()
        self._configure_actions()
        self._restore_view_settings()

        self.statusBar().showMessage(
            "Tip: Ctrl+drag duplicates selected objects, Alt+mouse wheel zooms"
        )

        self.properties_panel.clear()
        self.canvas.selectionSnapshotChanged.connect(self._handle_selection_snapshot)

        history = self.canvas.history()
        history.historyChanged.connect(self._update_history_actions)
        self._update_history_actions(history.can_undo(), history.can_redo())

        self.document_controller.dirtyChanged.connect(self._update_document_title)
        self.document_controller.pathChanged.connect(self._update_document_title)
        self._update_document_title()
        self._window_registry.register(self)
        if (
            self._recovery_enabled
            and check_startup_recovery
            and not self._window_registry.startup_recovery_checked
        ):
            self._window_registry.startup_recovery_checked = True
            QtCore.QTimer.singleShot(0, self._offer_recovery_candidates)

    def _load_ui(self) -> None:
        loader = QUiLoader()
        ui_file = QtCore.QFile(str(_UI_PATH))
        if not ui_file.open(QtCore.QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Could not open UI file: {_UI_PATH}")
        form = loader.load(ui_file, None)
        ui_file.close()
        if form is None:
            raise RuntimeError(f"Failed to load UI from {_UI_PATH}")

        central = self._take_widget(form, QtWidgets.QWidget, "centralwidget")
        if central is None:
            raise RuntimeError("Missing central widget in UI file")
        self.setCentralWidget(central)
        menu_bar = self._take_widget(form, QtWidgets.QMenuBar, "menubar")
        if menu_bar is not None:
            self.setMenuBar(menu_bar)
        status_bar = self._take_widget(form, QtWidgets.QStatusBar, "statusbar")
        if status_bar is not None:
            self.setStatusBar(status_bar)
        self.resize(form.size())
        self.setWindowTitle(form.windowTitle())

        self.mainSplitter = self._require_widget(central, QtWidgets.QSplitter, "mainSplitter")
        self.paletteContainer = self._require_widget(central, QtWidgets.QWidget, "paletteContainer")
        self.palettePlaceholder = self._require_widget(central, QtWidgets.QWidget, "palettePlaceholder")
        self.canvasContainer = self._require_widget(central, QtWidgets.QWidget, "canvasContainer")
        self.canvasPlaceholder = self._require_widget(central, QtWidgets.QGraphicsView, "canvasPlaceholder")
        self.propertiesContainer = self._require_widget(central, QtWidgets.QWidget, "propertiesContainer")
        self.propertiesPlaceholder = self._require_widget(central, QtWidgets.QWidget, "propertiesPlaceholder")

        layouts = [
            central.layout(),
            self.paletteContainer.layout(),
            self.canvasContainer.layout(),
            self.propertiesContainer.layout(),
        ]
        for layout in layouts:
            if layout is not None:
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

        action_names = [
            "actionNew",
            "actionOpen_project",
            "actionSave_project",
            "actionSave_project_as",
            "actionLoad_drawsvg_py",
            "actionSave_drawsvg_py",
            "actionExport_svg",
            "actionExport_png",
            "actionExport_pdf",
            "actionQuit",
            "actionUndo",
            "actionRedo",
            "actionClear_canvas",
            "actionShow_grid",
            "actionInfo",
        ]
        for name in action_names:
            action = form.findChild(QtGui.QAction, name)
            if action is None:
                raise RuntimeError(f"Missing QAction '{name}' in UI file")
            action.setParent(self)
            setattr(self, name, action)

        form.deleteLater()

    def _take_widget(
        self,
        parent: QtWidgets.QWidget,
        widget_type: type[QtWidgets.QWidget],
        object_name: str,
    ) -> QtWidgets.QWidget | None:
        widget = parent.findChild(widget_type, object_name)
        if widget is None:
            return None
        widget.setParent(None)
        return widget

    @staticmethod
    def _require_widget(
        parent: QtWidgets.QWidget,
        widget_type: type[QtWidgets.QWidget],
        object_name: str,
    ) -> QtWidgets.QWidget:
        widget = parent.findChild(widget_type, object_name)
        if widget is None:
            raise RuntimeError(f"Missing widget '{object_name}' in UI file")
        return widget

    def _install_custom_widgets(self) -> None:
        self.splitter = self.mainSplitter

        palette_container = self.paletteContainer
        canvas_container = self.canvasContainer
        properties_container = self.propertiesContainer
        properties_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        self.palette = PaletteList(palette_container)
        self.palette.setMinimumWidth(220)
        self.palette.shapeClicked.connect(self._add_shape_at_center)

        self.canvas_frame = QtWidgets.QWidget(canvas_container)
        canvas_layout = QtWidgets.QGridLayout(self.canvas_frame)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        self.canvas = CanvasView(self.canvas_frame)
        self.horizontal_ruler = RulerWidget(
            QtCore.Qt.Orientation.Horizontal, self.canvas, self.canvas_frame
        )
        self.vertical_ruler = RulerWidget(
            QtCore.Qt.Orientation.Vertical, self.canvas, self.canvas_frame
        )
        ruler_corner = QtWidgets.QWidget(self.canvas_frame)
        ruler_corner.setFixedSize(22, 22)
        canvas_layout.addWidget(ruler_corner, 0, 0)
        canvas_layout.addWidget(self.horizontal_ruler, 0, 1)
        canvas_layout.addWidget(self.vertical_ruler, 1, 0)
        canvas_layout.addWidget(self.canvas, 1, 1)

        self.properties_panel = PropertiesPanel(self.canvas)
        self.layers_panel = LayersPanel(self.canvas)
        self.right_panel_tabs = QtWidgets.QTabWidget(properties_container)
        self.right_panel_tabs.addTab(self.properties_panel, "Properties")
        self.right_panel_tabs.addTab(self.layers_panel, "Layers")
        properties_min_width = 260
        properties_container.setMinimumWidth(properties_min_width)

        self._replace_placeholder(palette_container, self.palettePlaceholder, self.palette)
        self._replace_placeholder(canvas_container, self.canvasPlaceholder, self.canvas_frame)
        self._replace_placeholder(
            properties_container, self.propertiesPlaceholder, self.right_panel_tabs
        )

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setCollapsible(2, True)
        self.splitter.setSizes([self.palette.minimumWidth(), 900, properties_min_width])

    @staticmethod
    def _replace_placeholder(
        container: QtWidgets.QWidget,
        placeholder: QtWidgets.QWidget,
        replacement: QtWidgets.QWidget,
    ) -> None:
        layout = container.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        index = layout.indexOf(placeholder)
        if index >= 0:
            item = layout.takeAt(index)
            if item is not None:
                orphan = item.widget()
                if orphan is not None:
                    orphan.setParent(None)
        placeholder.setParent(None)
        placeholder.deleteLater()
        if index >= 0:
            layout.insertWidget(index, replacement)
        else:
            layout.addWidget(replacement)

    def _configure_actions(self) -> None:
        self.actionNew.triggered.connect(self.new_document_window)
        self.actionOpen_project.triggered.connect(self.open_project)
        self.actionSave_project.triggered.connect(self.save_document)
        self.actionSave_project_as.triggered.connect(self.save_document_as)
        self.actionLoad_drawsvg_py.triggered.connect(self.load_drawsvg_py)
        self.actionSave_drawsvg_py.triggered.connect(self.export_drawsvg_py)
        self.actionExport_svg.triggered.connect(
            lambda _checked=False: self._export_scene("svg")
        )
        self.actionExport_png.triggered.connect(
            lambda _checked=False: self._export_scene("png")
        )
        self.actionExport_pdf.triggered.connect(
            lambda _checked=False: self._export_scene("pdf")
        )
        self.actionQuit.triggered.connect(self._request_quit)

        self.actionUndo.setShortcutContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.actionUndo.triggered.connect(self._handle_undo)

        self.actionRedo.setShortcutContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.actionRedo.triggered.connect(self._handle_redo)

        self.actionClear_canvas.triggered.connect(self._handle_clear_canvas)

        self.actionShow_grid.setCheckable(True)
        self.actionShow_grid.setChecked(True)
        self.actionShow_grid.toggled.connect(self._handle_toggle_grid)
        self.canvas.gridVisibilityChanged.connect(self.actionShow_grid.setChecked)

        self.menuView = self.menuBar().addMenu("&View")
        self.actionShow_guides = QtGui.QAction("Show guides", self, checkable=True)
        self.actionShow_guides.setChecked(True)
        self.menuView.addAction(self.actionShow_guides)
        self.actionShow_guides.toggled.connect(self.canvas.set_guides_visible)
        self.canvas.guidesVisibilityChanged.connect(self.actionShow_guides.setChecked)

        file_menu = self.menuBar().findChild(QtWidgets.QMenu, "menuFile")
        if file_menu is None:
            raise RuntimeError("Missing File menu in UI file")
        self.actionNew_from_template = QtGui.QAction("New from template…", self)
        file_menu.insertAction(self.actionOpen_project, self.actionNew_from_template)
        self.actionNew_from_template.triggered.connect(self.show_template_dialog)

        theme_menu = self.menuView.addMenu("Theme")
        self._theme_actions = QtGui.QActionGroup(self)
        for name in ("Light", "Dark"):
            action = theme_menu.addAction(name)
            action.setCheckable(True)
            action.setData(name.lower())
            self._theme_actions.addAction(action)
        self._theme_actions.triggered.connect(lambda action: self._set_theme(str(action.data())))
        self.actionShow_grid.toggled.connect(lambda _value: self._save_view_settings())
        self.actionShow_guides.toggled.connect(lambda _value: self._save_view_settings())

        self.menuTools = self.menuBar().addMenu("&Tools")
        self.actionCreate_connector = QtGui.QAction(
            "Create connector", self, checkable=True
        )
        self.menuTools.addAction(self.actionCreate_connector)
        self.actionCreate_connector.toggled.connect(
            self.canvas.set_connector_creation_enabled
        )
        self.canvas.connectorCreationChanged.connect(
            self._update_connector_creation_action
        )
        self.canvas.connectorCreationStartChanged.connect(
            self._update_connector_creation_prompt
        )

        about_menu = self.menuBar().findChild(QtWidgets.QMenu, "menuAbout")
        if about_menu is None:
            raise RuntimeError("Missing About menu in UI file")
        self.menuBar().removeAction(about_menu.menuAction())
        self.menuBar().addAction(about_menu.menuAction())

        self.actionInfo.triggered.connect(self._show_about_dialog)

    def _handle_undo(self) -> None:
        self.canvas.undo()

    def _update_connector_creation_action(self, enabled: bool) -> None:
        self.actionCreate_connector.setChecked(enabled)
        self.actionCreate_connector.setText(
            "Create connector (active)" if enabled else "Create connector"
        )
        message = (
            "Connector mode: click a start point or object. Press Esc to cancel."
            if enabled
            else "Connector mode off."
        )
        self.statusBar().showMessage(message, 5000)

    def _update_connector_creation_prompt(self, has_start: bool) -> None:
        if has_start and self.canvas.connector_creation_enabled():
            self.statusBar().showMessage(
                "Connector mode: click an end point or object. Press Esc to cancel.",
                0,
            )

    def _handle_redo(self) -> None:
        self.canvas.redo()

    def _handle_clear_canvas(self) -> None:
        self.canvas.clear_canvas()

    def _handle_toggle_grid(self, visible: bool) -> None:
        self.canvas.set_grid_visible(visible)

    def _show_about_dialog(self) -> None:
        version = get_version()
        body = (
            "<b>DrawSVG UI</b><br>"
            f"Version: {version}<br>"
            f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>'
        )

        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Information)
        dialog.setWindowTitle("About")
        dialog.setTextFormat(QtCore.Qt.TextFormat.RichText)
        dialog.setText(body)
        dialog.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
            | QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        dialog.exec()

    def _create_document_window(self) -> "MainWindow":
        return type(self)(
            recent_files_path=self._recent_files_path,
            window_registry=self._window_registry,
            recovery_store=self._recovery_store,
            recovery_enabled=self._recovery_enabled,
            check_startup_recovery=False,
        )

    def new_document_window(self, _checked: bool = False) -> "MainWindow":
        window = self._create_document_window()
        window.show()
        return window

    def new_document_from_template(self, template: str) -> "MainWindow":
        window = self._create_document_window()
        for shape, x, y in _TEMPLATES.get(template, ()):
            window.canvas.add_shape(shape, QtCore.QPointF(x, y), snap_to_grid=False)
        window.document_controller.refresh_dirty_state()
        window.show()
        return window

    def show_template_dialog(self, _checked: bool = False) -> "MainWindow | None":
        template, accepted = QtWidgets.QInputDialog.getItem(
            self,
            "New from template",
            "Template:",
            tuple(_TEMPLATES),
            editable=False,
        )
        if not accepted:
            return None
        return self.new_document_from_template(template)

    def _settings(self) -> QtCore.QSettings:
        return self._settings_instance or QtCore.QSettings(
            QtCore.QSettings.Format.IniFormat,
            QtCore.QSettings.Scope.UserScope,
            "DrawSVG UI",
            "DrawSVG UI Settings v1",
        )

    def _restore_view_settings(self) -> None:
        settings = self._settings()
        if settings.value("view/settings_version", 0, int) != 1:
            return
        self._restoring_view_settings = True
        try:
            self.actionShow_grid.setChecked(
                self._read_setting_bool(settings, "view/grid")
            )
            self.actionShow_guides.setChecked(
                self._read_setting_bool(settings, "view/guides")
            )
            self._set_theme(settings.value("view/theme", "light", str), persist=False)
        finally:
            self._restoring_view_settings = False

    @staticmethod
    def _read_setting_bool(settings: QtCore.QSettings, key: str) -> bool:
        value = settings.value(key, True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _save_view_settings(self) -> None:
        if getattr(self, "_restoring_view_settings", False):
            return
        settings = self._settings()
        settings.setValue("view/settings_version", 1)
        settings.setValue("view/grid", self.actionShow_grid.isChecked())
        settings.setValue("view/guides", self.actionShow_guides.isChecked())

    def _set_theme(self, theme: str, *, persist: bool = True) -> None:
        dark = theme == "dark"
        self.setStyleSheet("")
        palette = self.style().standardPalette()
        if dark:
            colors = {
                QtGui.QPalette.ColorRole.Window: "#252526",
                QtGui.QPalette.ColorRole.WindowText: "#f0f0f0",
                QtGui.QPalette.ColorRole.Base: "#1e1e1e",
                QtGui.QPalette.ColorRole.AlternateBase: "#2d2d30",
                QtGui.QPalette.ColorRole.ToolTipBase: "#333337",
                QtGui.QPalette.ColorRole.ToolTipText: "#f0f0f0",
                QtGui.QPalette.ColorRole.Text: "#f0f0f0",
                QtGui.QPalette.ColorRole.Button: "#333337",
                QtGui.QPalette.ColorRole.ButtonText: "#f0f0f0",
                QtGui.QPalette.ColorRole.BrightText: "#ffffff",
                QtGui.QPalette.ColorRole.Link: "#4ea1ff",
                QtGui.QPalette.ColorRole.LinkVisited: "#c586c0",
                QtGui.QPalette.ColorRole.Light: "#4b4b50",
                QtGui.QPalette.ColorRole.Midlight: "#3f3f46",
                QtGui.QPalette.ColorRole.Mid: "#3a3a3f",
                QtGui.QPalette.ColorRole.Dark: "#1b1b1d",
                QtGui.QPalette.ColorRole.Shadow: "#111111",
                QtGui.QPalette.ColorRole.Highlight: "#007acc",
                QtGui.QPalette.ColorRole.HighlightedText: "#ffffff",
                QtGui.QPalette.ColorRole.PlaceholderText: "#9d9d9d",
            }
            for role, color in colors.items():
                palette.setColor(role, QtGui.QColor(color))
            for role in (
                QtGui.QPalette.ColorRole.WindowText,
                QtGui.QPalette.ColorRole.Text,
                QtGui.QPalette.ColorRole.ButtonText,
            ):
                palette.setColor(
                    QtGui.QPalette.ColorGroup.Disabled,
                    role,
                    QtGui.QColor("#858585"),
                )
        self.setPalette(palette)
        self.setStyleSheet(_DARK_THEME_STYLESHEET if dark else "")
        self.canvas.setBackgroundBrush(QtGui.QColor("#2d2d30" if dark else "#f0f0f0"))
        for action in self._theme_actions.actions():
            action.setChecked(str(action.data()) == ("dark" if dark else "light"))
        if persist:
            self._settings().setValue("view/theme", "dark" if dark else "light")

    def open_project(self, _checked: bool = False) -> "MainWindow | None":
        selected_path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open DrawSVG Project",
            "",
            _PROJECT_FILTER,
        )
        if not selected_path:
            return None
        return self._open_project_path(selected_path)

    def _open_project_path(self, path: str | Path) -> "MainWindow | None":
        source = Path(path).expanduser().resolve()
        existing = self._window_registry.window_for_path(source)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return existing  # type: ignore[return-value]

        window = self._create_document_window()
        try:
            window.document_controller.load(source)
        except Exception as error:
            window._force_close = True
            window.close()
            QtWidgets.QMessageBox.critical(
                self,
                "Open Project failed",
                f"{error}\n\nSee the application log for diagnostic details.",
            )
            return None
        self._remember_recent_file(source)
        window._remember_recent_file(source)
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def save_document(self, _checked: bool = False) -> bool:
        if self.document_controller.path is None:
            return self.save_document_as()
        return self._save_document_to(self.document_controller.path)

    def save_document_as(self, _checked: bool = False) -> bool:
        current_path = self.document_controller.path
        suggested = str(current_path) if current_path is not None else "Untitled.drawsvg"
        selected_path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save DrawSVG Project",
            suggested,
            _PROJECT_FILTER,
        )
        if not selected_path:
            return False
        destination = Path(selected_path)
        if destination.suffix.casefold() != ".drawsvg":
            destination = destination.parent / f"{destination.name}.drawsvg"
        return self._save_document_to(destination)

    def _save_document_to(self, path: str | Path) -> bool:
        destination = Path(path).expanduser().resolve()
        existing = self._window_registry.window_for_path(destination)
        if existing is not None and existing is not self:
            existing.raise_()
            existing.activateWindow()
            QtWidgets.QMessageBox.warning(
                self,
                "Project already open",
                "This project is already open in another editor window.",
            )
            return False
        try:
            saved_path = self.document_controller.save(destination)
        except Exception as error:
            QtWidgets.QMessageBox.critical(
                self,
                "Save Project failed",
                f"{error}\n\nSee the application log for diagnostic details.",
            )
            return False
        self._remember_recent_file(saved_path)
        self.statusBar().showMessage(f"Saved {saved_path.name}", 5000)
        return True

    def _update_document_title(self, *_args: object) -> None:
        path = self.document_controller.path
        name = path.name if path is not None else "Untitled"
        dirty_marker = " *" if self.document_controller.dirty else ""
        self.setWindowTitle(f"{name}{dirty_marker} — DrawSVG UI")

    def _ask_unsaved_changes(self) -> str:
        name = (
            self.document_controller.path.name
            if self.document_controller.path is not None
            else "Untitled"
        )
        result = QtWidgets.QMessageBox.warning(
            self,
            "Unsaved changes",
            f"Save changes to {name}?",
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Save,
        )
        if result == QtWidgets.QMessageBox.StandardButton.Save:
            return "save"
        if result == QtWidgets.QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def _request_quit(self, _checked: bool = False) -> bool:
        windows = tuple(self._window_registry.windows())
        discard_windows: list[MainWindow] = []
        for window in windows:
            if not window.document_controller.dirty:
                continue
            choice = window._ask_unsaved_changes()
            if choice == "cancel":
                return False
            if choice == "save" and not window.save_document():
                return False
            if choice == "discard":
                discard_windows.append(window)

        for window in discard_windows:
            window.document_controller.discard_recovery()
        self._window_registry.quitting = True
        try:
            for window in windows:
                window.close()
        finally:
            self._window_registry.quitting = False
        return True

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self._force_close or self._window_registry.quitting:
            self._window_registry.unregister(self)
            event.accept()
            return
        if self.document_controller.dirty:
            choice = self._ask_unsaved_changes()
            if choice == "cancel" or choice == "save" and not self.save_document():
                event.ignore()
                return
            if choice == "discard":
                self.document_controller.discard_recovery()
        else:
            self.document_controller.discard_recovery()
        self._window_registry.unregister(self)
        event.accept()

    def _offer_recovery_candidates(self) -> None:
        for candidate in self._recovery_store.candidates():
            choice = self._ask_recovery_candidate(candidate)
            if choice == "later":
                break
            if choice == "discard":
                self._recovery_store.discard(candidate.document_id)
                continue
            use_current = (
                self.document_controller.path is None
                and not self.document_controller.dirty
                and not self.canvas._serialize_scene_state()["items"]
            )
            window = self if use_current else self._create_document_window()
            try:
                window.document_controller.restore_recovery(candidate)
            except Exception as error:
                if window is not self:
                    window._force_close = True
                    window.close()
                QtWidgets.QMessageBox.critical(
                    self,
                    "Recovery failed",
                    f"{error}\n\nSee the application log for diagnostic details.",
                )
                continue
            window.show()
            window.raise_()
            window.activateWindow()

    def _ask_recovery_candidate(self, candidate: RecoveryCandidate) -> str:
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Question)
        dialog.setWindowTitle("Recover document")
        dialog.setText(f"Recover unsaved changes for {candidate.display_name}?")
        recover_button = dialog.addButton(
            "Recover", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        discard_button = dialog.addButton(
            "Discard", QtWidgets.QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton("Later", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is recover_button:
            return "recover"
        if dialog.clickedButton() is discard_button:
            return "discard"
        return "later"

    def export_drawsvg_py(self) -> None:
        export_drawsvg_py(self.canvas.scene(), self)

    def _export_scene(self, export_format: str) -> None:
        if export_format == "png":
            self._export_png()
            return
        file_filter, extension, method_name = _EXPORT_FORMATS[export_format]
        selected_path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            f"Export {export_format.upper()}",
            "",
            file_filter,
        )
        if not selected_path:
            return

        output_path = Path(selected_path)
        if output_path.suffix.casefold() != extension:
            output_path = output_path.parent / f"{output_path.name}{extension}"

        renderer = ExportRenderer(self.canvas.scene())
        export_method = getattr(renderer, method_name)
        try:
            export_method(
                output_path,
                ExportRequest(hidden_items=tuple(self.canvas._pages.values())),
            )
        except (OSError, RuntimeError, ValueError) as error:
            QtWidgets.QMessageBox.critical(
                self,
                f"Export {export_format.upper()} failed",
                str(error),
            )
            return
        self.statusBar().showMessage(
            f"Exported {export_format.upper()} to {output_path}", 5000
        )

    def _export_png(self) -> None:
        renderer = ExportRenderer(self.canvas.scene())
        request = ExportRequest(hidden_items=tuple(self.canvas._pages.values()))
        initial_path = self.document_controller.path
        if initial_path is None:
            folder = QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.StandardLocation.DocumentsLocation
            )
            initial_path = Path(folder or Path.home()) / "Untitled.png"
        else:
            initial_path = initial_path.with_suffix(".png")
        try:
            content_rect = renderer._source_rects(request)[0]
            dialog = PngExportDialog(content_rect, initial_path, self)
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            output_path = dialog.output_path()
            renderer.export_png(output_path, replace(
                request, scale=dialog.scale(), background=dialog.background_color()
            ))
        except (OSError, RuntimeError, ValueError) as error:
            QtWidgets.QMessageBox.critical(self, "Export PNG failed", str(error))
            return
        self.statusBar().showMessage(f"Exported PNG to {output_path}", 5000)

    def load_drawsvg_py(self) -> None:
        self._open_python_document()

    def _open_python_document(self, path: str | Path | None = None) -> Path | None:
        window = self._create_document_window()
        loaded_path = import_drawsvg_py(window.canvas.scene(), window, path)
        if loaded_path is None:
            window._force_close = True
            window.close()
            return None
        window.document_controller.mark_imported()
        self._remember_recent_file(loaded_path)
        window._remember_recent_file(loaded_path)
        window.show()
        window.raise_()
        window.activateWindow()
        return Path(loaded_path)

    def _add_shape_at_center(self, shape: str) -> None:
        self.canvas.add_shape_at_view_center(shape)

    def _update_history_actions(self, can_undo: bool, can_redo: bool) -> None:
        self.actionUndo.setEnabled(can_undo)
        self.actionRedo.setEnabled(can_redo)

    def _handle_selection_snapshot(self, payload: dict) -> None:
        if payload.get("selection_type") == "multi":
            items = payload.get("items")
            if isinstance(items, list):
                self.properties_panel.show_selected_item_properties(
                    items, self._property_command_service
                )
                return
        self.properties_panel.update_snapshot(payload)

    def _load_recent_files(self) -> list[str]:
        try:
            data = json.loads(self._recent_files_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, OSError, UnicodeError):
            return []

        recent_files: list[str] = []
        seen: set[str] = set()
        if isinstance(data, list):
            for value in data:
                if not isinstance(value, str):
                    continue
                normalized = str(Path(value).expanduser().resolve())
                key = os.path.normcase(normalized)
                if key in seen:
                    continue
                recent_files.append(normalized)
                seen.add(key)
                if len(recent_files) == _RECENT_FILES_LIMIT:
                    break

        if data != recent_files:
            self._write_recent_files(recent_files)
        return recent_files

    def _write_recent_files(self, recent_files: list[str]) -> None:
        temporary_path: Path | None = None
        try:
            self._recent_files_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._recent_files_path.parent,
                prefix=f".{self._recent_files_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(
                    json.dumps(recent_files, ensure_ascii=False, indent=2) + "\n"
                )
                temporary_path = Path(temporary_file.name)
            temporary_path.replace(self._recent_files_path)
        except OSError:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _install_recent_files_menu(self) -> None:
        file_menu = self.menuBar().findChild(QtWidgets.QMenu, "menuFile")
        if file_menu is None:
            raise RuntimeError("Missing File menu in UI file")
        self.recent_files_menu = QtWidgets.QMenu("Recently Opened", file_menu)
        self.recent_files_menu.setObjectName("menuRecentlyOpened")
        file_menu.insertMenu(self.actionLoad_drawsvg_py, self.recent_files_menu)
        self._refresh_recent_files_menu()

    def _refresh_recent_files_menu(self) -> None:
        self.recent_files_menu.clear()
        for index, path in enumerate(self._recent_files, start=1):
            action = self.recent_files_menu.addAction(f"&{index} {Path(path).name}")
            action.setToolTip(path)
            action.setStatusTip(path)
            action.triggered.connect(
                lambda _checked=False, file_path=path: self._open_recent_file(
                    file_path
                )
            )
        self.recent_files_menu.setEnabled(bool(self._recent_files))

    def _remember_recent_file(self, path: str | Path) -> None:
        normalized = str(Path(path).expanduser().resolve())
        key = os.path.normcase(normalized)
        self._recent_files = [
            existing
            for existing in self._recent_files
            if os.path.normcase(existing) != key
        ]
        self._recent_files.insert(0, normalized)
        del self._recent_files[_RECENT_FILES_LIMIT:]
        self._write_recent_files(self._recent_files)
        self._refresh_recent_files_menu()

    def _open_recent_file(self, path: str) -> None:
        suffix = Path(path).suffix.casefold()
        if suffix == ".drawsvg":
            if self._open_project_path(path) is not None:
                self._remember_recent_file(path)
                return
        elif self._open_python_document(path) is not None:
            return
        failed_key = os.path.normcase(str(Path(path).expanduser().resolve()))
        self._recent_files = [
            existing
            for existing in self._recent_files
            if os.path.normcase(existing) != failed_key
        ]
        self._write_recent_files(self._recent_files)
        self._refresh_recent_files_menu()
