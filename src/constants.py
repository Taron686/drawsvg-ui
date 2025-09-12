from PySide6 import QtCore, QtGui

PALETTE_MIME = "application/x-drawsvg-shape"
SHAPES = (
    "Rectangle",
    "Ellipse",
    "Circle",
    "Triangle",
    "Line",
    "Arrow",
    "Text",
)

DEFAULTS = {
    "Rectangle": (160.0, 100.0),   # w, h
    "Ellipse":   (160.0, 100.0),   # w, h
    "Circle":    (100.0, 100.0),   # diameter, diameter
    "Triangle":  (160.0, 100.0),   # w, h
    "Line":      (150.0, 0.0),     # length, (unused)
    "Arrow":     (150.0, 0.0),     # length, (unused)
    "Text":      (100.0, 30.0),    # placeholder bbox
}

PEN_NORMAL = QtGui.QPen(QtGui.QColor("#222"), 2)
SELECTED_COLOR = QtGui.QColor("#14b5ff")
PEN_SELECTED = QtGui.QPen(SELECTED_COLOR, 2, QtCore.Qt.PenStyle.DotLine)
PEN_SELECTED.setCosmetic(True)
