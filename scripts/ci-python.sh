#!/usr/bin/env bash
# Print the Python interpreter the test/CI scripts should use.
#
# Priority:
#   1. $PYTHON, if it is an executable path or on the PATH
#   2. the project's `pipeline` conda environment in the usual locations
#   3. python3
#
# The suite imports PyQt5, pynibs, simnibs and mujoco, which only the
# `pipeline` environment has (see README).  Keeping the detection here means
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

for candidate in \
    "${HOME}/miniforge3/envs/pipeline/bin/python" \
    "${HOME}/miniconda3/envs/pipeline/bin/python" \
    "${HOME}/anaconda3/envs/pipeline/bin/python" \
    "/opt/conda/envs/pipeline/bin/python" \
    "/opt/miniforge3/envs/pipeline/bin/python" \
    "/usr/local/envs/pipeline/bin/python"; do
    if [ -x "$candidate" ]; then
        echo "$candidate"
        exit 0
    fi
done

if command -v python3 >/dev/null 2>&1; then
    command -v python3
    exit 0
fi

echo "no Python interpreter found (set PYTHON to the pipeline env)" >&2
exit 1
