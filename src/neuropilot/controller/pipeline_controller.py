import time
import numpy as np
import h5py
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

matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt
from enum import Enum, auto
from dotenv import load_dotenv
from .systems.emg import EMGComputer
from .systems.virtual_emg_computer2 import VirtualEMGComputer2
from .systems.stimulator import Stimulator
from .systems.virtual_stimulator import VirtualStimulator
from .systems.robot import Robot
from datetime import datetime
import pynibs
import gdist
# import multiprocessing
#try:
#    from simnibs.simulation.onlinefem import OnlineFEM, FemTargetPointCloud
#    from simnibs.mesh_tools.mesh_io import read_msh
#except ImportError:
#    print(f"Cannot import OnlineFEM from SimNIBS")
from .OnlineFEMManager import OnlineFEMManager

load_dotenv()
enable_health_check_and_control_panel = os.getenv('ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL', 'false').lower() == 'true'

root_folder = os.getenv('ROOT_FOLDER', os.getcwd())
#targets_file = f'{root_folder}/coil_placements/search_positions.hdf5'
EMG_PLOTS_FOLDER_PATH = f"{root_folder}/{os.getenv('EMG_PLOTS_FOLDER_PATH', 'emg_plots')}"
P2P_PLOTS_FOLDER_PATH = f"{root_folder}/{os.getenv('P2P_PLOTS_FOLDER_PATH', 'p2p_plots')}"
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
    def __init__(self, remote, simulation,control_panel = None):
        self.datetime_str = ""
        self.start_of_experiment = None
        self.control_panel = control_panel
        update_control_panel_func = self.control_panel.update_system_status if self.control_panel else None

        self.remote = remote

        ## Initializing systems
        self.systems = []

        self.robot = Robot(update_control_panel_func, self.remote)
        self.systems.append(self.robot)
        self.simulation = simulation
        # The Robot system speaks the relay protocol in both modes; only the
        # controller knows which one is behind it (the sim robot process).
        self.robot.DESCRIPTION = ("Simulated (virtual twin)" if simulation
                                  else "Real (via relay)")

        if not simulation:
            self.emg_computer = EMGComputer(update_control_panel_func)
            self.systems.append(self.emg_computer)
            self.stimulator = Stimulator(update_control_panel_func)
            self.systems.append(self.stimulator)
        else:
            self.emg_computer = VirtualEMGComputer2(update_control_panel_func)
            self.systems.append(self.emg_computer)
            self.stimulator = VirtualStimulator(update_control_panel_func)
            self.systems.append(self.stimulator)

        # Control Panel connection
        if self.control_panel:
            all_error_recoveries = {s : s.ERROR_RECOVERIES for s in self.systems}
            self.control_panel.initialize(all_error_recoveries)

        # Launch the systems
        self.stimulator.try_connect()
        self.emg_computer.try_connect()

        # to get the path of coil placement targets from the GUI
        self.targets_file = None
        self.target_order_fn = None
        self.target_order = None
        self.results_fn = None # TODO: Expose and sset via GUI

        # we need this attribute for log that shows current steps
        self.current_target_index = None

        # go back flag
        self._go_back= False

        # move coil up flag
        self.move_coil_up_flag = False

        #Start/pause
        self.is_paused = True
        self.is_finished = False

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
                                 'intensity':[]
                                 }

        self.e_matrix = None  # Will hold the big E-field matrix

        # -------------- Online stuff - hardcoded for now - TODO
        self.online_fem_mgr = OnlineFEMManager()
        #self.online_fem = None  # default: none has to be set from the GUI before start
        #self.onlinefem_ready = False
        #self.online_e_matrix = None
        #self.online_fem_coil_fn =None #"/data/pt_01756/coils/ccd/MagVenture_MCF_B65_2234.ccd.nii.gz" # or ccd?
        #self.online_fem_anisotropy = "scalar"
        #self.online_fem_anisotropy_fn = ""
        #self.online_fem_computer = None  # this is set by initialize_onlinefem
        #self.online_fem_solver_options = "pardiso"
        #self.online_fem_mesh = None # this is set by initialize_onlinefem
        #self.mesh_fn_hdf5 = "/data/pt_01756/probands/30298.bb/mesh/charm_beta/m2m_30298.bb/30298.bb.hdf5"
        #self.mesh_fn_msh = self.mesh_fn_hdf5.replace('.hdf5','.msh')
        #self.mesh_fn_msh = None
        #self.roi_fn_hdf5 = "/data/pt_01756/probands/30298.bb/mesh/charm_beta/roi/midlayer_m1s1pmd/geo.hdf5"
        #self.roi_fn_hdf5 = None


        # load env stuff
        self.config = {} # TODO: replace this from load project
        self.config["TMS_PULSE_TIME"] = float(os.getenv("TMS_PULSE_TIME"))/10
        self.config["START_MEP"] = int(os.getenv("START_MEP"))
        self.config["END_MEP"] = int(os.getenv("END_MEP"))
        self.config["MEASUREMENT_START_TIME"] = int(os.getenv("MEASUREMENT_START_TIME"))
        self.config["SAMPLING_RATE"] = int(os.getenv("SAMPLING_RATE"))
        self.config["CUTOFF_FREQ"] = int(os.getenv("CUTOFF_FREQ"))

        self.final_scores = {}
        self.stim_armed = False

        # Mapping settings
        self.fit_fun = pynibs.expio.fit_funs.linear
        self.map_elms = 1
        self.elm_idx_list = None
        self.n_elms = -1

    # def _init_onlinefem_background(self):
    #     try:
    #         self.initialize_onlinefem()
    #         self.onlinefem_ready = True
    #         print("OnlineFEM ready.")
    #         if self.control_panel:
    #             self.control_panel.update_button_states()
    #     except Exception as e:
    #         print(f"OnlineFEM initialization failed: {e}")
    #         self.onlinefem_ready = False
    #
    # def set_mesh_fn_msh(self, hdf5_path: str):
    #     if hdf5_path:
    #         self.mesh_fn_msh = hdf5_path.replace('.hdf5', '.msh')
    #         print(f"Controller: Mesh .msh path set to {self.mesh_fn_msh}")
    #     else:
    #         self.mesh_fn_msh = None
    #         print("Controller: Mesh .msh path cleared.")
    #
    # def set_roi_fn_hdf5(self, path: str):
    #     self.roi_fn_hdf5 = path
    #     print(f"Controller: ROI HDF5 path set to {path}")
    #
    # def set_coil_fn(self, path: str):
    #     self.online_fem_coil_fn = path
    #     print(f"Controller: Coil model path set to {path}")
    #
    # def initialize_onlinefem(self):
    #     with h5py.File(self.roi_fn_hdf5, 'r') as f:
    #         roi_tris = f["/mesh/elm/triangle_number_list"][:]
    #         roi_nodes = f["/mesh/nodes/node_coord"][:]
    #
    #     tri_baricenters = np.mean(roi_nodes[roi_tris], axis=1)
    #     self.online_fem_mesh = read_msh(self.mesh_fn_msh)
    #     roi_onlinefem = FemTargetPointCloud(center=tri_baricenters, mesh=self.online_fem_mesh)
    #     self.online_fem_computer = OnlineFEM(mesh=self.online_fem_mesh,
    #                      method="TMS",
    #                      fn_coil=self.online_fem_coil_fn,
    #                      roi=roi_onlinefem,
    #                      anisotropy_type=self.online_fem_anisotropy,
    #                      solver_options=self.online_fem_solver_options,
    #                      fn_logger=None,
    #                      useElements=True,
    #                      dataType=[1])

        # <--- NEW: Loader for the E-Matrix File --->
    def set_e_matrix_file(self, path: str):
        """Called by GUI when user loads the E-Matrix HDF5."""
        print(f"Controller: Loading E-Matrix from {path}...")

        self.e_matrix = None
        self.n_elms = None
        self.n_positions = None
        if self.control_panel is not None:
            self.control_panel.totaltargets1.setText("")

        if not path:
            print("Controller: Path cleared. E-Matrix removed from memory.")
            return

        try:
            with h5py.File(path, 'r') as f:
                # CHECK YOUR FILE KEY HERE: Is it 'e_matrix', 'E', 'magnE', or '/mesh/elm/data'?
                # specific to your data structure
                if 'E_mag' in f:
                    self.e_matrix = f['E_mag'][:]
                    print(f" -> E-Matrix loaded. Shape: {self.e_matrix.shape}")
                    self.n_elms = self.e_matrix.shape[1]
                    self.n_positions = self.e_matrix.shape[0]
                    self.set_map_elms(self.map_elms)
                    if self.control_panel is not None:
                        self.control_panel.totaltargets1.setText(f"{self.n_positions}")
                    # pass e-matrix to the virtual emg computer
                    if isinstance(self.emg_computer, VirtualEMGComputer2):
                        self.emg_computer.set_e_matrix(self.e_matrix)
                else:
                    print(f"Error: Keys found in file: {list(f.keys())}")
                    return
        except Exception as e:
            print(f"Critical Error loading E-Matrix: {e}")

    def set_map_elms(self, map_elms):
        self.map_elms = map_elms
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

    def toggle_start_pause(self):
        self.is_paused = not self.is_paused
        if not self.is_paused:
            self.move_coil_up_flag = False

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

    def toggle_free_drive(self, value):
        asyncio.create_task(self.remote.send_message('Neuronavigation to Robot: Set free drive', data={'set': value}))
        print(f"Free drive has been set to {value}")

    def set_default_speed(self, value):
        asyncio.create_task(self.remote.send_message('GUI to Robot: set default speed robot', data={'default_speed_ratio': value/100}))
        print(f"Default speed {value} has been sent to the Robot")

    def set_tuning_speed(self, value):
        asyncio.create_task(self.remote.send_message('GUI to Robot: set tuning speed robot', data={'tuning_speed_ratio': value/100}))
        print(f"Tuning speed {value} has been sent to the Robot")

    def finish_experiment(self):
        self.is_finished = True
        print("Finish pressed.")
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
        if fit_func == "Linear":
            self.fit_fun = pynibs.expio.fit_funs.linear
            print(f"Controller: Fit Function set to {fit_func}")
        elif fit_func == "Sigmoid":
            self.fit_fun = pynibs.expio.fit_funs.sigmoid4
            print(f"Controller: Fit Function set to {fit_func}")
        else:
            print(f"{fit_func} is not a valid fit function.")

    def set_minium_isi(self, value):
        self.minium_isi = value
        print(f"minium_isi set to: {value}")

    def set_n_repetitions(self,value):
        self.n_repetitions = value
        print(f"n_repetitions set to: {value}")

    def set_targets_file(self, path: str):
        print(f"Targets file set to: {path}")
        self.targets_file = path

        # Empty counters when nothing is loaded or the file cannot be read —
        # never show a bare 0.
        if self.control_panel is not None:
            self.control_panel.totaltargets2.setText("")
            self.control_panel.totaltargets3.setText("")
        if not path:
            return

        try:
            n_coil_placements = len(self.get_initial_targets()[0])
        except TypeError:
            print(f"Could not set targets_file to {path}")
            self.targets_file = None
            return

        if self.control_panel is not None:
            self.control_panel.totaltargets2.setText(f"{n_coil_placements}")
            self.control_panel.totaltargets3.setText(f"{n_coil_placements}")

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
        }
        self.remote.register_handlers(pub_to_func)

    def set_head_mesh(self, path: str):
        """Announce the project head mesh to the robot (sim: replaces the
        phantom; real robot: informational). Send path is fire-and-forget."""
        if path:
            self.remote.send_message(TOPIC_SET_HEAD_MESH, {"mesh_path": path})

    async def run(self):
        """
        Asynchronously runs the main algorithm (`run_algorithm`) and health checks (`run_health_checks`) concurrently.

        Returns
        -------
        None
        """
        # Announce the head mesh configured in the project window (session
        # cache) so a freshly started robot sim applies it immediately.
        if self.control_panel:
            fn_mesh = self.control_panel.loadmeshlabel.text().strip()
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

        target_queue, target_order = self.get_initial_targets()
        print("Coil targets are read")

        #self.control_panel.totaltargets1.setText(f"{len(target_queue)}") TODO REMOVE THIS . IT SHOULD BE UPDATED IN THE FUNCTION set_e_matrix_file()
        if self.control_panel is not None:
            self.control_panel.totaltargets2.setText(f"{len(target_queue)}")
            self.control_panel.totaltargets3.setText(f"{len(target_queue)}")

        self.start_of_experiment = datetime.now()
        self.datetime_str = f"{self.start_of_experiment.strftime('%Y%m%d_%H%M%S')}"

        while self.online_fem_mgr.is_online and not self.online_fem_mgr.is_ready:
            await asyncio.sleep(0.1)

        # for target_id, target in enumerate(target_queue):
        # for pulse_idx, target_id in enumerate(target_order):
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
                # print("Is paused")
                await asyncio.sleep(0.05)

            # If Finish was pressed while we were waiting, stop
            if self.is_finished:
                print("Experiment finished by user while waiting before target", target_id)
                break

            self.current_target_index = target_id
            # self.current_pulse_idx = pulse_idx
            current_target_text = (f"pulse {self.current_target_order_idx: >3} "
                                   f"({self.current_rep}/{self.n_repetitions}) "
                                   f"(target id: {target_id})")
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
                if self.control_panel is None or (self.control_panel and self.no_error_states()):
                    if self.current_step == Step.SEND_MARKER:
                        self.send_marker_step(target)
                    elif self.current_step == Step.START_TRACKING:
                        self.start_tracking_step(target)
                    elif self.current_step == Step.WAIT_FOR_TARGET_REACHED:
                        await self.wait_for_target_reached_step(target)
                    elif self.current_step == Step.FIRE_STIM:
                        self.fire_stim_step(target)
                    elif self.current_step == Step.COLLECT_DATA:
                        await self.collect_data_step(target)
                    elif self.current_step == Step.ANALYSE:
                        # print("Switched to analyse")
                        self.analyse_step(target)
                    elif self.current_step == Step.SKIP:
                        # print("Skip step")
                        self.switch_step(Step.COMPLETE)

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
            await asyncio.gather(*self.running_analyses_tasks)

        if self.simulation:
            self.final_adc1_geodesic_and_markers()

        # save results
        try:
            results = pd.DataFrame().from_dict(self.realized_targets)
            results_mep = pd.DataFrame().from_dict(self.mep_history)
            results_mep_amp = pd.DataFrame().from_dict(self.emg_preac_amp_history)
            results_mep_var = pd.DataFrame().from_dict(self.emg_preac_var_history)
            results = pd.concat([results.reset_index(drop=True),
                                 results_mep,
                                 results_mep_amp,
                                 results_mep_var], axis=1)
            if self.results_fn is not None:
                results.to_csv(self.results_fn, index=False)
        except Exception as e:
            print("Something wrong with results collection / saving:")
            print(e)

    def reset_algorithm(self):
        self.target_reached = False
        self.target_created = False
        self.realized_target = None

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
        # print(f"Switch_step start with {new_step}")
        if isinstance(new_step, str):
            if new_step.lower() == "skip":
                new_step = Step.COMPLETE
                asyncio.create_task(self.remote.send_message('STOP', data = {}))
                asyncio.create_task(self.remote.send_message("Press robot button", data={'pressed': False}))

            elif new_step.lower() == "previous":
                self._go_back = True
                print(f" before: self.current_pulse_idx {self.current_target_order_idx}")
                new_step = Step.COMPLETE
                asyncio.create_task(self.remote.send_message('STOP', data={}))
                asyncio.create_task(self.remote.send_message("Press robot button", data={'pressed': False}))
                if self.current_target_order_idx > 0:
                    self.current_target_order_idx -= 1
                self.current_rep = 1 # also reset repetitions
                print(f" after: self.current_pulse_idx {self.current_target_order_idx}")
        self.current_step_start_time = time.time()
        self.current_step = new_step
        # print("Current step is changed to %s" % self.current_step)

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
        hdf5_file_path = self.targets_file
        print(f"hdf5_file_path: {hdf5_file_path}")
        target_queue = []
        # Read about HDF5 files here: https://simnibs.github.io/simnibs/build/html/documentation/sim_struct/position.html
        with h5py.File(hdf5_file_path, 'r') as f:
            mats = f['matsimnibs'][:]
            for i in range(mats.shape[2]):
                # The matrices are the first two dimensions, and which matrix it is, is specified by the third dimension.
                # m is a 4x4 matrix.
                m = mats[:, :, i]
                #print("HERE IS THE TARGET MATRIX", m)

                # Transform to InVesalius coordinate convention. See Coil Axis Conventions in the Wiki
                # flip z axis
                m[:3,2] *= -1
                # exchange x and y axis
                x = m[:3,0].copy()
                m[:3,0] = m[:3,1]
                m[:3,1] = x

                # Extract pos and and angles 
                euler_angles = np.degrees(tr.euler_from_matrix(m, "sxyz"))

                pos = m[:3,3] #* 1.3    # This multiplication can be uncommented to push the target slightly outside scalp.
                target_queue.append((pos, euler_angles))

        print(f"target_order_fn: {self.target_order_fn}")
        if self.target_order_fn is not None:
            self.target_order = np.genfromtxt(self.target_order_fn).astype(int)
            # print(self.target_order)
        else:
            print(f"No target order file given. Running all coil placements.")
            self.target_order = np.array(list(range(len(target_queue)))).astype(int)

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
        asyncio.create_task(self.remote.send_message("Neuronavigation to Robot: Set objective", {'objective': 2}))

    def start_tracking_step(self, target):
        # Giving InVesalius some time to be ready
        if time.time() - self.current_step_start_time > 3.0:
            print("Tracking target with robot!")
            asyncio.create_task(self.remote.send_message("Press robot button", data = { 'pressed' : True}))

            self.switch_step(Step.WAIT_FOR_TARGET_REACHED)

    async def wait_for_target_reached_step(self, target):
        # self.target_reached is set to true by OnCoilAtTarget when InVesalius send that message.
        if self.running_analyses_tasks:
            await asyncio.gather(*self.running_analyses_tasks)
        if (self.target_reached and
                self.cobotOnTarget > self.pressure_thresh and
                (self.get_time_now() - self.time_at_stim >= self.minium_isi)):
            print("Stopping target tracking.")
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


    def get_time_now(self):
        """
        Returns the time in seconds since start of experiment.
        """
        return (datetime.now() - self.start_of_experiment).total_seconds()

    def fire_stim_step(self, target):
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
            if isinstance(self.emg_computer, VirtualEMGComputer2):
                self.emg_computer.set_current_state(
                    coil_placement_idx=self.current_target_index,
                    stimuator_amplitude =self.stimulator_amplitude,
                )


            #self.stimulator.fire()
            self.trigger_stim()

            # Create a marker in InVesalius
            topic = "Create marker"
            # data = {"stim_mark"}
            asyncio.create_task(self.remote.send_message(topic, data = {"label" : "stim_mark"}))

            self.stim_armed = False
            print("Switch to collect")
            self.switch_step(Step.COLLECT_DATA)

    async def collect_data_step(self, target):
        # Wait to collect the data until we get the call from InVesalius with the coil position at the moment of stimulation.
        # We also wait a short while to ensure the EMG Computer has printed its EMG file. This length of wait needs to be validated.
        if self.target_created and time.time() - self.current_step_start_time > 2.0:
            # self.stimulator.disarm()

            print(f"target pos, angles:\n {self.target_at_stim}")


            print(f"realized_target: {self.realized_target}")
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

            self.realized_targets['pressure'].append(self.pressure_at_stim)
            self.realized_targets['intensity'].append(self.stimulator_amplitude_at_stim)

            if self.online_fem_mgr.is_online:
                self.online_fem_mgr.compute_e_field(marker, self.stimulator_amplitude_at_stim)


            if self.online_fem_mgr.is_online and self.online_fem_mgr.e_matrix is not None:
                e_field_for_mep = self.online_fem_mgr.e_matrix[-1]  #last computed online efield
                # SMB reads are blocking network I/O; run them on a worker thread
                emg_data = await asyncio.to_thread(self.emg_computer.get_latest_emg_df, None, e_field_for_mep)
            else:
                # emg_data = self.emg_computer.get_latest_emg_df(idx=self.current_pulse_idx) # TODO: None -> latest file, for skipped targets.
                emg_data = await asyncio.to_thread(self.emg_computer.get_latest_emg_df, None, None)  # TODO: None -> latest file, for skipped targets.

            meps, emg_preac_amp, emg_preac_var = self.compute_meps(emg_data)

            # --- 1. STORE DATA in the pipeline_controller for the analysis ---
            # if meps:
            # Store the index of the coil position used
            self.used_coil_placements_idx.append(self.current_target_index)

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

            # passing data to the GUI for plotting the meps and the emg
            if self.control_panel:
                self.control_panel.on_new_emg_result(
                        target_index = self.current_target_order_idx,
                        emg_data = emg_data,
                        meps = meps,
                )
            # self.create_emg_plot(emg_data)
            # print("EMG plot printed!")

            # if self.online_fem:
            #     from scipy.spatial.transform import Rotation
            #     # compute matsimnibs
            #     #matsimnibs_realized = tr.compose_matrix(translate=marker[0], angles=marker[1])
            #     #matsimnibs_realized = tr.euler_matrix(marker[1][0], marker[1][1], marker[1][2], "sxyz")
            #
            #     matsimnibs_realized = np.eye(4)
            #     matsimnibs_realized[:3, :3] = Rotation.from_euler("xyz", marker[1], degrees=True).as_matrix()
            #     matsimnibs_realized[:3, 3] = np.array(marker[0], dtype=float)
            #     matsimnibs_realized[:3,3] = np.array(marker[0])
            #     didt_realized = self.stimulator_amplitude_at_stim * 1.4 * 1e6
            #     print(f"matsimnibs_realized: {matsimnibs_realized}")
            #
            #     matsimnibs_target = tr.compose_matrix(translate=self.target_at_stim[0], angles=self.target_at_stim[0])
            #     print(f"matsimnibs_target: {matsimnibs_target}")
            #
            #     # compute E-field
            #     e_mag = self.online_fem_computer.update_field(matsimnibs=matsimnibs_realized, didt=didt_realized)[0][0]
            #     e_mag = np.linalg.norm(e_mag, axis=1)
            #     print(f"e_mag.shape: {e_mag.shape}")
            #     # append online E-field
            #     if self.online_e_matrix is None:
            #         self.online_e_matrix = e_mag
            #     else:
            #         self.online_e_matrix = np.vstack((self.online_e_matrix, e_mag))

            # print("Data collected. Switching to Analysis...")
            # <--- CHANGE: Go to Analyse instead of Complete
            self.switch_step(Step.ANALYSE)
            results = pd.DataFrame().from_dict(self.realized_targets)
            results_mep = pd.DataFrame().from_dict(self.mep_history)
            results_mep_amp = pd.DataFrame().from_dict(self.emg_preac_amp_history)
            results_mep_var = pd.DataFrame().from_dict(self.emg_preac_var_history)
            results = pd.concat([results.reset_index(drop=True),
                                 results_mep,
                                 results_mep_amp,
                                 results_mep_var], axis=1)
            # print(results)
            if self.results_fn is not None:
                results.to_csv(self.results_fn.replace('.csv', f"{self.datetime_str}.csv"), index=False)

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
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(None, self.run_analysis)
            self.running_analyses_tasks.append(task)
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
            # loop = asyncio.get_event_loop()
            #
            # def _background():
            #     self.run_analysis()  # does the heavy work
            #     # nothing else here: we do NOT touch current_step from the worker
            #
            # loop.run_in_executor(self._analysis_executor, _background)
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(
                    None,  # default executor
                    self.run_analysis
            )
            self.running_analyses_tasks.append(task)  # optional tracking

            # task = asyncio.create_task(self.run_analysis(self.used_coil_placements_idx))
            # self.running_analyses_tasks.append(task)  # optional book-keeping

        else:
            print(f"Skipping analysis (N samples {n_samples} < 3.")

        # 2. Done. Move to Complete.
        print("Analyses started, moving to next target")
        self.switch_step(Step.COMPLETE)

    async def CobotOnTarget(self, data):
        # print(f"CobotOnTarget called, [TargetReached] is {data["force_feedback"]}")
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
        if data["state"] == True:
            self.target_reached = True

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
        print(f"GetRealizedTarget called: {data['markers']}")
        if data["markers"] is not None:
            print("GetRealizedTarget called")
            self.target_created = True
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

        # # Plot p2ps
        # sns.set(style='whitegrid')
        # p2p_array = []
        # fig, axes = plt.subplots(len(channels), 1, sharex=True, figsize=(12, 8))
        # for i, (ch, color) in enumerate(zip(channels, colors)):
        #     p2p, times, _ = pn.calc_p2p(ch)
        #     p2p_array.append(p2p)
        #     sns.lineplot(ax=axes[i], x='Time', y=ch, data=p2p_array, color=color)


        #     axes[i].set_ylim(ymin, ymax)  # Shared y-axis limits
        #     axes[i].grid(True, linestyle='--', alpha=0.5)
        #     axes[i].set_xlabel('Time' if i == len(channels) - 1 else '')
        #     axes[i].set_title(f'{ch} Signal')

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

        if len(channels) != 3:
            raise ValueError(
                    f"Expected exactly 3 EMG channels, got {len(channels)}: {channels}"
            )

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

    def run_analysis(self):
        print("--- Running Analysis ---")
        if self.e_matrix is None:
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
        # 2. Extract valid spatial targets for the E-matrix
        # actual_targets = [self.used_coil_placements_idx[i] for i in valid_indices]
        actual_targets = np.array(self.used_coil_placements_idx)[valid_indices]
        if self.online_fem_mgr.is_online:
            e_matrix_subset = self.online_fem_mgr.e_matrix[valid_indices, :].copy()
            diff = np.mean(np.abs(self.e_matrix[actual_targets[-1], :] * 75 * 1.4 - self.online_fem_mgr.e_matrix[valid_indices[-1], :]))
            print(f"diff: {diff}")

        #     e_matrix_subset = self.online_e_matrix[valid_indices,:].copy()
        #     diff = np.mean(np.abs(self.e_matrix[actual_targets[-1], :] * 75 * 1.4 - self.online_e_matrix[valid_indices[-1],:]))
        #     print(f"diff: {diff}")
        else:
            # offline e field
            e_matrix_subset = self.e_matrix[actual_targets, :].copy()

            # take realized stimulator intensity into account
            e_matrix_subset *= (np.array(self.realized_targets['intensity'])[valid_indices] * 1.4)[:,np.newaxis] # (3,)

        # 3. Filter the MEP history to match
        filtered_mep_history = {
            ch: [mep_list[i] for i in valid_indices]
            for ch, mep_list in self.mep_history.items()
        }

        # 4. Pass the filtered data to the ProcessPoolExecutor

        tasks = [
            (channel_name, filtered_mep_list, e_matrix_subset, self.fit_fun, self.elm_idx_list, self.n_elms)
            for channel_name, filtered_mep_list in filtered_mep_history.items()
        ]

        # Optionally reset or keep accumulating
        # self.final_scores = {}

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

                # Update shared dict
                self.final_scores[ch_name] = scores

                # Push *incremental* update for this channel
                if self.control_panel:
                    print(f"Channel {ch_name} ready. Updating mesh coloring.")
                    # Send only the updated channel to avoid redrawing all if you want:
                    self.control_panel.update_mesh_coloring({ch_name: scores})
                    # or send the whole accumulated dict:
                    # self.control_panel.update_mesh_coloring(self.final_scores)

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
