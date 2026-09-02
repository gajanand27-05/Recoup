"""A reported figure may not derive from output nothing real produced.

The conditions that produce a stub-derived number are the ORDINARY ones: no key
configured, `-m "not llm"` in CI, a placeholder in `.env`. So the gate has to be
structural. By report time a number is a float and carries no history; the whole
job of this module is to make it carry one.
"""

import pytest

from recoup.agent.llm import DETERMINISTIC, STUB
from recoup.eval.provenance_gate import (
    DERIVED,
    MEASURED,
    SIMULATED,
    Figure,
    ProvenanceError,
    require_reportable,
)


def _ok(name="recovery_rate", value=0.51):
    return Figure(name=name, value=value, unit="", sources=frozenset({SIMULATED}))


# --- refusal at construction -----------------------------------------------------


@pytest.mark.parametrize("bad", [STUB, DETERMINISTIC, "not_run", "unset", ""])
def test_a_figure_over_forbidden_output_cannot_be_constructed(bad):
    with pytest.raises(ProvenanceError, match="derives from"):
        Figure(name="accuracy", value=0.91, unit="", sources=frozenset({bad}))


def test_a_figure_with_no_stated_sources_is_refused():
    """Different from a bad source, and refused just as loudly: 'nobody recorded
    where this came from' is not 'this came from somewhere fine'."""
    with pytest.raises(ProvenanceError, match="no sources"):
        Figure(name="accuracy", value=0.91, unit="", sources=frozenset())


def test_a_clean_figure_constructs_and_renders():
    fig = Figure(
        name="recovery_rate", value=0.5123, unit="", sources=frozenset({SIMULATED})
    )
    assert "recovery_rate" in fig.render()


def test_deterministic_MACHINERY_is_reportable_but_a_deterministic_STANDIN_is_not():
    """The distinction the module turns on. The ledger, the frozen simulator and
    the policy engine are all deterministic and all reportable. What is forbidden
    is a stand-in for something that did not happen."""
    Figure(name="control_rate", value=0.34, unit="", sources=frozenset({SIMULATED}))
    with pytest.raises(ProvenanceError):
        Figure(name="agent_rate", value=0.42, unit="", sources=frozenset({DETERMINISTIC}))


# --- the part that matters: arithmetic must not launder provenance ---------------


def test_a_lift_over_a_stubbed_arm_is_refused_at_the_moment_it_is_derived():
    """THE PLANT THIS MODULE EXISTS FOR.

    Subtract two rates and the result is a float with no history. If one arm came
    from a stub, the lift is stub-derived even though the subtraction was not.
    """
    control = Figure(name="control", value=0.34, unit="", sources=frozenset({SIMULATED}))
    # An agent arm whose actions were all deterministic fallbacks, because the
    # model was never configured. Constructing it already fails.
    with pytest.raises(ProvenanceError):
        Figure(name="agent", value=0.42, unit="", sources=frozenset({DETERMINISTIC}))

    # And if one were smuggled in with mixed sources, combining must still refuse.
    smuggled = Figure(
        name="agent", value=0.42, unit="", sources=frozenset({SIMULATED, MEASURED})
    )
    object.__setattr__(smuggled, "sources", frozenset({SIMULATED, DETERMINISTIC}))
    with pytest.raises(ProvenanceError, match="derives from"):
        control.combined_with(
            smuggled, name="lift", value=0.08, unit="pp", caveat="sim only"
        )


def test_combining_clean_figures_carries_every_source_forward():
    a = Figure(name="a", value=1.0, unit="", sources=frozenset({SIMULATED}))
    b = Figure(name="b", value=2.0, unit="", sources=frozenset({MEASURED}))
    lift = a.combined_with(b, name="lift", value=1.0, unit="pp")
    assert lift.sources == frozenset({SIMULATED, MEASURED})


def test_a_three_way_derivation_keeps_all_three():
    a = Figure(name="a", value=1.0, unit="", sources=frozenset({SIMULATED}))
    b = Figure(name="b", value=2.0, unit="", sources=frozenset({MEASURED}))
    c = Figure(name="c", value=3.0, unit="", sources=frozenset({DERIVED}))
    out = a.combined_with(b, c, name="out", value=6.0, unit="")
    assert out.sources == frozenset({SIMULATED, MEASURED, DERIVED})


# --- the whole-report gate --------------------------------------------------------


def test_a_report_with_no_figures_is_refused():
    with pytest.raises(ProvenanceError, match="no figures"):
        require_reportable(run_id="run-empty")


def test_require_reportable_names_the_run_and_the_figure():
    clean = _ok()
    dirty = _ok(name="accuracy")
    object.__setattr__(dirty, "sources", frozenset({"not_run"}))
    with pytest.raises(ProvenanceError) as exc:
        require_reportable(clean, dirty, run_id="run-2026-09-02")
    assert "run-2026-09-02" in str(exc.value)
    assert "accuracy" in str(exc.value)


def test_a_clean_set_passes():
    require_reportable(_ok(), _ok(name="cost_per_recovery"), run_id="run-ok")


# --- the specific condition we are in right now ----------------------------------


def test_a_deselected_eval_is_not_run_and_not_reportable():
    """The exact live situation: the accuracy eval is deselected by default and
    the free tier cannot complete it. `not_run` must not become a number."""
    with pytest.raises(ProvenanceError, match="not_run"):
        Figure(
            name="intent_accuracy", value=0.91, unit="", sources=frozenset({"not_run"})
        )
