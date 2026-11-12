# Prerequisites

## What kind of machine

| Requirement | Details |
|---|---|
| **Operating system** | Linux. The suite is developed and used on Debian/Ubuntu; macOS and Windows are not tested. |
| **Display** | A graphical session (X11, or Wayland with XWayland). The controller is a PyQt5 application and needs a display; headless runs only make sense for the test suite. |
| **Python** | 3.11, in a conda environment named `pipeline` throughout this documentation. |
| **Disk** | ~6 GB for the environment and SimNIBS; subject meshes and E-field libraries add several GB per subject. |
| **RAM** | 8 GB is enough for the simulator and the GUI; a full SimNIBS head mesh and the online solver are happier with 16 GB. |
| **GPU** | None required. The 3-D view uses OpenGL; Mesa's software renderer is fine for everything except smooth interaction with a million-triangle mesh. |

## Software

| Piece | Needed for | Comes from |
|---|---|---|
| Python 3.11 + `pip` | everything | conda / miniforge |
| PyQt5, `qasync` | the controller GUI and its event loop | conda-forge |
| `pyvista`, `vtk` | the 3-D cortical view | conda-forge / pip |
| `pynibs` | MEP extraction and the fit functions | pip (GitLab) |
| `h5py`, `numpy`, `scipy` | every data file | conda-forge |
| `python-socketio`, `aiohttp` | the relay client | pip |
| `python-dotenv`, `pyyaml` | configuration | pip |
| `mujoco`, `pybullet`, `ikpy` | the virtual robot | pip |
| **SimNIBS 4.5** | the online E-field solver and `.msh` meshes | SimNIBS wheel + MKL/MUMPS |
| `magicpy` | driving the stimulator (MagVenture) | pip (vendor package) |
| `smbprotocol` | reading the EMG files from the acquisition PC | pip |
| InVesalius | real-mode neuronavigation | separate conda env |
| `tms-robot-control` | real-mode robot driver + production relay | separate GitLab checkout |

`pynibs` and `magicpy` are lab packages; if `pip install pynibs` cannot find
them on PyPI, install them from the group's GitLab or from a local wheel. The
suite imports them lazily, so the simulator runs without `magicpy`.

## Knowledge

You should be comfortable with:

- a terminal and a conda environment (activate, install, run);
- editing a YAML file without breaking indentation;
- the TMS basics: coil orientation, motor threshold, MEP, resting motor
  territory, why the coil needs to stay on target.

You do **not** need to know SimNIBS, FEM, Qt or robot kinematics to run the
simulator; the site explains what each file is for.

## For a real session only

The full hardware list is on [Hardware setup](install/hardware.md). In
short: the TMS robot, the neuronavigation camera and PCs, the stimulator, the
EMG amplifier and a network that connects them. None of it is needed to install
or explore the software.

!!! danger "Safety — research software, not a medical device"
    NeuroPilot has no medical approval. Real stimulation requires ethics
    approval, a trained operator, the stimulator's own safety limits and the
    subject's written consent. Do not use it to make clinical decisions.

## Next

- [Install the suite](install/install.md)
- [Hardware setup](install/hardware.md)
