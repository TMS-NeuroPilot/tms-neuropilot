"""E-field mode: persistence in the project file and the warm-up hint."""

import yaml
import pytest

pytest.importorskip("PyQt5.QtWidgets")


class FakeManager:
    def __init__(self, online=False, ready=False, initializing=False):
        self.online_fem = online
        self.ready = ready
        self.initializing = initializing
        self.mesh_fn_msh = None
        self.roi_fn_hdf5 = None
        self.coil_fn = None
        self.ensure_calls = []

    @property
    def is_online(self):
        return self.online_fem is True

    @property
    def is_ready(self):
        return self.ready

    def ensure_initialized(self, callback=None):
        self.ensure_calls.append(callback)

    def set_mesh_fn_msh(self, path):
        # Mirror OnlineFEMManager: the solver needs the sibling .msh.
        import os
        base, ext = os.path.splitext(str(path)) if path else ("", "")
        self.mesh_fn_msh = (path if ext.lower() == ".msh"
                            else base + ".msh") if path else None

    def set_roi_fn_hdf5(self, path):
        self.roi_fn_hdf5 = path

    def set_coil_fn(self, path):
        self.coil_fn = path


class FakeController:
    def __init__(self, manager=None, e_matrix=None):
        self.online_fem_mgr = manager or FakeManager()
        self.e_matrix = e_matrix
        self.manual = False
        self.start_of_experiment = None
        self.is_finished = False
        self.control_panel = None

    def __getattr__(self, name):
        """Any other controller call the window makes is a no-op."""
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            return None
        return call


def attach(window, **kwargs):
    ctrl = FakeController(**kwargs)
    window.set_controller(ctrl)
    return ctrl


def ready_paths(window, ctrl, tmp_path):
    """Make all three solver paths usable (the radios need them)."""
    mesh = tmp_path / "mesh.msh"
    mesh.write_text("x")
    (tmp_path / "mesh.hdf5").write_text("x")
    roi = tmp_path / "roi.hdf5"
    roi.write_text("x")
    coil = tmp_path / "coil.ccd"
    coil.write_text("x")
    window.loadmeshlabel.setText(str(tmp_path / "mesh.hdf5"))
    window.paste_mesh_path()
    window.loadroilabel.setText(str(roi))
    window.paste_roi_path()
    window.coilspathlineedit.setText(str(coil))
    window.paste_coil_path()


# ── the mode name ──────────────────────────────────────────────────────

def test_no_mode_selected_yet(window):
    assert window.efield_mode_name() is None


def test_mode_name_follows_the_radios(window):
    window.offline_efield_btn.setChecked(True)
    assert window.efield_mode_name() == "Precomputed"
    window.online_efield_btn.setChecked(True)
    assert window.efield_mode_name() == "Online"


# ── applying a mode ────────────────────────────────────────────────────

def test_apply_online_when_the_radios_are_enabled(window, tmp_path):
    ctrl = attach(window)
    ready_paths(window, ctrl, tmp_path)
    assert window._apply_efield_mode("Online") is True
    assert window.online_efield_btn.isChecked()
    assert ctrl.online_fem_mgr.online_fem is True


def test_apply_is_case_and_space_insensitive(window, tmp_path):
    ctrl = attach(window)
    ready_paths(window, ctrl, tmp_path)
    assert window._apply_efield_mode("  precomputed ") is True
    assert window.offline_efield_btn.isChecked()


def test_unknown_mode_name_is_ignored(window, tmp_path):
    ctrl = attach(window)
    ready_paths(window, ctrl, tmp_path)
    assert window._apply_efield_mode("banana") is False
    assert not window.online_efield_btn.isChecked()
    assert not window.offline_efield_btn.isChecked()


def test_mode_is_remembered_while_the_radios_are_disabled(window):
    ctrl = attach(window)
    assert window._apply_efield_mode("Online") is False
    assert window._pending_efield_mode == "online"


def test_pending_mode_is_applied_once_the_paths_arrive(window, tmp_path):
    ctrl = attach(window)
    window._apply_efield_mode("Online")
    assert not window.online_efield_btn.isChecked()

    ready_paths(window, ctrl, tmp_path)          # calls _check_paths_ready
    assert window.online_efield_btn.isChecked()
    assert window._pending_efield_mode is None
    assert ctrl.online_fem_mgr.online_fem is True


# ── project persistence ────────────────────────────────────────────────

def test_project_dict_contains_the_mode(window, tmp_path):
    ctrl = attach(window)
    ready_paths(window, ctrl, tmp_path)
    window.online_efield_btn.setChecked(True)
    assert window.get_config_dict()["efield_mode"] == "Online"


def test_project_roundtrip_keeps_the_mode(window, tmp_path):
    ctrl = attach(window)
    ready_paths(window, ctrl, tmp_path)
    window.online_efield_btn.setChecked(True)
    project = tmp_path / "proj.yaml"
    assert window.save_project_file(str(project)) is None

    window.offline_efield_btn.setChecked(True)   # change it before reloading
    assert window.load_project_file(str(project)) is None
    assert window.online_efield_btn.isChecked()
    assert window.efield_mode_name() == "Online"


def test_loading_a_project_applies_the_mode_after_the_paths(window, tmp_path):
    ctrl = attach(window)
    project = tmp_path / "proj.yaml"
    project.write_text(yaml.safe_dump({
        "e_field_path": str(tmp_path / "missing.hdf5"),   # invalid on purpose
        "efield_mode": "Online",
    }))
    assert window.load_project_file(str(project)) is None
    # Paths are unusable, so the mode could not be selected -- but nothing crashed
    assert window.efield_mode_name() in (None, "Online")


def test_mode_change_marks_the_project_dirty(window, tmp_path):
    ctrl = attach(window)
    ready_paths(window, ctrl, tmp_path)
    window._project_file = str(tmp_path / "proj.yaml")
    window._project_dirty = False
    window.online_efield_btn.setChecked(True)
    assert window._project_dirty is True


# ── the warm-up hint ───────────────────────────────────────────────────

def hint(window, ctrl=None):
    window.controller = ctrl
    window._update_efield_hint()
    return window.efield_hint.text()


def test_hint_asks_for_a_mode(window):
    assert "Choose a mode" in hint(window, None)


def test_hint_for_precomputed(window):
    ctrl = attach(window)
    window.offline_efield_btn.setChecked(True)
    text = hint(window, ctrl)
    assert "Precomputed" in text


def test_hint_while_warming_up(window):
    mgr = FakeManager(online=True, ready=False, initializing=True)
    attach(window, manager=mgr)
    window.online_efield_btn.setChecked(True)
    text = hint(window, window.controller)
    assert "Warming up" in text
    assert "wait" in text.lower()


def test_hint_when_ready(window):
    mgr = FakeManager(online=True, ready=True)
    attach(window, manager=mgr)
    window.online_efield_btn.setChecked(True)
    assert "ready" in hint(window, window.controller).lower()


def test_hint_when_the_solver_failed(window):
    mgr = FakeManager(online=True, ready=False, initializing=False)
    attach(window, manager=mgr)
    window.online_efield_btn.setChecked(True)
    text = hint(window, window.controller)
    assert "unavailable" in text.lower()
    assert "Precomputed" in text


def test_hint_tone_property(window):
    mgr = FakeManager(online=True, ready=False, initializing=True)
    attach(window, manager=mgr)
    window.online_efield_btn.setChecked(True)
    hint(window, window.controller)
    assert window.efield_hint.property("tone") == "busy"

    mgr.initializing, mgr.ready = False, True
    hint(window, window.controller)
    assert window.efield_hint.property("tone") == "ok"


def test_hint_updates_with_the_button_state(window):
    mgr = FakeManager(online=True, ready=False, initializing=True)
    ctrl = attach(window, manager=mgr)
    window.efield_mode_selected = True
    window.update_button_states()
    assert "Warming up" in window.efield_hint.text()

    mgr.initializing, mgr.ready = False, True
    window.update_button_states()
    assert "ready" in window.efield_hint.text().lower()


pytestmark = pytest.mark.gui
