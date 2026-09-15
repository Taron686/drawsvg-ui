# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

import sys
import warnings

from PySide6 import QtCore, QtWidgets

from app_logging import install_excepthook, shutdown_logging, start_session
from main_window import MainWindow

RECOVERY_ENABLED = False


def main():
    restore_hook = install_excepthook()
    start_session()
    try:
        app = QtWidgets.QApplication(sys.argv)
        win = MainWindow(
            recovery_enabled=RECOVERY_ENABLED,
            check_startup_recovery=RECOVERY_ENABLED,
        )
        win.show()
        return app.exec()
    finally:
        shutdown_logging()
        restore_hook()


if __name__ == "__main__":
    warnings.filterwarnings(
        "ignore",
        message="Enum value 'Qt::ApplicationAttribute.AA_UseHighDpiPixmaps' is marked as deprecated",
        category=DeprecationWarning,
    )
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    sys.exit(main())
