"""Session-side manager for the interpolated (surrogate) E-field.

Mirrors :class:`OnlineFEMManager`: background initialisation, one
``compute_e_field`` call per pulse, an accumulated ``e_matrix``. The
differences:

* the estimator is :class:`EFieldSurrogate` — numpy/h5py only, no SimNIBS, so
  this mode works on machines without the FEM stack;
* the library is verified against the session's ROI before use: the
  generator (``scripts/02_create_roi_efield_library.py``) stores an
  ``roi_hash`` over the ROI centroid sequence, and this manager recomputes it
  from the ROI file the session loaded. A mismatch means the E-field columns
  would be permuted relative to the map — that is an error, not a warning;
* a coil pose outside the trained domain is **skipped and excluded**: the
  pulse is recorded as an all-NaN row (so the pulse indices stay aligned) and
  the regression drops it, exactly like a pulse without a field. There is
  deliberately no interpolation outside the domain.
"""
import os
import threading
import warnings

import h5py
import numpy as np
from scipy.spatial.transform import Rotation

from .EFieldSurrogate import EFieldSurrogate, read_roi_surface, roi_geometry_hash


class SurrogateManager:
    """Load the interpolated E-field library and serve one row per pulse."""

    def __init__(self):
        self.surrogate = None           # EFieldSurrogate once initialised
        self.ready = False
        self.initializing = False       # a background initialize() is in flight
        self.e_matrix = None            # accumulated rows (n_pulses, n_elements)
        self.library_fn = None
        self.roi_fn_hdf5 = None
        self.last_check = None          # DomainCheck of the most recent pulse
        self._outside_logged = False    # rate-limit the outside-domain warning

    # ── Path setters ──────────────────────────────────────────────

    def set_library_path(self, path: str):
        path = path or None
        if path != self.library_fn:
            # A different library invalidates the loaded estimator and the
            # accumulated rows (they belong to the old file).
            self.ready = False
            self.surrogate = None
            self.e_matrix = None
        self.library_fn = path
        if self.library_fn and not os.path.isfile(self.library_fn):
            print(f"Interpolated E-field: library not found: {self.library_fn}")

    def set_roi_fn_hdf5(self, path: str):
        path = path or None
        if path != self.roi_fn_hdf5:
            # The ROI decides the element order the library is verified
            # against; a different ROI invalidates the loaded estimator.
            self.ready = False
            self.surrogate = None
            self.e_matrix = None
        self.roi_fn_hdf5 = path

    # ── Initialization ────────────────────────────────────────────

    def initialize(self):
        """Load the library, fit the estimator, verify the ROI element order."""
        if not self.library_fn:
            raise RuntimeError("no interpolated E-field library path set")
        if not self.roi_fn_hdf5:
            raise RuntimeError(
                "no ROI file set — the interpolated library is verified "
                "against the ROI the session uses")
        self.surrogate = EFieldSurrogate.from_file(self.library_fn,
                                                   on_outside="nan")

        with h5py.File(self.library_fn, "r") as f:
            library_hash = f.attrs.get("roi_hash")
        _, _, roi_centroids = read_roi_surface(self.roi_fn_hdf5)
        if library_hash is not None:
            if library_hash != roi_geometry_hash(roi_centroids):
                raise ValueError(
                    "The interpolated E-field library was computed for a "
                    "different ROI — the field columns would not match the "
                    f"map ({self.library_fn}).")
        else:
            print("[WARN] The interpolated library has no roi_hash attribute "
                  "(older generator) — its element order could not be verified.")
        if self.surrogate.n_elements != len(roi_centroids):
            raise ValueError(
                f"The interpolated library has {self.surrogate.n_elements} "
                f"elements, the session ROI has {len(roi_centroids)}.")

        print(f"Interpolated E-field ready: {self.surrogate.n_poses} placements, "
              f"{self.surrogate.n_elements} elements, guard "
              f"{self.surrogate.max_position_distance_mm:.1f} mm / "
              f"{self.surrogate.max_rotation_distance_deg:.0f} deg.")

    def init_background(self, callback=None):
        """Run initialize() in a background thread; sets ready on success."""
        requested = self.library_fn

        def _worker():
            try:
                self.initialize()
                if self.library_fn != requested:
                    # The operator pointed at another library while this load
                    # was running; its result must not mark the manager ready.
                    return
                self.ready = True
                if callback:
                    callback()
            except Exception as e:
                print(f"Interpolated E-field initialization failed: {e}")
                self.ready = False
            finally:
                self.initializing = False

        self.ready = False
        self.initializing = True
        threading.Thread(target=_worker, daemon=True).start()

    def ensure_initialized(self, callback=None):
        """Start initialization unless ready or already starting."""
        if self.ready or self.initializing:
            if self.ready and callback is not None:
                callback()
            return
        if not (self.library_fn and self.roi_fn_hdf5):
            print("Interpolated E-field: library or ROI path missing, "
                  "initialization not started.")
            return
        self.init_background(callback)

    # ── E-field computation ───────────────────────────────────────

    def compute_e_field(self, realized_marker, stimulator_amplitude_at_stim):
        """Interpolated E_mag row (V/m) for the realised marker and amplitude.

        A pose outside the trained domain returns an all-NaN row (still
        appended, so ``e_matrix`` stays index-aligned with the pulses); the
        regression drops non-finite rows.
        """
        if self.surrogate is None:
            return None

        pos = realized_marker[0]
        ori = realized_marker[1]
        matsimnibs = np.eye(4)
        matsimnibs[:3, :3] = Rotation.from_euler("xyz", ori,
                                                 degrees=True).as_matrix()
        matsimnibs[:3, 3] = np.array(pos, dtype=float)

        with warnings.catch_warnings():
            # The estimator warns per outside pose; the manager logs it once
            # per excursion instead (see below).
            warnings.simplefilter("ignore", RuntimeWarning)
            field_unit, check = self.surrogate.compute_e_field(matsimnibs)
        self.last_check = check
        if check.inside:
            self._outside_logged = False
        elif not self._outside_logged:
            self._outside_logged = True
            print(f"[WARN] Interpolated E-field: pose outside the trained "
                  f"domain ({'; '.join(check.reasons)}) — the pulse is "
                  f"recorded without a field and left out of the map.")

        # The library is at didt = 1e6 A/s; the online solver scales by
        # amplitude [%] * 1.4 [A/us per %] * 1e6 [A/s], i.e. the same factor
        # here without the 1e6 (NaN rows stay NaN).
        row = np.asarray(field_unit, dtype=float) \
            * (stimulator_amplitude_at_stim * 1.4)
        if self.e_matrix is None:
            self.e_matrix = row.reshape(1, -1)
        else:
            self.e_matrix = np.vstack((self.e_matrix, row))
        return row

    def reset(self):
        """Reset the accumulated E-field matrix (start of a new experiment)."""
        self.e_matrix = None

    # ── Status for the GUI hint ───────────────────────────────────

    @property
    def n_placements(self) -> int:
        return self.surrogate.n_poses if self.surrogate else 0

    @property
    def n_elements(self) -> int:
        return self.surrogate.n_elements if self.surrogate else 0
