"""Shared provenance machinery for the simulator's generative parameters.

Every number the simulator reads must be registered with a `class`:

    MEASURED      published figure, stated population, URL
    DERIVED       computed from a MEASURED figure by an arithmetic stated in PARAMS.md
    DEFINITIONAL  a normalisation anchor -- a choice of units, not a finding
    ASSUMPTION    not sourced; swept in the sensitivity analysis (Task 23b)

The checks live here rather than in each test file for one reason: iterating a
PARAMS dict only proves that everything ALREADY REGISTERED has a source. It says
nothing about a constant typed straight into a module and never registered, which
is how an unsourced beyond-curve decay survived the Task 8 draft and how
MAX_ATTEMPTS survived the ingest. `unregistered_constants()` is the check that
sits where that failure actually happens.
"""

import ast
import inspect
from pathlib import Path
from types import ModuleType

CLASSES = ("MEASURED", "DERIVED", "DEFINITIONAL", "ASSUMPTION")

# Types a generative parameter can be. `set` and `frozenset` were missing from
# the first version of this list, so an unregistered frozenset -- which is
# exactly the shape HARD_DECLINE_CODES has -- would have passed the scan
# silently. The scan reported clean and was blind to a whole category.
#
# `str` is excluded deliberately, not by the same oversight: module-level strings
# here are names and labels, not generative quantities. If a string ever becomes
# one -- a distribution name, a policy identifier -- it belongs in this tuple.
_PARAM_TYPES = (int, float, dict, list, tuple, set, frozenset)

# Numeric literals allowed inside function bodies without registration:
# probability bounds, indices, and off-by-one arithmetic.
# 0 == 0.0 and 1 == 1.0 in Python, so the float forms are covered by the ints.
_TRIVIAL_LITERALS = frozenset({0, 1, -1, 2})


def unregistered_constants(
    module: ModuleType, params: dict[str, dict], allowed: frozenset[str]
) -> list[str]:
    """Module-level numbers that no PARAMS entry claims.

    A parameter registers the module constant it stands for via `constant`.
    Anything numeric that is neither registered nor explicitly allowed is an
    unsourced, unmarked number in a system whose whole argument is provenance.
    """
    registered = {meta["constant"] for meta in params.values() if meta.get("constant")}
    offenders = []
    for name, value in vars(module).items():
        if name.startswith("__") or name in allowed or name in registered:
            continue
        if inspect.isfunction(value) or inspect.ismodule(value) or inspect.isclass(value):
            continue
        if isinstance(value, bool) or not isinstance(value, _PARAM_TYPES):
            continue
        offenders.append(name)
    return sorted(offenders)


def unregistered_literals(module: ModuleType) -> list[str]:
    """Magic numbers written inside function bodies.

    `unregistered_constants` walks module-level names, so a number typed directly
    into an expression -- `p *= 0.9` -- is invisible to it. That is the same
    class of hole as the one it was written to close, one level down. This reads
    the source, because the artifact is the code and `vars()` is a proxy for it.
    """
    source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[str] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Constant):
                continue
            if isinstance(node.value, bool) or not isinstance(node.value, int | float):
                continue
            if node.value in _TRIVIAL_LITERALS:
                continue
            offenders.append(f"{fn.name}() line {node.lineno}: {node.value}")
    return sorted(offenders)


def unread_assumptions(module: ModuleType, params: dict[str, dict]) -> list[str]:
    """Swept ASSUMPTIONs that no constant in the module implements.

    A parameter declared ASSUMPTION with a sweep range, which nothing actually
    reads, is worse than an undeclared one. The sensitivity analysis will vary it,
    observe no change, and report the result as INSENSITIVE -- manufacturing
    evidence of robustness from a parameter that was never wired up.

    A sweep dimension that cannot move the model is a false negative in the one
    analysis whose job is to find false negatives.
    """
    problems = []
    for name, meta in params.items():
        if meta.get("class") != "ASSUMPTION" or "sweep" not in meta:
            continue
        constant = meta.get("constant")
        if not constant:
            problems.append(f"{name}: ASSUMPTION with a sweep but no `constant` to vary")
            continue
        if not hasattr(module, constant):
            problems.append(f"{name}: names constant {constant!r}, which does not exist")
            continue
        # A parameter may be one entry of a container -- CHANNEL_MULTIPLIER["sms"]
        # is a swept assumption in its own right, and the sweep needs to know
        # exactly which key to move.
        key = meta.get("constant_key")
        if key is not None and key not in getattr(module, constant):
            problems.append(f"{name}: key {key!r} is not in {constant}")
    return problems


def params_problems(params: dict[str, dict]) -> list[str]:
    """Every way a registry entry can be malformed, as human-readable strings."""
    problems: list[str] = []
    for name, meta in params.items():
        cls = meta.get("class")
        if cls not in CLASSES:
            problems.append(f"{name}: class {cls!r} is not one of {CLASSES}")
            continue
        if not meta.get("source"):
            problems.append(f"{name}: no source")
        if cls == "MEASURED":
            if not str(meta.get("source", "")).startswith("http"):
                problems.append(f"{name}: MEASURED without a URL")
            if not meta.get("population"):
                problems.append(f"{name}: MEASURED without a population")
        if cls == "DERIVED" and not meta.get("derivation"):
            problems.append(f"{name}: DERIVED without a stated derivation")
        if cls == "ASSUMPTION":
            if "sweep" not in meta:
                problems.append(f"{name}: ASSUMPTION without a sweep range")
            if str(meta.get("source", "")).startswith("http"):
                problems.append(
                    f"{name}: ASSUMPTION citing a URL -- either it is sourced or it is not"
                )
        if "sweep" in meta:
            lo, hi = meta["sweep"]
            if not lo < hi:
                problems.append(f"{name}: sweep {meta['sweep']} is not an interval")
            value = meta.get("value")
            if isinstance(value, int | float) and not lo <= value <= hi:
                problems.append(f"{name}: value {value} lies outside its sweep {meta['sweep']}")
    return problems
