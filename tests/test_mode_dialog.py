"""The no-argument mode selector's labels and sizing."""

import pytest

pytest.importorskip("PyQt5.QtWidgets")


@pytest.fixture()
def dialog(qapp):
    from neuropilot.controller.experiment_mode import ModeSelectionDialog
    view = ModeSelectionDialog()
    yield view
    view.close()
    view.deleteLater()
    qapp.processEvents()


def test_dialog_uses_the_product_name(dialog):
    assert dialog.windowTitle() == "TMS NeuroPilot"


def test_dialog_contains_only_the_selector_heading_and_buttons(dialog):
    from PyQt5.QtWidgets import QLabel

    assert [label.text() for label in dialog.findChildren(QLabel)] == [
        "Select mode:"]
    assert (
        dialog.btn_sim.text(),
        dialog.btn_real.text(),
        dialog.btn_manual.text(),
        dialog.btn_training.text(),
    ) == ("Simulation", "Robotic TMS", "Manual TMS", "Training")


def test_selector_text_and_buttons_are_larger(dialog):
    assert dialog.btn_sim.minimumHeight() >= 70
    assert dialog.btn_real.minimumHeight() >= 70
    assert dialog.btn_manual.minimumHeight() >= 70
    assert dialog.btn_training.minimumHeight() >= 70


pytestmark = pytest.mark.gui
