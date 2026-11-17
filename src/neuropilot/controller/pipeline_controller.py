import sys
import time
import numpy as np
import h5py
import yaml
from . import transformations as tr
import asyncio
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import pandas as pd
import seaborn as sns
import matplotlib

from .transformations import compose_matrix

# Relay topic announcing the project head mesh to the robot side (the
# simulator converts it into its MuJoCo phantom; must match
# neuropilot.sim_robot.config.TOPIC_SET_HEAD_MESH).
TOPIC_SET_HEAD_MESH = "Pipeline to Robot: Set head mesh"
TOPIC_SET_START_POSE = "Pipeline to Robot: Set start pose"
TOPIC_SET_MOTION_LIMITS = "Pipeline to Robot: Set motion limits"

def precomputed_e_field_row(e_matrix, target_index, amplitude):
    """E-field row of the precomputed matrix, scaled to the stimulator output.

    ``e_matrix`` is the precomputed (n_targets, n_elements) matrix in V/m at
    100 % output; ``amplitude`` is the applied stimulator amplitude in percent.
    Returns None when no precomputed matrix or no target index is available.
    """
    if e_matrix is None or target_index is None:
        return None
    try:
        row = np.asarray(e_matrix[target_index], dtype=float)
    except (IndexError, TypeError, KeyError):
        return None
    return row * (float(amplitude) * 1.4)


def validate_simnibs_targets_file(path):
    """Cheap check of a SimNIBS placements file; returns the target count.

    Only the dataset shape and dtype are inspected, so the GUI can vet a path
    the moment it is entered without reading megabytes of matrices.  Raises
    ``ValueError`` with an operator-readable message.
    """
    if not path:
        raise ValueError("No coil placement file selected.")
    if not os.path.isfile(path):
        raise ValueError(f"Coil placement file not found: {path}")
    try:
        with h5py.File(path, 'r') as f:
            if 'matsimnibs' not in f:
                raise ValueError(f"{os.path.basename(path)} has no 'matsimnibs' "
                                 f"dataset (keys: {list(f.keys())}).")
            shape = f['matsimnibs'].shape
            dtype = f['matsimnibs'].dtype
    except OSError as e:
        raise ValueError(f"Cannot read {os.path.basename(path)}: {e}") from e
    if len(shape) != 3 or shape[:2] != (4, 4) or shape[2] < 1:
        raise ValueError(f"'matsimnibs' must be (4, 4, n), got {shape}.")
    if not np.issubdtype(dtype, np.number):
        raise ValueError(f"'matsimnibs' has non-numeric dtype {dtype}.")
    return int(shape[2])


def stamped_results_filename(path, stamp):
    """``results.csv`` + stamp -> ``results<stamp>.csv``.

    Only the extension is replaced: a folder or file name that happens to
    contain ".csv" earlier in the path must survive (``str.replace`` would
    hit every occurrence).
    """
    base, ext = os.path.splitext(str(path))
    return f"{base}{stamp}{ext or '.csv'}"


def read_simnibs_targets_data(path):
    """Read coil placements once and return ``(targets, matsimnibs)``.

    The matrices are kept so the caller can cache them for the GUI
    consistency check and the start of a run; ``read_simnibs_targets`` is the
    queue-only wrapper used by older callers.
    """
    validate_simnibs_targets_file(path)
    try:
        with h5py.File(path, 'r') as f:
            mats = f['matsimnibs'][:]
    except OSError as e:
        raise ValueError(f"Cannot read {os.path.basename(path)}: {e}") from e

    try:
        mats = np.asarray(mats, dtype=float)
    except (TypeError, ValueError) as e:
        raise ValueError(f"'matsimnibs' in {os.path.basename(path)} is not numeric.") from e
    if not np.isfinite(mats).all():
        raise ValueError(f"'matsimnibs' in {os.path.basename(path)} contains NaN/inf.")

    target_queue = []
    for i in range(mats.shape[2]):
        m = mats[:, :, i].copy()
        # Transform to InVesalius coil convention (see the wiki, Coil Axis
        # Conventions): flip z, then exchange x and y.  Positions are the same
        # in both frames, so the translation is left untouched.
        m[:3, 2] *= -1
        m[:3, 0], m[:3, 1] = m[:3, 1].copy(), m[:3, 0].copy()
        euler_angles = np.degrees(tr.euler_from_matrix(m, "sxyz"))
        target_queue.append((m[:3, 3], euler_angles))
    return target_queue, mats


def read_simnibs_targets(path):
    """Coil targets from a SimNIBS placements file, in InVesalius convention.

    Returns a list of ``(position_mm, euler_xyz_deg)`` tuples.  Raises
    ``ValueError`` with an operator-readable message when the file is
    missing, is not HDF5, or does not hold a (4, 4, n) ``matsimnibs``
    dataset -- the callers show that message instead of dying mid-run.
    """
    return read_simnibs_targets_data(path)[0]


def read_e_matrix_file(path):
    """Read a precomputed E-field library (worker-safe, no Qt).

    Returns ``(E_mag, matsimnibs_or_None)``.  Raises ``ValueError`` for a
    missing/odd dataset so the GUI can report the reason without leaving a
    half-loaded matrix behind.
    """
    with h5py.File(path, 'r') as f:
        if 'E_mag' not in f:
            raise ValueError(f"{os.path.basename(path)} has no 'E_mag' dataset "
                             f"(keys: {list(f.keys())}).")
        data = np.asarray(f['E_mag'][:])
        mats = f['matsimnibs'][:] if 'matsimnibs' in f else None
    if data.ndim != 2 or data.shape[0] < 1 or data.shape[1] < 1:
        raise ValueError(f"E_mag must be (placements, elements), got {data.shape}.")
    if not np.issubdtype(data.dtype, np.number):
        raise ValueError(f"E_mag has non-numeric dtype {data.dtype}.")
    if mats is not None:
        mats = np.asarray(mats)
    return data, mats


def _file_signature(path):
    """Cheap change detector for the target cache (mtime + size)."""
    try:
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def read_emg_config_elements(path, roi_fn=None):
    """Read an EMG source YAML and return one ROI element per channel.

    Runs without Qt so the GUI can load the config (and, for ``xyz`` entries,
    project onto the ROI) in a worker.  Raises ``ValueError`` with an
    operator-readable reason; direct callers keep the previous channels.
    """
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"EMG config unreadable: {e}") from e

    entries = data.get("sources", data) if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise ValueError("EMG config has no 'sources' list.")

    # ROI triangle centers for the xyz projection (the E-matrix columns
    # follow the ROI element order of the geo file).
    centers = None
    if roi_fn and os.path.isfile(roi_fn):
        try:
            with h5py.File(roi_fn, "r") as f:
                nodes = f["mesh/nodes/node_coord"][:]
                tris = f["mesh/elm/triangle_number_list"][:]
            centers = nodes[tris].mean(axis=1)
        except (OSError, KeyError, IndexError) as e:
            raise ValueError(
                f"EMG config: ROI unreadable ({e}) -- cannot project xyz sources.") from e

    elements = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"EMG source {i}: invalid entry {entry}")
        if entry.get("element_id") is not None:
            elements.append(int(entry["element_id"]))
        elif entry.get("xyz") is not None:
            if centers is None:
                raise ValueError(
                    "EMG source uses xyz but no ROI surface is loaded -- cannot project.")
            xyz = np.asarray(entry["xyz"], dtype=float)
            elem = int(np.argmin(np.linalg.norm(centers - xyz, axis=1)))
            dist = float(np.linalg.norm(centers[elem] - xyz))
            print(f"EMG source {i}: xyz {xyz.tolist()} -> element {elem} "
                  f"(distance {dist:.2f} mm)")
            elements.append(elem)
        else:
            raise ValueError(f"EMG source {i}: needs 'element_id' or 'xyz'.")
    return elements


def parse_target_order_file(path):
    """Ordered target indices from a text file (no range check)."""
    if not path:
        raise ValueError("No target order file selected.")
    if not os.path.isfile(path):
        raise ValueError(f"Target order file not found: {path}")
    with open(path) as f:
        text = f.read()
    if not text.strip():
        # genfromtxt would warn on an empty file; this is the same rejection
        # the empty case already gets below.
        raise ValueError(f"Target order {os.path.basename(path)} is empty or not numeric.")
    try:
        order = np.genfromtxt(path)
    except (OSError, ValueError) as e:
        raise ValueError(f"Cannot read target order {os.path.basename(path)}: {e}") from e
    order = np.atleast_1d(order)
    if order.size == 0 or not np.isfinite(order).all():
        raise ValueError(f"Target order {os.path.basename(path)} is empty or not numeric.")
    if not np.allclose(order, np.round(order)):
        raise ValueError(f"Target order {os.path.basename(path)} contains non-integer entries.")
    order = order.astype(int)
    if order.min() < 0:
        raise ValueError(f"Target order {os.path.basename(path)} contains negative entries.")
    return order


def read_target_order(path, n_targets):
    """Ordered target indices from a text file, validated against the queue."""
    order = parse_target_order_file(path)
    if order.max() >= n_targets:
        raise ValueError(f"Target order {os.path.basename(path)} references target "
                         f"{order.max()}, but only {n_targets} placements exist.")
    return order


def assemble_analysis_matrix(pulse_e_fields, valid_indices):
    """Regression matrix built from the per-pulse E-field rows.

    A pulse whose E-field is missing (None) or not finite (all-NaN, as written
    for a surrogate pulse outside the trained domain) is dropped, and the
    returned indices follow it, so the MEP history stays aligned with the
    matrix rows. ``pulse_e_fields`` is indexed by pulse number, exactly like
    the MEP history. Returns ``(kept_indices, matrix)`` with ``matrix is
    None`` when no pulse carries an E-field.
    """
    usable = []
    for i in valid_indices:
        i = int(i)
        if not (0 <= i < len(pulse_e_fields)) or pulse_e_fields[i] is None:
            continue
        row = np.asarray(pulse_e_fields[i], dtype=float)
        if np.all(np.isfinite(row)):
            usable.append(i)
    if not usable:
        return np.empty(0, dtype=int), None
    # A session that mixed two E-field sources of different width (another ROI
    # in the online solver) must not take the whole analysis down: keep the
    # majority width and drop the outliers.
    widths = [len(pulse_e_fields[i]) for i in usable]
    width = max(set(widths), key=widths.count)
    keep = [i for i in usable if len(pulse_e_fields[i]) == width]
    return np.asarray(keep, dtype=int), np.vstack([pulse_e_fields[i] for i in keep])

# Qt5Agg needs a display; on a headless machine (tests, batch tools) forcing
# it makes the import itself fail, so fall back to the non-interactive backend.
if (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        or sys.platform.startswith("win")):
    matplotlib.use("Qt5Agg")
else:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from enum import Enum, auto
from dotenv import load_dotenv
from .systems.emg import EMGComputer
from .systems.relay import RelaySystem
from .systems.virtual_emg import VirtualEMG
from .systems.stimulator import Stimulator
from .systems.virtual_stimulator import VirtualStimulator
from .systems.robot import Robot
from datetime import datetime
import pynibs
import gdist
from .OnlineFEMManager import OnlineFEMManager
from .SurrogateManager import SurrogateManager

load_dotenv()
enable_health_check_and_control_panel = os.getenv('ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL', 'false').lower() == 'true'

root_folder = os.getenv('ROOT_FOLDER', os.getcwd())
# Results folders live under ROOT_FOLDER; os.path.join keeps the separators
# right on Windows (a literal "/" here would produce mixed separators).
EMG_PLOTS_FOLDER_PATH = os.path.join(
    root_folder, os.getenv('EMG_PLOTS_FOLDER_PATH', 'emg_plots'))
P2P_PLOTS_FOLDER_PATH = os.path.join(
    root_folder, os.getenv('P2P_PLOTS_FOLDER_PATH', 'p2p_plots'))
for _folder in (EMG_PLOTS_FOLDER_PATH, P2P_PLOTS_FOLDER_PATH):
    try:
        os.makedirs(_folder, exist_ok=True)
    except OSError as _e:
        # e.g. cluster ROOT_FOLDER without /data on a local machine; plot saving will fail later
        print(f"Warning: could not create results folder {_folder!r}: {_e}")

class Step(Enum):
    INIT = auto()
    SEND_MARKER = auto()
    START_TRACKING = auto()
    WAIT_FOR_TARGET_REACHED = auto()
    FIRE_STIM = auto()
    COLLECT_DATA = auto()
    ANALYSE = auto()
    COMPLETE = auto()
    SKIP = auto()

class PipelineController:
    def __init__(self, remote, simulation,control_panel = None, manual=False,
                 training=False, manage_relay=False):
        if training and simulation:
            raise ValueError(
                "training mode uses the real stimulator; simulation must be off")
        self.datetime_str = ""
        self.start_of_experiment = None
        self.control_panel = control_panel
        update_control_panel_func = self.control_panel.update_system_status if self.control_panel else None

        self.remote = remote

        ## Initializing systems
        self.systems = []

        # The relay is the hub every peer uses. In real/manual/training mode
        # NeuroPilot can own it; in simulation the supervisor owns it.
        self.relay = RelaySystem(update_control_panel_func,
                                 manage=manage_relay,
                                 simulation=simulation)
        self.systems.append(self.relay)

        # Training mode: real stimulator and navigation, virtual EMG, and the
        # operator moves the coil (no robot). It is manual mode with a
        # simulated MEP trace.
        self.training = training

        # Manual mode: real stimulator/EMG/navigation but no robot — the
        # operator moves the coil by hand guided by Invesalius.
        self.manual = manual or training

        if not self.manual:
            self.robot = Robot(update_control_panel_func, self.remote)
            self.systems.append(self.robot)
            self.simulation = simulation
            # The Robot system speaks the relay protocol in both modes; only the
            # controller knows which one is behind it (the sim robot process).
            self.robot.DESCRIPTION = ("Simulated (virtual twin)" if simulation
                                      else "Real (via relay)")
        else:
            self.robot = None
            # Keep the mode the caller asked for: manual only removes the
            # robot, it does not turn a simulated session into a real one.
            self.simulation = simulation
            if self.control_panel:
                self.control_panel.set_robot_manual()

        if not simulation:
            if training:
                self.emg_computer = VirtualEMG(update_control_panel_func)
            else:
                self.emg_computer = EMGComputer(update_control_panel_func)
            self.systems.append(self.emg_computer)
            self.stimulator = Stimulator(update_control_panel_func)
            self.systems.append(self.stimulator)
        else:
            self.emg_computer = VirtualEMG(update_control_panel_func)
            self.systems.append(self.emg_computer)
            self.stimulator = VirtualStimulator(update_control_panel_func)
            self.systems.append(self.stimulator)

        # Control Panel connection
        if self.control_panel:
            all_error_recoveries = {s : s.ERROR_RECOVERIES for s in self.systems}
            self.control_panel.initialize(all_error_recoveries)

        # Launch the systems. Start the relay first: the peer systems and the
        # Remote connection need its port.
        self.relay.try_connect()
        self.stimulator.try_connect()
        self.emg_computer.try_connect()

        # to get the path of coil placement targets from the GUI
        self.targets_file = None
        self.target_order_fn = None
        self.target_order = None
        self._targets_cache = None      # (path, signature, queue, matsimnibs)
        self.results_fn = None # TODO: Expose and sset via GUI
        self.overwrite_results = True

        # we need this attribute for log that shows current steps
        self.current_target_index = None

        # go back flag
        self._go_back= False

        # move coil up flag
        self.move_coil_up_flag = False

        #Start/pause
        self.is_paused = True
        self.is_finished = False
        # The target loop is not running until a session starts; the GUI
        # polls is_draining() so Finish can show a spinner while the run
        # is still writing after Finish was pressed.
        self._run_done = True

        ## Show the Control Panel after system initializations
        if self.control_panel:
            self.control_panel.show()

        ## Algorithm logic
        self.current_target_order_idx = 0
        self.current_step = Step.INIT
        self.current_step_start_time = None
        self.target_reached = False
        self.target_created = False
        self.realized_target = None
        self.pressure_thresh = 1
        self.cobotOnTarget = 0
        self.running_analyses_tasks = []

        # Stimulator settings
        self.stimulator_amplitude = None
        self.start_pose_joints = None
        # Shoulder/elbow/wrist branch captured with the collision-tested
        # start pose. None keeps the simulator's free elbow-up solver.
        self.start_pose_branch = None
        # Collision-tested direct-or-safe-height limits. None leaves the
        # simulator on the values it read from .env.
        self.motion_limits = None
        self.stimulator_waveform = 'Biphasic'
        self.minium_isi = 4  # in seconds
        self.n_repetitions = 1 #
        self.current_rep = 1

        # keep track of some variables exactly during the stimulation
        self.time_at_stim = -1
        self.pressure_at_stim = -1
        self.target_at_stim = [[-1, -1, -1], [-1, -1, -1]]
        self.stimulator_amplitude_at_stim = -1

        # Data Storage for Analysis
        self.used_coil_placements_idx = []  # Stores the integer index (e.g., [0, 1, 5...])
        self.excluded_pulse_indices = set()
        # One E-field row per pulse, in the same order as used_coil_placements_idx.
        # The row comes from whichever source was active at stimulation time, so
        # the E-field mode can be switched between pulses without misaligning
        # the regression matrix. None marks a pulse whose field is missing.
        self.pulse_e_fields = []
        self.pulse_modes = []  # "online" / "precomputed" / "surrogate", for diagnostics and exports
        self.mep_history = {}  # Stores MEPs: {'ADC 0': [0.1, 0.5...], ...}  # {'ADC 0': [], 'ADC 1': []}
        self.emg_preac_amp_history = {}  # Stores MEPs: {'ADC 0': [0.1, 0.5...], ...}  # {'ADC 0': [], 'ADC 1': []}
        self.emg_preac_var_history = {}  # Stores MEPs: {'ADC 0': [0.1, 0.5...], ...}  # {'ADC 0': [], 'ADC 1': []}
        self.realized_targets = {'idx':[],
                                 'idx_pulse' : [],

                                 'time':[],

                                 'x_realized':[],
                                 'y_realized': [],
                                 'z_realized': [],
                                 'rota_realized': [],
                                 'rotb_realized': [],
                                 'rotc_realized': [],

                                 'x_target':[],
                                 'y_target': [],
                                 'z_target': [],
                                 'rota_target': [],
                                 'rotb_target': [],
                                 'rotc_target': [],

                                 'pressure':[],
                                 'intensity':[],
                                 'e_field_mode':[],
                                 }

        self.e_matrix = None  # Will hold the big E-field matrix

        # Online-field state lives in the managers; the GUI selects which
        # source ("precomputed"/"online"/"surrogate") is active per pulse.
        self.online_fem_mgr = OnlineFEMManager()
        # E-field mode: "precomputed" / "online" / "surrogate" (the GUI sets
        # it; a string, so future sources such as a predicted field can be
        # added without another flag). None until the operator picks one.
        self.efield_mode = None
        self.surrogate_mgr = SurrogateManager()


        # load env stuff
        self.config = {} # TODO: replace this from load project
        # The defaults match .env.example and docs/CONFIG.md: a checkout with
        # no .env must still start (the windows are the documented ones).
        self.config["TMS_PULSE_TIME"] = float(os.getenv("TMS_PULSE_TIME", "5"))/10
        self.config["START_MEP"] = int(os.getenv("START_MEP", "10"))
        self.config["END_MEP"] = int(os.getenv("END_MEP", "100"))
        self.config["MEASUREMENT_START_TIME"] = int(os.getenv("MEASUREMENT_START_TIME", "0"))
        self.config["SAMPLING_RATE"] = int(os.getenv("SAMPLING_RATE", "4000"))
        self.config["CUTOFF_FREQ"] = int(os.getenv("CUTOFF_FREQ", "500"))

        self.final_scores = {}
        self.stim_armed = False
        self._online_hold_logged = False
        self._health_hold_logged = False
        self._amplitude_hold_logged = False
        self._analysis_generation = 0
        self._pulse_width = None
        self._library_mats = None
        self.library_warning = None
        self._fire_mono = None
        self._realized_mono = None
        self._last_pulse_mono = None
        # How long to wait for InVesalius to confirm the realized coil pose
        # before the pulse is skipped (never spin forever).
        self.collect_timeout_s = float(os.getenv("COLLECT_TIMEOUT_S", "20"))
        # How long to wait for the EMG file of a pulse (the Signal PC writes
        # it after the sweep); then the pulse is recorded without a MEP.
        self.emg_timeout_s = float(os.getenv("EMG_TIMEOUT_S", "5"))
        # A precomputed pulse whose coil missed the planned placement by more
        # than this is flagged in the step log (the field is the planned one).
        self.max_aim_error_mm = float(os.getenv("MAX_AIM_ERROR_MM", "5"))
        self._emg_files_before = None
        self.aborted_by = None
        self.debug_geodesic = os.getenv("NEUROPILOT_DEBUG_GEODESIC", "").lower() in ("1", "true", "yes")

        # Mapping settings
        from .fit_functions import DEFAULT_FIT_NAME, resolve as resolve_fit
        self.fit_fun = resolve_fit(DEFAULT_FIT_NAME)
        self.map_elms = 1
        self.elm_idx_list = None
        self.n_elms = -1

    def clear_e_matrix(self):
        """Drop the precomputed matrix before a new file is read."""
        self.e_matrix = None
        self.n_elms = None
        self.n_positions = None
        self._library_mats = None

    def apply_e_matrix_file(self, path, data, mats=None):
        """Install an E-field matrix already read by a worker.

        The GUI calls this on the GUI thread after ``read_e_matrix_file``
        returned; direct callers can keep using ``set_e_matrix_file``.
        """
        self.e_matrix = np.asarray(data)
        self._library_mats = None if mats is None else np.asarray(mats)
        print(f" -> E-Matrix loaded. Shape: {self.e_matrix.shape}")
        self.n_elms = self.e_matrix.shape[1]
        self.n_positions = self.e_matrix.shape[0]
        self.set_map_elms(self.map_elms)
        if isinstance(self.emg_computer, VirtualEMG):
            self.emg_computer.set_e_matrix(self.e_matrix)
        self._check_library_consistency()
        return True

    def set_e_matrix_file(self, path: str):
        """Called by GUI when user loads the E-Matrix HDF5."""
        print(f"Controller: Loading E-Matrix from {path}...")
        self.clear_e_matrix()

        if not path:
            print("Controller: Path cleared. E-Matrix removed from memory.")
            return

        try:
            data, mats = read_e_matrix_file(path)
            self.apply_e_matrix_file(path, data, mats)
        except Exception as e:
            self.clear_e_matrix()
            print(f"Critical Error loading E-Matrix: {e}")

    def set_map_elms(self, map_elms):
        self.map_elms = map_elms
        if self.n_elms in (None, -1):
            # No E-matrix yet: the index list is rebuilt by set_e_matrix_file
            # once n_elms is known.  (np.arange(0, None, k) would raise.)
            return
        if self.map_elms > 1:
            self.elm_idx_list = np.arange(0, self.n_elms, self.map_elms) # TODO this doesn't work as expected
        elif self.map_elms == 1:
            self.elm_idx_list = None
        else:
            print("E-field not set. Cannot select elms to fit.")

    def set_results_filename(self, path: str):
        """
        Assigns the save path/filename received from the GUI to the controller.
        """
        self.results_fn = path
        print(f"Results filename set to: {path}")

    def set_overwrite_results(self, enabled: bool):
        """Keep or bypass an existing file at ``results_fn``."""
        self.overwrite_results = bool(enabled)

    def _results_output_path(self):
        """Final results path, honouring the overwrite checkbox.

        With overwrite off and an existing target, write the final table to
        the timestamped checkpoint name instead of replacing the operator's
        existing file.  A missing target is safe to write directly.
        """
        if not self.results_fn:
            return None
        if self.overwrite_results or not os.path.exists(self.results_fn):
            return self.results_fn
        stamp = self.datetime_str or datetime.now().strftime("%Y%m%d_%H%M%S")
        return stamped_results_filename(self.results_fn, stamp)

    def toggle_start_pause(self):
        self.is_paused = not self.is_paused
        if not self.is_paused:
            self.move_coil_up_flag = False
            # A project can be loaded after the controller started.  Re-send
            # the setup at the first Start so the robot uses the values now
            # shown in the project, not the values from app startup.
            if self.current_step == Step.INIT:
                self._announce_start_setup()

    def set_stopped_true(self):
        self.move_coil_up_flag = True
    #enable the stimulator
    def enable_stimulator(self):
        print("Arming stimulator")
        if self.stimulator.avail:
            self.stimulator.arm()
            # Ensure amplitude is set
            if self.stimulator_amplitude is not None:
                self.stimulator.set_amplitude(self.stimulator_amplitude)
            else:
                print("Warning: No amplitude set. Firing at hardware default.")

    def set_pause_true(self):
        self.is_paused = True

    def _send_async(self, topic, data=None):
        """Fire-and-forget relay send.

        The GUI slots can run before the qasync loop exists; without a
        running loop the send is dropped (same semantics as a disconnected
        relay), never raised.  The loop is checked before the coroutine is
        created, so a dropped send cannot warn "coroutine was never
        awaited" from the garbage collector."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.remote.send_message(topic, data=data))

    def toggle_free_drive(self, value):
        self._send_async('Neuronavigation to Robot: Set free drive', data={'set': value})
        print(f"Free drive has been set to {value}")

    def set_default_speed(self, value):
        self._send_async('GUI to Robot: set default speed robot', data={'default_speed_ratio': value/100})
        print(f"Default speed {value} has been sent to the Robot")

    def set_tuning_speed(self, value):
        self._send_async('GUI to Robot: set tuning speed robot', data={'tuning_speed_ratio': value/100})
        print(f"Tuning speed {value} has been sent to the Robot")

    def push_robot_settings(self):
        """Send the current GUI settings to the robot.

        The sliders are restored from the session cache before the relay is
        connected, so the sends at that moment are dropped and the robot keeps
        its own defaults (the simulated robot starts at 25 % / 10 %).  Pushing
        again when the run actually starts guarantees the robot uses the values
        shown in the GUI without the operator having to nudge a slider."""
        if self.control_panel is None:
            return
        try:
            self.set_default_speed(self.control_panel.spinBox2.value())
            self.set_tuning_speed(self.control_panel.spinBox3.value())
        except Exception as e:
            print(f"[WARN] could not push robot speeds: {e}")

    def finish_experiment(self):
        if self.is_finished:
            return
        self.is_finished = True
        print("Finish pressed.")
        # Release the robot and stop it, exactly like the Skip button: Finish
        # used to jump to SKIP without the cleanup, leaving the coil pressed.
        self._request_stop()
        self.switch_step(Step.SKIP)

    def set_amplitude_stim(self, amplitude):
        self.stimulator_amplitude = amplitude
        if self.stimulator.avail:
            self.stimulator.set_amplitude(amplitude)
            print(f"The amplitude is set to {amplitude}")

    def set_target_order_fn(self,value):
        self.target_order_fn = value
        print(f"target_order_fn set to {value}")

    def set_waveform(self, waveform):
        self.stimulator_waveform = waveform
        if self.stimulator.avail:
            self.stimulator.set_waveform(waveform)
            print(f"The waveform is set to {waveform}")

    def set_fit_function(self, fit_func: str):
        """Select the regression model (any pynibs fit function)."""
        from .fit_functions import resolve as resolve_fit
        function = resolve_fit(fit_func)
        if function is None:
            print(f"{fit_func} is not a valid fit function.")
            return
        self.fit_fun = function
        print(f"Controller: Fit Function set to {fit_func}")

    def set_minium_isi(self, value):
        self.minium_isi = value
        print(f"minium_isi set to: {value}")

    def set_n_repetitions(self,value):
        self.n_repetitions = value
        print(f"n_repetitions set to: {value}")

    def set_targets_file_header(self, path: str, n_targets):
        """Record a placements path and its header count without reading it.

        ``validate_simnibs_targets_file`` already knows the count from the
        HDF5 header.  The GUI shows that immediately and reads the matrices in
        a worker; the full :meth:`set_targets_file` then fills the cache used
        by the consistency check and by the start of a run.
        """
        print(f"Targets file set to: {path}")
        self.targets_file = path
        self._targets_cache = None
        if self.control_panel is not None:
            self.control_panel.totaltargets3.setText("")
        if not path:
            return
        if self.control_panel is not None:
            self.control_panel.totaltargets3.setText(f"{int(n_targets)}")

    def set_targets_file(self, path: str, target_queue=None, target_mats=None):
        print(f"Targets file set to: {path}")
        self.targets_file = path
        self._targets_cache = None

        # Empty counters when nothing is loaded or the file cannot be read —
        # never show a bare 0.
        if self.control_panel is not None:
            self.control_panel.totaltargets3.setText("")
        if not path:
            return

        try:
            if target_queue is None:
                target_queue, target_mats = read_simnibs_targets_data(path)
            n_coil_placements = len(target_queue)
        except (ValueError, OSError) as e:
            print(f"Could not set targets_file to {path}: {e}")
            self.targets_file = None
            self._targets_cache = None
            return

        self._targets_cache = (path, _file_signature(path),
                               target_queue, target_mats)
        try:
            # Keep the old side effect: the target order is read and
            # validated as soon as the placement file is usable.
            _, self.target_order = self.get_initial_targets()
        except (ValueError, OSError) as e:
            print(f"Could not set targets_file to {path}: {e}")
            self.targets_file = None
            self._targets_cache = None
            return
        if self.control_panel is not None:
            self.control_panel.totaltargets3.setText(f"{n_coil_placements}")
        self._check_library_consistency()

    def register_remote_handlers(self):
        """
        Registers the remote handles specified in this function with the remote to the Relay server.

        Returns
        -------
        None
        """
        pub_to_func = {
            'From Neuronavigation: Coil at target': self.OnCoilAtTarget,
            'From Neuronavigation: Coil target created' : self.GetRealizedTarget,
            'Robot to Neuronavigation: Send force sensor data': self.CobotOnTarget,
            'SIM - Robot to Neuronavigation: Tracking State': self.OnRobotTrackingState,
        }
        self.remote.register_handlers(pub_to_func)

    def OnRobotTrackingState(self, payload):
        """Joint configuration of the simulated robot -> embedded 3D view."""
        if not isinstance(payload, dict):
            return
        if self.control_panel is None or not self.simulation:
            return
        qpos = payload.get("qpos")
        if qpos:
            self.control_panel.update_robot_scene(qpos)

    def set_head_mesh(self, path):
        """Announce the project head mesh to the robot.

        ``None`` or an empty path resets the simulator to its default
        phantom, so a stale subject mesh never outlives the project that
        selected it.  The send is fire-and-forget.  During startup the
        session cache can be applied before the qasync loop exists, so fall
        back to a one-shot loop instead of raising.
        """
        coro = self.remote.send_message(
            TOPIC_SET_HEAD_MESH, {"mesh_path": path or None})
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            try:
                asyncio.run(coro)
            except Exception as e:
                print(f"[WARN] could not announce the head mesh: {e}")

    def _announce_start_setup(self):
        """Send the project start pose, branch and movement limits."""
        if self.motion_limits:
            self._send_async(TOPIC_SET_MOTION_LIMITS,
                             dict(self.motion_limits))
        if self.start_pose_joints:
            payload = {"joints": list(self.start_pose_joints)}
            if self.start_pose_branch is not None:
                payload["branch"] = list(self.start_pose_branch)
            self._send_async(TOPIC_SET_START_POSE, payload)

    def set_motion_limits(self, limits, announce=False):
        """Store the collision-tested movement limits.

        The experiment start announces them on
        ``Pipeline to Robot: Set motion limits``.  ``announce=True`` sends
        them immediately, which is useful when the operator presses "Use at
        start pose" before starting the run.
        """
        if not limits:
            return
        try:
            payload = {
                "safe_height_mm": float(limits["safe_height_mm"]),
                "translation_threshold_mm": float(
                    limits["translation_threshold_mm"]),
                "rotation_threshold_deg": float(
                    limits["rotation_threshold_deg"]),
            }
        except (KeyError, TypeError, ValueError):
            print("[WARN] motion limits ignored: incomplete values")
            return
        self.motion_limits = payload
        if not announce or self.remote is None:
            return
        coro = self.remote.send_message(TOPIC_SET_MOTION_LIMITS, payload)
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            try:
                asyncio.run(coro)
            except Exception as e:
                print(f"[WARN] could not announce motion limits: {e}")

    def set_start_pose(self, joints, branch=None):
        """Store and announce the collision-tested arm start configuration.

        ``branch`` is the shoulder/elbow/wrist choice that produced the
        start pose.  Sending it with the joints makes the simulated planner
        keep the collision-tested arm shape for every target instead of
        silently choosing a different IK branch.
        """
        if not joints:
            return
        self.start_pose_joints = [float(v) for v in joints]
        self.start_pose_branch = (
            [str(v) for v in branch] if branch is not None else None)
        payload = {"joints": list(self.start_pose_joints)}
        if self.start_pose_branch is not None:
            payload["branch"] = list(self.start_pose_branch)
        if self.remote is None:
            return
        coro = self.remote.send_message(TOPIC_SET_START_POSE, payload)
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            try:
                asyncio.run(coro)
            except Exception as e:
                print(f"[WARN] could not announce the start pose: {e}")

    def apply_emg_config_elements(self, elements):
        """Apply already-projected channel elements on the GUI thread."""
        if not isinstance(self.emg_computer, VirtualEMG):
            return False
        try:
            self.emg_computer.set_channel_elements(elements)
        except ValueError as e:
            print(f"EMG config rejected: {e}")
            return False
        if self.control_panel:
            publish = getattr(self.control_panel, "set_emg_channels", None)
            if publish is not None:
                publish(self.emg_computer.display_names)
            sources = getattr(self.control_panel, "set_emg_sources", None)
            if sources is not None:
                sources(elements)
        return True

    def set_emg_config(self, path: str):
        """Load the EMG channel sources from a project config file.

        Each entry names one cortical source, either as an ``element_id``
        into the loaded ROI or as an ``xyz`` position (mm, SimNIBS
        coordinates) which is projected to the closest ROI element. The
        sources are assigned positionally to the channel names from .env
        (EMG_CHANNELS). Applies to the simulated EMG only.
        """
        if not isinstance(self.emg_computer, VirtualEMG):
            print("EMG channel config applies to the simulated EMG only.")
            return
        if not path or not os.path.isfile(path):
            print(f"EMG config not found: {path}")
            return
        roi_fn = self.control_panel.loadroilabel.text().strip() if self.control_panel else None
        try:
            elements = read_emg_config_elements(path, roi_fn)
        except (OSError, ValueError, yaml.YAMLError) as e:
            print(f"EMG config ignored: {e}")
            return
        self.apply_emg_config_elements(elements)

    async def run(self):
        """
        Asynchronously runs the main algorithm (`run_algorithm`) and health checks (`run_health_checks`) concurrently.

        Returns
        -------
        None
        """
        # Announce the head mesh configured in the project window (session
        # cache) so a freshly started robot sim applies it immediately.
        self._announce_start_setup()
        if self.control_panel:
            fn_mesh = self.control_panel.loadmeshlabel.text().strip() or None
            self.set_head_mesh(fn_mesh)
        if self.control_panel:
            await asyncio.gather(
                    self.run_algorithm(),
                    self.run_health_checks(),
            )
        else:
            await asyncio.gather(
                    self.run_algorithm(),
            )

    async def run_algorithm(self):
        """Run the target loop, tracking whether it is still draining.

        The GUI keeps the Finish button pressed until this returns: after
        Finish was pressed (or the run ended on its own) the loop and the
        final analysis wait may still be writing."""
        self._run_done = False
        try:
            await self._run_target_loop()
        finally:
            self._run_done = True

    async def _run_target_loop(self):
        """
        Asynchronously reads coil targets and then runs the algorithm through the step sequence until all targets have been completed.

        Returns
        -------
        None
        """

        # Wait until GUI sets self.targets_file
        while self.targets_file is None:
            # Give GUI + other tasks time to run
            await asyncio.sleep(0.1)

        try:
            target_queue, target_order = self.get_initial_targets()
        except ValueError as e:
            # Wrong/removed placement files are caught when the path is set;
            # this is the safety net so a run never dies silently.
            message = f"Cannot start: {e}"
            print(message)
            if self.control_panel is not None:
                self.control_panel.finishedsteps.appendPlainText(message)
            self.is_finished = True
            return
        print("Coil targets are read")

        # The robot must run with the speeds shown in the GUI, not with its
        # power-on defaults (the restored slider values were sent while the
        # relay was still connecting and were dropped).
        self.push_robot_settings()

        if self.control_panel is not None:
            self.control_panel.totaltargets3.setText(f"{len(target_queue)}")

        self.start_of_experiment = datetime.now()
        self.datetime_str = f"{self.start_of_experiment.strftime('%Y%m%d_%H%M%S')}"

        mgr = self._active_efield_manager()
        while (mgr is not None and not mgr.is_ready and mgr.initializing):
            await asyncio.sleep(0.1)
            mgr = self._active_efield_manager()

        print(f"len target_order: {len(target_order)}")
        while self.current_target_order_idx < len(target_order):
            target_id = target_order[self.current_target_order_idx]
            target = target_queue[target_id]
            print(f"target id {target_id}: {target}")

            # 1) Check Finish flag BEFORE starting this target
            if self.is_finished:
                print("Experiment finished by user before starting target", target_id)
                break

            # 2) Wait here until Start is pressed (allow_next_target == True)
            while self.is_paused and not self.is_finished:
                # we stay here between targets when user pressed Pause
                await asyncio.sleep(0.05)

            # If Finish was pressed while we were waiting, stop
            if self.is_finished:
                print("Experiment finished by user while waiting before target", target_id)
                break

            self.current_target_index = target_id
            current_target_text = (f"pulse {self.current_target_order_idx}"
                                   f" · {self.current_rep}/{self.n_repetitions}"
                                   f" · target {target_id}")
            if self.control_panel is not None:
                self.control_panel.currenttarget.setText(current_target_text)
            if self.control_panel is not None:
                self.control_panel.finishedsteps.appendPlainText("")
                self.control_panel.finishedsteps.appendPlainText(f"=== BEGIN TARGET {self.current_target_order_idx:03d} "
                                                                 f"({self.current_rep}/{self.n_repetitions}) ===")
            print(f"New target: {target}")

            # Resetting the algorithm
            self.reset_algorithm()

            # Go to the first step
            self.switch_step(Step.SEND_MARKER)

            # Running the algorithm.
            while self.current_step != Step.COMPLETE:
                if self.move_coil_up_flag:
                    break
                # Stop/Skip/Finish must work even when a system is unhealthy:
                # the operator has to be able to end a session with a dead EMG
                # or robot.  Only the *work* steps are gated on the health.
                if self.current_step == Step.SKIP:
                    self.switch_step(Step.COMPLETE)
                    continue
                if self.control_panel is not None and not self.no_error_states():
                    if not self._health_hold_logged:
                        self._health_hold_logged = True
                        self._log_step(
                            f"Held at {self.current_step.name}: "
                            f"{self._health_reason()} not ready. "
                            "Finish ends the session.")
                    await asyncio.sleep(0.05)
                    continue
                if self._health_hold_logged:
                    self._health_hold_logged = False
                    self._log_step("All systems ready again, continuing.")

                try:
                    if self.current_step == Step.SEND_MARKER:
                        self.send_marker_step(target)
                    elif self.current_step == Step.START_TRACKING:
                        self.start_tracking_step(target)
                    elif self.current_step == Step.WAIT_FOR_TARGET_REACHED:
                        await self.wait_for_target_reached_step(target)
                    elif self.current_step == Step.FIRE_STIM:
                        if self.is_paused:
                            # Pause works inside a target too: hold before the
                            # pulse instead of only between targets.
                            await asyncio.sleep(0.05)
                            continue
                        self.fire_stim_step(target)
                    elif self.current_step == Step.COLLECT_DATA:
                        await self.collect_data_step(target)
                    elif self.current_step == Step.ANALYSE:
                        self.analyse_step(target)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # One failing step must not take the whole session down
                    # silently: report it, stop the run and save what we have.
                    self._abort_run(e)
                    break

                # To stop CPU overload
                await asyncio.sleep(0.05)

            await asyncio.sleep(0.05)

            # stay at this target id if repetitions are not completed
            if self._go_back:
                self._go_back = False
            elif self.current_rep < self.n_repetitions:
                print("Adding repetition")
                self.current_rep += 1
            else:
                print("Repetitions done")
                self.current_rep = 1
                self.current_target_order_idx += 1

        print("We are done.")
        self.move_robot_away_from_head()

        if self.running_analyses_tasks:
            print("Waiting for final R2 map.")
            # A failed analysis must not abort the finalisation (and lose the
            # results file): the failure was logged when it happened.
            await asyncio.gather(*self.running_analyses_tasks,
                                 return_exceptions=True)
            self.running_analyses_tasks = []
            self.push_mapping_results()

        if self.simulation and self.debug_geodesic:
            self.final_adc1_geodesic_and_markers()

        # save results
        try:
            results = pd.DataFrame().from_dict(self.realized_targets)
            results_mep = pd.DataFrame().from_dict(self.mep_history)
            results_mep_amp = pd.DataFrame().from_dict(self.emg_preac_amp_history)
            results_mep_var = pd.DataFrame().from_dict(self.emg_preac_var_history)
            # The data layer speaks ADC; label the MEP columns with the
            # configured display names for the results output.
            if isinstance(self.emg_computer, VirtualEMG):
                rename = {}
                for key, name in self.emg_computer.display_name_map().items():
                    rename[key] = name
                    rename[f"{key}_preact_p2p"] = f"{name}_preact_p2p"
                    rename[f"{key}_preact_var"] = f"{name}_preact_var"
                results_mep = results_mep.rename(columns=rename)
                results_mep_amp = results_mep_amp.rename(columns=rename)
                results_mep_var = results_mep_var.rename(columns=rename)
            results = pd.concat([results.reset_index(drop=True),
                                 results_mep,
                                 results_mep_amp,
                                 results_mep_var], axis=1)
            out_fn = self._results_output_path()
            if out_fn is not None:
                results.to_csv(out_fn, index=False)
                if out_fn != self.results_fn:
                    self._log_step(
                        f"Existing results file kept; wrote {out_fn}")
        except Exception as e:
            # A save failure must be visible to the operator, not just printed.
            self._log_step(f"[WARN] could not write the results file: "
                           f"{type(e).__name__}: {e}")

    # ── mapping results for the 3D page ─────────────────────────────────
    def placement_records(self):
        """One record per collected pulse, in acquisition order."""
        rt = self.realized_targets
        count = len(rt['idx'])
        records = []
        for i in range(count):
            position = [rt['x_realized'][i], rt['y_realized'][i], rt['z_realized'][i]]
            rotation = [rt['rota_realized'][i], rt['rotb_realized'][i], rt['rotc_realized'][i]]
            target_position = [rt['x_target'][i], rt['y_target'][i], rt['z_target'][i]]
            target_rotation = [rt['rota_target'][i], rt['rotb_target'][i], rt['rotc_target'][i]]
            try:
                aim = float(np.linalg.norm(np.array(position) - np.array(target_position)))
            except (TypeError, ValueError):
                aim = 0.0
            mep = {ch: (hist[i] if i < len(hist) else None)
                   for ch, hist in self.mep_history.items()}
            records.append({
                "trial": i,
                "pulse_index": rt['idx'][i],
                "target_index": rt['idx_pulse'][i],
                "time": rt['time'][i],
                "position": position,
                "rotation": rotation,
                "target_position": target_position,
                "target_rotation": target_rotation,
                "aim_error_mm": aim,
                "intensity": rt['intensity'][i],
                "pressure": rt['pressure'][i],
                "mep": mep,
                # Which E-field source this pulse used (the mode can change
                # between pulses; see set of pulse_modes).
                "e_field_mode": (self.pulse_modes[i]
                                 if i < len(self.pulse_modes) else None),
            })
        return records

    def push_mapping_results(self):
        """Hand the results page the placement log and the current R² maps."""
        if self.control_panel is None:
            return
        try:
            self.control_panel.update_mapping_results({
                "placements": self.placement_records(),
                "channels": list(self.mep_history.keys()),
                "scores": dict(self.final_scores) if self.final_scores else None,
            })
        except Exception as e:
            print(f"[WARN] mapping results update failed: {e}")

    def reset_algorithm(self):
        self.target_reached = False
        self.target_created = False
        self.realized_target = None
        self._realized_mono = None

    async def run_health_checks(self):
        """
        Asynchronously performs continuous health checks on all registered systems by calling `check_system`.
        
        For each loop of health checks it runs all system checks concurrently until all checks have finished, and then runs them again.
        I.e. the time between health checks is as long as the longest health check is.

        Returns
        -------
        None
        """
        while True:
            # All checks are run concurrently, but we wait till all have finished. So the time between health checks is as long as the longest check.
            await asyncio.gather(*(s.check_system() for s in self.systems))
            # To stop CPU overload
            await asyncio.sleep(0.5)

    def _log_step(self, text):
        """One line to stdout and to the operator's step log."""
        print(text)
        panel = self.control_panel
        if panel is None:
            return
        try:
            panel.finishedsteps.appendPlainText(text)
        except (AttributeError, RuntimeError):
            pass

    def _health_reason(self):
        bad = [getattr(system, "NAME", "?") for system in self.systems
               if system.is_error_state()]
        return ", ".join(bad) if bad else "a subsystem"

    def _abort_run(self, error):
        """A step raised: stop the run, tell the operator, keep the data."""
        import traceback
        self._log_step(f"[ERROR] {self.current_step.name} failed: "
                       f"{type(error).__name__}: {error}")
        traceback.print_exc()
        self.aborted_by = f"{self.current_step.name}: {error}"
        self.is_finished = True
        self.current_step = Step.COMPLETE

    def _request_stop(self):
        """Send the same stop/robot-release as the Skip button, if possible."""
        if self.manual:
            return
        try:
            # The loop is checked before the coroutine is created, so a
            # dropped send cannot warn "coroutine was never awaited".
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (GUI-only session or a unit test): the relay
            # sends are best effort.
            return
        loop.create_task(self.remote.send_message('STOP', data={}))
        loop.create_task(self.remote.send_message(
            "Press robot button", data={'pressed': False}))

    @property
    def is_running(self):
        """A session has started and has not finished yet."""
        return self.start_of_experiment is not None and not self.is_finished

    def is_draining(self):
        """Finish was pressed (or the run ended on its own) and work may
        still be writing: the target loop or an in-flight analysis.

        The GUI keeps the Finish button pressed with a spinner until this
        clears.  The cobot's own deceleration after the STOP release is not
        observable from the controller; the release is sent at Finish and
        the robot system only reports connection health."""
        if not self.is_finished:
            return False
        if not self._run_done:
            return True
        return any(not task.done() for task in self.running_analyses_tasks)

    def reset_session(self):
        """Back to the pre-session state so Start can begin a new run.

        The results file is kept: the overwrite switch asks before the next
        run overwrites it."""
        self.is_finished = False
        self.is_paused = True                  # waiting for Start again
        self.start_of_experiment = None
        self.current_target_order_idx = 0
        self.current_target_index = None
        self.current_step = Step.INIT
        self.current_step_start_time = None
        self.current_rep = 1
        self._go_back = False
        self.move_coil_up_flag = False
        self._run_done = True
        self.reset_algorithm()

    def switch_step(self, new_step):
        """
        This method updates:
        - `self.current_step` to the given `new_step`.
        - `self.current_step_start_time` to the current system time, to keep track of time spent in current step.

        Parameters
        ----------
        new_step : Step or str
            The new step in the algorithm's execution state machine. Expected to be an enum or constant representing a valid step.

        Returns
        -------
        None
        """
        if isinstance(new_step, str):
            if new_step.lower() == "skip":
                new_step = Step.COMPLETE
                if not self.manual:
                    asyncio.create_task(self.remote.send_message('STOP', data = {}))
                    asyncio.create_task(self.remote.send_message("Press robot button", data={'pressed': False}))

            elif new_step.lower() == "previous":
                if self.current_step in (Step.FIRE_STIM, Step.COLLECT_DATA):
                    # The step would resume and overwrite the jump; ignore it
                    # instead of mislabelling the pulse that is in flight.
                    self._log_step("Previous ignored: a pulse is in flight.")
                    return
                self._go_back = True
                print(f" before: self.current_pulse_idx {self.current_target_order_idx}")
                new_step = Step.COMPLETE
                if not self.manual:
                    asyncio.create_task(self.remote.send_message('STOP', data={}))
                    asyncio.create_task(self.remote.send_message("Press robot button", data={'pressed': False}))
                if self.current_target_order_idx > 0:
                    self.current_target_order_idx -= 1
                self.current_rep = 1 # also reset repetitions
                print(f" after: self.current_pulse_idx {self.current_target_order_idx}")
        self.current_step_start_time = time.time()
        # Wall-clock is for the logs; the state machine measures intervals on
        # the monotonic clock so an NTP jump cannot shorten the ISI.
        self.current_step_started_mono = time.monotonic()
        self.current_step = new_step

        # update the GUI log that shows the steps
        if self.control_panel:
            # 1) get the step name
            step_name = self.current_step.name

            # 2) tie stamp
            ts = datetime.now().strftime("%H:%M:%S")

            # 3) build the line to the log
            if self.current_target_index is not None:
                line = f"[{ts}] {step_name}"
            else:
                line = f"[{ts}] {step_name} "

            # 4) append line
            self.control_panel.finishedsteps.appendPlainText(line)

            # 5) ensure the log scrolls to the bottom so the newest line is visible
            self.control_panel.finishedsteps.ensureCursorVisible()

    def set_pid(self, stiffness, damping, proportional, integral, derivative):
        data = {'stiffness': stiffness,
                'damping': damping,
                'proportional': proportional,
                'integral': integral,
                'derivative': derivative}
        asyncio.create_task(self.remote.send_message('Set PID values', data=data))

    def set_damping(self, value):
        asyncio.create_task(self.remote.send_message('Set damping', data={'damping': value}))

    def no_error_states(self):
        """
        Checks whether all registered systems are free of error states by calling their `is_error_state()` method

        Returns
        -------
        bool
            True if none of the systems are in an error state; False otherwise.
        """
        return not any(s.is_error_state() for s in self.systems)

    def get_initial_targets(self):
        """
        Loads the coil targets from the specified HDF5 file and transforms them to InVesalius axis convention.

        Returns
        -------
        list of tuple of (np.ndarray, np.ndarray)
            A list of targets, where each target is a tuple (position, euler_angles). Euler angles in degrees.
        """
        print(f"hdf5_file_path: {self.targets_file}")
        target_queue = None
        cache = getattr(self, "_targets_cache", None)
        if cache and cache[0] == self.targets_file \
                and cache[1] == _file_signature(self.targets_file):
            target_queue = cache[2]
        if target_queue is None:
            target_queue, target_mats = read_simnibs_targets_data(self.targets_file)
            self._targets_cache = (self.targets_file,
                                   _file_signature(self.targets_file),
                                   target_queue, target_mats)

        print(f"target_order_fn: {self.target_order_fn}")
        if self.target_order_fn is not None:
            self.target_order = read_target_order(self.target_order_fn, len(target_queue))
        else:
            print(f"No target order file given. Running all coil placements.")
            self.target_order = np.arange(len(target_queue), dtype=int)

        print(f"len(self.target_order): {len(self.target_order)}")
        return target_queue, self.target_order

    def send_marker_step(self, target):
        # As constructed by `get_initial_targets`
        pos = target[0]
        rot = target[1]

        #render should be false for some reason i remember
        topic = 'External Controller to Neuronavigation: Create Marker'
        data = {
            'position' : pos.tolist(),
            'orientation' : rot.tolist(),
            'label' : f'SimNIBS {self.current_target_order_idx:0>3}',
            'marker_type' : 3,
            # Because false on check is previous for some reason
            'is_target' : True
        }
        print("Sending target to InVesalius!")
        # Sending data compressed an extra layer to avoid pypubsub issues with automatic topic connection due to the way invesalius treats data
        asyncio.create_task(self.remote.send_message(topic, {'data': data}))
        self.cobotOnTarget = False

        self.switch_step(Step.START_TRACKING)

    def move_robot_away_from_head(self):
        """
        Sends robot awawy from head by sending objective = 2
        """
        if self.manual:
            return  # no robot to move away
        asyncio.create_task(self.remote.send_message("Neuronavigation to Robot: Set objective", {'objective': 2}))

    def start_tracking_step(self, target):
        # Giving InVesalius some time to be ready
        if time.time() - self.current_step_start_time > 3.0:
            if self.manual:
                # No robot: Invesalius tracks the hand-held coil directly.
                print("Tracking target (manual)")
            else:
                print("Tracking target with robot!")
                asyncio.create_task(self.remote.send_message("Press robot button", data = { 'pressed' : True}))

            self.switch_step(Step.WAIT_FOR_TARGET_REACHED)

    async def wait_for_target_reached_step(self, target):
        # self.target_reached is set to true by OnCoilAtTarget when InVesalius send that message.
        if self.running_analyses_tasks:
            await asyncio.gather(*self.running_analyses_tasks)
        # Manual mode: the hand-held coil provides the pressure -- only the
        # coil-at-target signal and the ISI gate the stimulation.
        force_ok = self.manual or self.cobotOnTarget > self.pressure_thresh
        # minium_isi is a safety limit: measure it on the monotonic clock so a
        # system clock jump can never shorten the interval between pulses.
        last_pulse_mono = getattr(self, "_last_pulse_mono", None)
        isi_ok = (last_pulse_mono is None
                  or self.mono_now() - last_pulse_mono >= self.minium_isi)
        if self.target_reached and force_ok and isi_ok:
            print("Stopping target tracking.")
            if not self.manual:
                asyncio.create_task(self.remote.send_message("Press robot button", data={'pressed': False}))
            self.switch_step(Step.FIRE_STIM)

    def trigger_stim(self):
        """Called by the GUI button or by fire_stim_step() to trigger the stimulation."""

        # Spawns a background task so the GUI doesn't freeze
        asyncio.create_task(self._async_manual_stim())

    async def _async_manual_stim(self):
        try:
            loop = asyncio.get_running_loop()

            # This passes the synchronous magicpy function to a background worker.
            # We 'await' the worker, NOT the magicpy function directly.
            await loop.run_in_executor(None, self.stimulator.fire) # type: ignore
        except Exception as e:
            print(f"Error during stimulation: {e}")


    def mono_now(self):
        """Seconds on a monotonic clock (immune to system clock jumps)."""
        return time.monotonic()

    def get_time_now(self):
        """
        Returns the time in seconds since start of experiment.
        """
        return (datetime.now() - self.start_of_experiment).total_seconds()

    def _active_efield_manager(self):
        """The manager the current mode waits on / computes with.

        ``None`` for the precomputed mode (its field is a lookup, not a
        solver). Uses ``getattr`` so partially initialised test doubles work.
        """
        mode = getattr(self, "efield_mode", None)
        if mode == "online":
            return self.online_fem_mgr
        if mode == "surrogate":
            return self.surrogate_mgr
        return None

    def fire_stim_step(self, target):
        if self.stimulator_amplitude is None:
            # The GUI normally sets this, but a session restored without a
            # cache and started without touching the slider must not crash
            # inside the stimulator call after the coil was pressed on.
            if not self._amplitude_hold_logged:
                self._amplitude_hold_logged = True
                self._log_step("Holding stimulation: no stimulator amplitude set.")
            return
        self._amplitude_hold_logged = False

        # A switch to a solver-based mode may land mid-run.  Hold the pulse
        # until the active source (online solver or interpolated library) is
        # ready instead of firing a pulse whose E-field cannot be computed;
        # the coil simply stays on target meanwhile.  Switching back to
        # precomputed releases the hold immediately.
        mgr = self._active_efield_manager()
        if mgr is not None and not mgr.is_ready:
            if not self._online_hold_logged:
                self._online_hold_logged = True
                kind = ("online E-field solver" if self.efield_mode == "online"
                        else "interpolated E-field library")
                message = (f"Holding stimulation: {kind} not ready yet "
                           "(switch to precomputed to continue without it).")
                print(message)
                if self.control_panel is not None:
                    self.control_panel.finishedsteps.appendPlainText(message)
            return
        if self._online_hold_logged:
            self._online_hold_logged = False
            print("E-field ready, stimulation resumes.")

        if not self.stim_armed:
            self.stimulator.arm()
            self.stim_armed = True
            self.stimulator.set_amplitude(self.stimulator_amplitude)

        self.stimulator_amplitude_at_stim = self.stimulator_amplitude
        # Give the stimulator a short bit to arm itself.
        if time.time() - self.current_step_start_time > 1:
            print("Firing Stimulator!")
            self.target_at_stim = target
            self.time_at_stim = self.get_time_now()
            self.pressure_at_stim = self.cobotOnTarget

            # Feed coil position + intensity to the virtual EMG computer
            if isinstance(self.emg_computer, VirtualEMG):
                self.emg_computer.set_current_state(
                    coil_placement_idx=self.current_target_index,
                    stimuator_amplitude=self.stimulator_amplitude_at_stim,
                )


            # A late realized-target message from the previous pulse must not
            # be used for this one.
            self.target_created = False
            self.realized_target = None
            self._fire_mono = self.mono_now()

            # Remember which EMG files already exist: the pulse's own sweep
            # must not be one of them (a slow Signal PC would otherwise hand
            # back the previous pulse's data, which looks plausible).
            self._emg_files_before = None
            snapshot = getattr(self.emg_computer, "signal_files", None)
            if callable(snapshot):
                try:
                    self._emg_files_before = snapshot()
                except Exception as e:
                    self._log_step(f"[WARN] could not list the EMG folder: {e}")

            self.trigger_stim()

            # Create a marker in InVesalius
            topic = "Create marker"
            asyncio.create_task(self.remote.send_message(topic, data = {"label" : "stim_mark"}))

            self.stim_armed = False
            self._last_pulse_mono = self.mono_now()
            print("Switch to collect")
            self.switch_step(Step.COLLECT_DATA)

    async def collect_data_step(self, target):
        # Wait to collect the data until we get the call from InVesalius with the coil position at the moment of stimulation.
        # We also wait a short while to ensure the EMG Computer has printed its EMG file. This length of wait needs to be validated.
        # A realized target that arrived *before* this pulse fired belongs to
        # the previous one; drop it instead of recording the wrong geometry.
        if (self.target_created and self._fire_mono is not None
                and getattr(self, "_realized_mono", None) is not None
                and self._realized_mono < self._fire_mono):
            self._log_step("Ignoring a realized target from the previous pulse.")
            self.target_created = False
            self.realized_target = None
        if not self.target_created:
            waited = time.time() - self.current_step_start_time
            if waited > self.collect_timeout_s:
                # InVesalius never answered: do not spin forever.
                self._log_step(
                    f"No realized target after {waited:.0f} s -- pulse skipped.")
                self.switch_step(Step.COMPLETE)
                return
        if self.target_created and time.time() - self.current_step_start_time > 2.0:

            print(f"target pos, angles:\n {self.target_at_stim}")


            rounded_target = self.realized_target
            if isinstance(rounded_target, dict) and "markers" in rounded_target:
                rounded_target = dict(rounded_target)
                rounded_target["markers"] = [
                    [round(float(value), 2) for value in marker]
                    for marker in rounded_target["markers"]]
            print(f"realized_target: {rounded_target}")
            marker = self.realized_target['markers']
            print(f"marker pos, angles:\n {marker}")
            self.realized_targets['idx'].append(self.current_target_order_idx)
            self.realized_targets['idx_pulse'].append(self.current_target_index)
            self.realized_targets['time'].append(self.time_at_stim)

            self.realized_targets['x_realized'].append(marker[0][0])
            self.realized_targets['y_realized'].append(marker[0][1])
            self.realized_targets['z_realized'].append(marker[0][2])
            self.realized_targets['rota_realized'].append(marker[1][0])
            self.realized_targets['rotb_realized'].append(marker[1][1])
            self.realized_targets['rotc_realized'].append(marker[1][2])

            self.realized_targets['x_target'].append(self.target_at_stim[0][0])
            self.realized_targets['y_target'].append(self.target_at_stim[0][1])
            self.realized_targets['z_target'].append(self.target_at_stim[0][2])
            self.realized_targets['rota_target'].append(self.target_at_stim[1][0])
            self.realized_targets['rotb_target'].append(self.target_at_stim[1][1])
            self.realized_targets['rotc_target'].append(self.target_at_stim[1][2])

            aim = self._aim_error(marker, self.target_at_stim)
            if (aim is not None and self.efield_mode == "precomputed"
                    and aim > self.max_aim_error_mm):
                # Precomputed mode uses the *planned* placement's field, so a
                # miss means the regression is fed a field the cortex did not
                # get.  Say so instead of hiding it.
                self._log_step(f"[WARN] coil was {aim:.1f} mm from the planned "
                               f"position -- the precomputed field is the planned one.")

            self.realized_targets['pressure'].append(self.pressure_at_stim)
            self.realized_targets['intensity'].append(self.stimulator_amplitude_at_stim)
            self.realized_targets['e_field_mode'].append(
                self.efield_mode if self.efield_mode in ("online", "surrogate")
                else "precomputed")

            # E-field this pulse actually saw, from whichever source is active
            # right now (the mode may change between pulses). The solvers
            # return the row they appended — never read e_matrix[-1] here, a
            # skipped pulse would otherwise repeat the previous row.
            if self.efield_mode == "online":
                e_row = self.online_fem_mgr.compute_e_field(
                    marker, self.stimulator_amplitude_at_stim)
                pulse_mode = "online"
            elif self.efield_mode == "surrogate":
                e_row = self.surrogate_mgr.compute_e_field(
                    marker, self.stimulator_amplitude_at_stim)
                pulse_mode = "surrogate"
            else:
                e_row = precomputed_e_field_row(self.e_matrix,
                                                self.current_target_index,
                                                self.stimulator_amplitude_at_stim)
                pulse_mode = "precomputed"

            # The virtual EMG is driven by the realised field; a pulse outside
            # the interpolated domain has an all-NaN row and gets none.
            e_field_for_mep = e_row if (pulse_mode in ("online", "surrogate")
                                        and e_row is not None
                                        and np.all(np.isfinite(e_row))) else None
            emg_data = await self._read_emg(e_field_for_mep)

            if self.current_step != Step.COLLECT_DATA:
                # Skip/Finish arrived while the EMG was being read: drop this
                # pulse instead of recording it and jumping to ANALYSE.
                self._log_step("Pulse discarded: the step was aborted while reading the EMG.")
                return

            if emg_data is None:
                # Never fall back to the previous sweep: record the pulse with
                # an unmeasurable MEP so the map reports it instead of using
                # another pulse's amplitude.
                self._log_step("[WARN] no new EMG file for this pulse -- "
                               "recorded without a MEP.")
                channels = list(getattr(self.emg_computer, "data_channel_names", [])
                                or self.mep_history.keys())
                nan = {ch: float("nan") for ch in channels}
                meps, emg_preac_amp, emg_preac_var = nan, dict(nan), dict(nan)
            else:
                try:
                    meps, emg_preac_amp, emg_preac_var = self.compute_meps(emg_data)
                except ValueError as e:
                    # A sweep without channel columns: keep the histories
                    # aligned with NaNs instead of aborting the pulse.
                    self._log_step(f"[WARN] could not analyse the EMG sweep: {e}")
                    channels = list(getattr(self.emg_computer, "data_channel_names", [])
                                    or self.mep_history.keys())
                    nan = {ch: float("nan") for ch in channels}
                    meps, emg_preac_amp, emg_preac_var = nan, dict(nan), dict(nan)

            # --- 1. STORE DATA in the pipeline_controller for the analysis ---
            e_row = self._check_row_width(e_row)

            # Store the index of the coil position used
            self.used_coil_placements_idx.append(self.current_target_index)
            # ... and the E-field row of the same pulse (kept index-aligned)
            self.pulse_e_fields.append(None if e_row is None else np.array(e_row, dtype=float, copy=True))
            self.pulse_modes.append(pulse_mode)

            # Store MEPs
            for ch, val in meps.items():
                if ch not in self.mep_history:
                    self.mep_history[ch] = []
                self.mep_history[ch].append(val)

            for ch, val in emg_preac_amp.items():
                if ch not in self.emg_preac_amp_history:
                    self.emg_preac_amp_history[ch] = []
                self.emg_preac_amp_history[ch].append(val)

            for ch, val in emg_preac_var.items():
                if ch not in self.emg_preac_var_history:
                    self.emg_preac_var_history[ch] = []
                self.emg_preac_var_history[ch].append(val)

            # Live view for the results page: placements + MEPs collected so far.
            self.push_mapping_results()

            # passing data to the GUI for plotting the meps and the emg
            if self.control_panel:
                self.control_panel.on_new_emg_result(
                        target_index = self.current_target_order_idx,
                        emg_data = emg_data,
                        meps = meps,
                )

            self.switch_step(Step.ANALYSE)
            results = pd.DataFrame().from_dict(self.realized_targets)
            results_mep = pd.DataFrame().from_dict(self.mep_history)
            results_mep_amp = pd.DataFrame().from_dict(self.emg_preac_amp_history)
            results_mep_var = pd.DataFrame().from_dict(self.emg_preac_var_history)
            results = pd.concat([results.reset_index(drop=True),
                                 results_mep,
                                 results_mep_amp,
                                 results_mep_var], axis=1)
            if self.results_fn is not None:
                out_fn = stamped_results_filename(self.results_fn, self.datetime_str)
                try:
                    results.to_csv(out_fn, index=False)
                except OSError as e:
                    # The folder may have been deleted while the mapping ran;
                    # the pulse is already recorded, so do not lose the run.
                    print(f"[WARN] could not write {out_fn}: {e}")

    def set_pulse_inclusion(self, pulse_idx, included):
        """Adds or removes a specific sequential pulse from the mapping calculation."""
        if included:
            self.excluded_pulse_indices.discard(pulse_idx)
            print(f"Re-included pulse {pulse_idx} back to mapping.")
        else:
            self.excluded_pulse_indices.add(pulse_idx)
            print(f"Excluded pulse {pulse_idx} from mapping.")

        # Method A: Trigger real-time background analysis
        valid_count = len(self.used_coil_placements_idx) - len(self.excluded_pulse_indices)

        if valid_count >= 3:
            print(f"--- Triggering Real-Time Analysis ({valid_count} valid pulses) ---")
            self.request_analysis()
        else:
            print(f"Skipping analysis (Only {valid_count} valid pulses).")


    def analyse_step(self, target):
        """
        Performs pynibs regression if we have collected enough data (every 3rd pulse).
        """
        # 1. Check if we need to run analysis (Every 3 pulses)
        n_samples = len(self.used_coil_placements_idx)

        # Only run if we have at least 3 samples
        if n_samples >= 3:
            print(f"--- Triggering Analysis (Sample {n_samples}) ---")
            self.request_analysis()

        else:
            print(f"Skipping analysis (N samples {n_samples} < 3).")

        # 2. Done. Move to Complete.
        print("Analyses started, moving to next target")
        self.switch_step(Step.COMPLETE)

    async def CobotOnTarget(self, data):
        """Force sensor state from the relay (payload may be incomplete)."""
        if isinstance(data, dict) and "force_feedback" in data:
            self.cobotOnTarget = data["force_feedback"]

    async def OnCoilAtTarget(self, data):
        """
        Callback triggered by the connection to the relay server when InVesalius sends that the coil is at the target.

        If the received `data` contains `"data[state]" == True`, the internal flag
        `self.target_reached` is set to `True`.

        Parameters
        ----------
        data : dict
            Dictionary containing the state information. Expected to have a key:
            - `"state"` (bool): True if the coil has reached the target position.

        Returns
        -------
        None
        """
        if isinstance(data, dict) and "state" in data:
            # InVesalius sends the transition in both directions; follow it so
            # a coil that leaves the target is noticed instead of latching.
            self.target_reached = data["state"] is True or data["state"] == 1

    async def GetRealizedTarget(self, data):
        """
        Callback triggered by the connection to the relay server when InVesalius sends the coil position registered at the time of stimulation.

        If the received `data` contains a non-`None` `"markers"` field, this method:
        - Prints a confirmation message.
        - Sets the internal flag `self.target_created` to `True`.
        - Stores the entire `data` dictionary in `self.realized_target` for potential future use.

        Parameters
        ----------
        data : dict
            Dictionary containing the realized target. Expected to have a key:
            - `"markers"`: Data related to target markers; if `None`, no action is taken.

        Returns
        -------
        None
        """
        if not isinstance(data, dict) or data.get("markers") is None:
            # A malformed or empty frame must not raise inside the relay.
            return
        print(f"GetRealizedTarget called: {data['markers']}")
        self.target_created = True
        self._realized_mono = self.mono_now()
        # Store but not used
        self.realized_target = data

    def create_emg_plot(self, emg_data):
        df = emg_data
        channels = df.columns[1:]
        # EMG graph colors
        colors = sns.color_palette("tab10", len(channels))

        # Get global min and max for all channels to give them the same yscale
        ymin = min(df[ch].min() for ch in channels)
        ymax = max(df[ch].max() for ch in channels)

        # Plot RAW EMGs
        sns.set_theme(style='whitegrid')
        fig, axes = plt.subplots(len(channels), 1, sharex=True, figsize=(12, 8))
        for i, (ch, color) in enumerate(zip(channels, colors)):
            sns.lineplot(ax=axes[i], x='Time', y=ch, data=df, color=color)
            axes[i].set_ylabel(ch)
            axes[i].set_ylim(ymin, ymax)  # Shared y-axis limits
            axes[i].grid(True, linestyle='--', alpha=0.5)
            axes[i].set_xlabel('Time' if i == len(channels) - 1 else '')
            axes[i].set_title(f'{ch} Signal')

        plt.tight_layout()

        # Save the plot
        files = list(os.listdir(EMG_PLOTS_FOLDER_PATH))
        filename = f"emg_plot_{len(files)}.png"
        filepath = os.path.join(EMG_PLOTS_FOLDER_PATH,filename)
        plt.savefig(filepath, dpi=300)
        plt.close()  # Close figure to avoid overlap in loop

    def compute_meps(self, emg_df):
        """
        Compute MEP (max - min) for each EMG channel.

        Parameters
        ----------
        emg_df : pandas.DataFrame
            EMG dataframe with columns: Time, Ch1, Ch2, Ch3 (or similar)

        Returns
        -------
        meps : dict
            Dictionary mapping channel name -> MEP amplitude
            Example: {"Ch1": 0.012, "Ch2": 0.008, "Ch3": 0.015}
        emg_preac_amp : dict
            Dictionary mapping channel name -> emg_preac_amp value
            Example: {"Ch1": 0.012, "Ch2": 0.008, "Ch3": 0.015}
        emg_preac_var : dict
            Dictionary mapping channel name -> emg_preac_var value
            Example: {"Ch1": 0.012, "Ch2": 0.008, "Ch3": 0.015}
        """
        # All channels except Time
        channels = emg_df.columns[1:]

        if len(channels) == 0:
            raise ValueError("No EMG channels found in the data frame.")

        meps = {}
        emg_preac_amp = {}
        emg_preac_var = {}
        for ch in channels:
            sweep = emg_df[ch].dropna()

            if sweep.empty:
                meps[ch] = float("nan")
                emg_preac_amp[ch] = float("nan")
                emg_preac_var[ch] = float("nan")
            else:
                meps[f"{ch}"] = pynibs.expio.calc_p2p(sweep,
                                                          tms_pulse_time=self.config["TMS_PULSE_TIME"],
                                                          start_mep=self.config["START_MEP"],
                                                          end_mep=self.config["END_MEP"],
                                                          measurement_start_time=self.config["MEASUREMENT_START_TIME"],
                                                          sampling_rate=self.config["SAMPLING_RATE"],
                                                          cutoff_freq=self.config["CUTOFF_FREQ"])[0]

                # meps[ch] = float(s.max() - s.min())
                emg_preac_amp[f"{ch}_preact_p2p"], emg_preac_var[f"{ch}_preact_var"] = (
                    pynibs.expio.calc_emg_preactivation(sweep,
                        tms_pulse_time=self.config["TMS_PULSE_TIME"],
                        measurement_start_time=self.config["MEASUREMENT_START_TIME"],
                        sampling_rate=self.config["SAMPLING_RATE"],
                ))
        return meps, emg_preac_amp, emg_preac_var

    @staticmethod
    def _aim_error(realized, planned):
        """Distance (mm) between the realized and the planned coil centre."""
        try:
            return float(np.linalg.norm(np.asarray(realized[0], dtype=float)
                                        - np.asarray(planned[0], dtype=float)))
        except (TypeError, ValueError, IndexError):
            return None

    async def _read_emg(self, e_field_for_mep=None):
        """This pulse's EMG sweep, waiting briefly for the file to appear.

        The SMB read is blocking, so it runs on a worker thread.  ``None``
        means "no new file": the caller records the pulse without a MEP.
        """
        after = getattr(self, "_emg_files_before", None)
        deadline = time.monotonic() + self.emg_timeout_s
        while True:
            try:
                if isinstance(self.emg_computer, VirtualEMG):
                    data = await asyncio.to_thread(
                        self.emg_computer.get_latest_emg_df, None, e_field_for_mep)
                else:
                    data = await asyncio.to_thread(
                        self.emg_computer.get_latest_emg_df, None,
                        e_field_for_mep, after)
            except Exception as e:
                self._log_step(f"[WARN] EMG read failed: {type(e).__name__}: {e}")
                return None
            if data is not None:
                return data
            if time.monotonic() > deadline:
                return None
            await asyncio.sleep(0.25)

    def run_analysis(self, generation=None):
        """Regress every channel on the collected pulses.

        ``generation`` identifies the request: results of a superseded run
        (the operator toggled an exclusion or loaded another library while it
        was running) are discarded instead of overwriting the newer map.
        """
        print("--- Running Analysis ---")
        generation = (self._analysis_generation if generation is None
                      else generation)
        if (self.efield_mode in (None, "precomputed") and self.e_matrix is None
                and not self.pulse_e_fields):
            print("Skipping: No E-Matrix loaded yet.")
            return

        # 1. Filter for valid sequential indices
        valid_indices = np.array([
            i for i in range(len(self.used_coil_placements_idx))
            if i not in self.excluded_pulse_indices
        ])

        if len(valid_indices) < 3:
            return
        print(f"valid_indices: {valid_indices}")
        print(f"self.realized_targets['intensity']: {self.realized_targets['intensity']}")
        print(f" self.used_coil_placements_idx: {self.used_coil_placements_idx}")
        # 2. Build the regression matrix from the per-pulse E-fields.  Pulses
        # collected from the precomputed matrix and from the online solver are
        # both in V/m for the applied amplitude, so they mix without a mode
        # switch invalidating the run; pulses without a field are dropped.
        recorded = len(valid_indices)
        valid_indices, e_matrix_subset = assemble_analysis_matrix(self.pulse_e_fields, valid_indices)
        if e_matrix_subset is None or len(valid_indices) < 3:
            print(f"Skipping analysis: {len(valid_indices)} pulse(s) with an E-field (need 3).")
            return
        dropped = recorded - len(valid_indices)
        if dropped:
            # Never hide a pulse that has no field: the map is then built from
            # an undisclosed subset of the session.
            self._log_step(f"[WARN] {dropped} pulse(s) without an E-field were "
                           f"left out of the map ({len(valid_indices)} used).")
        if self.efield_mode in ("online", "surrogate"):
            print(f"online pulses: {self.pulse_modes.count('online')} / "
                  f"interpolated pulses: {self.pulse_modes.count('surrogate')} / "
                  f"precomputed pulses: {self.pulse_modes.count('precomputed')}")
        # 3. Filter the MEP history to match, per channel: a non-finite MEP
        # (empty/partial EMG sweep) would otherwise turn the whole channel's
        # R² map into NaN.
        tasks = []
        for channel_name, mep_list in self.mep_history.items():
            meps = [mep_list[i] if i < len(mep_list) else float("nan")
                    for i in valid_indices]
            finite = [pos for pos, value in enumerate(meps)
                      if value is not None and np.isfinite(value)]
            if len(finite) < 3:
                self._log_step(f"[WARN] channel {channel_name}: only {len(finite)} "
                               f"finite MEP(s) -- no map for this channel.")
                continue
            if len(finite) != len(meps):
                self._log_step(f"[WARN] channel {channel_name}: {len(meps) - len(finite)} "
                               f"MEP(s) were not measurable and are left out.")
            tasks.append((channel_name, [meps[pos] for pos in finite],
                          e_matrix_subset[finite], self.fit_fun,
                          self.elm_idx_list, self.n_elms))

        with ProcessPoolExecutor() as executor:
            futures = {executor.submit(_regress_single_channel, t): t[0] for t in tasks}

            for fut in as_completed(futures):
                channel_name = futures[fut]
                try:
                    ch_name, scores = fut.result()
                except Exception as e:
                    print(f"Analysis failed for {channel_name}: {e}")
                    continue

                if scores is None:
                    print(f"Skipping {channel_name}: Length mismatch.")
                    continue

                if generation != self._analysis_generation:
                    # A newer request superseded this run; its results win.
                    self._log_step(f"[INFO] discarding a superseded analysis "
                                   f"result for {channel_name}.")
                    continue

                # Update shared dict
                self.final_scores[ch_name] = scores

                # Push *incremental* update for this channel.  This runs on a
                # worker thread, so it is delivered through a Qt signal.
                print(f"Channel {ch_name} ready. Update mapping results.")
                self._deliver_scores({ch_name: scores})

    def _check_library_consistency(self):
        """Warn when the E-field library does not match the placements file.

        The two files are chosen independently in the Project page; mixing
        generations gives every pulse another placement's field while the map
        still looks plausible.
        """
        self.library_warning = None
        if self.e_matrix is None or not self.targets_file:
            return True
        try:
            n_placements = validate_simnibs_targets_file(self.targets_file)
        except ValueError:
            return True
        n_rows = int(self.e_matrix.shape[0])
        if n_rows != n_placements:
            self.library_warning = (
                f"E-field library: {n_rows} placements, coil placement file: "
                f"{n_placements} -- pulses would get the wrong field.")
            self._log_step(f"[WARN] {self.library_warning}")
            return False
        if self._library_mats is not None:
            placements = None
            cache = getattr(self, "_targets_cache", None)
            if cache and cache[0] == self.targets_file \
                    and cache[1] == _file_signature(self.targets_file):
                placements = cache[3]
            if placements is None:
                # The GUI loads the placements in a worker; report the
                # count-only warning now and compare matrices when they land.
                return True
            # SimNIBS writes placements as (4, 4, n); some E-field libraries
            # store the same matrices as (n, 4, 4).  Normalise before the
            # comparison, otherwise differently ordered files look identical
            # because the shapes never match.
            library = self._library_mats
            if (placements.ndim == 3 and library.ndim == 3
                    and placements.shape != library.shape):
                if placements.shape[:2] == (4, 4) and library.shape[1:] == (4, 4):
                    library = library.transpose(1, 2, 0)
                elif library.shape[:2] == (4, 4) and placements.shape[1:] == (4, 4):
                    placements = placements.transpose(1, 2, 0)
            if (placements.shape == library.shape
                    and not np.allclose(placements, library, atol=0.5)):
                self.library_warning = (
                    "The E-field library was computed for different coil "
                    "placements than the loaded placement file.")
                self._log_step(f"[WARN] {self.library_warning}")
                return False
        return True

    def _check_row_width(self, row):
        """Drop an E-field row whose element count differs from the run's."""
        if row is None:
            return None
        if self._pulse_width is None:
            self._pulse_width = int(len(row))
            return row
        if len(row) != self._pulse_width:
            self._log_step(
                f"[WARN] E-field row has {len(row)} elements but the run uses "
                f"{self._pulse_width} -- this pulse is left out of the map.")
            return None
        return row

    def _deliver_scores(self, scores):
        """Hand finished R² maps to the GUI, from any thread.

        ``run_analysis`` executes in the default executor; writing QTableWidget
        or VTK objects from there is undefined behaviour.  The window exposes a
        queued ``scores_ready`` signal; non-Qt panels (tests, headless tools)
        are called directly.
        """
        panel = self.control_panel
        if panel is None:
            return
        signal = getattr(panel, "scores_ready", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit(dict(scores))
        else:
            panel.update_mesh_coloring(scores)

    def request_analysis(self):
        """Queue a map update; older in-flight runs become stale."""
        self._analysis_generation += 1
        generation = self._analysis_generation
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (unit tests / GUI-only): run synchronously.
            self.run_analysis(generation)
            return
        import functools
        task = loop.run_in_executor(
            None, functools.partial(self.run_analysis, generation))
        # Keep only the live tasks so a long session does not accumulate them.
        self.running_analyses_tasks = [t for t in self.running_analyses_tasks
                                       if not t.done()]
        self.running_analyses_tasks.append(task)
        return task

    def _geodesic_dist_between_cells(self, mesh, cell_a, cell_b):
        """Geodesic distance between two mesh cells (triangles) using gdist."""
        nodes = mesh.points.copy().astype(np.float64)
        tris = mesh.faces.reshape(-1, 4)[:, 1:].astype(np.int32)
        source_vertices = tris[cell_a].astype(np.int32)
        nodes_dist = gdist.compute_gdist(nodes, tris, source_indices=source_vertices)
        target_vertices = tris[cell_b]
        dist = float(np.mean(nodes_dist[target_vertices]))
        return dist

    def final_adc1_geodesic_and_markers(self):
        """Compute geodesic distance and mark cells after experiment completes."""
        if "ADC 1" not in self.final_scores or not self.control_panel:
            return
        scores = self.final_scores["ADC 1"]
        mesh = self.control_panel.widget_3d_viewer.current_mesh
        if mesh is None:
            return
        best_elem = int(np.argmax(scores))
        try:
            if best_elem != 5165:
                dist = self._geodesic_dist_between_cells(mesh, 5165, best_elem)
                print(
                    f"[ADC 1] Geodesic dist true cell (5165) -> highest score cell ({best_elem}): {dist:.2f} mm | score={scores[best_elem]:.4f}")
            else:
                print(f"[ADC 1] Highest score cell IS the true cell (5165) | score={scores[best_elem]:.4f}")
        except Exception as e:
            centers = mesh.cell_centers().points
            dist = float(np.linalg.norm(centers[5165] - centers[best_elem]))
            print(f"[ADC 1] Euclidean fallback: {dist:.2f} mm | score={scores[best_elem]:.4f}")

        if best_elem != 5165:
            self.control_panel.widget_3d_viewer.mark_cells(
                cell_indices=[5165, best_elem],
                colors=['red', 'yellow'],
                labels=['True (5165)', f'Best ({best_elem})']
            )
        else:
            self.control_panel.widget_3d_viewer.mark_cells(
                cell_indices=[5165],
                colors=['red'],
                labels=['True (5165)']
            )

def _regress_single_channel(args):
    channel_name, mep_list, e_matrix_subset, fit_fun, elm_idx_list, n_elms = args
    mep_values = np.array(mep_list)

    if len(mep_values) != e_matrix_subset.shape[0]:
        return channel_name, None  # mismatch
    print(f"elm_idx_list: {elm_idx_list}")
    scores = pynibs.regression.regress_data(
            e_matrix_subset,
            mep_values,
            elm_idx_list=elm_idx_list,
            fun=fit_fun,
            refit_discontinuities=False,
            n_refit=0,
    )

    # if not all elements are fitted, we still want to return the map for all elements
    if elm_idx_list is not None:
        res_scores = np.zeros(n_elms)
        res_scores[elm_idx_list] = scores
        scores = res_scores
    return channel_name, scores
