import sys
import warnings

from PySide6 import QtCore, QtGui, QtWidgets

from main_window import MainWindow


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    warnings.filterwarnings(
        "ignore",
        message="Enum value 'Qt::ApplicationAttribute.AA_UseHighDpiPixmaps' is marked as deprecated",
        category=DeprecationWarning,
    )
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    main()
