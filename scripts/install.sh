#!/usr/bin/env bash
# One-command NeuroPilot installation.
#
#   scripts/install.sh                         # conda env 'neuropilot'
#   scripts/install.sh --env-name my-env      # custom conda env name
#   scripts/install.sh --with-invesalius      # install the PR test InVesalius branch
#   scripts/install.sh --with-invesalius --with-robot-control
#                                             # also clone the GitHub robot-control fork
#
# Prerequisite: conda (miniforge or miniconda) on the PATH.
# The environment spec is environment.yml in the repository root; the
# long-form recipe with the reasoning is docs/site/pages/install/install.md.
set -euo pipefail

usage() {
    echo "usage: scripts/install.sh [--env-name NAME] [--with-invesalius] [--with-robot-control]"
}

WITH_INVESALIUS=0
WITH_ROBOT_CONTROL=0
ENV_NAME="neuropilot"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-invesalius)
            WITH_INVESALIUS=1
            shift
            ;;
        --with-robot-control)
            WITH_ROBOT_CONTROL=1
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

# Temporary local-test refs. Override with the NEUROPILOT_* variables.
INV_REPO="${NEUROPILOT_INVESALIUS_REPO:-https://github.com/0nu/invesalius3.git}"
INV_REF="${NEUROPILOT_INVESALIUS_REF:-installer-three-prs}"
INV_DIR="${NEUROPILOT_INVESALIUS_DIR:-$(dirname "$REPO_ROOT")/invesalius-prs}"
ROBOT_REPO="${NEUROPILOT_ROBOT_REPO:-https://github.com/0nu/tms-robot-control.git}"
ROBOT_REF="${NEUROPILOT_ROBOT_REF:-installer-omron-relay}"
ROBOT_DIR="${NEUROPILOT_ROBOT_DIR:-$(dirname "$REPO_ROOT")/tms-robot-control}"

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
if [ ! -e "$CONDA_PREFIX/lib/libmkl_intel_lp64.so.2" ]; then
    announce "installing MKL 2024.2.0 for the petsc4py ABI..."
    pip install "mkl==2024.2.0"
fi
announce "NeuroPilot installed; checking required imports..."

# ── 3. Verify the heavy imports before anything else runs ──────────────
import_check() {
    python - <<'PY'
import importlib
import sys
import traceback

modules = (
    "numpy", "h5py", "PyQt5", "qasync", "pyvista", "mujoco",
    "pybullet", "pynibs", "magicpy", "simnibs", "pandas", "seaborn",
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

# ── 4. Optional: InVesalius PR test branch ─────────────────────────────
if [ "$WITH_INVESALIUS" -eq 1 ]; then
    if [ ! -d "$INV_DIR" ]; then
        announce "cloning InVesalius '$INV_REF' from GitHub into $INV_DIR..."
        git clone --branch "$INV_REF" --depth 1 "$INV_REPO" "$INV_DIR"
    else
        announce "using existing InVesalius checkout at $INV_DIR; checking out '$INV_REF'..."
        git -C "$INV_DIR" fetch origin "$INV_REF" --depth 1
        git -C "$INV_DIR" checkout -B "$INV_REF" FETCH_HEAD
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

# ── 5. Optional: GitHub robot-control checkout ──────────────────────────
if [ "$WITH_ROBOT_CONTROL" -eq 1 ]; then
    if [ ! -d "$ROBOT_DIR" ]; then
        announce "cloning robot-control '$ROBOT_REF' from GitHub into $ROBOT_DIR..."
        git clone --branch "$ROBOT_REF" --depth 1 "$ROBOT_REPO" "$ROBOT_DIR"
    else
        announce "using existing robot-control checkout at $ROBOT_DIR; checking out '$ROBOT_REF'..."
        git -C "$ROBOT_DIR" fetch origin "$ROBOT_REF" --depth 1
        git -C "$ROBOT_DIR" checkout -B "$ROBOT_REF" FETCH_HEAD
    fi
    if [ -f "$ROBOT_DIR/.env.example" ] && [ ! -f "$ROBOT_DIR/.env" ]; then
        cp "$ROBOT_DIR/.env.example" "$ROBOT_DIR/.env"
        announce "created $ROBOT_DIR/.env from .env.example; edit it for your robot."
    fi
    ENV_FILE="$REPO_ROOT/.env"
    if [ -f "$ENV_FILE" ] && ! grep -q '^TMS_ROBOT_CONTROL_PATH=' "$ENV_FILE"; then
        printf '\nTMS_ROBOT_CONTROL_PATH="%s"\n' "$ROBOT_DIR" >> "$ENV_FILE"
        announce "added TMS_ROBOT_CONTROL_PATH to $ENV_FILE"
    elif [ ! -f "$ENV_FILE" ]; then
        echo "[install] create $ENV_FILE and set:"
        echo "  TMS_ROBOT_CONTROL_PATH=\"$ROBOT_DIR\""
    fi
    announce "installing robot-control dependencies in '$ENV_NAME'..."
    pip install -r "$ROBOT_DIR/requirements.txt"
    announce "robot-control dependencies installed."
fi

announce "installation complete. Start with:  conda activate $ENV_NAME && neuropilot sim"
if [ "$WITH_ROBOT_CONTROL" -eq 1 ]; then
    echo "[install] robot-control:  conda activate $ENV_NAME && cd $ROBOT_DIR && python main_loop.py"
fi
