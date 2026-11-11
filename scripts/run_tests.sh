#!/usr/bin/env bash
# Headless test suite (no display needed): the same command the CI job runs.
#
#   scripts/run_tests.sh                     # everything except the GUI tests
#   scripts/run_tests.sh tests/test_gui_config_tab.py   # extra pytest args
#   PYTHON=/path/to/python scripts/run_tests.sh
#
# Run the full suite, GUI tests included, on a workstation with `pytest`.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python}" -m pytest -m "not gui" "$@"
