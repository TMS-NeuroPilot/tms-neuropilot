#!/usr/bin/env bash
# One-command NeuroPilot installation.
#
#   scripts/install.sh                         # conda env 'neuropilot'
#   scripts/install.sh --env-name my-env      # custom conda env name
#   scripts/install.sh --with-invesalius      # also clone + install InVesalius
#
# Prerequisite: conda (miniforge or miniconda) on the PATH.
# The environment spec is environment.yml in the repository root; the
# long-form recipe with the reasoning is docs/site/pages/install/install.md.
set -euo pipefail

usage() {
    echo "usage: scripts/install.sh [--env-name NAME] [--with-invesalius]"
}

WITH_INVESALIUS=0
ENV_NAME="neuropilot"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-invesalius)
            WITH_INVESALIUS=1
            shift
            ;;
        --env-name)
            if [ "$#" -lt 2 ] || [ -z "${2:-}" ]; then
                echo "error: --env-name needs a value" >&2
                usage >&2
                exit 1
            fi
            ENV_NAME="$2"
            shift 2
            ;;
        --env-name=*)
            ENV_NAME="${1#*=}"
            if [ -z "$ENV_NAME" ]; then
                echo "error: --env-name needs a value" >&2
                usage >&2
                exit 1
            fi
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 1
            ;;
    esac
done
if [[ "$ENV_NAME" == *[[:space:]]* ]]; then
    echo "error: the conda environment name cannot contain whitespace" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── 1. Conda environment from the one-file spec ────────────────────────
if conda env list | awk -v name="$ENV_NAME" '$1 == name { found=1 } END { exit !found }'; then
    echo "[install] conda env '$ENV_NAME' already exists -- skipping create"
else
    conda env create -f environment.yml -n "$ENV_NAME"
fi
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# ── 2. NeuPilot in editable mode ────────────────────────────────────────
pip install -e . --no-deps

# ── 3. Verify the heavy imports before anything else runs ──────────────
if ! python -c "import numpy, h5py, PyQt5, qasync, pyvista, mujoco, pybullet, pynibs, magicpy" 2>/dev/null; then
    echo "[install] a core import failed -- see docs/site/pages/install/install.md"
    exit 1
fi
if ! python -c "import simnibs" 2>/dev/null; then
    cat <<'NOTE'
[install] 'import simnibs' failed. The petsc4py wheel links older MKL
sonames (libmkl*.so.2). Copy those files from a working SimNIBS
environment into "$CONDA_PREFIX/lib" and rerun, or see
docs/site/pages/install/install.md ("MKL sonames").
NOTE
    exit 1
fi
echo "[install] imports ok"

# ── 4. Optional: InVesalius (real, manual and training modes) ───────────
if [ "$WITH_INVESALIUS" -eq 1 ]; then
    INV_DIR="$(dirname "$REPO_ROOT")/invesalius-mpi"
    if [ ! -d "$INV_DIR" ]; then
        git clone https://gitlab.gwdg.de/tms-localization/cobot/invesalius-mpi.git "$INV_DIR"
    fi
    if ! conda env list | grep -qE '^invesalius\s'; then
        conda create -n invesalius python=3.12 -y
    fi
    conda activate invesalius
    conda install -c conda-forge -y wxpython=4.2.2 numpy scipy pillow matplotlib \
        scikit-image nibabel pyserial psutil vtk==9.4.2 cython h5py imageio \
        pypubsub gdcm pyacvd
    pip install "python-socketio[client]" pypolaris
    pip install -e "$INV_DIR" --no-deps
    conda activate "$ENV_NAME"
    echo "[install] InVesalius installed in the 'invesalius' env ($INV_DIR)"
fi

echo "[install] done. Start with:  conda activate $ENV_NAME && neuropilot sim"
