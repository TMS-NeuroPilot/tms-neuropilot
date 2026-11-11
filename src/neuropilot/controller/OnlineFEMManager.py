import os

import numpy as np
import h5py
import threading
from scipy.spatial.transform import Rotation

try:
    from simnibs.simulation.onlinefem import OnlineFEM, FemTargetPointCloud
    from simnibs.mesh_tools.mesh_io import read_msh
    SIMNIBS_AVAILABLE = True
except ImportError:
    SIMNIBS_AVAILABLE = False
    print("Cannot import OnlineFEM from SimNIBS")


class OnlineFEMManager:
    def __init__(self):
        self.online_fem = None          # True/False/None — set by GUI radio buttons
        self.ready = False
        self.e_matrix = None            # accumulated online E-field matrix (n_pulses, n_elements)

        self.coil_fn = None
        # Overridable from .env (Config tab: E-field → solver, anisotropy).
        self.anisotropy = os.getenv("ONLINE_FEM_ANISOTROPY", "scalar")
        self.anisotropy_fn = ""
        self.solver_options = os.getenv("ONLINE_FEM_SOLVER", "pardiso")

        self.computer = None            # the OnlineFEM solver instance
        self.mesh = None                # SimNIBS mesh object
        self.mesh_fn_msh = None
        self.roi_fn_hdf5 = None

    # ── Path setters ──────────────────────────────────────────────

    def set_mesh_fn_msh(self, hdf5_path: str):
        if hdf5_path:
            self.mesh_fn_msh = hdf5_path.replace('.hdf5', '.msh')
            print(f"OnlineFEM: Mesh .msh path set to {self.mesh_fn_msh}")
        else:
            self.mesh_fn_msh = None
            print("OnlineFEM: Mesh .msh path cleared.")

    def set_roi_fn_hdf5(self, path: str):
        self.roi_fn_hdf5 = path
        print(f"OnlineFEM: ROI HDF5 path set to {path}")

    def set_coil_fn(self, path: str):
        self.coil_fn = path
        print(f"OnlineFEM: Coil model path set to {path}")

    # ── Initialization ────────────────────────────────────────────

    def initialize(self):
        """Load mesh, ROI, build FemTargetPointCloud, and create OnlineFEM solver."""
        with h5py.File(self.roi_fn_hdf5, 'r') as f:
            roi_tris = f["/mesh/elm/triangle_number_list"][:]
            roi_nodes = f["/mesh/nodes/node_coord"][:]

        tri_baricenters = np.mean(roi_nodes[roi_tris], axis=1)
        self.mesh = read_msh(self.mesh_fn_msh)
        roi_onlinefem = FemTargetPointCloud(center=tri_baricenters, mesh=self.mesh)
        self.computer = OnlineFEM(
            mesh=self.mesh,
            method="TMS",
            fn_coil=self.coil_fn,
            roi=roi_onlinefem,
            anisotropy_type=self.anisotropy,
            solver_options=self.solver_options,
            fn_logger=None,
            useElements=True,
            dataType=[1],
        )

    def init_background(self, callback=None):
        """
        Run initialize() in a background thread.
        Sets self.ready = True on success.
        Calls callback() on success (e.g. to update GUI button states).
        """
        def _worker():
            try:
                self.initialize()
                self.ready = True
                print("OnlineFEM ready.")
                if callback:
                    callback()
            except Exception as e:
                print(f"OnlineFEM initialization failed: {e}")
                self.ready = False

        self.ready = False
        threading.Thread(target=_worker, daemon=True).start()

    # ── E-field computation ───────────────────────────────────────

    def compute_e_field(self, realized_marker, stimulator_amplitude_at_stim):
        """
        Compute E-field for a realized coil position and append to e_matrix.

        Parameters
        ----------
        realized_marker : list
            [pos, ori] where pos = [x, y, z] in mm, ori = [rota, rotb, rotc] in degrees (XYZ Euler).
        stimulator_amplitude_at_stim : float
            Stimulator amplitude at the moment of stimulation.

        Returns
        -------
        e_mag : np.ndarray or None
            E-field magnitude per element (n_elements,), or None if not online.
        """
        if not self.is_online or self.computer is None:
            return None

        pos = realized_marker[0]
        ori = realized_marker[1]

        #print(f"DEBUG pos = {pos} ori = {ori}")

        #pos = [x + 5 for x in pos]
        #pos[:2] = [x + 15 for x in pos[:2]]
        #ori = [x + 5 for x in ori]

        #print(f"DEBUG pos = {pos} ori = {ori}")

        # Build 4x4 matsimnibs matrix
        matsimnibs = np.eye(4)
        matsimnibs[:3, :3] = Rotation.from_euler("xyz", ori, degrees=True).as_matrix()
        matsimnibs[:3, 3] = np.array(pos, dtype=float)

        # dI/dt: amplitude (0-100%) * 1.4 (A/us per %) * 1e6 (convert to A/s)
        didt = stimulator_amplitude_at_stim * 1.4 * 1e6

        # Compute E-field
        e_raw = self.computer.update_field(matsimnibs=matsimnibs, didt=didt)[0][0]
        e_mag = np.linalg.norm(e_raw, axis=1)

        # Append to accumulated matrix
        if self.e_matrix is None:
            self.e_matrix = e_mag.reshape(1, -1)  # shape (1, n_elements)
        else:
            self.e_matrix = np.vstack((self.e_matrix, e_mag))

        return e_mag

    # ── Properties ────────────────────────────────────────────────

    @property
    def is_online(self):
        return self.online_fem is True

    @property
    def is_ready(self):
        return self.ready

    @property
    def is_offline(self):
        return self.online_fem is False

    def reset(self):
        """Reset accumulated E-field matrix (call at start of new experiment)."""
        self.e_matrix = None
