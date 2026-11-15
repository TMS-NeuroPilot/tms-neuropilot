"""GUI logic for choosing the E-field mode.

The methods under test are plain Python (they only touch attributes), so they
are exercised on a lightweight stand-in instead of a real window -- no display,
no OpenGL, no hardware.
"""

from types import SimpleNamespace

import pytest

from neuropilot.controller.control_panel import MainWindow

on_mode_changed = MainWindow.on_efield_mode_changed
check_paths_ready = MainWindow._check_paths_ready
update_button_states = MainWindow.update_button_states
update_finish_button = MainWindow._update_finish_button
disable_finished_transport = MainWindow._disable_finished_transport


class FakeButton:
    def __init__(self, checked=False, enabled=True):
        self._checked = checked
        self._enabled = enabled
        self.enable_calls = []

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        self._checked = bool(value)

    def setEnabled(self, value):
        self._enabled = bool(value)
        self.enable_calls.append(self._enabled)

    def isEnabled(self):
        return self._enabled

    def setText(self, text):
        self._text = text

    def setDown(self, down):
        self._down = bool(down)


class FakeManager:
    def __init__(self, ready=False):
        self.online_fem = None
        self.ready = ready
        # The panel checks that the derived .msh really exists; any file will do.
        self.mesh_fn_msh = __file__
        self.roi_fn_hdf5 = "roi.hdf5"
        self.coil_fn = "coil.hdf5"
        self.ensure_calls = []
        self.init_background_calls = []

    @property
    def is_online(self):
        return self.online_fem is True

    @property
    def is_ready(self):
        return self.ready

    def ensure_initialized(self, callback=None):
        self.ensure_calls.append(callback)

    def init_background(self, callback=None):
        self.init_background_calls.append(callback)


class FakeSurrogateManager:
    def __init__(self):
        self.ready = False
        self.initializing = False
        self.library_fn = None
        self.roi_fn_hdf5 = None
        self.ensure_calls = []

    @property
    def is_ready(self):
        return self.ready

    def ensure_initialized(self, callback=None):
        self.ensure_calls.append(callback)


class FakeController:
    def __init__(self, mgr=None, e_matrix=None, manual=False):
        self.online_fem_mgr = mgr or FakeManager()
        self.surrogate_mgr = FakeSurrogateManager()
        self.efield_mode = None
        self.e_matrix = e_matrix
        self.manual = manual
        self.start_of_experiment = None
        self.is_finished = False

    @property
    def running(self):
        return self.start_of_experiment is not None and not self.is_finished


def make_panel(controller=None, online=False, offline=False, surrogate=False):
    panel = SimpleNamespace(
        controller=controller,
        online_efield_btn=FakeButton(online),
        offline_efield_btn=FakeButton(offline),
        surrogate_efield_btn=FakeButton(surrogate),
        efield_mode_selected=False,
        robot_ready=True, stim_ready=True, emg_ready=True,
        relay_ready=True,
        start_btn=FakeButton(), skiptarget=FakeButton(), back_btn=FakeButton(),
        move_coil_up=FakeButton(), finish_btn=FakeButton(),
    )
    panel.update_button_states = lambda: update_button_states(panel)
    # The window forwards the solver callback through a Qt signal so it runs
    # on the GUI thread; the stand-in calls the slot directly.
    panel.online_fem_ready = SimpleNamespace(emit=lambda: update_button_states(panel))
    panel.surrogate_library_ready = SimpleNamespace(emit=lambda: update_button_states(panel))
    # Bound helpers the real window has; the stand-in keeps them inert.
    panel._update_efield_hint = lambda: None
    panel._mark_project_dirty = lambda *a, **k: None
    panel._update_finish_button = lambda: update_finish_button(panel)
    panel._disable_finished_transport = lambda: disable_finished_transport(panel)
    return panel


# ── switching ───────────────────────────────────────────────────────────

def test_switching_to_online_initializes_the_solver():
    ctrl = FakeController()
    panel = make_panel(ctrl, online=True)
    on_mode_changed(panel)
    assert ctrl.online_fem_mgr.online_fem is True
    assert len(ctrl.online_fem_mgr.ensure_calls) == 1
    assert ctrl.online_fem_mgr.init_background_calls == []   # idempotent path only


def test_switching_to_precomputed_does_not_touch_the_solver():
    ctrl = FakeController()
    panel = make_panel(ctrl, offline=True)
    on_mode_changed(panel)
    assert ctrl.online_fem_mgr.online_fem is False
    assert ctrl.online_fem_mgr.ensure_calls == []


def test_switching_to_interpolated_selects_the_mode_and_loads():
    ctrl = FakeController()
    panel = make_panel(ctrl, surrogate=True)
    on_mode_changed(panel)
    assert ctrl.efield_mode == "surrogate"
    assert len(ctrl.surrogate_mgr.ensure_calls) == 1
    assert ctrl.online_fem_mgr.online_fem is False


def test_switching_back_from_interpolated_releases_the_mode():
    ctrl = FakeController()
    panel = make_panel(ctrl, surrogate=True)
    on_mode_changed(panel)
    panel.surrogate_efield_btn.setChecked(False)
    panel.offline_efield_btn.setChecked(True)
    on_mode_changed(panel)
    assert ctrl.efield_mode == "precomputed"
    assert ctrl.online_fem_mgr.online_fem is False


def test_both_radios_stay_enabled_after_a_selection():
    ctrl = FakeController()
    panel = make_panel(ctrl, online=True)
    on_mode_changed(panel)
    assert panel.online_efield_btn.isEnabled()
    assert panel.offline_efield_btn.isEnabled()


def test_mode_can_be_switched_back_and_forth():
    ctrl = FakeController()
    panel = make_panel(ctrl, online=True)
    on_mode_changed(panel)
    panel.online_efield_btn.setChecked(False)
    panel.offline_efield_btn.setChecked(True)
    on_mode_changed(panel)
    assert ctrl.online_fem_mgr.online_fem is False
    panel.offline_efield_btn.setChecked(False)
    panel.online_efield_btn.setChecked(True)
    on_mode_changed(panel)
    assert ctrl.online_fem_mgr.online_fem is True
    # Each switch asks the (idempotent) manager to make sure it is running.
    assert len(ctrl.online_fem_mgr.ensure_calls) == 2


def test_radio_selection_marks_the_mode_as_chosen():
    panel = make_panel(FakeController(), offline=True)
    assert panel.efield_mode_selected is False
    on_mode_changed(panel)
    assert panel.efield_mode_selected is True


def test_handler_ignores_the_deselection_half_of_a_toggle():
    # QRadioButton emits toggled(False) for the button losing the click.
    panel = make_panel(FakeController())
    on_mode_changed(panel)
    assert panel.efield_mode_selected is False
    assert panel.controller.online_fem_mgr.online_fem is None


def test_switching_without_a_controller_is_harmless():
    panel = make_panel(None, online=True)
    on_mode_changed(panel)
    assert panel.efield_mode_selected is True


# ── path readiness ──────────────────────────────────────────────────────

def test_radios_enable_once_all_paths_are_set():
    panel = make_panel(FakeController())
    check_paths_ready(panel)
    assert panel.online_efield_btn.isEnabled()
    assert panel.offline_efield_btn.isEnabled()


@pytest.mark.parametrize("attr", ["mesh_fn_msh", "roi_fn_hdf5", "coil_fn"])
def test_radios_stay_disabled_while_a_path_is_missing(attr):
    ctrl = FakeController()
    setattr(ctrl.online_fem_mgr, attr, None)
    panel = make_panel(ctrl)
    check_paths_ready(panel)
    assert not panel.online_efield_btn.isEnabled()
    assert not panel.offline_efield_btn.isEnabled()


def test_radios_stay_enabled_after_the_mode_was_chosen():
    ctrl = FakeController()
    panel = make_panel(ctrl, online=True)
    on_mode_changed(panel)
    check_paths_ready(panel)
    assert panel.offline_efield_btn.isEnabled()


def test_completing_the_paths_later_starts_the_online_solver():
    # Online was selected while a path was still missing (the radios are
    # disabled then, but a study profile can set the mode), so the manager
    # must be asked again once the paths are complete.
    ctrl = FakeController()
    panel = make_panel(ctrl, online=True)
    panel.efield_mode_selected = True
    ctrl.online_fem_mgr.mesh_fn_msh = None
    check_paths_ready(panel)
    assert ctrl.online_fem_mgr.ensure_calls == []

    ctrl.online_fem_mgr.mesh_fn_msh = __file__
    check_paths_ready(panel)
    assert len(ctrl.online_fem_mgr.ensure_calls) == 1


def test_complete_paths_in_precomputed_mode_do_not_start_the_solver():
    ctrl = FakeController()
    panel = make_panel(ctrl, offline=True)
    panel.efield_mode_selected = True
    check_paths_ready(panel)
    assert ctrl.online_fem_mgr.ensure_calls == []


def test_no_controller_keeps_the_radios_disabled():
    panel = make_panel(None)
    check_paths_ready(panel)
    assert not panel.online_efield_btn.isEnabled()
    assert not panel.offline_efield_btn.isEnabled()
    assert not panel.surrogate_efield_btn.isEnabled()


def test_interpolated_radio_needs_the_library_and_the_roi():
    ctrl = FakeController()
    panel = make_panel(ctrl)
    check_paths_ready(panel)
    assert not panel.surrogate_efield_btn.isEnabled()

    ctrl.surrogate_mgr.library_fn = __file__
    check_paths_ready(panel)
    assert not panel.surrogate_efield_btn.isEnabled()   # still needs the ROI

    ctrl.surrogate_mgr.roi_fn_hdf5 = __file__
    check_paths_ready(panel)
    assert panel.surrogate_efield_btn.isEnabled()


# ── start-button gating ─────────────────────────────────────────────────

def test_nothing_starts_before_a_mode_is_chosen():
    panel = make_panel(FakeController())
    update_button_states(panel)
    assert not panel.start_btn.isEnabled()


def test_precomputed_mode_needs_a_loaded_matrix():
    panel = make_panel(FakeController(e_matrix=None), offline=True)
    on_mode_changed(panel)
    assert not panel.start_btn.isEnabled()

    panel.controller.e_matrix = object()
    update_button_states(panel)
    assert panel.start_btn.isEnabled()


def test_online_mode_waits_for_the_solver():
    ctrl = FakeController(FakeManager(ready=False))
    panel = make_panel(ctrl, online=True)
    on_mode_changed(panel)
    assert not panel.start_btn.isEnabled()

    ctrl.online_fem_mgr.ready = True
    update_button_states(panel)
    assert panel.start_btn.isEnabled()


def test_switching_to_precomputed_releases_an_unready_solver():
    ctrl = FakeController(FakeManager(ready=False), e_matrix=object())
    panel = make_panel(ctrl, online=True)
    on_mode_changed(panel)
    assert not panel.start_btn.isEnabled()
    panel.online_efield_btn.setChecked(False)
    panel.offline_efield_btn.setChecked(True)
    on_mode_changed(panel)
    assert panel.start_btn.isEnabled()


def test_running_experiment_stays_controllable():
    ctrl = FakeController(FakeManager(ready=False), e_matrix=None)
    panel = make_panel(ctrl, offline=True)
    on_mode_changed(panel)
    assert not panel.start_btn.isEnabled()

    # A running experiment may be finished/skipped even if a system drops out.
    ctrl.start_of_experiment = object()
    update_button_states(panel)
    assert panel.finish_btn.isEnabled()
    assert panel.start_btn.isEnabled()


def test_missing_robot_blocks_the_start_but_not_finish():
    ctrl = FakeController(e_matrix=object())
    panel = make_panel(ctrl, offline=True)
    on_mode_changed(panel)
    panel.robot_ready = False
    update_button_states(panel)
    assert not panel.start_btn.isEnabled()
    assert not panel.finish_btn.isEnabled()


def test_manual_mode_does_not_need_a_robot():
    ctrl = FakeController(e_matrix=object(), manual=True)
    panel = make_panel(ctrl, offline=True)
    on_mode_changed(panel)
    panel.robot_ready = False
    update_button_states(panel)
    assert panel.start_btn.isEnabled()
