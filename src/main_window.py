from PySide6 import QtCore, QtGui, QtWidgets

from canvas_view import CanvasView
from palette import PaletteList
from properties_panel import PropertiesPanel
from export_drawsvg import export_drawsvg_py
from import_drawsvg import import_drawsvg_py


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DrawSVG Canvas – PySide6")
        self.resize(1200, 800)

        self.splitter = QtWidgets.QSplitter()
        self.splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)

        self.palette = PaletteList()
        self.palette.setMinimumWidth(220)

        self.canvas = CanvasView()
        self.palette.shapeClicked.connect(self._add_shape_at_center)

        self.properties_panel = PropertiesPanel(self.canvas)

        self.splitter.addWidget(self.palette)
        self.splitter.addWidget(self.canvas)
        self.splitter.addWidget(self.properties_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.setCentralWidget(self.splitter)

        self.properties_panel.clear()
        self.canvas.selectionSnapshotChanged.connect(
            self._handle_selection_snapshot
        )

        self._build_menu()
        self.statusBar().showMessage(
            "Tip: Ctrl+drag duplicates selected objects, Alt+mouse wheel zooms"
        )

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        act_load_py = QtGui.QAction("Load drawsvg-.py", self)
        act_load_py.triggered.connect(self.load_drawsvg_py)
        file_menu.addAction(act_load_py)

        act_save_py = QtGui.QAction("Save drawsvg-.py", self)
        act_save_py.triggered.connect(self.export_drawsvg_py)
        file_menu.addAction(act_save_py)

        file_menu.addSeparator()
        act_quit = QtGui.QAction("Quit", self)
        act_quit.setShortcut(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Quit))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        edit_menu = self.menuBar().addMenu("&Edit")

        self.act_undo = QtGui.QAction("Undo", self)
        self.act_undo.setShortcut(
            QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Undo)
        )
        self.act_undo.setShortcutContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.act_undo.triggered.connect(self.canvas.undo)
        edit_menu.addAction(self.act_undo)

        self.act_redo = QtGui.QAction("Redo", self)
        self.act_redo.setShortcut(
            QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Redo)
        )
        self.act_redo.setShortcutContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.act_redo.triggered.connect(self.canvas.redo)
        edit_menu.addAction(self.act_redo)

        edit_menu.addSeparator()

        act_clear_canvas = QtGui.QAction("Clear canvas", self)
        act_clear_canvas.triggered.connect(self.canvas.clear_canvas)
        edit_menu.addAction(act_clear_canvas)

        self.act_show_grid = QtGui.QAction("Show grid", self)
        self.act_show_grid.setCheckable(True)
        self.act_show_grid.setChecked(True)
        self.act_show_grid.toggled.connect(self.canvas.set_grid_visible)
        edit_menu.addAction(self.act_show_grid)

        self.canvas.gridVisibilityChanged.connect(self.act_show_grid.setChecked)

        history = self.canvas.history()
        history.historyChanged.connect(self._update_history_actions)
        self._update_history_actions(history.can_undo(), history.can_redo())

    def export_drawsvg_py(self):
        export_drawsvg_py(self.canvas.scene(), self)

    def load_drawsvg_py(self):
        import_drawsvg_py(self.canvas.scene(), self)

    def _add_shape_at_center(self, shape: str) -> None:
        self.canvas.add_shape_at_view_center(shape)

    def _update_history_actions(self, can_undo: bool, can_redo: bool) -> None:
        self.act_undo.setEnabled(can_undo)
        self.act_redo.setEnabled(can_redo)

    def _handle_selection_snapshot(self, payload: dict) -> None:
        self.properties_panel.update_snapshot(payload)
