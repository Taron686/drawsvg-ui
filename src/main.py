# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

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
