from __future__ import annotations

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from items import RectItem
from main_window import MainWindow


@pytest.fixture
def palette_window(application, tmp_path):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(
        recent_files_path=tmp_path / "recent.json", settings=settings, recovery_enabled=False,
    )
    window.canvas.setFixedSize(800, 600)
    window.show()
    application.processEvents()
    window.canvas.setTransform(QtGui.QTransform())
    window.canvas._master_origin = QtCore.QPointF()
    window.canvas.centerOn(117, 139)
    try:
        yield window
    finally:
        window._force_close = True
        window.close()


def _click_shape(window, shape, alt):
    palette = window.palette
    cell = next(palette.item(index) for index in range(palette.count())
                if palette.item(index).data(QtCore.Qt.ItemDataRole.UserRole) == shape)
    palette.scrollToItem(cell)
    before = set(window.canvas.scene().items())
    modifiers = (QtCore.Qt.KeyboardModifier.AltModifier if alt
                 else QtCore.Qt.KeyboardModifier.NoModifier)
    QTest.mouseClick(palette.viewport(), QtCore.Qt.MouseButton.LeftButton, modifiers,
                     palette.visualItemRect(cell).center())
    created = [item for item in window.canvas.scene().items()
               if item not in before and item.data(0) == shape]
    assert len(created) == 1
    return created[0]


@pytest.mark.parametrize("grid,alignment,normal", [
    (True, True, (50, 100)), (True, False, (50, 100)),
    (False, True, (40, 88)), (False, False, (36, 88)),
])
@pytest.mark.parametrize("alt", [False, True])
def test_palette_click_respects_alt_in_all_snap_modes(palette_window, grid, alignment, normal, alt):
    view = palette_window.canvas
    view.set_grid_snap_enabled(grid)
    view.set_alignment_snap_enabled(alignment)
    view._grid_size = 50
    view.add_guide("vertical", 39)
    item = _click_shape(palette_window, "Rectangle", alt)
    assert item.pos() == QtCore.QPointF(*((36, 88) if alt else normal))
    if alt or not alignment:
        assert view._active_snap_guides == {}
    elif not grid:
        assert view._active_snap_guides["vertical"] == 39


@pytest.mark.parametrize("shape", ["Line", "Arrow"])
@pytest.mark.parametrize("alt", [False, True])
def test_palette_click_alt_preserves_default_line_size_and_avoids_collisions(palette_window, shape, alt):
    view = palette_window.canvas
    view._grid_size = 40
    first = _click_shape(palette_window, shape, alt)
    assert first.path().boundingRect().width() == (150 if alt else 160)
    if alt:
        assert first.pos() == QtCore.QPointF(41, 138)
    second = _click_shape(palette_window, shape, alt)
    assert second.path().boundingRect().width() == (150 if alt else 160)
    assert not first.sceneBoundingRect().intersects(second.sceneBoundingRect())


def test_palette_alt_preview_does_not_avoid_a_collision_only_at_snapped_position(palette_window):
    view = palette_window.canvas
    view._grid_size = 50
    # The free Rectangle ends at x196; the grid-bound preview reaches x210.
    obstacle = RectItem(202, 130, 3, 3)
    obstacle.setData(0, "Rectangle")
    view.scene().addItem(obstacle)
    item = _click_shape(palette_window, "Rectangle", True)
    assert item.pos() == QtCore.QPointF(36, 88)
    assert not item.sceneBoundingRect().intersects(obstacle.sceneBoundingRect())


def test_palette_modifier_lifecycle_clears_previous_helper_feedback(palette_window):
    view = palette_window.canvas
    view.set_grid_snap_enabled(False)
    view.add_guide("vertical", 39)
    normal = _click_shape(palette_window, "Rectangle", False)
    assert normal.pos() == QtCore.QPointF(40, 88)
    assert view._active_snap_guides == {"vertical": 39}
    view.scene().removeItem(normal)
    free = _click_shape(palette_window, "Rectangle", True)
    assert free.pos() == QtCore.QPointF(36, 88)
    assert view._active_snap_guides == {}
    view.scene().removeItem(free)
    normal_again = _click_shape(palette_window, "Rectangle", False)
    assert normal_again.pos() == QtCore.QPointF(40, 88)
    assert view._active_snap_guides == {"vertical": 39}
