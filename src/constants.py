# drawsvg-ui
# Copyright (C) 2025 Andreas Wambold
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from PySide6 import QtCore, QtGui

PALETTE_MIME = "application/x-drawsvg-shape"
SHAPES = (
    "Rectangle",
    "Rounded Rectangle",
    "Split Rounded Rectangle",
    "Ellipse",
    "Circle",
    "Triangle",
    "Diamond",
    "Line",
    "Arrow",
    "Block Arrow",
    "Curvy Right Bracket",
    "Text",
    "Folder Tree",
)

DEFAULTS = {
    "Rectangle": (160.0, 100.0),   # w, h
    "Rounded Rectangle": (160.0, 100.0),   # w, h
    "Split Rounded Rectangle": (180.0, 120.0),   # w, h
    "Ellipse":   (160.0, 100.0),   # w, h
    "Circle":    (100.0, 100.0),   # diameter, diameter
    "Triangle":  (160.0, 100.0),   # w, h
    "Diamond":   (140.0, 140.0),   # w, h
    "Line":      (150.0, 0.0),     # length, (unused)
    "Arrow":     (150.0, 0.0),     # length, (unused)
    "Block Arrow": (200.0, 120.0), # w, h
    "Curvy Right Bracket": (80.0, 160.0),  # w, h
    "Text":      (100.0, 50.0),    # placeholder bbox
    "Folder Tree": (240.0, 200.0), # auto-sized, reference bbox
}

PEN_NORMAL = QtGui.QPen(QtGui.QColor("#000"), 2)
SELECTED_COLOR = QtGui.QColor("#16CCFA")
PEN_SELECTED = QtGui.QPen(SELECTED_COLOR, 1, QtCore.Qt.PenStyle.DashLine)
PEN_SELECTED.setCosmetic(True)
DEFAULT_FILL = QtGui.QBrush(QtCore.Qt.white)
DEFAULT_TEXT_COLOR = QtGui.QColor("#000")
DEFAULT_FONT_FAMILY = "Arial"

# Hover preview for selectable items in the canvas.
# Increase/decrease strength for a stronger/weaker effect.
HOVER_PREVIEW_STRENGTH = 0.8
# Total number of X markers drawn around the hovered item's border.
HOVER_PREVIEW_X_COUNT = 16
HOVER_PREVIEW_COLOR = QtGui.QColor("#14b5ff")

# Default dash patterns used when exporting/importing common pen styles.
PEN_STYLE_DASH_ARRAYS = {
    QtCore.Qt.PenStyle.SolidLine: (),
    QtCore.Qt.PenStyle.DashLine: (4.0, 4.0),
    QtCore.Qt.PenStyle.DotLine: (1.0, 4.0),
}
