from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ruler_widget import RulerWidget


def test_dense_horizontal_ruler_keeps_ticks_but_spaces_labels(
    application: QtWidgets.QApplication, canvas_view
) -> None:
    ruler = RulerWidget(QtCore.Qt.Orientation.Horizontal, canvas_view)
    ruler.resize(400, 22)
    canvas_view.ruler_ticks = lambda *_args: tuple(
        (float(index), float(index * 10)) for index in range(10)
    )
    canvas_view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), 0)
    ruler._scene_range = lambda: (0.0, 9.0)
    painted: list[bool] = []
    ruler._paint_tick = lambda *_args, show_label=True, **_kwargs: painted.append(
        show_label
    )

    ruler.paintEvent(QtGui.QPaintEvent(ruler.rect()))

    assert len(painted) == 10  # tick marks are retained at every position
    assert 1 <= sum(painted) < len(painted)  # labels are adaptively thinned
    ruler.close()


def test_paint_tick_can_draw_tick_without_label(
    application: QtWidgets.QApplication, canvas_view
) -> None:
    ruler = RulerWidget(QtCore.Qt.Orientation.Horizontal, canvas_view)
    ruler.resize(100, 22)
    image = QtGui.QImage(ruler.size(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    ruler._paint_tick(painter, 20, 10.0, show_label=False)
    painter.end()
    assert image.pixelColor(20, 19).alpha() > 0
    ruler.close()
