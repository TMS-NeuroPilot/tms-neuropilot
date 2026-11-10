"""
Builds the GUI from the .ui file, imports it, adds functionality, and runs the application.
"""
import os
import sys
import numpy as np
from placement_functions import read_simnibs_placements
from relay_server_functions import RelayServerRemote
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QFileDialog, QMessageBox
from pyvistaqt import QtInteractor
import pyvista as pv
import pyqtgraph as pg
import pandas as pd
from PyQt5.QtCore import Qt
import asyncio
from PyQt5.QtCore import QEvent
from qasync import QEventLoop, asyncSlot
import pathlib

# create a new .py file from the .ui file
bin_folder = os.path.split(sys.executable)[0]
pyuic5 = f"{bin_folder}/pyuic5"
assert os.path.exists(pyuic5), f"pyuic5 not found at {pyuic5}. Please check your PyQt5 installation."
scripts_folder = pathlib.Path(__file__).parent.absolute()

#/data/u_numssen_software/conda/envs/simnibs4.5beta/lib/python3.11/site-packages/qt5_applications/Qt/bin/designer
print(f"Updating gui.py from gui.ui...")
cmd = f"{pyuic5} {scripts_folder}/pipeline_control.ui > {scripts_folder}/pipeline_control.py"
print(cmd)
os.system(cmd)

from pipeline_control import Ui_MainWindow  # adjust this to match your file name
class MainApp(QMainWindow, Ui_MainWindow):
# from pipeline_control import Ui_MainWindow  # adjust this to match your file name
# class MainApp(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()

        self.setupUi(self)  # initializes widgets from the .ui file

        # --------------------------------------------------------------------------------------------------------------
        # Tab 1 - Mesh and ROI loading
        self.start_mesh_dir = "/data/pt_01756/probands/15484.08/mesh/charm_4.1_refined_M1_fs/m2m_15484.08/"
        self.pb_loadMesh.clicked.connect(self.dlg_open_mesh)
        self.pb_loadROI.clicked.connect(self.dlg_open_roi)
        self.pb_load_coil_placements.clicked.connect(self.dlg_open_coil_placements)

        # fitting settings
        self.cobo_fitfunction.currentTextChanged.connect(self.cobo_fitfunction_onchaned)
        self.chBo_binarize.toggled.connect(self.on_binarize_toggled)
        self.spbo_binary.valueChanged.connect(self.on_binary_value_changed)
        self.spbo_binary.setEnabled(self.chBo_binarize.isChecked())

        # relay server
        self.text_port.editingFinished.connect(self.set_port)
        self.text_url.editingFinished.connect(self.set_url)
        self.pb_relay_server_connect.clicked.connect(self.connect2relayserver)


        # stimulation settings
        self.chBo_randomize.toggled.connect(self.on_randomize_toggled)
        self.spbo_rando.valueChanged.connect(self.on_randomize_value_changed)
        self.spbo_rando.setEnabled(self.chBo_randomize.isChecked())
        self.spbo_isi.valueChanged.connect(self.on_isi_value_changed)
        self.spbo_ppp.valueChanged.connect(self.on_ppp_value_changed)
        self.sp_current_pulse_idx.valueChanged.connect(self.on_current_pulse_idx_changed)

        self.mesh_fn = None
        self.roi_fn = None
        self.placements_fn = None
        self.placements = None  # will be initialized in init_placements()
        self.placement_indices = None
        self.fit_function = self.cobo_fitfunction.currentText()
        self.binary_threshold = self.spbo_binary.value()  # initialize with current value
        self.seed = self.spbo_rando.value()  # initialize with current value
        self.isi = self.spbo_isi.value()
        self.pulsesperplacement = self.spbo_ppp.value()
        self.randomize_enabled = self.chBo_randomize.isChecked()
        self.curent_zap_idx = self.sp_current_pulse_idx.value()  # initialize with current value
        self.port = self.text_port.text()
        self.url = self.text_url.text()
        # --------------------------------------------------------------------------------------------------------------
        # Tab 2 - Experiment control
        self.stop = False
        self.exp_pb_start.clicked.connect(self.start_experiment)

        # default stuff
        self.placements_fn = f"{scripts_folder}/../example_data/search_positions.hdf5"
        self.init_placements()
        self.testing = True


    def dlg_open_mesh(self):
        # Open the file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select mesh .hdf5 file",        # dialog title
            self.start_mesh_dir,                     # start directory
            "HDF5 Files (*.hdf5);;All Files (*)"  # filter
        )
        if file_path:
            # show in a QLineEdit
            # self.filePathEdit.setText(file_path)
            # or: do something with the file path
            print("Selected mesh file:", file_path)
            self.mesh_fn = file_path
            self.lbl_mesh_fn.setText(f"Mesh file: {self.mesh_fn}")

    def dlg_open_roi(self):
        # Open the file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ROI .hdf5 file",        # dialog title
            self.start_mesh_dir,                     # start directory
            "HDF5 Files (*.hdf5);;All Files (*)" # filter
        )
        if file_path:
            # show in a QLineEdit
            # self.filePathEdit.setText(file_path)
            # or: do something with the file path
            print("Selected ROI file:", file_path)
            self.roi_fn = file_path
            self.lbl_roi_fn.setText(f"Mesh file: {self.roi_fn}")

    def dlg_open_coil_placements(self):
        # Open the file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select coil placements .hdf5 file",        # dialog title
            self.start_mesh_dir,                     # start directory
            "HDF5 Files (*.hdf5);;All Files (*)" # filter
        )
        if file_path:
            # show in a QLineEdit
            # self.filePathEdit.setText(file_path)
            # or: do something with the file path
            print("Selected coil placements file:", file_path)
            self.placements_fn = file_path
            self.lbl_coil_placements_fn.setText(f"Placements file: {self.placements_fn}")
            self.init_placements()

    def cobo_fitfunction_onchaned(self, text):
        # update the variable
        self.fit_function = text
        print("fit_function set to:", self.fit_function)

    def on_binarize_toggled(self, checked: bool):
        # update variable
        self.binarize_enabled = checked
        # enable/disable spinbox
        self.spbo_binary.setEnabled(checked)
        print("binarize_enabled:", self.binarize_enabled)

        # optionally: if disabling, you might reset binary_threshold
        # if not needed, omit this line
        # if not checked: self.binary_threshold = None

    def set_port(self):
        self.port = self.text_port.text()
        print("Port set to:", self.port)

    def set_url(self):
        self.url = self.text_url.text()
        print("URL set to:", self.url)

    @asyncSlot()
    async def connect2relayserver(self):
        # connect to the relay server
        url = f'http://{self.url}:{self.port}'
        try:
            self.remote.disconnect()
        except Exception as e:
            print("Error disconnecting from previous remote:", e)
        try:
            self.remote = RelayServerRemote(url)
            await self.remote.connect()
        except Exception as e:
            self.show_error("Connection Error", f"Could not connect to relay server:\n{e}")

        # register periodic checks
        asyncio.create_task(self.check_remote_connection())

    def on_binary_value_changed(self, value):
        # update variable
        self.binary_threshold = value
        print("binary_threshold:", self.binary_threshold)

    def on_randomize_toggled(self, checked: bool):
        # update variable
        self.randomize_enabled = checked
        # enable/disable spinbox
        self.spbo_rando.setEnabled(checked)
        print("randomize_enabled:", self.randomize_enabled)
        self.init_placements()
        # optionally: if disabling, you might reset binary_threshold
        # if not needed, omit this line
        # if not checked: self.binary_threshold = None

    def on_randomize_value_changed(self, value):
        # update variable
        self.seed = value
        print("seed:", self.seed)
        self.init_placements()

    def on_isi_value_changed(self, value):
        # update variable
        self.isi = value
        print("isi:", self.isi)

    def on_ppp_value_changed(self, value):
        # update variable
        self.pulsesperplacement = value
        print("pulsesperplacement:", self.pulsesperplacement)

    def closeEvent(self, event: QEvent):
        # stop the asyncio loop so the script can exit
        print("Closing window, stopping loop…")
        QApplication.quit()
        loop = asyncio.get_event_loop()
        loop.stop()
        event.accept()
        quit()

        # def closeEvent(self, event):

    def on_current_pulse_idx_changed(self, value):
        # update variable
        self.curent_zap_idx = value
        print("curent_zap_idx:", self.curent_zap_idx)

    def start_experiment(self):
        # Schedule the async coroutine
        asyncio.create_task(self.experiment_loop())

    async def experiment_loop(self, stop_after_one=False):
        while self.curent_zap_idx <= len(self.placement_indices) and not self.stop:
            if stop_after_one:
                self.stop = True
            placement = self.placements[self.placement_indices[self.curent_zap_idx]]
            # for placement in self.placements:
            # STEP 1: send to InVesalius
            await self.send_to_invesalius(placement)

            # STEP 2: wait until robot is there
            await self.wait_until_robot_ready(placement)

            # STEP 3: fire TMS
            await self.fire_tms()

            # STEP 4: read EMG
            emg_data = await self.read_emg()

            # STEP 5: compute stats
            stats = self.compute_stats(emg_data)
            print("Stats for placement:", placement, stats)

            # Update the current pulse index
            self.sp_current_pulse_idx.setValue(self.curent_zap_idx + 1)

    async def send_to_invesalius(self, placement):
        # e.g. send placement over network
        print("Sending to InVesalius:", placement)
        pos = placement[0]
        rot = placement[1]
        # render false
        topic = 'External Controller to Neuronavigation: Create Marker'
        data = {
            'position': pos.tolist(),
            'orientation': rot.tolist(),
            'label': 'SimNIBS 0',
            'marker_type': 3,
            # Because false on check is previous for some reason
            'is_target': True
        }
        print("Sending target to InVesalius!")
        asyncio.create_task(self.invesalius_remote.send_message(topic, {'data': data}))
        await asyncio.sleep(0.1)  # simulate delay

    async def wait_until_robot_ready(self, placement):
        print("Waiting for robot at:", placement)
        # poll robot status via async API or run in thread
        while not await self.robot_is_at_target(placement):
            await asyncio.sleep(0.2)  # wait and poll

    async def robot_is_at_target(self, placement):
        # check via Modbus or API
        return True  # placeholder

    async def fire_tms(self):
        print("Firing TMS")
        await asyncio.sleep(0.05)  # simulate command delay

    async def read_emg(self):
        print("Reading EMG")
        await asyncio.sleep(0.1)  # simulate acquisition
        return [1, 2, 3]  # dummy data

    def compute_stats(self, emg_data):
        # synchronous, fast
        return {"mean": sum(emg_data) / len(emg_data)}

    # helper functions
    def show_error(self, title: str, message: str):
        QMessageBox.critical(self, title, message)

    def init_placements(self):
        if self.placements_fn is None:
            return
        try:
            self.placements = read_simnibs_placements(self.placements_fn, n_positions=15)
            self.placement_indices = list(range(len(self.placements)))
            if self.randomize_enabled:
                np.random.seed(self.seed)
                np.random.shuffle(self.placement_indices)
            print(f"Loaded {len(self.placements)} placements from {self.placements_fn}")
            print("placement_indices", self.placement_indices)
        except Exception as e:
            self.show_error("File Error", f"Could not open file:\n{e}")

    async def check_remote_connection(self):
        while True:
            try:
                if self.remote.connected:
                    # e.g. update a status label
                    self.lbl_relay_is_connected.setText("Connected: yes")
                else:
                    self.lbl_relay_is_connected.setText("Connected: no")
            except Exception as e:
                self.lbl_relay_is_connected.setText(f"Connected: no")
                print(f"Error checking remote connection: {e}")
            # wait 1 second before checking again
            await asyncio.sleep(1)

if __name__ == "__main__":
    # convert .ui to py:
    # os.system("/data/u_numssen_software/conda/envs/simnibs4.5beta/bin/pyuic5 /data/u_numssen_software/git/dosing_atlas/visualization/gui.ui > /data/u_numssen_software/git/dosing_atlas/visualization/gui.py")
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainApp()
    window.show()

    with loop:
        loop.run_forever()
    sys.exit(app.exec_())
