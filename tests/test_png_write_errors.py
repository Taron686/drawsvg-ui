import pytest
from PySide6 import QtGui

from export_renderer import ExportRenderer, ExportRequest


@pytest.mark.parametrize("details", [
    "Access is denied.",
    "Cannot open device for writing: Das System kann die angegebene Datei nicht finden.",
])
def test_png_write_failure_explains_folder_permissions(canvas_view, monkeypatch, tmp_path, details):
    canvas_view.add_shape_at_view_center("Rectangle")
    monkeypatch.setattr(QtGui.QImageWriter, "write", lambda *_: False)
    monkeypatch.setattr(QtGui.QImageWriter, "error", lambda *_: QtGui.QImageWriter.ImageWriterError.DeviceError)
    monkeypatch.setattr(QtGui.QImageWriter, "errorString", lambda *_: details)
    output = tmp_path / "blocked.png"
    with pytest.raises(RuntimeError) as caught:
        ExportRenderer(canvas_view.scene()).export_png(output, ExportRequest())
    message = str(caught.value)
    assert str(output) in message
    assert "permission to write" in message
    assert "Controlled folder access may be blocking" in message
    assert details in message
    assert not output.exists()


def test_png_missing_folder_is_reported_separately(canvas_view, tmp_path):
    canvas_view.add_shape_at_view_center("Rectangle")
    with pytest.raises(RuntimeError, match="save folder does not exist") as caught:
        ExportRenderer(canvas_view.scene()).export_png(
            tmp_path / "missing" / "image.png", ExportRequest()
        )
    assert "Controlled folder access" not in str(caught.value)


def test_png_encoder_error_is_not_reported_as_permission_error(canvas_view, monkeypatch, tmp_path):
    canvas_view.add_shape_at_view_center("Rectangle")
    monkeypatch.setattr(QtGui.QImageWriter, "write", lambda *_: False)
    monkeypatch.setattr(QtGui.QImageWriter, "error", lambda *_: QtGui.QImageWriter.ImageWriterError.UnsupportedFormatError)
    monkeypatch.setattr(QtGui.QImageWriter, "errorString", lambda *_: "Unsupported image format")
    with pytest.raises(RuntimeError, match="Unsupported image format") as caught:
        ExportRenderer(canvas_view.scene()).export_png(tmp_path / "image.png", ExportRequest())
    assert "permission to write" not in str(caught.value)
