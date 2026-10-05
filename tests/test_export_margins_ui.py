from __future__ import annotations

import runpy
from xml.etree import ElementTree

import pytest
from PySide6 import QtCore, QtGui, QtPdf, QtWidgets

import main_window
from main_window import MainWindow
from png_export_dialog import PngExportDialog
from shape_registry import SHAPE_REGISTRY


@pytest.fixture
def margin_window(application, tmp_path):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(recent_files_path=tmp_path / "recent.json", settings=settings,
                        recovery_enabled=False)
    yield window, settings
    window._force_close = True
    window.close()


def _choose_margins(dialog):
    dialog.custom_margins.setChecked(True)
    dialog.link_sides.setChecked(False)
    for side, value in (("left", 10), ("top", 5), ("right", 20), ("bottom", 15)):
        getattr(dialog, side).setValue(value)
    dialog.accept()
    return dialog.result()


def test_edit_margins_persist_without_changing_document(margin_window, monkeypatch, tmp_path):
    window, settings = margin_window
    edit = window.menuBar().findChild(QtWidgets.QMenu, "menuEdit")
    assert "Export Margins…" in [action.text() for action in edit.actions()]
    before = window.canvas._serialize_scene_state()
    dirty = window.document_controller.dirty
    states = list(window.canvas.history()._states)
    settings.setValue("unrelated/value", "preserved")
    monkeypatch.setattr(main_window.ExportMarginsDialog, "exec", _choose_margins)
    window.actionExport_margins.trigger()
    settings.sync()
    restored = MainWindow(recent_files_path=tmp_path / "recent2.json", settings=settings,
                          recovery_enabled=False)
    try:
        margins = restored._export_margins
        assert (margins.left, margins.top, margins.right, margins.bottom) == (10, 5, 20, 15)
        assert not restored._export_margins_linked
        assert window.canvas._serialize_scene_state() == before
        assert window.document_controller.dirty == dirty
        assert list(window.canvas.history()._states) == states
        assert settings.value("unrelated/value") == "preserved"
    finally:
        restored._force_close = True
        restored.close()


def test_cancel_margin_changes_keeps_settings(margin_window, monkeypatch):
    window, settings = margin_window
    monkeypatch.setattr(main_window.ExportMarginsDialog, "exec", _choose_margins)
    window.actionExport_margins.trigger()
    before = {key: settings.value(key) for key in settings.allKeys()}
    margins = window._export_margins

    def cancel(dialog):
        dialog.left.setValue(99)
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(main_window.ExportMarginsDialog, "exec", cancel)
    window.actionExport_margins.trigger()
    assert window._export_margins == margins
    assert {key: settings.value(key) for key in settings.allKeys()} == before


@pytest.mark.parametrize("bad_value", ["broken", "nan", "inf", -1, 10001])
def test_invalid_saved_margin_uses_legacy_defaults(application, tmp_path, bad_value):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    for key, value in {"enabled": True, "linked": False, "left": bad_value,
                       "top": 5, "right": 20, "bottom": 15}.items():
        settings.setValue(f"export/margins/{key}", value)
    window = MainWindow(recent_files_path=tmp_path / "recent.json", settings=settings,
                        recovery_enabled=False)
    try:
        assert window._export_margins is None
        assert window._export_margins_linked is True
    finally:
        window._force_close = True
        window.close()


@pytest.mark.parametrize("export_format", ["svg", "png", "pdf", "py"])
def test_menu_exports_use_margin_preferences(margin_window, monkeypatch, tmp_path, export_format):
    window, _settings = margin_window
    item = SHAPE_REGISTRY.create("Rectangle", 100, 200, 100, 50)
    item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
    item.setBrush(QtGui.QColor("red"))
    window.canvas.scene().addItem(item)
    item.setSelected(True)
    window.canvas.history().capture_now()
    window.canvas.history()._timer.stop()
    before = window.canvas._serialize_scene_state()
    states = list(window.canvas.history()._states)
    dirty = window.document_controller.dirty
    monkeypatch.setattr(main_window.ExportMarginsDialog, "exec", _choose_margins)
    window.actionExport_margins.trigger()
    output = tmp_path / f"drawing.{export_format}"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **kw: (str(output), ""))

    def choose_png(dialog):
        dialog.folder.setText(str(tmp_path))
        dialog.filename.setText(output.name)
        dialog.dpi.setValue(192)
        assert dialog.pixel_size.text() == "260 × 140 pixels"
        dialog.background.setCurrentIndex(1)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PngExportDialog, "exec", choose_png)
    errors = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a: errors.append(a[2]))
    action = window.actionSave_drawsvg_py if export_format == "py" else getattr(window, f"actionExport_{export_format}")
    action.trigger()
    assert not errors
    assert output.exists()
    if export_format == "png":
        image = QtGui.QImage(str(output))
        assert image.size() == QtCore.QSize(260, 140)
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(25, 15).red() == 255
    elif export_format == "pdf":
        pdf = QtPdf.QPdfDocument()
        assert pdf.load(str(output)) == QtPdf.QPdfDocument.Error.None_
        assert pdf.pagePointSize(0) == QtCore.QSizeF(130, 70)
        pdf.close()
    else:
        root = (ElementTree.fromstring(runpy.run_path(str(output))["build_drawing"]().as_svg())
                if export_format == "py" else ElementTree.parse(output).getroot())
        assert tuple(map(float, root.attrib["viewBox"].split()[2:])) == (130, 70)
    assert window.canvas._serialize_scene_state() == before
    assert list(window.canvas.history()._states) == states
    assert window.document_controller.dirty == dirty
    assert item.isSelected()


def test_reset_margins_restores_legacy_mode_after_restart(margin_window, monkeypatch, tmp_path):
    window, settings = margin_window
    monkeypatch.setattr(main_window.ExportMarginsDialog, "exec", _choose_margins)
    window.actionExport_margins.trigger()

    def reset(dialog):
        dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Reset).click()
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(main_window.ExportMarginsDialog, "exec", reset)
    window.actionExport_margins.trigger()
    settings.sync()
    restored = MainWindow(recent_files_path=tmp_path / "restored.json", settings=settings,
                          recovery_enabled=False)
    try:
        assert restored._export_margins is None
        assert restored._export_margins_linked
    finally:
        restored._force_close = True
        restored.close()


def test_custom_empty_python_export_reports_error(margin_window, monkeypatch, tmp_path):
    window, _settings = margin_window
    monkeypatch.setattr(main_window.ExportMarginsDialog, "exec", _choose_margins)
    window.actionExport_margins.trigger()
    output = tmp_path / "empty.py"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **kw: (str(output), ""))
    errors = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a: errors.append(a[2]))
    window.actionSave_drawsvg_py.trigger()
    assert len(errors) == 1
    assert not output.exists()
