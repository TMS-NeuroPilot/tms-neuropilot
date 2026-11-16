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

announce() {
    printf '[install] %s\n' "$*"
    sleep 1
}

# ── 1. Conda environment from the one-file spec ────────────────────────
if conda env list | awk -v name="$ENV_NAME" '$1 == name { found=1 } END { exit !found }'; then
    announce "conda env '$ENV_NAME' already exists; reusing it."
else
    announce "creating conda env '$ENV_NAME' from environment.yml (this can take several minutes)..."
    conda env create -f environment.yml -n "$ENV_NAME"
fi
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"
announce "activated conda env '$ENV_NAME'."

# ── 2. NeuPilot in editable mode ────────────────────────────────────────
announce "installing NeuroPilot in editable mode..."
pip install -e . --no-deps
announce "NeuroPilot installed; checking required imports..."

# ── 3. Verify the heavy imports before anything else runs ──────────────
import_check() {
    python - <<'PY'
import importlib
import sys
import traceback

modules = (
    "numpy", "h5py", "PyQt5", "qasync", "pyvista", "mujoco",
    "pybullet", "pynibs", "magicpy", "simnibs",
)
failed = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception:
        print(f"[install] import failed: {name}")
        traceback.print_exc()
        failed.append(name)
if failed:
    sys.exit(1)
PY
}

IMPORT_LOG="$(mktemp)"
trap 'rm -f "$IMPORT_LOG"' EXIT
if ! import_check >"$IMPORT_LOG" 2>&1; then
    cat "$IMPORT_LOG"
    if grep -qE 'libmkl_[A-Za-z0-9_]+\.so\.2' "$IMPORT_LOG"; then
        SIMNIBS_ENV="${NEUROPILOT_SIMNIBS_ENV:-$(conda info --base)/envs/simnibs}"
        SIMNIBS_LIB="$SIMNIBS_ENV/lib"
        if [ ! -d "$SIMNIBS_LIB" ]; then
            SIMNIBS_LIB="$(conda info --base)/envs/pipeline/lib"
        fi
        if [ -d "$SIMNIBS_LIB" ]; then
            announce "missing MKL .so.2 libraries; copying them from $SIMNIBS_LIB"
            find "$SIMNIBS_LIB" -maxdepth 1 -name 'libmkl*.so.2' \
                -exec cp -a {} "$CONDA_PREFIX/lib/" \;
            announce "MKL repair complete; rechecking imports..."
            if ! import_check >"$IMPORT_LOG" 2>&1; then
                cat "$IMPORT_LOG"
                echo "[install] the MKL repair did not fix the imports; see docs/site/pages/install/install.md"
                exit 1
            fi
        else
            echo "[install] missing MKL .so.2 libraries and no SimNIBS environment was found."
            echo "[install] Set NEUROPILOT_SIMNIBS_ENV to a working SimNIBS environment and rerun."
            exit 1
        fi
    else
        echo "[install] fix the failed import shown above, then rerun."
        exit 1
    fi
fi
announce "all required imports loaded."

# ── 4. Optional: InVesalius (real, manual and training modes) ───────────
if [ "$WITH_INVESALIUS" -eq 1 ]; then
    INV_DIR="$(dirname "$REPO_ROOT")/invesalius-mpi"
    if [ ! -d "$INV_DIR" ]; then
        announce "cloning InVesalius into $INV_DIR..."
        git clone https://gitlab.gwdg.de/tms-localization/cobot/invesalius-mpi.git "$INV_DIR"
    else
        announce "using existing InVesalius checkout at $INV_DIR."
    fi
    if ! conda env list | grep -qE '^invesalius\s'; then
        announce "creating conda env 'invesalius'..."
        conda create -n invesalius python=3.12 -y
    else
        announce "conda env 'invesalius' already exists; reusing it."
    fi
    conda activate invesalius
    announce "installing InVesalius dependencies in 'invesalius'..."
    conda install -c conda-forge -y wxpython=4.2.2 numpy scipy pillow matplotlib \
        scikit-image nibabel pyserial psutil vtk==9.4.2 cython h5py imageio \
        pypubsub gdcm pyacvd
    announce "installing InVesalius Python packages..."
    pip install "python-socketio[client]" pypolaris
    pip install -e "$INV_DIR" --no-deps
    conda activate "$ENV_NAME"
    announce "InVesalius installed in the 'invesalius' env ($INV_DIR)."
fi

announce "installation complete. Start with:  conda activate $ENV_NAME && neuropilot sim"
