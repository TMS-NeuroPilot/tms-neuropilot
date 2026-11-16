#!/usr/bin/env bash
# Print the Python interpreter the test/CI scripts should use.
#
# Priority:
#   1. $PYTHON, if it is an executable path or on the PATH
#   2. the project's `neuropilot` conda environment in the usual locations
#   3. the legacy `pipeline` environment, for existing lab machines
#   4. python3
#
# The suite imports PyQt5, pynibs, simnibs and mujoco, which only the
# `neuropilot` environment has (see README).  Keeping the detection here means
# the CI job and the local script agree on what "the right python" is.
set -euo pipefail

if [ -n "${PYTHON:-}" ]; then
    if [ -x "$PYTHON" ]; then
        echo "$PYTHON"
        exit 0
    fi
    if command -v "$PYTHON" >/dev/null 2>&1; then
        command -v "$PYTHON"
        exit 0
    fi
    echo "PYTHON='$PYTHON' is not executable and not on the PATH" >&2
    exit 1
fi

for env_name in neuropilot pipeline; do
    for prefix in \
        "${HOME}/miniforge3" \
        "${HOME}/miniconda3" \
        "${HOME}/anaconda3" \
        "/opt/conda" \
        "/opt/miniforge3" \
        "/usr/local"; do
        candidate="${prefix}/envs/${env_name}/bin/python"
        if [ -x "$candidate" ]; then
            echo "$candidate"
            exit 0
        fi
    done
done

if command -v python3 >/dev/null 2>&1; then
    command -v python3
    exit 0
fi

echo "no Python interpreter found (set PYTHON to the neuropilot env)" >&2
exit 1
