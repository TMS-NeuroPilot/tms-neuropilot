import h5py
import numpy as np
from .. import transformations as tr
def read_simnibs_placements(placement_fn, n_positions=None):
    """
    Reads SimNIBS placements from a file and returns a list of target positions and Euler angles.

    Parameters
    ----------
    placement_fn : str
        Path to the SimNIBS placements file (HDF5 format).

    Returns
    -------
    target_queue : list of tuples
        Each tuple contains a position (numpy array) and Euler angles (numpy array).
        The position is scaled by a factor of 1.2.
    """
    target_queue = []
    with h5py.File(placement_fn, 'r') as f:
        mats = f['matsimnibs'][:]
        if n_positions is not None:
            print(f"Reading only the first {n_positions} placements from {placement_fn}")
        else:
            print(f"Reading all placements from {placement_fn}")
            n_positions = mats.shape[2]
        for i in range(15):#range(mats.shape[2]):
            m = mats[:, :, i]
            m[:3,0] *= -1
            m[:3,2] *= -1

            x = m[:3,0].copy()
            m[:3,0] = m[:3,1]
            m[:3,1] = -x

            euler_angles = np.degrees(tr.euler_from_matrix(m, "sxyz"))
            pos = m[:3,3] *1.2
            target_queue.append((pos, euler_angles))

    return target_queue