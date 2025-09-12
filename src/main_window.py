from PySide6 import QtCore, QtGui, QtWidgets

from canvas_view import CanvasView
from palette import PaletteList
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

        self.splitter.addWidget(self.palette)
        self.splitter.addWidget(self.canvas)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self.splitter)

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
        act_clear_canvas = QtGui.QAction("Clear canvas", self)
        act_clear_canvas.triggered.connect(self.canvas.clear_canvas)
        edit_menu.addAction(act_clear_canvas)

        act_show_grid = QtGui.QAction("Show grid", self)
        act_show_grid.setCheckable(True)
        act_show_grid.setChecked(True)
        act_show_grid.toggled.connect(self.canvas.set_grid_visible)
        edit_menu.addAction(act_show_grid)

    def export_drawsvg_py(self):
        export_drawsvg_py(self.canvas.scene(), self)

    def load_drawsvg_py(self):
        import_drawsvg_py(self.canvas.scene(), self)
