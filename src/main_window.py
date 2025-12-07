# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtUiTools import QUiLoader

from app_info import GITHUB_URL, get_version
from canvas_view import CanvasView
from export_drawsvg import export_drawsvg_py
from import_drawsvg import import_drawsvg_py
from palette import PaletteList
from properties_panel import PropertiesPanel

_UI_PATH = Path(__file__).resolve().parent / "ui" / "main_window.ui"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self._load_ui()

        self._install_custom_widgets()
        self._configure_actions()

        self.statusBar().showMessage(
            "Tip: Ctrl+drag duplicates selected objects, Alt+mouse wheel zooms"
        )

        self.properties_panel.clear()
        self.canvas.selectionSnapshotChanged.connect(self._handle_selection_snapshot)

        history = self.canvas.history()
        history.historyChanged.connect(self._update_history_actions)
        self._update_history_actions(history.can_undo(), history.can_redo())

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
            "actionLoad_drawsvg_py",
            "actionSave_drawsvg_py",
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

        self.canvas = CanvasView(canvas_container)

        self.properties_panel = PropertiesPanel(self.canvas)
        properties_min_width = max(
            260,
            self.properties_panel.minimumWidth(),
            self.properties_panel.minimumSizeHint().width(),
        )
        properties_container.setMinimumWidth(properties_min_width)

        self._replace_placeholder(palette_container, self.palettePlaceholder, self.palette)
        self._replace_placeholder(canvas_container, self.canvasPlaceholder, self.canvas)
        self._replace_placeholder(
            properties_container, self.propertiesPlaceholder, self.properties_panel
        )

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setCollapsible(2, True)
        self.splitter.setSizes([self.palette.minimumWidth(), 900, properties_min_width + 40])

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
        self.actionLoad_drawsvg_py.triggered.connect(self.load_drawsvg_py)
        self.actionSave_drawsvg_py.triggered.connect(self.export_drawsvg_py)
        self.actionQuit.triggered.connect(self.close)

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

        self.actionInfo.triggered.connect(self._show_about_dialog)

    def _handle_undo(self) -> None:
        self.canvas.undo()

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

    def export_drawsvg_py(self) -> None:
        export_drawsvg_py(self.canvas.scene(), self)

    def load_drawsvg_py(self) -> None:
        import_drawsvg_py(self.canvas.scene(), self)

    def _add_shape_at_center(self, shape: str) -> None:
        self.canvas.add_shape_at_view_center(shape)

    def _update_history_actions(self, can_undo: bool, can_redo: bool) -> None:
        self.actionUndo.setEnabled(can_undo)
        self.actionRedo.setEnabled(can_redo)

    def _handle_selection_snapshot(self, payload: dict) -> None:
        self.properties_panel.update_snapshot(payload)
