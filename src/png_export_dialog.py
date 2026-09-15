"""Settings and destination for a single PNG export."""

from pathlib import Path
import re

from PySide6 import QtCore, QtGui, QtWidgets

from export_renderer import ExportRenderer, PNG_BASE_DPI


class PngExportDialog(QtWidgets.QDialog):
    def __init__(self, content_rect: QtCore.QRectF, initial_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export PNG")
        self.setMinimumWidth(520)
        self._content_rect = content_rect
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.dpi = QtWidgets.QSpinBox()
        self.dpi.setRange(36, 1200)
        self.dpi.setSuffix(" DPI")
        self.dpi.setValue(300)
        form.addRow("Resolution", self.dpi)
        self.pixel_size = QtWidgets.QLabel()
        form.addRow("Image size", self.pixel_size)
        self.background = QtWidgets.QComboBox()
        self.background.addItems(["White", "Transparent"])
        form.addRow("Background", self.background)

        folder_row = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLineEdit(str(initial_path.parent))
        browse = QtWidgets.QPushButton("Browse…")
        folder_row.addWidget(self.folder)
        folder_row.addWidget(browse)
        form.addRow("Save folder", folder_row)
        self.filename = QtWidgets.QLineEdit(initial_path.name)
        form.addRow("File name", self.filename)
        self.full_path = QtWidgets.QLineEdit()
        self.full_path.setReadOnly(True)
        form.addRow("Full path", self.full_path)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        browse.clicked.connect(self._browse)
        self.folder.textChanged.connect(self._refresh)
        self.filename.textChanged.connect(self._refresh)
        self.dpi.valueChanged.connect(self._refresh)
        self._refresh()

    def output_path(self) -> Path:
        name = self.filename.text().strip()
        if (
            not name or name in {".", ".."} or name.endswith((".", " "))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0])
        ):
            raise ValueError("Enter a valid file name without folder separators.")
        if not name.casefold().endswith(".png"):
            name += ".png"
        if not self.folder.text().strip():
            raise ValueError("Choose a save folder.")
        folder = Path(self.folder.text().strip()).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("The save folder does not exist.")
        path = folder / name
        if path.is_dir():
            raise ValueError("The output path points to a folder.")
        return path

    def scale(self) -> float:
        return self.dpi.value() / PNG_BASE_DPI

    def background_color(self) -> QtGui.QColor | None:
        return QtGui.QColor("white") if self.background.currentIndex() == 0 else None

    def _refresh(self) -> None:
        self.full_path.clear()
        self.pixel_size.clear()
        try:
            size = ExportRenderer._pixel_size(self._content_rect, self.scale())
            self.pixel_size.setText(f"{size.width():,} × {size.height():,} pixels")
            self.full_path.setText(str(self.output_path()))
            message = ""
        except (OSError, ValueError) as error:
            message = str(error)
        self.error.setText(message)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setEnabled(not message)

    def _browse(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Save folder", self.folder.text()
        )
        if folder:
            self.folder.setText(folder)

    def accept(self) -> None:
        self._refresh()
        if self.error.text():
            return
        path = self.output_path()
        if path.exists() and QtWidgets.QMessageBox.question(
            self, "Replace file?", f"Replace the existing file?\n{path}",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        super().accept()
