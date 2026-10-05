import pytest
from PySide6 import QtWidgets


@pytest.fixture
def dialog_type():
    from export_margins_dialog import ExportMarginsDialog

    return ExportMarginsDialog


def test_defaults_keep_legacy_margins_until_custom_enabled(application, dialog_type):
    dialog = dialog_type(None, True)
    assert dialog.margins() is None
    assert dialog.linked()
    fields = (dialog.left, dialog.top, dialog.right, dialog.bottom)
    assert [field.value() for field in fields] == [5, 5, 5, 5]
    assert not any(field.isEnabled() for field in fields)
    assert not dialog.link_sides.isEnabled()

    dialog.custom_margins.click()
    assert all(field.isEnabled() for field in fields)
    assert dialog.link_sides.isEnabled()
    dialog.custom_margins.click()
    assert dialog.margins() is None
    assert not any(field.isEnabled() for field in fields)
    assert not dialog.link_sides.isEnabled()


@pytest.mark.parametrize("side", ("left", "top", "right", "bottom"))
def test_linked_edit_updates_every_side(application, dialog_type, side):
    from export_margins import ExportMargins

    dialog = dialog_type(None, True)
    dialog.custom_margins.click()
    getattr(dialog, side).setValue(12.34)
    assert dialog.margins() == ExportMargins(12.34, 12.34, 12.34, 12.34)


def test_independent_edits_and_linking_use_left_value(application, dialog_type):
    from export_margins import ExportMargins

    original = ExportMargins(1.25, 2.5, 3.75, 4)
    dialog = dialog_type(original, False)
    assert dialog.margins() == original
    dialog.top.setValue(20)
    assert dialog.margins() == ExportMargins(1.25, 20, 3.75, 4)
    dialog.link_sides.click()
    assert dialog.linked()
    assert dialog.margins() == ExportMargins(1.25, 1.25, 1.25, 1.25)
    dialog.link_sides.click()
    dialog.bottom.setValue(40)
    assert dialog.margins() == ExportMargins(1.25, 1.25, 1.25, 40)


def test_opening_does_not_overwrite_asymmetric_values(application, dialog_type):
    from export_margins import ExportMargins

    original = ExportMargins(1, 2, 3, 4)
    dialog = dialog_type(original, True)
    assert dialog.margins() == original


def test_controls_keep_values_within_export_model_limits(application, dialog_type):
    from export_margins import ExportMargins

    dialog = dialog_type(None, False)
    dialog.custom_margins.click()
    dialog.left.setValue(-1)
    dialog.top.setValue(10001)
    dialog.right.setValue(3.456)
    dialog.bottom.setValue(0.01)
    assert dialog.margins() == ExportMargins(0, 10000, 3.46, 0.01)


def test_ok_accepts_explicit_zero_margins(application, dialog_type):
    from export_margins import ExportMargins

    dialog = dialog_type(None, True)
    dialog.custom_margins.click()
    dialog.left.setValue(0)
    dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.margins() == ExportMargins(0, 0, 0, 0)


@pytest.mark.parametrize("close_window", (False, True))
def test_cancel_rejects_edits_without_mutating_input(application, dialog_type, close_window):
    from export_margins import ExportMargins

    original = ExportMargins(1, 2, 3, 4)
    dialog = dialog_type(original, False)
    dialog.show()
    dialog.left.setValue(99)
    if close_window:
        dialog.close()
    else:
        dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).click()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Rejected
    assert original == ExportMargins(1, 2, 3, 4)


def test_reset_changes_pending_dialog_without_accepting(application, dialog_type):
    from export_margins import ExportMargins

    original = ExportMargins(1, 2, 3, 4)
    dialog = dialog_type(original, False)
    dialog.show()
    dialog.top.setValue(77)
    dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Reset).click()
    assert dialog.isVisible()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Rejected
    assert dialog.margins() is None
    assert dialog.linked()
    assert [dialog.left.value(), dialog.top.value(), dialog.right.value(), dialog.bottom.value()] == [5, 5, 5, 5]
    assert not dialog.left.isEnabled()
    assert not dialog.link_sides.isEnabled()
    assert original == ExportMargins(1, 2, 3, 4)
    dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.margins() is None
