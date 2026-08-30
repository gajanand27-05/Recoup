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

import inspect
from types import ModuleType

CLASSES = ("MEASURED", "DERIVED", "DEFINITIONAL", "ASSUMPTION")


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
        if isinstance(value, bool) or not isinstance(value, int | float | dict | list | tuple):
            continue
        offenders.append(name)
    return sorted(offenders)


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
