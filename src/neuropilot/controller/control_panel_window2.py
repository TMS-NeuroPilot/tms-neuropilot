from PyQt5 import QtWidgets, uic
import sys
import os
from .systems.system import SystemStatus
import pynibs
import time
import yaml

def resource_path(relative_path: str) -> str:
    """
    Get the absolute path to a resource.
    Works in dev and when bundled with PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):  # PyInstaller temp folder
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))  # folder of this .py file

    return os.path.join(base_path, relative_path)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, simulation):
        super().__init__()

        # ui is inside the "gui" folder
        ui_path = resource_path(os.path.join("gui", "pipeline_control2.ui"))
        uic.loadUi(ui_path, self)

        # The .ui files set label fonts in point sizes, which scale with the
        # X screen's reported DPI (high-DPI screens render ~2x and clip the
        # fixed-width labels). Pixel-based label fonts are DPI-independent.
        # Group-box titles (Stimulator / Robot / Mapping ...) otherwise inherit
        # the app default font and render larger than everything else.
        self.setStyleSheet(self.styleSheet() + "\nQLabel { font-size: 14px; }\nQGroupBox::title { font-size: 14px; }")

        # create a pipeline controller instance
        self.controller = None

        self.toggle_free_drive_set = True

        # list to store the emg data
        #self.emg_results = []
        # New History Management
        self.emg_history = []  # List of dictionaries
        self.current_history_idx = -1

        # Connect the signals from EmgNavGraphWidget
        self.widget_emg_signal.prev_clicked.connect(self.show_previous_emg)
        self.widget_emg_signal.next_clicked.connect(self.show_next_emg)
        self.widget_emg_signal.inclusion_toggled.connect(self.handle_inclusion_change)

        # for plotting
        self.history_targets = []

        # Storage (Over Time)
        #history_meps = {
        #    'ADC 0': [0.05, 0.06, 0.04, 0.08],  # A clean list of Y-values for plotting
        #    'ADC 1': [0.12, 0.11, 0.13, 0.12],
        #    'ADC 2': [0.02, 0.01, 0.02, 0.02]
        #}
        self.history_meps = {}

        # 2nd. Tap (Connections)
        # the following components are dicts
        # they will be used to mapp through them to fill the UI elements
        # Will be filled in initialize()
        self.all_error_recoveries = {}  # {system_obj: {error_msg: recovery_name}}
        self.status_labels = {}  # {system_obj: QLabel}
        self.message_labels = {}  # {system_obj: QLabel}
        self.recover_buttons = {}  # {system_obj: QPushButton}
        self.pending_recovery = {}  # {system_obj: str}  # which recovery to call next
        self.last_update_labels={} # {system_obj: QLabel}

        #1. Tab (Project)
        self.loadmeshBtn.clicked.connect(self.pick_mesh)
        self.loadmeshlabel.editingFinished.connect(self.paste_mesh_path)

        self.loadROIBtn.clicked.connect(self.pick_ROI)
        self.loadroilabel.editingFinished.connect(self.paste_roi_path)

        self.target_order_PathBtn.clicked.connect(self.pick_target_order_path)
        self.target_order_LineEdit.editingFinished.connect(self.paste_target_order_path)

        self.loadplacementsBtn.clicked.connect(self.pick_coilplacement)
        self.loadplacementlabel.editingFinished.connect(self.paste_coil_placements_path)

        self.load_e_matrixBtn.clicked.connect(self.pick_e_field)
        self.load_e_matrix_label.editingFinished.connect(self.paste_e_field_path)

        self.savePathBtn.clicked.connect(self.pick_save_path)
        self.savePathLineEdit.editingFinished.connect(self.paste_save_path)

        self.coilPathBtn.clicked.connect(self.pick_coil_path)
        self.coilspathlineedit.editingFinished.connect(self.paste_coil_path)

        self.load_yaml.clicked.connect(self.on_load_yaml)
        self.save_yaml.clicked.connect(self.on_save_yaml)


        #3rd. Tab (control)
        self.efield_mode_selected = False
        self.online_efield_btn.setEnabled(False)
        self.offline_efield_btn.setEnabled(False)

        self.online_efield_btn.toggled.connect(self.on_efield_mode_changed)
        self.offline_efield_btn.toggled.connect(self.on_efield_mode_changed)


        self.led_labels = {}  # map LED labels to systems

        # 1. Initialize Explicit Hardware Flags for Disabling and enabling the start and skip button
        self.robot_ready = False
        self.stim_ready = False
        self.emg_ready = False

        # 2. Disable execution buttons by default on startup
        self.start_btn.setEnabled(False)
        self.skiptarget.setEnabled(False)
        self.back_btn.setEnabled(False)
        self.enableBtn.setEnabled(False)
        self.fireBtn.setEnabled(False)

        self.skiptarget.clicked.connect(self.on_skip_step_clicked)
        self.back_btn.clicked.connect(self.on_back_clicked)
        self.start_btn.clicked.connect(self.on_start_pause_clicked)
        self.finish_btn.clicked.connect(self.on_finish_clicked)
        self.move_coil_up.clicked.connect(self.on_move_coil_up)
        self.freedrive.clicked.connect(self.toggle_free_drive_func)
        self.enableBtn.clicked.connect(self.on_enable_clicked)
        self.fireBtn.clicked.connect(self.on_fire_stim_clicked)

        self.slider.valueChanged.connect(self.slider1_spinbox1)
        self.spinBox.valueChanged.connect(self.slider1_spinbox1)

        self.slider2.valueChanged.connect(self.slider2_spinbox2)
        self.spinBox2.valueChanged.connect(self.slider2_spinbox2)

        self.slider3.valueChanged.connect(self.slider3_spinbox3)
        self.spinBox3.valueChanged.connect(self.slider3_spinbox3)

        self.sampling_spinBox.valueChanged.connect(self.on_subsampling_changed)
        self.n_repetitions_spinBox.valueChanged.connect(self.on_n_repetitions_changed)
        self.min_interval_spinBox.valueChanged.connect(self.on_min_interval_changed)

        self.pulseShapeComboBox.currentTextChanged.connect(self.on_pulse_shape_changed)
        self.fitFunctionComboBox.currentTextChanged.connect(self.on_fit_function_changed)


        #4th Tab
        # --- set the title for each widget ---
        if hasattr(self, 'widget_mep_trend'):
            self.widget_mep_trend.set_title("MEPs")

        if hasattr(self, 'widget_emg_signal'):
            self.widget_emg_signal.set_title("Last EMG")
            self.refresh_emg_nav_display()

    def on_efield_mode_changed(self):
        if not (self.online_efield_btn.isChecked() or self.offline_efield_btn.isChecked()):
            return
        if self.controller:
            self.controller.online_fem_mgr.online_fem = self.online_efield_btn.isChecked()
            if self.controller.online_fem_mgr.is_online:
                import threading
                # self.controller.online_fem_mgr.ready = False #redundent
                #threading.Thread(target=self.controller.online_fem_mgr.init_background, daemon=True).start()
                self.controller.online_fem_mgr.init_background(callback=self.update_button_states)

        #self.online_efield_btn.setEnabled(False)
        #self.offline_efield_btn.setEnabled(False)
        if self.online_efield_btn.isChecked():
            self.offline_efield_btn.setEnabled(False)  # grey out the other
        else:
            self.online_efield_btn.setEnabled(False)  # grey out the other
        self.efield_mode_selected = True
        self.update_button_states()

    def _check_paths_ready(self):
        all_set = (
                self.controller
                and self.controller.online_fem_mgr.mesh_fn_msh
                and self.controller.online_fem_mgr.roi_fn_hdf5
                and self.controller.online_fem_mgr.coil_fn
        )
        if not self.efield_mode_selected:
            self.online_efield_btn.setEnabled(bool(all_set))
            self.offline_efield_btn.setEnabled(bool(all_set))

    def update_button_states(self):
        if not self.efield_mode_selected:
            self.start_btn.setEnabled(False)
            self.skiptarget.setEnabled(False)
            self.back_btn.setEnabled(False)
            return

        fem_ok = True
        if self.controller and self.controller.online_fem_mgr.is_online:
            fem_ok = self.controller.online_fem_mgr.is_ready

        if self.robot_ready and self.stim_ready and self.emg_ready and fem_ok:
            self.start_btn.setEnabled(True)
            self.skiptarget.setEnabled(True)
            self.back_btn.setEnabled(True)
        else:
            self.start_btn.setEnabled(False)
            self.skiptarget.setEnabled(False)
            self.back_btn.setEnabled(False)

    def update_mesh_coloring(self, scores_dict):
        """
        Called by Controller.
        scores_dict: {'ADC 0': array, 'ADC 1': array, ...}
        """
        if hasattr(self, 'widget_3d_viewer'):
            self.widget_3d_viewer.apply_scores(scores_dict)

    # set the status of self.robot_led, self.stim_led, self.emg_led
    def set_led_status(self, led_widget, status_val: str, color_val: str):
        """Architectural helper to safely update LED states and force CSS re-evaluation."""
        if led_widget is None:
            return

        # 1. Update the dynamic properties
        led_widget.setProperty("status", status_val)
        led_widget.setProperty("color", color_val)

        # 2. Force the Qt Style Engine to re-evaluate the CSS
        led_widget.style().unpolish(led_widget)
        led_widget.style().polish(led_widget)
        led_widget.update()


    def on_new_emg_result(self, target_index, emg_data, meps):
        """
        target_index: int
        emg_data: DataFrame with 's', 'ADC 0', 'ADC 1', 'ADC 2'
        meps: Dict {'ADC 0': 0.05, ...}
        """
        # 1. Update History (For the Trend Plot)
        self.history_targets.append(target_index)
        for ch, val in meps.items():
            # 1. If we haven't seen "ADC 0" before, create a new list for it
            if ch not in self.history_meps:
                self.history_meps[ch] = []
            # 2. Add the new value to the end of that specific channel's list
            self.history_meps[ch].append(float(val))

        # 2. Update Widget 1: MEP Trend
        # "widget_mep_trend" is the objectName you set in Qt Designer
        if self.controller:
            exclusion = self.controller.excluded_pulse_indices
        else:
            exclusion = None

        if hasattr(self, 'widget_mep_trend'):
            self.widget_mep_trend.update_as_trend(
                    target_indices=self.history_targets,
                    history_dict=self.history_meps,
                    exclusion=exclusion
            )

        order = 6
        # 3. Update Widget 2: Raw Signal
        # "widget_emg_signal" is the objectName you set in Qt Designer
        if hasattr(self, 'widget_emg_signal'):
            time_vals = emg_data["Time"]
            #print(f"time vals len/max: {len(time_vals)} / {max(time_vals)}")
            # Filter columns to only get ADC channels

            signal_dict = {col: pynibs.expio.butter_lowpass_filter(emg_data[col],
                                                                   int(os.getenv("CUTOFF_FREQ")),
                                                                   int(os.getenv("SAMPLING_RATE")),
                                                                   order) for col in emg_data.columns if "ADC" in col}

            # Create A dictionary for each received emg
            new_record = {
                "target_index": target_index,
                "time_array": time_vals,
                "data_dict": signal_dict,
                "meps": meps,
                "included": True
            }
            # Append to history and update index to the latest
            self.emg_history.append(new_record)
            self.current_history_idx = len(self.emg_history) - 1

            # Update the UI to show this latest pulse
            self.refresh_emg_nav_display()

            self.widget_emg_signal.update_as_signal(
                    time_array=time_vals,
                    data_dict=signal_dict
            )

    def refresh_emg_nav_display(self):
        if not self.emg_history or self.current_history_idx == -1:
            self.widget_emg_signal.btn_prev.setEnabled(False)
            self.widget_emg_signal.btn_next.setEnabled(False)
            self.widget_emg_signal.chk_include.setChecked(False)
            self.widget_emg_signal.chk_include.setEnabled(False)
            return

        # Get the record at the current index
        record = self.emg_history[self.current_history_idx]

        # Update the graph visually
        self.widget_emg_signal.update_as_signal(record["time_array"], record["data_dict"])

        # Update labels
        self.widget_emg_signal.set_title(f"{record['target_index']+1}. EMG")

        # Logic for buttons: Disable 'Prev' if at start, 'Next' if at end
        self.widget_emg_signal.btn_prev.setEnabled(self.current_history_idx > 0)
        self.widget_emg_signal.btn_next.setEnabled(self.current_history_idx < len(self.emg_history) - 1)

        # Update checkbox without triggering its signal
        self.widget_emg_signal.chk_include.blockSignals(True)
        self.widget_emg_signal.chk_include.setEnabled(True)
        self.widget_emg_signal.chk_include.setChecked(record["included"])
        self.widget_emg_signal.chk_include.blockSignals(False)

    def show_previous_emg(self):
        if self.current_history_idx > 0:
            self.current_history_idx -= 1
            self.refresh_emg_nav_display()

    def show_next_emg(self):
        if self.current_history_idx < len(self.emg_history) - 1:
            self.current_history_idx += 1
            self.refresh_emg_nav_display()

    def handle_inclusion_change(self, is_included):
        if self.current_history_idx == -1:
            return

        record = self.emg_history[self.current_history_idx]
        record["included"] = is_included

        # Tell the controller to update the map
        if self.controller:
            self.controller.set_pulse_inclusion(record['target_index'], is_included)
        if hasattr(self, 'widget_mep_trend'):
            self.widget_mep_trend.update_as_trend(
                    target_indices=self.history_targets,
                    history_dict=self.history_meps,
                    exclusion=self.controller.excluded_pulse_indices
            )


    def toggle_free_drive_func(self):
        if self.controller:
            if self.toggle_free_drive_set:
                print("test_func")
                self.controller.toggle_free_drive(self.toggle_free_drive_set)
                self.freedrive.setText("Disable free Drive")
                self.toggle_free_drive_set = not self.toggle_free_drive_set

            elif not self.toggle_free_drive_set:
                print("test_func")
                self.controller.toggle_free_drive(self.toggle_free_drive_set)
                self.freedrive.setText("Enable free Drive")
                self.toggle_free_drive_set = not self.toggle_free_drive_set

    def on_pulse_shape_changed(self, shape_text: str):
        """
        Triggered when the user selects a new pulse shape from the dropdown.
        """
        print(f"UI: Pulse shape selected -> {shape_text}")
        if self.controller:
            try:
                self.controller.set_waveform(shape_text)
            except ValueError:
                print("Couldn't set waveform.")
                if shape_text == "Biphasic":
                    self.pulseShapeComboBox.setCurrentIndex(1)
                elif shape_text == "Monophasic":
                    self.pulseShapeComboBox.setCurrentIndex(0)


    def on_fit_function_changed(self, fit_func: str):
        """
        Triggered when the user selects a new Fit Function from the dropdown.
        """
        print(f"UI: Fit Function shape selected -> {fit_func}")
        if self.controller:
            self.controller.set_fit_function(fit_func)

    def initialize(self, all_error_recoveries):
        self.all_error_recoveries = all_error_recoveries

        # Wire each system to its labels & Recover button in the .ui
        for system, err_map in all_error_recoveries.items():
            name = getattr(system, "NAME", "").lower()

            if "robot" in name:
                self._bind_system(
                        system=system,
                        status_label=getattr(self, "robotStatusLabel", None),
                        message_label=getattr(self, "robotMessageLabel", None),
                        recover_button=getattr(self, "robotRecoverButton", None),
                        last_update_label=getattr(self, "robotLastUpdateLabel", None),
                        led_label=getattr(self, "led_robot", None) # the status of the led in the connection tap
                )

            elif "stimulator" in name:  # stimulator
                self._bind_system(
                        system=system,
                        status_label=getattr(self, "stimStatusLabel", None),
                        message_label=getattr(self, "stimMessageLabel", None),
                        recover_button=getattr(self, "stimRecoverButton", None),
                        last_update_label=getattr(self, "stimLastUpdateLabel", None),
                        led_label=getattr(self, "led_stim", None)  # the status of the led in the connection tap
                )

            elif "emg computer" in name:
                self._bind_system(
                        system=system,
                        status_label=getattr(self, "emgStatusLabel", None),
                        message_label=getattr(self, "emgMessageLabel", None),
                        recover_button=getattr(self, "emgRecoverButton", None),
                        last_update_label=getattr(self, "emgLastUpdateLabel", None),
                        led_label=getattr(self, "led_emg", None)  # the status of the led in the connection tap
                )

        # Initialize display
        for sys_obj, lbl in self.status_labels.items():
            if lbl is not None:
                lbl.setText("Not Initialized")
            #   lbl.setStyleSheet("color: #595959")
        for sys_obj, lbl in self.message_labels.items():
            if lbl is not None:
                lbl.setText("")

    def _bind_system(self, system, status_label, message_label, recover_button, last_update_label=None,led_label=None):
        """Connects one system to its status/message labels and its Recover button."""
        if status_label is None:
            print(f"[WARN] No status label for system {getattr(system, 'NAME', '?')}")
            return

        self.status_labels[system] = status_label
        self.message_labels[system] = message_label
        if last_update_label is not None:
            self.last_update_labels[system] = last_update_label
        self.led_labels[system] = led_label

        if recover_button is not None:
            self.recover_buttons[system] = recover_button
            recover_button.setEnabled(False)
            # capture system object in default arg
            recover_button.clicked.connect(lambda _, s=system: self.on_recover_clicked(s))

    def update_system_status(self, system=None, status=None, message=None):
        if system is None:
            return

        status_label = self.status_labels.get(system)
        message_label = self.message_labels.get(system)
        recover_button = self.recover_buttons.get(system)
        led_widget = self.led_labels.get(system)

        if status_label is None:
            # No UI mapped for this system (shouldn't happen if everything wired)
            return

        # By default: disable Recover
        if recover_button is not None:
            recover_button.setEnabled(False)
            self.pending_recovery[system] = None

        if status == SystemStatus.OK:
            status_label.setStyleSheet("color: #0D9E42")
            status_label.setText("OK")
            self.set_led_status(led_widget, "on", "green")
            if message_label:
                message_label.setText("")

        elif status == SystemStatus.ERROR:
            status_label.setStyleSheet("color: #B50E0E")
            status_label.setText("ERROR")
            self.set_led_status(led_widget, "on", "red")

            msg_text = message

            # Use ERROR_RECOVERIES to see if there is a defined recovery
            err_map = self.all_error_recoveries.get(system, {})
            if message in err_map:
                recovery_name = err_map[message]
                self.pending_recovery[system] = recovery_name
                if recover_button is not None and recovery_name is not None:
                    # change button text to recovery_name
                    recover_button.setText(recovery_name)
                    recover_button.setEnabled(True)
                else:
                    msg_text += "\nNo Recovery Implemented"

            else:
                msg_text += "\nNo Recovery Implemented"

            if message_label:
                message_label.setText(msg_text)

        elif status == SystemStatus.NAN:
            status_label.setStyleSheet("color: #595959")
            status_label.setText("Status: Not Initialized")
            self.set_led_status(led_widget, "off", "")
            if message_label:
                message_label.setText("")

        # add a "last update" label in the UI and set it here

        last_lbl = self.last_update_labels.get(system)
        if last_lbl is not None:
            last_lbl.setText(time.strftime("%H:%M:%S", time.localtime(time.time())))

        # 1. Identify which system is updating and set its specific flag
        name = getattr(system, "NAME", "").lower()
        is_system_ok = (status == SystemStatus.OK)

        if "robot" in name:
            self.robot_ready = is_system_ok
        elif "stimulator" in name:
            self.stim_ready = is_system_ok
        elif "emg computer" in name:
            self.emg_ready = is_system_ok

        # 2. Evaluate if ALL three systems are True (The AND Gate)
        self.update_button_states()

        if self.stim_ready:
            self.enableBtn.setEnabled(True)
            self.fireBtn.setEnabled(True)
        else:
            self.enableBtn.setEnabled(False)
            self.fireBtn.setEnabled(False)

    def on_recover_clicked(self, system):
        """Called when user clicks the Recover button for a system."""
        recovery_name = self.pending_recovery.get(system)
        if recovery_name:
            print(f"Recovering {getattr(system, 'NAME', '?')} with {recovery_name}")
            system.recover(recovery_name)
        else:
            print("No recovery action stored for this system.")

    def set_controller(self, controller):
        self.controller = controller
        if self.controller:
            self.slider1_spinbox1(20)

    # functions for the elements in the second Tap
    # === BEGIN: Handlers for loading the Mesh ===
    def pick_mesh(self):
        """Opens file dialog and loads mesh into the 3D widget."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select Mesh File",
                os.getcwd(),
                "HDF5 Files (*.hdf5 *.h5);;VTK Files (*.vtk)"
        )
        if file_path:
            # just show path in QLineEdit
            self.loadmeshlabel.setText(file_path)
            print(f"Loading mesh: {file_path}")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(file_path)
            self._check_paths_ready()

    def paste_mesh_path(self):
        file_path = self.loadmeshlabel.text().strip()
        if not file_path:
            print("No file path given.")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(None)
            self._check_paths_ready()

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            print(f"Loading mesh: {file_path}")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(file_path)
            self._check_paths_ready()
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadmeshlabel.setText("")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(None)
            self._check_paths_ready()

    # === END: Handlers for loading the Mesh ===

    # === BEGIN: Handlers for loading the coil path ===
    def pick_coil_path(self):
        """Opens file dialog for TMS coil model (.ccd) file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Coil Model File",
            os.getcwd(),
            "CCD Files (*.ccd *.ccd.nii.gz)"
        )
        if file_path:
            self.coilspathlineedit.setText(file_path)
            print(f"GUI: Coil model set: {file_path}")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(file_path)
            self._check_paths_ready()

    def paste_coil_path(self):
        file_path = self.coilspathlineedit.text().strip()
        if not file_path:
            print("GUI: No coil path given.")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(None)
            self._check_paths_ready()
        elif os.path.isfile(file_path):
            print(f"GUI: Coil model set: {file_path}")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(file_path)
            self._check_paths_ready()
        else:
            print(f"GUI: Wrong path: The file '{file_path}' does not exist.")
            self.coilspathlineedit.setText("")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(None)
            self._check_paths_ready()

    # === END: Handlers for loading the coil path ===


    # === BEGIN: Handlers for loading the ROI ===
    def pick_ROI(self):
        """Opens file dialog and loads HDF5 mesh."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select Mesh File",
                os.getcwd(),
                "HDF5 Files (*.hdf5 *.h5);;VTK Files (*.vtk)"
        )
        if file_path:
            # just show path in QLineEdit
            self.loadroilabel.setText(file_path)
            print(f"Loading ROI: {file_path}")
            if hasattr(self, 'widget_3d_viewer'):
                # Call the new HDF5 loader
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(file_path)
            self._check_paths_ready()

    def paste_roi_path(self):
        file_path = self.loadroilabel.text().strip()
        if not file_path:
            print("No file path given.")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(None)
            self._check_paths_ready()

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            print(f"Loading ROI: {file_path}")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(file_path)
            self._check_paths_ready()
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadroilabel.setText("")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(None)
            self._check_paths_ready()

    # === END: Handlers for loading the ROI ===

    # === BEGIN: Handlers for loading the Target Path  ===
    def pick_target_order_path(self):
        """Opens file dialog and loads Target Order txt file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select Target Order File",
                os.getcwd(),
                "Text Files (*.txt)"
        )
        if file_path:
            # just show path in QLineEdit
            self.target_order_LineEdit.setText(file_path)
            if self.controller:
                self.controller.set_target_order_fn(file_path)

    def paste_target_order_path(self):
        file_path = self.target_order_LineEdit.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_target_order_fn(None) # passing None instead of empty string because this line (if self.target_order_fn is not None:) in the pipeline controller

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            if self.controller:
                self.controller.set_target_order_fn(file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.target_order_LineEdit.setText("")
            # Optional: UI popup here to warn the user visually
    # === END: Handlers for loading the Target Path  ===

    # === BEGIN: Handlers for loading the coil placements  ===
    def pick_coilplacement(self):
        file_path_coil_placement, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select a file",
                os.getcwd(),
                "HDF5 Files (*.hdf5)"
        )
        if file_path_coil_placement:
            # just show path in QLineEdit
            self.loadplacementlabel.setText(file_path_coil_placement)
            if self.controller:
                self.controller.set_targets_file(file_path_coil_placement)

    def paste_coil_placements_path(self):
        file_path = self.loadplacementlabel.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_targets_file(None)

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            if self.controller:
                self.controller.set_targets_file(file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadplacementlabel.setText("")
            # Optional: UI popup here to warn the user visually
    # === END: Handlers for loading the coil placements ===

    # === BEGIN: Handlers for loading the E-Field ===
    def pick_e_field(self):
        """Opens file dialog and loads HDF5 E Field."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select Mesh File",
                os.getcwd(),
                "HDF5 Files (*.hdf5)"
        )
        if file_path:
            # just show path in QLineEdit
            self.load_e_matrix_label.setText(file_path)
            print(f"Loading E Field: {file_path}")
            if self.controller:
                self.controller.set_e_matrix_file(file_path)

    def paste_e_field_path(self):
        file_path = self.load_e_matrix_label.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_e_matrix_file(file_path)

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            if self.controller:
                print(f"Loading E Field: {file_path}")
                self.controller.set_e_matrix_file(file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.load_e_matrix_label.setText("")
            # Optional: UI popup here to warn the user visually
    # === END: Handlers for loading the E-Field ===

    # === BEGIN: Handlers for loading the saving path ===
    def pick_save_path(self):
        # 1. Look at the target order text box to see where they loaded from
        target_path = self.target_order_LineEdit.text().strip()

        # 2. Default to current working directory just in case the box is empty
        start_folder = os.getcwd()

        # 3. If there is a target path, extract ONLY the folder part
        if target_path:
            extracted_folder = os.path.dirname(target_path)
            # Verify the folder actually exists before telling the dialog to open it
            if os.path.isdir(extracted_folder):
                start_folder = extracted_folder

        # 4. Open the Save dialog explicitly in that 'start_folder'
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Select Save Location",
                start_folder,  # <--- This tells the window exactly where to open!
                "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            if not file_path.lower().endswith('.csv'):
                file_path= file_path + ".csv"
            self.savePathLineEdit.setText(file_path)
            #notify the controller immediately
            if self.controller:
                self.controller.set_results_filename(file_path)

    def paste_save_path(self):
        file_path = self.savePathLineEdit.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_results_filename(None)
            return

        if not file_path.lower().endswith('.csv'):
            file_path += '.csv'
            self.savePathLineEdit.setText(file_path)  # Update UI to show the fix

        # 2. Extract just the folder path
        folder_path = os.path.dirname(file_path)

        # 3. Create the folder(s) if they do not exist
        if folder_path:  # Ensures it's not empty
            try:
                os.makedirs(folder_path, exist_ok=True)
                print(f"Verified or created directory: {folder_path}")
            except OSError as e:
                print(f"Error: Could not create directory. {e}")
                return

        if self.controller:
            print(f"the Path for saving the results has been set: {file_path}")
            self.controller.set_results_filename(file_path)
    # === END: Handlers for loading the saving path ===

    # ===
    def on_load_yaml(self):
        """Opens file dialog and loads YAML file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Load Config",
                "",
                # os.getcwd(),
                "YAML Files (*.yaml *.yml)"
        )
        if file_path:
            try:
                with open(file_path, "r") as f:
                    data = yaml.safe_load(f)
            except (OSError, yaml.YAMLError) as e:
                QtWidgets.QMessageBox.warning(
                    self, "Invalid YAML",
                    f"Could not load config file:\n{e}"
                )
                return
            self.apply_config_dict(data)

    def on_save_yaml(self):
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Select Save Location",
                os.getcwd(),
                "YAML Files (*.yaml *.yml)"
        )
        if file_path:
            # 1. Ensure the file has the correct extension
            if not file_path.lower().endswith(('.yaml', '.yml')):
                file_path += '.yaml'

            # 2. Get the state and save
            data = self.get_config_dict()
            with open(file_path, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            print(f"Configuration successfully saved to: {file_path}")


    def on_skip_step_clicked(self):
        if self.controller:
            print("Skip Step")
            self.controller.switch_step("skip")

    def on_back_clicked(self):
        if self.controller:
            print("Previous Step")
            self.controller.switch_step("previous")

    def on_start_pause_clicked(self):
        if self.controller:

            self.controller.toggle_start_pause()

            if self.controller.is_paused:
                self.start_btn.setText("Start")
            else:
                self.start_btn.setText("Pause")

    def on_enable_clicked(self):
        if self.controller:
            self.controller.enable_stimulator()

    def on_fire_stim_clicked(self):
        if self.controller:
            self.controller.trigger_stim()

    def on_finish_clicked(self):
        if self.controller:
            self.controller.finish_experiment()

    def on_move_coil_up(self):
        if self.controller:
            self.controller.set_stopped_true()
            self.controller.set_pause_true()
            self.controller.move_robot_away_from_head()
            self.start_btn.setText("Start")

    def slider1_spinbox1(self,value):
        print(f"Slider1 and spinbox1 value changed to {value}")
        self.slider.blockSignals(True)
        self.spinBox.blockSignals(True)

        self.slider.setValue(value)
        self.spinBox.setValue(value)

        self.slider.blockSignals(False)
        self.spinBox.blockSignals(False)

        if self.controller:
            self.controller.set_amplitude_stim(value)

    def slider2_spinbox2(self,value):
        print(f"Slider2 and spinbox2 value changed to {value}")
        self.slider2.blockSignals(True)
        self.spinBox2.blockSignals(True)

        self.slider2.setValue(value)
        self.spinBox2.setValue(value)

        self.slider2.blockSignals(False)
        self.spinBox2.blockSignals(False)
        if self.controller:
            self.controller.set_default_speed(value)

    def slider3_spinbox3(self,value):
        print(f"Slider3 and spinbox3 value changed to {value}")
        self.slider3.blockSignals(True)
        self.spinBox3.blockSignals(True)

        self.slider3.setValue(value)
        self.spinBox3.setValue(value)

        self.slider3.blockSignals(False)
        self.spinBox3.blockSignals(False)
        if self.controller:
            self.controller.set_tuning_speed(value)

    def on_subsampling_changed(self,value):
        if self.controller:
            self.controller.set_map_elms(value)
            print(f"Subsampling set to {value}")

    def on_n_repetitions_changed(self, value):
        if self.controller:
            self.controller.set_n_repetitions(value)

    def on_min_interval_changed(self,value):
        if self.controller:
            self.controller.set_minium_isi(value)

    ##################################################
    def get_config_dict(self):
        """Return controller and GUI parameters as a plain dict."""
        return {
            "fit_fun": self.fitFunctionComboBox.currentText(),
            "map_elms": self.sampling_spinBox.value(),
            "results_fn": self.savePathLineEdit.text() or None,
            "stimulator_amplitude": self.spinBox.value(),
            "target_order_fn": self.target_order_LineEdit.text() or None,
            "stimulator_waveform": self.pulseShapeComboBox.currentText(),
            "minium_isi": self.min_interval_spinBox.value(),
            "n_repetitions": self.n_repetitions_spinBox.value(),
            "targets_file": self.loadplacementlabel.text() or None,
            "default_speed": self.spinBox2.value(),
            "tuning_speed": self.spinBox3.value(),
            "mesh_head_path": self.loadmeshlabel.text() or None,
            "mesh_RIO_path": self.loadroilabel.text() or None,
            "e_field_path": self.load_e_matrix_label.text() or None,
            "coil_path": self.coilspathlineedit.text() or None,

        }

    def apply_config_dict(self, d):
        """Apply only the keys present in d to controller state and UI."""
        setters = {
            # ComboBoxes use setCurrentText
            "fit_fun": self.fitFunctionComboBox.setCurrentText,
            "stimulator_waveform": self.pulseShapeComboBox.setCurrentText,

            # SpinBoxes use setValue
            "map_elms": self.sampling_spinBox.setValue,
            "stimulator_amplitude": self.spinBox.setValue,
            "minium_isi": self.min_interval_spinBox.setValue,
            "n_repetitions": self.n_repetitions_spinBox.setValue,
            "default_speed": self.spinBox2.setValue,
            "tuning_speed": self.spinBox3.setValue,

            # LineEdits use setText, but we wrap them in lambdas for two reasons:
            # 1. To prevent crashes if 'v' is None (using 'v or ""')
            # 2. To trigger manual backend functions since LineEdits don't have automatic valueChanged signals here
            "results_fn": lambda v: (self.savePathLineEdit.setText(v or ""),self.paste_save_path()),
            "target_order_fn": lambda v: (self.target_order_LineEdit.setText(v or ""),self.paste_target_order_path()),
            "targets_file": lambda v: (self.loadplacementlabel.setText(v or ""), self.paste_coil_placements_path()),
            "mesh_head_path": lambda v: (self.loadmeshlabel.setText(v or ""),self.paste_mesh_path()),
            "mesh_RIO_path": lambda v: (self.loadroilabel.setText(v or ""),self.paste_roi_path()),
            "e_field_path": lambda v: (self.load_e_matrix_label.setText(v or ""),self.paste_e_field_path()),
            "coil_path": lambda v: (self.coilspathlineedit.setText(v or ""), self.paste_coil_path()),
        }

        # Iterate through the config and apply the values using the matched setter function
        for key, setter in setters.items():
            if key in d:
                val = d[key]
                # For SpinBoxes, we must ensure we don't pass a None value
                if val is None and key not in ["results_fn", "target_order_fn", "targets_file", "mesh_head_path",
                                               "mesh_RIO_path", "e_field_path",  "coil_path"]:
                    continue

                    # Execute the matched function
                setter(val)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
