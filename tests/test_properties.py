"""Seeded random property checks for the pure helpers.

These are not exhaustive proofs; they are cheap invariants over many random
inputs, aimed at the bugs a single hand-written example misses (a value with
``#`` inside, an excluded pulse beyond the history, a base name that already
contains ".csv").
"""

import math
import os
import random
import string

import numpy as np
import pytest

from neuropilot.controller.config_store import MANAGED_KEYS, ConfigStore
from neuropilot.controller.pipeline_controller import (
    assemble_analysis_matrix, stamped_results_filename,
)
from neuropilot.lab_profile import LAB_KEYS, LabProfile, apply_environment

SEED = 20261111
VALUES = string.ascii_letters + string.digits + " #\"'=\\:/.-_ü\t@!%&+,;<>?[]{}|~^"


def rng():
    return random.Random(SEED)


# ── analysis matrix ────────────────────────────────────────────────────

def test_assembled_matrix_keeps_rows_and_indices_aligned():
    rnd = rng()
    for _ in range(300):
        n = rnd.randint(0, 12)
        rows = [None if rnd.random() < 0.25
                else np.array([rnd.uniform(-1e3, 1e3) for _ in range(4)])
                for _ in range(n)]
        excluded = {i for i in range(n) if rnd.random() < 0.2}
        wanted = [i for i in range(n) if i not in excluded]

        kept, matrix = assemble_analysis_matrix(rows, wanted)
        if matrix is None:
            assert all(rows[i] is None for i in wanted), (rows, wanted)
            assert len(kept) == 0
            continue
        assert list(kept) == sorted(kept)
        assert len(kept) == matrix.shape[0]
        assert matrix.shape[1] == 4
        for row_index, pulse in enumerate(kept):
            assert pulse in wanted
            assert rows[pulse] is not None
            np.testing.assert_allclose(matrix[row_index], rows[pulse])


def test_assembled_matrix_ignores_out_of_range_indices():
    rnd = rng()
    for _ in range(100):
        n = rnd.randint(0, 6)
        rows = [np.ones(3) for _ in range(n)]
        indices = [rnd.randint(-5, n + 5) for _ in range(8)]
        kept, matrix = assemble_analysis_matrix(rows, indices)
        assert all(0 <= i < n for i in kept)
        if matrix is not None:
            assert matrix.shape[0] == len(kept)


# ── result file names ──────────────────────────────────────────────────

def test_stamped_results_filename_only_changes_the_extension():
    rnd = rng()
    for _ in range(300):
        folder = "/".join("".join(rnd.choice(VALUES) for _ in range(4))
                          for _ in range(rnd.randint(0, 3)))
        name = "".join(rnd.choice(VALUES) for _ in range(rnd.randint(0, 10)))
        ext = rnd.choice([".csv", ".CSV", ""])
        path = (folder + "/" if folder else "") + name + ext
        stamp = "20260101_000000"
        out = stamped_results_filename(path, stamp)
        assert os.path.dirname(out) == os.path.dirname(path)
        expected_ext = os.path.splitext(os.path.basename(path))[1] or ".csv"
        assert out.endswith(expected_ext)
        assert stamp in out
        # The folder part is never touched, even when it contains ".csv".
        folder_len = len(os.path.dirname(path))
        assert path[:folder_len] == out[:folder_len]
        # ... and the original stem is kept.
        stem = os.path.splitext(os.path.basename(path))[0]
        assert os.path.basename(out).startswith(stem)


# ── .env round-trip (oracle: python-dotenv itself) ─────────────────────

def test_env_values_round_trip_like_dotenv(tmp_path):
    dotenv_values = pytest.importorskip("dotenv").dotenv_values
    rnd = rng()
    cases = ["", "plain", "p#ss word", 'quo"ted', "it's", "  padded  ",
             "a=b#c", "back\\slash", "tab\there", "ünïcode", "#leading"]
    cases += ["".join(rnd.choice(VALUES) for _ in range(rnd.randint(0, 12)))
              for _ in range(150)]
    for value in cases:
        if "${" in value:      # dotenv interpolates those; out of scope
            continue
        path = tmp_path / ".env"
        store = ConfigStore(path)
        store.write({"EMG_COMPUTER_PASSWORD": value})
        written = path.read_text()
        assert written.startswith("EMG_COMPUTER_PASSWORD=")
        parsed = dotenv_values(path).get("EMG_COMPUTER_PASSWORD", "")
        assert store.read().get("EMG_COMPUTER_PASSWORD", "") == parsed, (
            value, written)
        if value.strip():
            assert parsed == value.strip() or parsed == value


def test_managed_keys_round_trip_together(tmp_path):
    rnd = rng()
    path = tmp_path / ".env"
    store = ConfigStore(path)
    values = {}
    for key in MANAGED_KEYS:
        value = "".join(rnd.choice(VALUES) for _ in range(rnd.randint(0, 10)))
        values[key] = value
    store.write(values)
    read_back = store.read()
    for key, value in values.items():
        if "${" in value:
            continue
        assert read_back[key].strip() == value.strip(), key


def test_repeated_writes_stay_stable(tmp_path):
    rnd = rng()
    path = tmp_path / ".env"
    store = ConfigStore(path)
    for _ in range(20):
        values = {key: "".join(rnd.choice(VALUES)
                               for _ in range(rnd.randint(0, 6)))
                  for key in rnd.sample(list(MANAGED_KEYS), 5)}
        store.write(values)
    text = path.read_text()
    first = ConfigStore(path).read()
    store.write(first)
    assert path.read_text() == text            # idempotent


# ── lab profile round-trip ─────────────────────────────────────────────

def test_lab_profile_round_trips_random_values(tmp_path):
    rnd = rng()
    path = tmp_path / "lab.yaml"
    profile = LabProfile(path)
    for _ in range(100):
        keys = rnd.sample(list(LAB_KEYS), rnd.randint(1, len(LAB_KEYS)))
        values = {key: "".join(rnd.choice(VALUES)
                               for _ in range(rnd.randint(0, 8)))
                  for key in keys}
        profile.write(values)
        read_back = profile.read()
        for key, value in values.items():
            assert read_back[key] == value, key


def test_apply_environment_never_exports_blank_values():
    rnd = rng()
    for _ in range(100):
        values = {key: rnd.choice(["", "  ", "x", "\t"])
                  for key in rnd.sample(list(LAB_KEYS), 4)}
        environ = {}
        applied = apply_environment(values, environ)
        for key in applied:
            assert environ[key].strip()


def test_lab_profile_path_is_stable(tmp_path):
    path = tmp_path / "lab.yaml"
    profile = LabProfile(path)
    profile.write({"RELAY_HOST": "h"})
    assert LabProfile(path).path == profile.path


# ── numerics that feed the analysis ────────────────────────────────────

@pytest.mark.parametrize("seed", range(5))
def test_precomputed_rows_scale_linearly(seed):
    from neuropilot.controller.pipeline_controller import precomputed_e_field_row
    rnd = random.Random(seed)
    matrix = np.array([[rnd.uniform(0, 200) for _ in range(6)] for _ in range(3)])
    target = rnd.randrange(3)
    low, high = sorted((rnd.uniform(1, 50), rnd.uniform(51, 100)))
    row_low = precomputed_e_field_row(matrix, target, low)
    row_high = precomputed_e_field_row(matrix, target, high)
    ratio = high / low
    np.testing.assert_allclose(row_high / row_low, np.full(6, ratio), rtol=1e-9)


def test_scale_for_a_random_amplitude_matches_the_factor():
    from neuropilot.controller.pipeline_controller import precomputed_e_field_row
    rnd = rng()
    for _ in range(100):
        amplitude = rnd.uniform(0, 100)
        row = precomputed_e_field_row(np.ones((1, 3)), 0, amplitude)
        np.testing.assert_allclose(row, np.full(3, amplitude * 1.4))
        assert np.isfinite(row).all()
