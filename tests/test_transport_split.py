"""The failure this pins is not a mislabelled row -- those are hard now. It is a
report that finds every row saying `sim`, presents one pooled number, and never
says the split was empty. Nothing is wrong with the data; the output is silently
missing the caveat that makes it honest.
"""

import pytest

from recoup.eval.transport_split import (
    TransportSplit,
    require_declared_split,
    summarise,
)


def _rows(real: int = 0, sim: int = 0) -> list[dict]:
    return [{"transport": "real"}] * real + [{"transport": "sim"}] * sim


def test_an_all_sim_run_is_reportable_but_says_so():
    split = summarise(_rows(sim=2000))
    assert split.is_pooled_reporting_safe is True
    assert split.sole_transport == "sim"
    assert "No event in this run came from Razorpay" in split.caveat()


def test_an_all_real_run_says_the_simulator_was_not_used():
    split = summarise(_rows(real=12))
    assert split.sole_transport == "real"
    assert "simulator was not used" in split.caveat()


def test_a_mixed_run_refuses_to_pool():
    # The case D-009 forbids: one figure mixing a real outcome with a modelled one.
    with pytest.raises(ValueError, match="refusing to pool run 'run-1'"):
        require_declared_split(_rows(real=4, sim=1996), run_id="run-1")


def test_a_mixed_run_names_both_counts_so_the_split_can_be_reported():
    split = summarise(_rows(real=4, sim=1996))
    assert split.is_pooled_reporting_safe is False
    assert split.sole_transport is None
    assert "4 real and 1996 simulated" in split.caveat()


def test_an_empty_finished_run_is_an_error_naming_that_run():
    # Not a generic "nothing was measured" -- that is indistinguishable from a
    # mid-run view, and the fix under pressure would be to soften the predicate.
    with pytest.raises(ValueError, match="run 'run-2026-08-30'"):
        require_declared_split([], run_id="run-2026-08-30")


def test_a_partial_state_has_a_path_that_does_not_raise():
    # A mid-run view, or a fixture with no rows yet, must have somewhere to go
    # other than through the gate. Otherwise the gate is what gets loosened.
    split = summarise([])
    assert split.total == 0
    assert split.is_pooled_reporting_safe is False
    assert "Nothing was measured" in split.caveat()


def test_the_escape_hatch_still_refuses_bad_data():
    # summarise() tolerates an incomplete run. It does not tolerate a row that
    # never declared its transport -- that is corruption, not incompleteness.
    with pytest.raises(ValueError, match="unknown transport"):
        summarise([{"transport": None}])


def test_an_unknown_transport_value_stops_everything():
    # A third value would mean some row was written by a path that never declared
    # itself. Nothing downstream can be trusted until that is explained.
    with pytest.raises(ValueError, match="unknown transport"):
        summarise([{"transport": "real"}, {"transport": "mock"}])


def test_a_missing_transport_is_treated_as_unknown_not_as_sim():
    with pytest.raises(ValueError, match="unknown transport"):
        summarise([{"transport": "sim"}, {}])


def test_a_legitimate_pooled_run_returns_the_split_for_the_caveat():
    split = require_declared_split(_rows(sim=5), run_id="run-ok")
    assert split == TransportSplit(real=0, sim=5)
    assert split.total == 5


def test_the_caveat_is_never_empty():
    # Whatever the shape of the run, there is always a sentence to print. A
    # report can omit it only by choosing to.
    for rows in (_rows(), _rows(sim=1), _rows(real=1), _rows(real=1, sim=1)):
        assert summarise(rows).caveat().strip()
