"""The fit-function registry must match what pynibs actually offers."""

import pytest
from pynibs.expio import fit_funs

from neuropilot.controller.fit_functions import (
    DEFAULT_FIT_NAME, FIT_FUNCTIONS, fit_names, resolve,
)


def test_registry_is_not_empty_and_ordered():
    names = fit_names()
    assert len(names) >= 5
    assert list(FIT_FUNCTIONS) == names


def test_every_entry_is_a_callable():
    for name, fun in FIT_FUNCTIONS.items():
        assert callable(fun), name


def test_entries_come_from_pynibs():
    for name, fun in FIT_FUNCTIONS.items():
        assert getattr(fun, "__module__", "").startswith("pynibs"), name


def test_default_resolves():
    assert resolve(None) is FIT_FUNCTIONS[DEFAULT_FIT_NAME]
    assert resolve("") is FIT_FUNCTIONS[DEFAULT_FIT_NAME]


@pytest.mark.parametrize("name", list(FIT_FUNCTIONS))
def test_resolve_exact(name):
    assert resolve(name) is FIT_FUNCTIONS[name]


@pytest.mark.parametrize("name", list(FIT_FUNCTIONS))
def test_resolve_is_case_and_space_insensitive(name):
    assert resolve(f"  {name.upper()} ") is FIT_FUNCTIONS[name]


def test_legacy_names_still_map_to_the_old_models():
    # Project files and study profiles written before the registry existed.
    assert resolve("Linear") is fit_funs.linear
    assert resolve("Sigmoid") is fit_funs.sigmoid4


def test_unknown_name_is_rejected():
    assert resolve("quadratic") is None
    assert resolve(42) is None


def test_no_duplicate_functions():
    # Two menu entries pointing at the same model would be confusing.
    functions = list(FIT_FUNCTIONS.values())
    assert len(functions) == len(set(functions))
