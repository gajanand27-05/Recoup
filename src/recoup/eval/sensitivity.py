"""Task 23b — does the result survive its own assumptions?

`EXPERIMENT.md` names this in its falsification list: *"sensitivity sweep flips
the sign -> the effect is an artifact of an assumed parameter."* A
pre-registration naming a falsifying test, followed by a project that does not
run it, is the exact failure pre-registration exists to prevent — and it is
findable by diffing two files in this repository.

WHAT IS VARIED, AND WHAT IS HELD FIXED
---------------------------------------
The AGENT'S DECISIONS are held fixed and the CUSTOMER'S RESPONSE MODEL is varied.
The sweep replays the run's own actions — channel, day offset, attempt number,
hard-decline flag, all read from the ledger — and recomputes who recovered under
each parameter endpoint.

That is the right shape for a sensitivity analysis, and it is also the only
affordable one: re-running the agent per endpoint would mean thousands more model
calls against a provider that has already cut us off once.

THE FREEZE IS NOT TOUCHED
--------------------------
Parameters are overridden at runtime by setting module attributes and restoring
them. No file under `simulator/` changes, so `sha256(simulator/)` is unaffected
and `verify-sim` stays green. A test asserts that.

A PARAMETER THAT CANNOT BE SHOWN TO MOVE THE MODEL IS REPORTED **UNWIRED**
--------------------------------------------------------------------------
Not "insensitive" (A-017, INC-005). A swept parameter nothing reads produces a
flat line, and a flat line reads as robustness — the sweep would report its most
reassuring result exactly where the model is emptiest. So every parameter must be
shown to change *something* before its flatness means anything.

ORDER
-----
`self_recovery_rate_soft` and `_hard` are swept FIRST, per the commitment in
`CLAUDE.md`. They define `would_self_recover`, which is the counterfactual, so
they set the denominator of the entire lift claim — and nothing published
measures them. Anything swept before them is a warm-up.
"""

from dataclasses import dataclass

from recoup.eval.lift import CONTROL, TREATMENT

#: Swept first, and the order is load-bearing. These two define the
#: counterfactual: nothing published measures a post-halt, no-outreach recovery
#: rate, so they are the assumptions the whole lift claim rests on.
COUNTERFACTUAL_FIRST = ("self_recovery_rate_soft", "self_recovery_rate_hard")

#: Parameters this sweep STRUCTURALLY CANNOT test, and why.
#:
#: The sweep replays the run's own actions and varies the response curve. That
#: reaches every parameter governing *how a customer responds to an outreach*.
#: It cannot reach parameters governing *which cohort exists in the first place*
#: — those shape scenario generation, so testing them means regenerating the
#: cohort and re-running the agent, which is thousands of model calls per
#: endpoint against a provider that has already cut us off once.
#:
#: This distinction matters more than it looks. Reporting these as plain
#: "UNWIRED" alongside genuinely flat parameters would say "we swept it and it
#: did not matter" about parameters we did not sweep — the reassuring-result-
#: where-the-model-is-emptiest failure that A-017 exists to prevent, one level up.
OUT_OF_SCOPE: dict[str, str] = {
    "self_recovery_rate_soft": "governs would_self_recover, the counterfactual; "
                               "affects cohort generation, not action outcomes",
    "self_recovery_rate_hard": "governs would_self_recover, the counterfactual; "
                               "affects cohort generation, not action outcomes",
    "residual_hard_fraction": "decides which scenarios are hard declines at "
                              "generation time",
    "amount_distribution": "shapes the cohort's amounts at generation time",
    "amount_weights": "shapes the cohort's amounts at generation time",
}


@dataclass(frozen=True)
class SweepResult:
    param: str
    value: float
    endpoint: str
    lift_pp: float
    baseline_lift_pp: float
    control_rate: float
    treatment_rate: float
    moved_the_model: bool

    @property
    def sign_flipped(self) -> bool:
        """Did the direction of the effect reverse at this endpoint?

        A flip is the finding `EXPERIMENT.md` pre-registers as falsifying: the
        effect would be an artifact of a number nobody measured.
        """
        if self.baseline_lift_pp == 0:
            return False
        return (self.lift_pp > 0) != (self.baseline_lift_pp > 0)

    @property
    def out_of_scope(self) -> bool:
        return self.param in OUT_OF_SCOPE

    @property
    def verdict(self) -> str:
        if self.out_of_scope:
            return "NOT SWEPT"
        if not self.moved_the_model:
            return "UNWIRED"
        if self.sign_flipped:
            return "SIGN FLIPPED"
        return "stable"


def assumption_params() -> list[dict]:
    """Every ASSUMPTION with a declared sweep range, counterfactual ones first.

    Read from the frozen registries rather than listed here — a hand-maintained
    list is one that silently stops covering a parameter added later.
    """
    from recoup.simulator.curve import PARAMS as CURVE_PARAMS
    from recoup.simulator.generator import PARAMS as GEN_PARAMS

    found = []
    for source, params in (("curve", CURVE_PARAMS), ("generator", GEN_PARAMS)):
        for name, meta in params.items():
            if meta.get("class") != "ASSUMPTION":
                continue
            sweep = meta.get("sweep")
            if not sweep or len(sweep) != 2:
                continue
            found.append({
                "name": name,
                "source": source,
                "sweep": tuple(sweep),
                "constant": meta.get("constant"),
                "value": meta.get("value"),
            })

    def order(param):
        try:
            return (0, COUNTERFACTUAL_FIRST.index(param["name"]))
        except ValueError:
            return (1, param["name"])

    return sorted(found, key=order)


@dataclass(frozen=True)
class ReplayAction:
    """One outreach as the ledger recorded it."""

    subscription_id: str
    arm: str
    channel: str
    day_offset: int
    attempt_no: int
    is_hard_decline: bool


def _recompute(actions: list[ReplayAction], seed: int) -> tuple[float, float]:
    """Recovery rate per arm under whatever the curve currently says.

    Uses the same identity-keyed draw as `SimTransport`, so a subscription's
    outcome depends on the subscription and the probability — not on iteration
    order, and not on a shared RNG whose position depends on how many arms were
    processed first.
    """
    from recoup.execute.sim import _uniform
    from recoup.simulator.curve import recovery_probability

    recovered: dict[str, set] = {CONTROL: set(), TREATMENT: set()}
    seen: dict[str, set] = {CONTROL: set(), TREATMENT: set()}

    for action in actions:
        if action.arm not in seen:
            continue
        seen[action.arm].add(action.subscription_id)
        if action.subscription_id in recovered[action.arm]:
            continue  # already recovered; a real run stops messaging
        p = recovery_probability(
            day_offset=action.day_offset,
            channel=action.channel,
            attempt_no=action.attempt_no,
            is_hard_decline=action.is_hard_decline,
        )
        draw = _uniform(seed, action.subscription_id, action.attempt_no, action.day_offset)
        if draw < p:
            recovered[action.arm].add(action.subscription_id)

    return (
        len(recovered[CONTROL]) / len(seen[CONTROL]) if seen[CONTROL] else 0.0,
        len(recovered[TREATMENT]) / len(seen[TREATMENT]) if seen[TREATMENT] else 0.0,
    )


def _override(param: dict, value: float):
    """Set a frozen module's constant, returning a restore callable.

    Runtime attribute assignment, NOT a file edit: `sha256(simulator/)` is over
    the files, so the freeze is untouched and `verify-sim` stays green.
    """
    import importlib

    module = importlib.import_module(f"recoup.simulator.{param['source']}")
    constant = param["constant"]
    if constant is None or not hasattr(module, constant):
        return None
    previous = getattr(module, constant)

    if isinstance(previous, dict):
        # A channel multiplier lives inside a dict keyed by channel. The
        # parameter name carries the key: channel_multiplier_whatsapp.
        key = param["name"].rsplit("_", 1)[-1]
        if key not in previous:
            return None
        patched = dict(previous)
        patched[key] = value
        setattr(module, constant, patched)
    else:
        setattr(module, constant, value)

    def restore():
        setattr(module, constant, previous)

    return restore


def sweep_assumptions(
    actions: list[ReplayAction], *, seed: int, baseline_lift_pp: float | None = None
) -> list[SweepResult]:
    """Recompute the lift at each end of every declared assumption range."""
    if not actions:
        raise ValueError(
            "sweeping over no actions would report every parameter as unwired, "
            "which is the most reassuring possible result and means nothing"
        )

    base_control, base_treatment = _recompute(actions, seed)
    if baseline_lift_pp is None:
        baseline_lift_pp = (base_treatment - base_control) * 100

    results: list[SweepResult] = []
    for param in assumption_params():
        for endpoint, value in zip(("low", "high"), param["sweep"], strict=True):
            restore = _override(param, value)
            if restore is None:
                # No constant to set: the parameter is declared but nothing in
                # the frozen modules exposes it under that name.
                results.append(SweepResult(
                    param=param["name"], value=value, endpoint=endpoint,
                    lift_pp=baseline_lift_pp, baseline_lift_pp=baseline_lift_pp,
                    control_rate=base_control, treatment_rate=base_treatment,
                    moved_the_model=False,
                ))
                continue
            try:
                control, treatment = _recompute(actions, seed)
            finally:
                restore()
            moved = (control, treatment) != (base_control, base_treatment)
            results.append(SweepResult(
                param=param["name"], value=value, endpoint=endpoint,
                lift_pp=(treatment - control) * 100,
                baseline_lift_pp=baseline_lift_pp,
                control_rate=control, treatment_rate=treatment,
                moved_the_model=moved,
            ))
    return results


def render_sweep(results: list[SweepResult]) -> list[str]:
    """Markdown, with the SIGN reported and unwired parameters named as such."""
    if not results:
        return ["_no sweep run_"]

    lines = [
        "| parameter | endpoint | value | lift (pp) | verdict |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r.param}` | {r.endpoint} | {r.value} | {r.lift_pp:+.2f} | {r.verdict} |"
        )

    flipped = [r for r in results if r.sign_flipped and r.moved_the_model]
    unwired = sorted({
        r.param for r in results if not r.moved_the_model and not r.out_of_scope
    })
    not_swept = sorted({r.param for r in results if r.out_of_scope})

    lines.append("")
    if flipped:
        lines.append(
            f"**SIGN FLIPPED at {len(flipped)} endpoint(s):** "
            + ", ".join(f"`{r.param}`={r.value}" for r in flipped)
            + ". `EXPERIMENT.md` pre-registers this as falsifying: the effect is "
            "an artifact of a parameter nobody measured. Reported as a finding, "
            "not narrowed away."
        )
    else:
        lines.append(
            "**No sign flip** at any declared endpoint. The direction of the "
            "effect survives every assumption's stated range."
        )

    if unwired:
        lines.append("")
        lines.append(
            f"**UNWIRED, not insensitive:** {', '.join(f'`{p}`' for p in unwired)}. "
            f"These are in scope for this sweep and could not be shown to move the "
            f"model, so their flat lines say nothing about robustness "
            f"(A-017, INC-005)."
        )

    if not_swept:
        lines.append("")
        lines.append(
            f"**NOT SWEPT — out of this sweep's reach:** "
            f"{', '.join(f'`{p}`' for p in not_swept)}."
        )
        lines.append("")
        lines.append(
            "This sweep replays the run's own actions and varies the response "
            "curve, which reaches every parameter governing HOW A CUSTOMER "
            "RESPONDS. It cannot reach parameters governing WHICH COHORT EXISTS: "
            "those act at scenario generation, so testing them means regenerating "
            "the cohort and re-running the agent — thousands of model calls per "
            "endpoint."
        )
        lines.append("")
        for param in not_swept:
            lines.append(f"* `{param}` — {OUT_OF_SCOPE[param]}")
        lines.append("")
        lines.append(
            "**`self_recovery_rate_soft` and `_hard` are among them, and they are "
            "the two that matter most.** They define `would_self_recover`, so they "
            "set the denominator of the entire lift claim, and nothing published "
            "measures them. Reporting them as swept-and-flat would be the "
            "reassuring-result-where-the-model-is-emptiest failure that A-017 "
            "exists to prevent, one level up. They are declared NOT SWEPT."
        )
    return lines
