from math import ceil

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from items import RectItem
from main_window import MainWindow
from png_export_dialog import PngExportDialog


@pytest.mark.parametrize("transparent", (False, True))
def test_png_menu_renders_selected_resolution_and_background(application, monkeypatch, tmp_path, transparent):
    window = MainWindow(recent_files_path=tmp_path / "recent.json", recovery_enabled=False)
    item = RectItem(0, 0, 160, 100)
    item.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    window.canvas.scene().addItem(item)
    bounds = item.sceneBoundingRect()

    def choose(dialog):
        assert dialog.dpi.value() == 300
        dialog.folder.setText(str(tmp_path))
        dialog.filename.setText("My diagram")
        dialog.background.setCurrentIndex(int(transparent))
        assert dialog.full_path.text() == str(tmp_path / "My diagram.png")
        dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).click()
        return dialog.result()

    monkeypatch.setattr(PngExportDialog, "exec", choose)
    window.actionExport_png.trigger()
    image = QtGui.QImage(str(tmp_path / "My diagram.png"))
    assert image.size() == QtCore.QSize(ceil(bounds.width() * 300 / 96), ceil(bounds.height() * 300 / 96))
    assert image.dotsPerMeterX() * 0.0254 == pytest.approx(300, abs=0.02)
    assert image.dotsPerMeterY() == image.dotsPerMeterX()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    assert center.alpha() == (0 if transparent else 255)
    if not transparent:
        assert center == QtGui.QColor("white")
    window._force_close = True
    window.close()


def test_cancel_png_does_not_write_file(application, monkeypatch, tmp_path):
    window = MainWindow(recent_files_path=tmp_path / "recent.json", recovery_enabled=False)
    window.canvas.scene().addItem(RectItem(0, 0, 20, 20))

    def cancel(dialog):
        dialog.folder.setText(str(tmp_path))
        dialog.filename.setText("cancelled.png")
        dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).click()
        return dialog.result()

    monkeypatch.setattr(PngExportDialog, "exec", cancel)
    window.actionExport_png.trigger()
    assert not (tmp_path / "cancelled.png").exists()
    window._force_close = True
    window.close()


def test_destination_validation_and_pixel_budget(application, tmp_path):
    dialog = PngExportDialog(QtCore.QRectF(0, 0, 160, 100), tmp_path / "drawing.png")
    save = dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
    assert save.isEnabled()
    for name in ("", "../escape", "CON.png", "bad:name"):
        dialog.filename.setText(name)
        assert not save.isEnabled()
    dialog.filename.setText("diagram.PNG")
    assert dialog.output_path() == tmp_path / "diagram.PNG"
    dialog.folder.setText(str(tmp_path / "missing"))
    assert not save.isEnabled()
    huge = PngExportDialog(QtCore.QRectF(0, 0, 10000, 10000), tmp_path / "huge.png")
    assert not huge.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).isEnabled()
    assert "64 megapixel" in huge.error.text()


def test_overwrite_requires_confirmation(application, monkeypatch, tmp_path):
    path = tmp_path / "existing.png"
    path.write_bytes(b"existing")
    dialog = PngExportDialog(QtCore.QRectF(0, 0, 160, 100), path)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_: QtWidgets.QMessageBox.StandardButton.No)
    dialog.accept()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Rejected
    assert path.read_bytes() == b"existing"
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_: QtWidgets.QMessageBox.StandardButton.Yes)
    dialog.accept()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
