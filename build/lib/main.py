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
