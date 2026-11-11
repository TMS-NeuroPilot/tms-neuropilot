"""Fit functions offered for the mapping regression.

All shapes come from :mod:`pynibs.expio.fit_funs`; the display names are what
the GUI shows and what the project/study files store.  "log" variants model
the logarithm of the response, the plain ones the raw MEP amplitude.
"""

from pynibs.expio import fit_funs

# Ordered: display name -> pynibs function.
FIT_FUNCTIONS = {
    "Linear": fit_funs.linear,
    "Linear (log)": fit_funs.linear_log,
    "Sigmoid": fit_funs.sigmoid4,           # pynibs' default (4 parameters)
    "Sigmoid (3-parameter)": fit_funs.sigmoid,
    "Sigmoid (log)": fit_funs.sigmoid4_log,
    "Exponential": fit_funs.exp,
    "Exponential (no offset)": fit_funs.exp0,
    "Exponential (log)": fit_funs.exp_log,
    "Step": fit_funs.step,
}

DEFAULT_FIT_NAME = "Linear"


def fit_names():
    """Display names in menu order."""
    return list(FIT_FUNCTIONS)


def resolve(name):
    """pynibs function for a display name (case-insensitive), else None."""
    if not name:
        return FIT_FUNCTIONS[DEFAULT_FIT_NAME]
    if name in FIT_FUNCTIONS:
        return FIT_FUNCTIONS[name]
    lowered = str(name).strip().lower()
    for key, fun in FIT_FUNCTIONS.items():
        if key.lower() == lowered:
            return fun
    return None
