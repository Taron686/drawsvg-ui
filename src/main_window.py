from __future__ import annotations

import json
import os
import tempfile
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
_RECENT_FILES_LIMIT = 10
_RECENT_FILES_NAME = "recent_files.json"


def _default_recent_files_path() -> Path:
    data_dir = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data_dir) / _RECENT_FILES_NAME


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, recent_files_path: Path | None = None):
        super().__init__()

        self._load_ui()

        self._install_custom_widgets()
        self._recent_files_path = recent_files_path or _default_recent_files_path()
        self._recent_files = self._load_recent_files()
        self._install_recent_files_menu()
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
        loaded_path = import_drawsvg_py(self.canvas.scene(), self)
        if loaded_path is not None:
            self._remember_recent_file(loaded_path)

    def _add_shape_at_center(self, shape: str) -> None:
        self.canvas.add_shape_at_view_center(shape)

    def _update_history_actions(self, can_undo: bool, can_redo: bool) -> None:
        self.actionUndo.setEnabled(can_undo)
        self.actionRedo.setEnabled(can_redo)

    def _handle_selection_snapshot(self, payload: dict) -> None:
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
        file_menu.insertMenu(self.actionSave_drawsvg_py, self.recent_files_menu)
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
        loaded_path = import_drawsvg_py(self.canvas.scene(), self, path)
        if loaded_path is not None:
            self._remember_recent_file(loaded_path)
            return
        failed_key = os.path.normcase(str(Path(path).expanduser().resolve()))
        self._recent_files = [
            existing
            for existing in self._recent_files
            if os.path.normcase(existing) != failed_key
        ]
        self._write_recent_files(self._recent_files)
        self._refresh_recent_files_menu()
