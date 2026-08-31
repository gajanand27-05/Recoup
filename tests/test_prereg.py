"""The pre-registration must predate every run artifact.

`EXPERIMENT.md` is only evidence if it was committed before the numbers existed.
The date inside the file proves nothing -- it is written by whoever writes the
file. What is checkable is the commit that added it, against the timestamps of
rows in any ledger that exists.

This is cheap now and impossible to reconstruct later: once a run has happened,
no amount of care recovers the ordering that was not established.
"""

from pathlib import Path

from recoup.eval.prereg import check_prereg_order, experiment_commit_time
from recoup.ledger.store import Ledger

REPO = Path(__file__).resolve().parents[1]


def _row(ts: str, sub: str = "sub_1") -> dict:
    return {
        "run_id": "run-test",
        "ts": ts,
        "event_type": "webhook.received",
        "subscription_id": sub,
        "customer_id": "cust_1",
        "arm": None,
        "transport": "sim",
        "payload": {"event": "subscription.halted"},
    }


# --- the real repository ------------------------------------------------------------


def test_experiment_md_has_a_commit_time():
    when = experiment_commit_time(REPO)
    assert when is not None, "EXPERIMENT.md is not committed -- the pre-registration has no date"


def test_this_repository_currently_satisfies_the_ordering():
    result = check_prereg_order(REPO, REPO / "runs")
    assert result.verified, result.reason
    assert result.ok, result.reason


# --- the planted failure ---------------------------------------------------------------
# The guard above passes vacuously today, because `runs/` holds nothing. A guard
# that has never been shown to fire is an assumption. These construct the exact
# violation it exists to catch.


def test_a_ledger_row_predating_the_prereg_is_caught(tmp_path):
    runs = tmp_path / "runs"
    lg = Ledger(str(runs / "old.db"))
    lg.append(_row("2020-01-01T00:00:00Z"))  # long before EXPERIMENT.md was committed

    result = check_prereg_order(REPO, runs)
    assert result.verified
    assert not result.ok
    assert result.rows_before, "the offending row must be reported, not just a boolean"
    db, seq, ts = result.rows_before[0]
    assert "old.db" in db
    assert ts == "2020-01-01T00:00:00Z"


def test_the_offending_rows_are_named_so_the_run_can_be_identified(tmp_path):
    runs = tmp_path / "runs"
    lg = Ledger(str(runs / "batch-a.db"))
    lg.append(_row("2019-06-01T12:00:00Z", sub="sub_x"))
    lg.append(_row("2019-06-01T12:00:01Z", sub="sub_y"))

    result = check_prereg_order(REPO, runs)
    assert len(result.rows_before) == 2
    assert all("batch-a.db" in db for db, _, _ in result.rows_before)


def test_a_ledger_written_after_the_prereg_is_fine(tmp_path):
    runs = tmp_path / "runs"
    lg = Ledger(str(runs / "new.db"))
    lg.append(_row("2099-01-01T00:00:00Z"))

    result = check_prereg_order(REPO, runs)
    assert result.ok, result.reason


def test_a_mixed_ledger_is_caught_on_its_earliest_row(tmp_path):
    # A run that started before the prereg and continued after is still a violation.
    runs = tmp_path / "runs"
    lg = Ledger(str(runs / "mixed.db"))
    lg.append(_row("2020-01-01T00:00:00Z"))
    lg.append(_row("2099-01-01T00:00:00Z"))

    result = check_prereg_order(REPO, runs)
    assert not result.ok
    assert len(result.rows_before) == 1


# --- silence must not read as success ------------------------------------------------


def test_an_absent_runs_directory_is_a_pass_not_an_error(tmp_path):
    result = check_prereg_order(REPO, tmp_path / "does_not_exist")
    assert result.verified
    assert result.ok


def test_an_unverifiable_check_is_not_reported_as_ok(tmp_path):
    """If the prereg commit cannot be found, the answer is 'cannot verify'.

    `ok` alone would be True for a repository where EXPERIMENT.md was never
    committed -- the strongest possible reading of the weakest possible evidence.
    `verified` is separate precisely so a caller cannot mistake one for the other.
    """
    result = check_prereg_order(tmp_path, tmp_path / "runs")  # not a git repo
    assert result.verified is False
    assert "cannot" in result.reason.lower() or "not found" in result.reason.lower()


def test_runs_present_but_no_prereg_commit_is_a_violation(tmp_path):
    # The worst case: numbers exist and nothing was pre-registered.
    runs = tmp_path / "runs"
    Ledger(str(runs / "x.db")).append(_row("2099-01-01T00:00:00Z"))

    result = check_prereg_order(tmp_path, runs)
    assert result.ok is False
    assert result.verified is False


# --- timestamp handling -----------------------------------------------------------------


def test_timezone_offsets_are_compared_correctly(tmp_path):
    """The prereg commit date carries +05:30; ledger rows are UTC with Z.

    Comparing them as strings, or dropping the offset, would put a row five and a
    half hours on the wrong side of the boundary -- and the boundary is the
    entire claim.
    """
    when = experiment_commit_time(REPO)
    assert when is not None
    assert when.tzinfo is not None, "a naive commit time would compare against UTC by accident"

    runs = tmp_path / "runs"
    lg = Ledger(str(runs / "edge.db"))
    # One second after the prereg commit, expressed in UTC.
    from datetime import timedelta

    from recoup.clock import to_iso_z

    lg.append(_row(to_iso_z(when + timedelta(seconds=1))))
    assert check_prereg_order(REPO, runs).ok

    lg2 = Ledger(str(runs / "edge2.db"))
    lg2.append(_row(to_iso_z(when - timedelta(seconds=1))))
    assert not check_prereg_order(REPO, runs).ok
