from PySide6 import QtCore

from main_window import MainWindow


def test_saved_grid_preference_is_part_of_clean_startup_baseline(application, tmp_path):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    settings.setValue("view/settings_version", 1)
    settings.setValue("view/grid", False)
    window = MainWindow(recent_files_path=tmp_path / "recent.json", settings=settings,
                        recovery_enabled=False)
    try:
        window.document_controller.refresh_dirty_state()
        assert not window.document_controller.dirty
        assert window.document_controller.revision == 0
        assert not window.canvas._serialize_scene_state()["grid_visible"]
        assert not window.canvas.history().can_undo()
        application.processEvents()
        window.document_controller.refresh_dirty_state()
        assert not window.document_controller.dirty
    finally:
        window._force_close = True
        window.close()
