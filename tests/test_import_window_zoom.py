from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from main_window import MainWindow


def test_load_dialog_fits_imported_canvas_after_show(
    application: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    drawing = tmp_path / "drawing.py"
    drawing.write_text(
        "import drawsvg as draw\n"
        "d = draw.Drawing(402, 363, origin=(-253, -468))\n"
        "d.append(draw.Rectangle(-246, -461, 160, 100, fill='white'))\n",
        encoding="utf-8",
    )
    root = MainWindow(
        recent_files_path=tmp_path / "recent.json", recovery_enabled=False
    )
    messages = []
    previous_handler = QtCore.qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )

    def select_file(*_args, **_kwargs):
        # A native file dialog pumps events while the target window is hidden.
        application.processEvents()
        return str(drawing), "Python (*.py)"

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", select_file)
    try:
        root.show()
        application.processEvents()
        root.load_drawsvg_py()
        for _ in range(3):
            application.processEvents()
        imported = next(w for w in root._window_registry.windows() if w is not root)
        imported.grab()
        assert imported.canvas.transform().m11() > 0.1
        assert not any("QPainter::" in message for message in messages)

        # Showing an existing window must preserve the user's zoom.
        imported.canvas.scale(1.5, 1.5)
        zoom = imported.canvas.transform().m11()
        imported.hide()
        imported.show()
        application.processEvents()
        assert imported.canvas.transform().m11() == pytest.approx(zoom)
    finally:
        for window in tuple(root._window_registry.windows()):
            window._force_close = True
            window.close()
        QtCore.qInstallMessageHandler(previous_handler)
