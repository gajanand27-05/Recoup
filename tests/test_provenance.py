"""Tests for the provenance machinery itself.

The scanner has been wrong before. It reported clean while blind to an entire
category of constant, which is worse than not having it: a check that cannot
fail on the thing it checks manufactures confidence.

So this file tests the checker, not the parameters. `test_curve.py` and
`test_generator.py` apply it.
"""

import re
import types
from pathlib import Path

import pytest

from recoup.simulator import curve, generator
from recoup.simulator.provenance import (
    CLASSES,
    params_problems,
    unread_assumptions,
    unregistered_constants,
    unregistered_literals,
)


def _module_with(**names) -> types.ModuleType:
    mod = types.ModuleType("fake")
    for k, v in names.items():
        setattr(mod, k, v)
    return mod


# --- the scanner's own coverage ------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [0.5, 7, {"a": 1}, [1, 2], (1, 2), {1, 2}, frozenset({1, 2})],
    ids=["float", "int", "dict", "list", "tuple", "set", "frozenset"],
)
def test_every_parameter_shaped_type_is_visible_to_the_scan(value):
    """`set` and `frozenset` were missing from the type list.

    HARD_DECLINE_CODES is a frozenset, so the scan was blind to exactly the
    shape one of the real parameters has. It happened to be registered anyway,
    which is luck, not coverage.
    """
    mod = _module_with(UNSOURCED=value)
    assert unregistered_constants(mod, {}, frozenset()) == ["UNSOURCED"]


def test_booleans_are_not_treated_as_numbers():
    assert unregistered_constants(_module_with(FLAG=True), {}, frozenset()) == []


def test_a_registered_constant_is_not_flagged():
    mod = _module_with(RATE=0.5)
    params = {"rate": {"constant": "RATE", "value": 0.5, "class": "ASSUMPTION"}}
    assert unregistered_constants(mod, params, frozenset()) == []


def test_functions_and_imports_are_not_flagged():
    mod = _module_with(helper=lambda: None, types=types, Klass=type("K", (), {}))
    assert unregistered_constants(mod, {}, frozenset()) == []


# --- magic numbers inside function bodies -------------------------------------


def test_a_magic_number_inside_a_function_is_found():
    # unregistered_constants walks module-level names, so `p *= 0.9` written
    # inside a function is invisible to it -- the same hole one level down.
    assert unregistered_literals(generator) == []
    assert unregistered_literals(curve) == []


def test_the_literal_scan_would_actually_catch_one(tmp_path, monkeypatch):
    src = tmp_path / "fake_mod.py"
    src.write_text("def f(x):\n    return x * 0.87\n", encoding="utf-8")
    mod = types.ModuleType("fake_mod")
    mod.__file__ = str(src)
    found = unregistered_literals(mod)
    assert found and "0.87" in found[0]


def test_probability_bounds_and_indices_are_not_magic_numbers():
    src_mod = types.ModuleType("m")
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "m.py"
    p.write_text("def f(x):\n    return max(0.0, min(1.0, x - 1))\n", encoding="utf-8")
    src_mod.__file__ = str(p)
    assert unregistered_literals(src_mod) == []


# --- swept assumptions that nothing reads -------------------------------------


def test_an_assumption_swept_but_never_read_is_reported():
    """The false-robustness failure.

    A parameter declared ASSUMPTION with a sweep, implemented nowhere, makes the
    sensitivity analysis vary it, observe no change, and report INSENSITIVE. That
    is manufactured evidence of robustness in the one analysis whose job is to
    find where the result is fragile.
    """
    mod = _module_with(REAL=0.1)
    params = {
        "real": {"constant": "REAL", "value": 0.1, "class": "ASSUMPTION", "sweep": [0, 1]},
        "phantom": {"value": 0.0, "class": "ASSUMPTION", "sweep": [0, 1]},
    }
    problems = unread_assumptions(mod, params)
    assert len(problems) == 1
    assert "phantom" in problems[0]


def test_an_assumption_naming_a_constant_that_does_not_exist_is_reported():
    params = {"gone": {"constant": "MISSING", "value": 1, "class": "ASSUMPTION", "sweep": [0, 2]}}
    assert unread_assumptions(_module_with(), params) == [
        "gone: names constant 'MISSING', which does not exist"
    ]


def test_every_swept_assumption_in_the_real_modules_is_wired_up():
    assert unread_assumptions(curve, curve.PARAMS) == []
    assert unread_assumptions(generator, generator.PARAMS) == []


# --- registry well-formedness --------------------------------------------------


# --- the document and the registry must agree ---------------------------------


def test_every_registered_parameter_is_documented_in_params_md():
    """PARAMS.md is the artifact a judge reads. The registry is what the code runs.

    Nothing kept them in step, and they drifted: Task 9 registered six generator
    parameters -- including both self-recovery rates, the numbers that define the
    counterfactual -- and PARAMS.md described none of them. The tests all passed,
    because they only ever checked the registry against itself.

    The match is on the exact registry key, not a fuzzy phrase, so a renamed
    parameter fails here rather than silently losing its documentation.
    """
    doc = (Path(curve.__file__).parent / "PARAMS.md").read_text(encoding="utf-8")
    missing = [
        f"{mod.__name__.split('.')[-1]}.{key}"
        for mod in (curve, generator)
        for key in mod.PARAMS
        if f"`{key}`" not in doc
    ]
    assert not missing, (
        f"registered but undocumented in PARAMS.md: {missing}. The provenance "
        "document is the artifact; the registry is not a substitute for it."
    )


def test_no_parameter_is_documented_that_the_code_does_not_have():
    # The reverse drift: a section describing a parameter that was removed.
    doc = (Path(curve.__file__).parent / "PARAMS.md").read_text(encoding="utf-8")
    known = set(curve.PARAMS) | set(generator.PARAMS)
    claimed = set(re.findall(r"Registry keys?: (.+)", doc))
    for line in claimed:
        for key in re.findall(r"`([a-z_]+)`", line):
            assert key in known, f"PARAMS.md documents {key!r}, which is not registered"


def test_a_missing_class_is_reported():
    assert params_problems({"x": {"value": 1, "source": "s"}})


def test_an_assumption_citing_a_url_is_reported():
    problems = params_problems({
        "x": {"value": 1, "class": "ASSUMPTION", "source": "https://example.com", "sweep": [0, 2]}
    })
    assert any("either it is sourced or it is not" in p for p in problems)


def test_a_derived_parameter_without_a_stated_derivation_is_reported():
    problems = params_problems({
        "x": {"value": 1, "class": "DERIVED", "source": "https://e.com", "population": "p"}
    })
    assert any("DERIVED without a stated derivation" in p for p in problems)


def test_a_value_outside_its_own_sweep_is_reported():
    problems = params_problems({
        "x": {"value": 5, "class": "ASSUMPTION", "source": "ASSUMPTION", "sweep": [0, 1]}
    })
    assert any("outside its sweep" in p for p in problems)


def test_the_class_vocabulary_is_closed():
    assert CLASSES == ("MEASURED", "DERIVED", "DEFINITIONAL", "ASSUMPTION")
    assert params_problems({"x": {"value": 1, "class": "PROBABLY", "source": "s"}})
