"""Precomputed per-element E-field surrogate with an explicit validity domain.

The library is the ``e.hdf5`` written by
``scripts/02_create_roi_efield_library.py``: ``E_mag`` with shape
``(n_poses, n_elements)`` at ``didt = 1e6 A/s``, and ``matsimnibs`` with shape
``(n_poses, 4, 4)``.

The estimator compresses the fields with PCA (default 20 components) and
interpolates the coefficients over the coil pose: inverse-distance weighting
over nearby scalp positions, and over nearby coil rotations at each position.
The interpolation approach follows Grosshagauer et al. (2025), "Reducing
target E-field variability in repetitive TMS through online motion
compensation", Brain Stimulation, doi:10.1016/j.brs.2025.102990 — code by
Michael Woletz and Sarah Grosshagauer in
https://github.com/fMRIat/EfieldInterpolation. This implementation is
independent of that GPLv3 repository and does not import it.

Every query is checked against the sampled domain *before* interpolation.
``max_position_distance_mm`` and ``max_rotation_distance_deg`` default to the
median nearest-neighbour gaps of the library. ``on_outside`` selects the
policy when a pose is outside:

* ``"warn"``  -- emit a ``RuntimeWarning`` and return the interpolated field
* ``"nan"``   -- emit a warning and return an all-NaN field (drop the pulse)
* ``"raise"`` -- raise :class:`OutsideDomainError`

The returned field is per unit dI/dt (the library was generated at 1e6 A/s):
multiply by ``didt / 1e6`` -- or by ``amplitude_percent * 1.4`` -- for V/m.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import warnings

import numpy as np


class OutsideDomainError(RuntimeError):
    """Raised when a coil pose lies outside the surrogate's sampled domain."""


def read_roi_surface(path, roi_idx=None):
    """Read an ROI surface from either supported HDF5 layout.

    Returns ``(points, triangles, centroids)`` with 0-based triangles:

    * the m2m layout written by pynibs (``roi_surface/<idx>`` with
      ``node_coord_mid`` / ``node_number_list`` / ``tri_center_coord_mid``),
      which ``scripts/02_create_roi_efield_library.py`` reads; and
    * the pipeline layout (``mesh/elm/triangle_number_list`` +
      ``mesh/nodes/node_coord``), i.e. the ``geo.hdf5`` a session loads.

    Both describe the same surface. Centroids are always computed from the
    triangle nodes (the m2m file also stores them, but as float32, which
    differs from the float64 computation by ~1e-5 mm — enough to break an
    exact hash). The centroid sequence defines the E-field column order;
    compare :func:`roi_geometry_hash` values to verify that a library and a
    session ROI are the same element list.
    """
    import h5py

    path = Path(path)
    with h5py.File(path, "r") as handle:
        if "roi_surface" in handle:
            group_name = roi_idx or next(iter(handle["roi_surface"]))
            group = handle[f"roi_surface/{group_name}"]
            points = np.asarray(group["node_coord_mid"][:], dtype=np.float64)
            raw = np.asarray(group["node_number_list"][:, :3], dtype=np.int64)
        elif "mesh" in handle:
            points = np.asarray(handle["mesh/nodes/node_coord"][:],
                                dtype=np.float64)
            raw = np.asarray(handle["mesh/elm/triangle_number_list"][:, :3],
                             dtype=np.int64)
        else:
            raise KeyError(f"{path} has neither 'roi_surface' nor 'mesh' groups")
    triangles = raw - raw.min()
    if triangles.max() >= len(points):
        raise ValueError("ROI triangles reference nodes outside the point list")
    centroids = points[triangles].mean(axis=1)
    return points, triangles, centroids


def roi_geometry_hash(centroids):
    """SHA256 over the rounded centroid sequence of an ROI.

    The centroid order *is* the E-field column order, so equal hashes mean a
    library and a session ROI carry the same element list. Round-trip stable
    across the two HDF5 layouts (verified on the ernie data).
    """
    data = np.round(np.asarray(centroids, dtype=np.float64), 4)
    digest = hashlib.sha256()
    digest.update(f"{data.shape}:".encode())
    digest.update(np.ascontiguousarray(data, dtype="<f8").tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class DomainCheck:
    """Distance from a query pose to the nearest sampled pose."""

    inside: bool
    position_distance_mm: float
    rotation_distance_deg: float
    reasons: tuple

    def message(self) -> str:
        return ("coil pose outside the E-field surrogate's sampled domain: "
                + "; ".join(self.reasons))


def read_library(path):
    """Read ``E_mag`` and ``matsimnibs`` from an ``e.hdf5`` library.

    ``matsimnibs`` is accepted in the ``(n, 4, 4)`` layout written by the
    generator and in the ``(4, 4, n)`` layout of ``search_positions.hdf5``.
    The sibling file is used only when the main file has no matrices.
    """
    import h5py                      # lazy: synthetic tests need no h5py

    path = Path(path)
    with h5py.File(path, "r") as f:
        if "E_mag" not in f:
            raise KeyError(f"{path} has no 'E_mag' dataset")
        e_mag = np.asarray(f["E_mag"][:], dtype=np.float64)
        if "matsimnibs" in f:
            mats = np.asarray(f["matsimnibs"][:], dtype=np.float64)
            # The generator writes (n, 4, 4); accept (4, 4, n) too, but do not
            # transpose a genuine (4, 4, 4) library.
            if (mats.ndim == 3 and mats.shape[1:] != (4, 4)
                    and mats.shape[:2] == (4, 4)):
                mats = np.transpose(mats, (2, 0, 1))
        else:
            sibling = path.with_name("search_positions.hdf5")
            if not sibling.is_file():
                raise KeyError(
                    f"{path} has no 'matsimnibs' and {sibling} is missing")
            with h5py.File(sibling, "r") as f:
                mats = np.asarray(f["matsimnibs"][:], dtype=np.float64)
            if mats.ndim == 3 and mats.shape[:2] == (4, 4):
                mats = np.transpose(mats, (2, 0, 1))

    if e_mag.ndim != 2:
        raise ValueError(f"E_mag must be 2-D, got shape {e_mag.shape}")
    if mats.ndim != 3 or mats.shape[1:] != (4, 4):
        raise ValueError(f"matsimnibs must be (n, 4, 4), got {mats.shape}")
    if mats.shape[0] != e_mag.shape[0]:
        raise ValueError("E_mag and matsimnibs disagree on the number of poses")
    return e_mag, mats


def _quaternion_from_matrix(matrix):
    """Unit quaternion ``[x, y, z, w]`` from a 3x3 rotation matrix."""
    m = np.asarray(matrix, dtype=np.float64)
    trace = np.trace(m)
    if trace > 0.0:
        s = np.sqrt(trace + 1.0) * 2.0
        q = np.array([(m[2, 1] - m[1, 2]) / s,
                      (m[0, 2] - m[2, 0]) / s,
                      (m[1, 0] - m[0, 1]) / s,
                      0.25 * s])
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        q = np.array([0.25 * s,
                      (m[0, 1] + m[1, 0]) / s,
                      (m[0, 2] + m[2, 0]) / s,
                      (m[2, 1] - m[1, 2]) / s])
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        q = np.array([(m[0, 1] + m[1, 0]) / s,
                      0.25 * s,
                      (m[1, 2] + m[2, 1]) / s,
                      (m[0, 2] - m[2, 0]) / s])
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        q = np.array([(m[0, 2] + m[2, 0]) / s,
                      (m[1, 2] + m[2, 1]) / s,
                      0.25 * s,
                      (m[1, 0] - m[0, 1]) / s])
    q /= np.linalg.norm(q)
    return -q if q[3] < 0.0 else q


def _rotation_angles(quaternions, query):
    """Full angle in radians between a query quaternion and a set of them."""
    dots = np.clip(np.abs(np.asarray(quaternions) @ query), 0.0, 1.0)
    return 2.0 * np.arccos(dots)


def _inverse_distance_weighting(values, distances, power):
    weights = 1.0 / np.power(np.asarray(distances) + 1e-12, power)
    values = np.asarray(values)
    return (weights[:, None] * values).sum(axis=0) / weights.sum()


class EFieldSurrogate:
    """PCA + pose interpolation of a precomputed per-element E-field library.

    Parameters
    ----------
    n_components : int
        Number of PCA components; clipped to ``min(n_poses, n_elements)``.
    max_position_distance_mm, max_rotation_distance_deg : float or None
        Domain limits. The defaults are the median nearest-neighbour gaps of
        the training library.
    position_search_mm, rotation_search_deg : float or None
        Neighbourhood used for interpolation. Defaults extend the largest
        nearest-neighbour gap by half the median gap (the upstream scheme).
    on_outside : {"warn", "nan", "raise"}
        What ``compute_e_field`` does for a pose outside the domain.
    idw_power : float
        Inverse-distance exponent, default 2.
    clip_nonnegative : bool
        Clip the PCA reconstruction to non-negative values. Use this for
        magnitude libraries; leave it False for vector components, whose
        negative signs are meaningful.
    """

    def __init__(self, n_components=20, max_position_distance_mm=None,
                 max_rotation_distance_deg=None, position_search_mm=None,
                 rotation_search_deg=None, on_outside="warn", idw_power=2.0,
                 clip_nonnegative=False):
        if on_outside not in ("warn", "nan", "raise"):
            raise ValueError("on_outside must be 'warn', 'nan' or 'raise'")
        if idw_power <= 0:
            raise ValueError("idw_power must be positive")
        self._requested_components = int(n_components)
        self._position_limit = max_position_distance_mm
        self._rotation_limit = max_rotation_distance_deg
        self._position_search = position_search_mm
        self._rotation_search = rotation_search_deg
        self.n_components = int(n_components)
        self.max_position_distance_mm = max_position_distance_mm
        self.max_rotation_distance_deg = max_rotation_distance_deg
        self.position_search_mm = position_search_mm
        self.rotation_search_deg = rotation_search_deg
        self.on_outside = on_outside
        self.idw_power = float(idw_power)
        self.clip_nonnegative = bool(clip_nonnegative)
        self._fitted = False

    # ── construction ──────────────────────────────────────────────

    @classmethod
    def from_file(cls, path, **kwargs):
        e_mag, mats = read_library(path)
        return cls.from_arrays(e_mag, mats, **kwargs)

    @classmethod
    def from_arrays(cls, e_mag, mats, **kwargs):
        estimator = cls(**kwargs)
        estimator.fit(e_mag, mats)
        return estimator

    def fit(self, e_mag, mats):
        """Fit the PCA basis and the pose neighbourhood structure."""
        e_mag = np.asarray(e_mag, dtype=np.float64)
        mats = np.asarray(mats, dtype=np.float64)
        if e_mag.ndim != 2:
            raise ValueError("E_mag must be 2-D")
        if mats.ndim != 3 or mats.shape[1:] != (4, 4):
            raise ValueError("mats must have shape (n, 4, 4)")
        if len(mats) != len(e_mag):
            raise ValueError("E_mag and mats disagree on the number of poses")
        if len(e_mag) < 2:
            raise ValueError("at least two placements are needed")
        if not np.isfinite(e_mag).all():
            raise ValueError("E_mag contains non-finite values")
        if not np.isfinite(mats).all():
            raise ValueError("mats contains non-finite values")

        self._mean = e_mag.mean(axis=0)
        centred = e_mag - self._mean
        _, singular, components = np.linalg.svd(centred, full_matrices=False)
        k = min(self._requested_components, len(singular), e_mag.shape[1])
        if k < 1:
            raise ValueError("n_components must be at least 1")
        self.n_components = k
        self._components = components[:k]
        self._coefficients = centred @ self._components.T

        translations = np.round(mats[:, :3, 3], 4)
        self._positions, inverse = np.unique(translations, axis=0,
                                             return_inverse=True)
        quaternions = np.array([_quaternion_from_matrix(m[:3, :3])
                                for m in mats])
        self._pose_indices = []
        self._pose_quaternions = []
        for i in range(len(self._positions)):
            idx = np.flatnonzero(inverse == i)
            self._pose_indices.append(idx)
            self._pose_quaternions.append(quaternions[idx])

        position_gaps = self._nearest_neighbour_gaps(self._positions)
        rotation_gaps = []
        for quats in self._pose_quaternions:
            if len(quats) >= 2:
                dots = np.clip(np.abs(quats @ quats.T), 0.0, 1.0)
                angles = 2.0 * np.arccos(dots)
                np.fill_diagonal(angles, np.inf)
                rotation_gaps.append(angles.min(axis=1))
        rotation_gaps = (np.concatenate(rotation_gaps)
                         if rotation_gaps else np.array([0.0]))

        if self._position_limit is None:
            self.max_position_distance_mm = float(np.median(position_gaps))
        else:
            self.max_position_distance_mm = float(self._position_limit)
        if self._rotation_limit is None:
            self.max_rotation_distance_deg = float(
                np.degrees(np.median(rotation_gaps)))
        else:
            self.max_rotation_distance_deg = float(self._rotation_limit)
        if self._position_search is None:
            self.position_search_mm = float(
                position_gaps.max() + 0.5 * np.median(position_gaps))
        else:
            self.position_search_mm = float(self._position_search)
        if self._rotation_search is None:
            self.rotation_search_deg = float(
                np.degrees(rotation_gaps.max()
                           + 0.5 * np.median(rotation_gaps)))
        else:
            self.rotation_search_deg = float(self._rotation_search)

        self._fitted = True
        return self

    @staticmethod
    def _nearest_neighbour_gaps(points):
        if len(points) < 2:
            return np.zeros(1)
        distances = np.linalg.norm(points[:, None, :] - points[None, :, :],
                                   axis=2)
        np.fill_diagonal(distances, np.inf)
        return distances.min(axis=1)

    # ── queries ───────────────────────────────────────────────────

    @property
    def n_elements(self):
        return int(self._mean.shape[0])

    @property
    def n_poses(self):
        """Number of library placements the estimator was trained on."""
        return int(self._coefficients.shape[0])

    def check_pose(self, matsimnibs):
        """Return the domain check for a 4x4 coil pose, without interpolating."""
        self._require_fitted()
        mat = self._pose_matrix(matsimnibs)
        t = mat[:3, 3]
        q = _quaternion_from_matrix(mat[:3, :3])
        distances = np.linalg.norm(self._positions - t, axis=1)
        nearest = int(np.argmin(distances))
        position_distance = float(distances[nearest])
        rotation_distance = float(np.degrees(
            _rotation_angles(self._pose_quaternions[nearest], q).min()))

        reasons = []
        if position_distance > self.max_position_distance_mm:
            reasons.append(
                f"position is {position_distance:.2f} mm from the nearest "
                f"sample (limit {self.max_position_distance_mm:.2f} mm)")
        if rotation_distance > self.max_rotation_distance_deg:
            reasons.append(
                f"rotation is {rotation_distance:.1f} deg from the nearest "
                f"sample (limit {self.max_rotation_distance_deg:.1f} deg)")
        return DomainCheck(not reasons, position_distance, rotation_distance,
                           tuple(reasons))

    def compute_e_field(self, matsimnibs):
        """Interpolate the per-element E-field magnitude for a 4x4 coil pose.

        Returns ``(e_mag, DomainCheck)``. ``e_mag`` is per unit dI/dt (the
        library was generated at 1e6 A/s); multiply by ``didt / 1e6``.
        """
        check = self.check_pose(matsimnibs)
        if not check.inside:
            message = check.message()
            if self.on_outside == "raise":
                raise OutsideDomainError(message)
            warnings.warn(message, RuntimeWarning, stacklevel=2)
            if self.on_outside == "nan":
                return np.full(self.n_elements, np.nan), check
        return self._interpolate(matsimnibs), check

    def _interpolate(self, matsimnibs):
        self._require_fitted()
        mat = self._pose_matrix(matsimnibs)
        t = mat[:3, 3]
        q = _quaternion_from_matrix(mat[:3, :3])
        distances = np.linalg.norm(self._positions - t, axis=1)
        selected = distances <= self.position_search_mm
        if not selected.any():
            selected[np.argmin(distances)] = True

        coefficients, weights = [], []
        for i in np.flatnonzero(selected):
            angles = _rotation_angles(self._pose_quaternions[i], q)
            within = angles <= np.radians(self.rotation_search_deg)
            pose_idx = self._pose_indices[i]
            if within.any():
                coefficients.append(_inverse_distance_weighting(
                    self._coefficients[pose_idx[within]], angles[within],
                    self.idw_power))
            else:
                coefficients.append(
                    self._coefficients[pose_idx[int(np.argmin(angles))]])
            weights.append(1.0 / (distances[i] ** 2 + 1e-12))

        coefficients = np.average(np.asarray(coefficients), axis=0,
                                  weights=np.asarray(weights))
        field = self._mean + coefficients @ self._components
        if self.clip_nonnegative:
            return np.clip(field, 0.0, None)
        return field

    @staticmethod
    def _pose_matrix(matsimnibs):
        mat = np.asarray(matsimnibs, dtype=np.float64)
        if mat.shape != (4, 4):
            raise ValueError(f"coil pose must be 4x4, got {mat.shape}")
        return mat

    def _require_fitted(self):
        if not self._fitted:
            raise RuntimeError("call fit() or use from_file()/from_arrays()")
