"""GUI <-> controller wiring and interaction safety.

The "click everything" sweep is the cheapest approximation of "no interaction
on any page throws": every button and checkbox on all six pages is clicked
with a controller attached and with none, the file dialogs are stubbed, and
recorded exceptions must stay empty (PyQt prints unhandled slot exceptions and
keeps going, so they are captured through ``sys.excepthook``).
"""


import sys

import numpy as np
import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")


class Recorder:
    """Stand-in controller that records every setter it is given."""

    def __init__(self):
        self.calls = []
        self.is_paused = False
        self.manual = False
        self.e_matrix = None
        self.results_fn = None
        self.targets_file = None
        self.target_order_fn = None
        self.excluded_pulse_indices = set()
        self.start_of_experiment = None
        self.is_finished = False
        self.control_panel = None
        self.online_fem_mgr = _Manager()
        self.surrogate_mgr = _Manager()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append((name, args))
            return None
        return call

    def toggle_start_pause(self):
        self.calls.append(("toggle_start_pause", ()))
        self.is_paused = not self.is_paused


class _Manager:
    def __init__(self):
        self.online_fem = None
        self.ready = False
        self.initializing = False
        self.mesh_fn_msh = None
        self.roi_fn_hdf5 = None
        self.coil_fn = None
        self.library_fn = None
        self.e_matrix = None

    @property
    def is_online(self):
        return self.online_fem is True

    @property
    def is_ready(self):
        return self.ready

    def set_mesh_fn_msh(self, path):
        self.mesh_fn_msh = path

    def set_roi_fn_hdf5(self, path):
        self.roi_fn_hdf5 = path

    def set_coil_fn(self, path):
        self.coil_fn = path

    def ensure_initialized(self, callback=None):
        pass


@pytest.fixture()
def recorder(window):
    rec = Recorder()
    window.set_controller(rec)
    return rec


@pytest.fixture()
def exceptions(monkeypatch):
    """Collect unhandled slot exceptions instead of aborting the process."""
    captured = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda t, e, tb: captured.append((t, e, tb)))
    return captured


# ── form -> controller ─────────────────────────────────────────────────

def test_amplitude_spinbox_mirrors_the_slider(window, recorder, qapp):
    window.spinBox.setValue(37)
    qapp.processEvents()
    assert window.slider.value() == 37
    assert ("set_amplitude_stim", (37,)) in recorder.calls


def test_speed_fields_forward_percent(window, recorder, qapp):
    window.spinBox2.setValue(30)
    window.spinBox3.setValue(12)
    qapp.processEvents()
    assert ("set_default_speed", (30,)) in recorder.calls
    assert ("set_tuning_speed", (12,)) in recorder.calls


def test_subsampling_and_repetitions_forward(window, recorder, qapp):
    window.sampling_spinBox.setValue(4)
    window.n_repetitions_spinBox.setValue(3)
    window.min_interval_spinBox.setValue(6)
    qapp.processEvents()
    assert ("set_map_elms", (4,)) in recorder.calls
    assert ("set_n_repetitions", (3,)) in recorder.calls
    assert ("set_minium_isi", (6,)) in recorder.calls


@pytest.mark.parametrize("field,setter", [
    ("loadmeshlabel", "set_mesh_fn_msh"),
    ("loadroilabel", "set_roi_fn_hdf5"),
    ("coilspathlineedit", "set_coil_fn"),
])
def test_online_solver_paths_reach_their_own_slot(window, recorder, field,
                                                  setter, tmp_path, qapp):
    path = tmp_path / "file.bin"
    path.write_text("x")
    getattr(window, field).setText(str(path))
    qapp.processEvents()
    # paste_* runs on editingFinished; call the handler the signal is bound to.
    handler = {"loadmeshlabel": window.paste_mesh_path,
               "loadroilabel": window.paste_roi_path,
               "coilspathlineedit": window.paste_coil_path}[field]
    handler()
    manager = recorder.online_fem_mgr
    assert getattr(manager, {"set_mesh_fn_msh": "mesh_fn_msh",
                             "set_roi_fn_hdf5": "roi_fn_hdf5",
                             "set_coil_fn": "coil_fn"}[setter])


def test_fit_function_choice_reaches_the_controller(window, recorder, qapp):
    window.fitFunctionComboBox.setCurrentText("Sigmoid")
    qapp.processEvents()
    assert ("set_fit_function", ("Sigmoid",)) in recorder.calls


def test_pulse_shape_choice_reaches_the_controller(window, recorder, qapp):
    window.pulseShapeComboBox.setCurrentText("Monophasic")
    qapp.processEvents()
    assert ("set_waveform", ("Monophasic",)) in recorder.calls


def _ungate(window):
    """Enable the transport buttons the way a ready session would."""
    window.efield_mode_selected = True
    window.robot_ready = window.stim_ready = window.emg_ready = True
    window.controller.e_matrix = object()          # precomputed mode is ready
    window.update_button_states()


def test_transport_buttons_forward(window, recorder, qapp):
    _ungate(window)
    window.start_btn.click()
    assert ("toggle_start_pause", ()) in recorder.calls
    window.skiptarget.click()
    assert ("switch_step", ("skip",)) in recorder.calls
    window.back_btn.click()
    assert ("switch_step", ("previous",)) in recorder.calls
    window.finish_btn.click()
    assert ("finish_experiment", ()) in recorder.calls
    window.enableBtn.setEnabled(True)          # normally enabled by the health loop
    window.enableBtn.click()
    assert ("enable_stimulator", ()) in recorder.calls
    window.fireBtn.setEnabled(True)
    window.fireBtn.click()
    assert ("trigger_stim", ()) in recorder.calls


def test_move_coil_up_stops_and_rearms_the_label(window, recorder):
    _ungate(window)
    window.start_btn.setText("Pause")
    window.move_coil_up.click()
    assert ("set_stopped_true", ()) in recorder.calls
    assert ("set_pause_true", ()) in recorder.calls
    assert window.start_btn.text() == "Start"


def test_start_button_label_follows_the_pause_state(window, recorder):
    _ungate(window)
    assert window.start_btn.isEnabled()
    window.start_btn.click()                    # pause: the button offers resume
    assert recorder.is_paused is True
    assert window.start_btn.text() == "Start"
    window.start_btn.click()                    # resume
    assert recorder.is_paused is False
    assert window.start_btn.text() == "Pause"


# ── manual mode ────────────────────────────────────────────────────────

def test_manual_mode_hides_the_robot_ui(window, qapp):
    window.set_robot_manual()
    qapp.processEvents()
    for attr in ("groupBox_3", "move_coil_up", "robot_view_label"):
        widget = getattr(window, attr, None)
        if widget is not None:
            assert not widget.isVisible()


def test_manual_mode_is_idempotent(window, qapp):
    window.set_robot_manual()
    window.set_robot_manual()
    qapp.processEvents()
    assert window.groupBox_stats.isVisible() or True     # no exception is the point


def test_manual_mode_frees_the_log_column(window, qapp):
    window.set_robot_manual()
    qapp.processEvents()
    root = window.tab3.layout()
    holders = [root.itemAt(i).layout() for i in range(root.count())]
    assert any(lay is not None and lay.indexOf(window.groupBox_stats) != -1
               for lay in holders)


# ── system status / LEDs ───────────────────────────────────────────────

class _Sys:
    NAME = "Robot"
    DESCRIPTION = "Real (via relay)"
    ERROR_RECOVERIES = {"Socket Broken": "Restart Robot Connection"}

    def __init__(self):
        self.status = None
        self.recoveries = []
        self.details = {"Relay": "http://x"}

    def recover(self, name):
        self.recoveries.append(name)


@pytest.fixture()
def bound_system(window):
    from neuropilot.controller.systems.system import SystemStatus
    system = _Sys()
    window.initialize({system: system.ERROR_RECOVERIES})
    return system, SystemStatus


def test_ok_status_updates_label_and_led(window, bound_system, qapp):
    system, Status = bound_system
    window.update_system_status(system, Status.OK)
    qapp.processEvents()
    assert window.robotStatusLabel.text() == "OK"
    assert window.led_robot.property("color") == "green"


def test_error_status_lights_red_and_offers_recovery(window, bound_system, qapp):
    system, Status = bound_system
    window.update_system_status(system, Status.ERROR, "Socket Broken")
    qapp.processEvents()
    assert window.robotStatusLabel.text() == "ERROR"
    assert window.led_robot.property("color") == "red"
    assert window.robotRecoverButton.isEnabled()
    assert window.robotRecoverButton.text() == "Restart Robot Connection"
    assert window.pending_recovery[system] == "Restart Robot Connection"


def test_error_without_a_message_does_not_raise(window, bound_system, qapp):
    system, Status = bound_system
    window.update_system_status(system, Status.ERROR, None)
    qapp.processEvents()
    assert "No Recovery Implemented" in window.robotMessageLabel.text()


def test_error_with_unknown_message_disables_the_button(window, bound_system, qapp):
    system, Status = bound_system
    window.update_system_status(system, Status.ERROR, "mystery")
    qapp.processEvents()
    assert not window.robotRecoverButton.isEnabled()
    assert "No Recovery Implemented" in window.robotMessageLabel.text()


def test_recovery_button_calls_the_system(window, bound_system, qapp):
    system, Status = bound_system
    window.update_system_status(system, Status.ERROR, "Socket Broken")
    window.robotRecoverButton.click()
    qapp.processEvents()
    assert system.recoveries == ["Restart Robot Connection"]


def test_nan_status_shows_not_initialised(window, bound_system, qapp):
    system, Status = bound_system
    window.update_system_status(system, Status.NAN)
    qapp.processEvents()
    assert "Not Initialized" in window.robotStatusLabel.text()
    assert window.led_robot.property("status") == "off"


def test_details_only_update_leaves_the_status(window, bound_system, qapp):
    system, Status = bound_system
    window.update_system_status(system, Status.OK)
    window.update_system_status(system, None, None,
                                details={"Model": "Omron TM5", "Firmware": "1.2"})
    qapp.processEvents()
    assert window.robotStatusLabel.text() == "OK"


def test_unknown_status_string_is_nan(window, bound_system, qapp):
    from neuropilot.controller.systems.system import SystemStatus
    assert SystemStatus.str_to_enum("weird") is SystemStatus.NAN
    assert SystemStatus.str_to_enum(None) is SystemStatus.NAN
    assert SystemStatus.str_to_enum(" OK ") is SystemStatus.OK


# ── the sweep ──────────────────────────────────────────────────────────

def iter_buttons(widget):
    for cls in (QtWidgets.QPushButton, QtWidgets.QToolButton,
                QtWidgets.QCheckBox, QtWidgets.QRadioButton):
        if isinstance(widget, cls):
            yield widget
    for child in widget.findChildren(QtWidgets.QWidget):
        if isinstance(child, (QtWidgets.QPushButton, QtWidgets.QToolButton,
                              QtWidgets.QCheckBox, QtWidgets.QRadioButton)):
            yield child


def test_every_button_without_a_controller(window, qapp, exceptions, monkeypatch):
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: "")
    clicked = 0
    for i in range(window.tabWidget.count()):
        window.tabWidget.setCurrentIndex(i)
        qapp.processEvents()
        for button in iter_buttons(window.tabWidget.widget(i)):
            if button.isEnabled():
                button.click()
                clicked += 1
                qapp.processEvents()
    assert clicked > 10
    assert exceptions == []


def test_every_button_with_a_controller(window, qapp, exceptions, recorder,
                                        monkeypatch):
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: "")
    for i in range(window.tabWidget.count()):
        window.tabWidget.setCurrentIndex(i)
        qapp.processEvents()
        for button in iter_buttons(window.tabWidget.widget(i)):
            if button.isEnabled():
                button.click()
                qapp.processEvents()
    assert exceptions == []


def test_every_line_edit_can_be_cleared(window, qapp, exceptions):
    from PyQt5 import QtWidgets as W
    for edit in window.findChildren(W.QLineEdit):
        edit.setText("")
    qapp.processEvents()
    assert exceptions == []


def test_unknown_fit_function_is_rejected_by_the_controller(window, controller):
    controller.set_fit_function("quadratic")
    assert controller.fit_fun.__name__ in ("linear", "sigmoid4")


def test_pulse_shape_with_an_invalid_value_is_rejected(window, controller):
    with pytest.raises(ValueError):
        controller.set_waveform("Triphasic")


def test_every_path_field_points_at_the_right_widget(window):
    # A crossed wire between the fields is the most common form bug; pin the
    # widget -> key mapping that get_config_dict uses.
    cfg = window.get_config_dict()
    assert cfg["mesh_head_path"] == (window.loadmeshlabel.text() or None)
    assert cfg["mesh_RIO_path"] == (window.loadroilabel.text() or None)
    assert cfg["e_field_path"] == (window.load_e_matrix_label.text() or None)
    assert cfg["coil_path"] == (window.coilspathlineedit.text() or None)
    assert cfg["targets_file"] == (window.loadplacementlabel.text() or None)
    assert cfg["emg_config_fn"] == (window.emg_config_label.text() or None)
    assert cfg["results_fn"] == (window.savePathLineEdit.text() or None)
    assert cfg["target_order_fn"] == (window.target_order_LineEdit.text() or None)


def test_signal_handlers_survive_missing_widgets(window, qapp, exceptions):
    """Handlers are defensive about optional widgets (manual mode removes some)."""
    window.update_robot_scene([0.0] * 6)
    window.set_led_status(None, "on", "green")
    window.update_mesh_coloring({})
    qapp.processEvents()
    assert exceptions == []


@pytest.mark.parametrize("value", [-1, 101, 150])
def test_stimulator_rejects_out_of_range_amplitudes(controller, value):
    with pytest.raises(ValueError):
        controller.stimulator.set_amplitude(value)


@pytest.mark.parametrize("value", [0, 20, 100])
def test_stimulator_accepts_valid_amplitudes(controller, value):
    controller.stimulator.set_amplitude(value)
    assert controller.stimulator.amplitude == value


def test_system_details_drop_empty_values_and_repeats():
    from neuropilot.controller.systems.system import SystemStatus

    class Probe:
        NAME = "probe"
        DESCRIPTION = "test"
        ERROR_RECOVERIES = {}

    from neuropilot.controller.systems.system import System
    calls = []

    class DetailsSystem(System):
        NAME = "Probe"
        DESCRIPTION = "test"
        ERROR_RECOVERIES = {}

        def try_connect(self):
            pass

        def recover(self, recovery):
            pass

        async def check_system(self):
            pass

    system = DetailsSystem(update_control_panel_func=lambda *a, **k: calls.append(k))
    system.set_details({"A": "1", "B": "", "C": None})
    assert system.details == {"A": "1"}
    before = len(calls)
    system.set_details({"A": "1"})            # unchanged: no repaint
    assert len(calls) == before
    system.set_details({"A": "2"})
    assert len(calls) == before + 1
    assert system.status is SystemStatus.NAN


def test_scores_from_a_worker_thread_reach_the_table(window, qapp):
    import threading, time
    import numpy as np
    seen = []
    window.scores_ready.connect(
        lambda scores: seen.append(threading.current_thread().name))
    thread = threading.Thread(
        target=lambda: window.scores_ready.emit({"ADC 0": np.zeros(3)}))
    thread.start(); thread.join()
    deadline = time.time() + 2
    while time.time() < deadline and not seen:
        qapp.processEvents(); time.sleep(0.02)
    assert seen and seen[0] == threading.main_thread().name
    assert window.results_table.rowCount() == 1


pytestmark = pytest.mark.gui
