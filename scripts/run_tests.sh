#!/usr/bin/env bash
# Headless test suite (no display needed): the same command the CI job runs.
#
#   scripts/run_tests.sh                     # everything except the GUI tests
#   scripts/run_tests.sh tests/test_gui_config_tab.py   # extra pytest args
#   PYTHON=/path/to/python scripts/run_tests.sh
#
# The interpreter is detected like in CI (scripts/ci-python.sh): $PYTHON, the
# `pipeline` conda env, then python3.  Run the full suite, GUI tests included,
# on a workstation with `pytest`.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=$(bash scripts/ci-python.sh)
echo "Interpreter: $PYTHON ($($PYTHON --version 2>&1))"

export ROOT_FOLDER="${ROOT_FOLDER:-/tmp/neuropilot_tests}"
export NEUROPILOT_LAB_FILE="${NEUROPILOT_LAB_FILE:-$ROOT_FOLDER/lab.yaml}"
export NEUROPILOT_ENV_FILE="${NEUROPILOT_ENV_FILE:-$ROOT_FOLDER/.env}"
mkdir -p "$ROOT_FOLDER"

exec "$PYTHON" -m pytest -m "not gui" "$@"
