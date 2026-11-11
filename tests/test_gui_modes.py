"""Mode-specific GUI behaviour and the guards around a live session."""

import pytest
import yaml

pytest.importorskip("PyQt5.QtWidgets")


class RunningController:
    """A controller that reports a live session and records the cleanup."""

    is_running = True
    manual = False
    e_matrix = None
    controls = None

    def __init__(self):
        self.calls = []
        self.start_of_experiment = object()
        self.is_finished = False
        self.online_fem_mgr = type("M", (), {
            "is_online": False, "is_ready": True, "initializing": False,
            "mesh_fn_msh": None, "roi_fn_hdf5": None, "coil_fn": None,
            "ensure_initialized": lambda self, callback=None: None})()

    def finish_experiment(self):
        self.calls.append("finish")

    def move_robot_away_from_head(self):
        self.calls.append("move_away")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append(name)
            return None
        return call


class StimulatorStub:
    def __init__(self):
        self.disarmed = 0

    def disarm(self):
        self.disarmed += 1


@pytest.fixture()
def running(window):
    controller = RunningController()
    window.set_controller(controller)
    return controller


def test_project_load_is_refused_while_a_session_runs(window, running, tmp_path):
    project = tmp_path / "proj.yaml"
    project.write_text(yaml.safe_dump({"fit_fun": "Sigmoid"}))

    error = window.load_project_file(str(project))
    assert error and "running" in error.lower()
    assert window.fitFunctionComboBox.currentText() != "Sigmoid"


def test_project_load_works_again_after_the_run(window, running, tmp_path):
    running.is_running = False
    project = tmp_path / "proj.yaml"
    project.write_text(yaml.safe_dump({"fit_fun": "Sigmoid"}))
    assert window.load_project_file(str(project)) is None
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"


def test_apply_config_dict_is_refused_while_a_session_runs(window, running):
    before = window.get_config_dict()
    assert window.apply_config_dict({"n_repetitions": 9}) is False
    assert window.get_config_dict() == before


def test_study_apply_is_refused_while_a_session_runs(window, running):
    window.cfg_fit_function.setCurrentText("Sigmoid")
    window.cfg_subsampling.setValue(3)
    window.on_study_apply()
    assert "Not applied" in window.cfg_study_status.text()
    assert window.fitFunctionComboBox.currentText() != "Sigmoid"


def test_study_apply_works_after_the_run(window, running):
    running.is_running = False
    window.cfg_fit_function.setCurrentText("Sigmoid")
    window.on_study_apply()
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"


def test_closing_during_a_session_finishes_it(window, running, qapp):
    stimulator = StimulatorStub()
    running.stimulator = stimulator
    window.close()
    qapp.processEvents()
    assert "finish" in running.calls
    assert "move_away" in running.calls
    assert stimulator.disarmed == 1


def test_closing_after_the_session_does_not_finish_it(window, running, qapp):
    running.is_running = False
    window.close()
    qapp.processEvents()
    assert "finish" not in running.calls


def test_manual_mode_hides_the_robot_and_keeps_the_session_usable(window, qapp):
    window.set_robot_manual()
    window.simulation = True
    qapp.processEvents()
    # The page still lays out and the log card took the camera column.
    assert window.groupBox_stats is not None
    assert not window.move_coil_up.isVisible()


pytestmark = pytest.mark.gui
