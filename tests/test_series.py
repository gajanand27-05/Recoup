"""The fallback series must be a series over the RUN, not over completion order.

The defect this file exists for produced a table that looked entirely plausible:

```
      1-200   control=94   treatment=106
    201-400   control=191  treatment=9
    401-600   control=200  treatment=0
    601-800   control=200  treatment=0
```

Two windows with no treatment subscriptions at all, which reads as a broken 50/50
assignment. Assignment was fine — 48.2% treatment across all 2,000 scenarios. The
skew was duration: a control subscription makes no model calls and finishes in
milliseconds, a treatment one makes about seven and takes twenty seconds, so
control drains through the queue while treatment lags.

A window of 200 *completions* is a window of whichever arm is faster.
"""

import pytest

from recoup.batch.series import (
    FALLBACK_ALARM,
    WINDOW,
    Window,
    fallback_series,
    read_checkpoint,
    render_series,
    submission_index,
)


def _record(index: int, arm: str, decided: int, fallbacks: int) -> dict:
    return {
        "subscription_id": f"sub_sim_20260902_{index:06d}",
        "stats": {"arm": arm, "model_decided": decided, "fallbacks": fallbacks},
    }


def test_submission_index_reads_the_generated_position():
    assert submission_index("sub_sim_20260902_000042") == 42
    assert submission_index("sub_sim_20260902_001999") == 1999


def test_an_id_without_an_index_sorts_first_rather_than_silently_interleaving():
    assert submission_index("sub_handmade") == -1


# --- THE ORDERING DEFECT ------------------------------------------------------


def test_windows_are_index_ranges_not_completion_ranks():
    """The plant, permanent.

    Completions arrive in an order unrelated to submission: every control
    subscription finishes before any treatment one. If windows were built from
    completion rank, the first window would be all control and the last all
    treatment. Built from the index, each window has both.
    """
    records = []
    # All control first — the real run's completion order, exaggerated.
    for i in range(0, 400, 2):
        records.append(_record(i, "control", 0, 0))
    for i in range(1, 400, 2):
        records.append(_record(i, "treatment", 10, 1))

    windows = fallback_series(records, window=WINDOW)
    by_range: dict[tuple[int, int], set[str]] = {}
    for w in windows:
        by_range.setdefault((w.start, w.end), set()).add(w.arm)

    assert by_range, "no windows produced"
    for (start, end), arms in by_range.items():
        assert arms == {"control", "treatment"}, (
            f"window {start}-{end} contains only {arms}. The series is ordered by "
            f"completion, so a window is whichever arm finished faster rather than "
            f"a slice of the run."
        )


def test_a_window_label_matches_the_indices_it_contains():
    """Sorting alone was not enough, and the difference is invisible in output.

    With a run in progress the completed set is not a contiguous prefix, so
    slicing a sorted list into chunks of 200 gives windows whose boundaries are
    RANKS while their labels say index ranges.
    """
    # Indices 0-99 and 1000-1099 completed; nothing between.
    records = [_record(i, "treatment", 10, 1) for i in range(100)]
    records += [_record(i, "treatment", 10, 1) for i in range(1000, 1100)]

    windows = fallback_series(records, window=200)
    ranges = sorted({(w.start, w.end) for w in windows})
    assert ranges == [(1, 200), (1001, 1200)], (
        f"windows {ranges} — a rank-sliced series would report (1,200) and "
        f"(201,400), labelling index 1000+ subscriptions as the second 200"
    )


# --- the rate ------------------------------------------------------------------


def test_the_rate_is_fallbacks_over_decisions():
    windows = fallback_series([_record(0, "treatment", 90, 10)], window=200)
    treatment = next(w for w in windows if w.arm == "treatment")
    assert treatment.rate == pytest.approx(0.10)


def test_a_control_window_has_no_rate_rather_than_a_zero_one():
    """The control calls no model. Printing 0.0% invites comparison with the
    treatment arm's rate, which would be comparing a number to its absence."""
    windows = fallback_series([_record(0, "control", 0, 0)], window=200)
    control = next(w for w in windows if w.arm == "control")
    assert control.total == 0
    assert "n/a" in "\n".join(render_series(windows))


def test_a_window_over_the_alarm_is_flagged():
    windows = fallback_series([_record(0, "treatment", 80, 20)], window=200)
    treatment = next(w for w in windows if w.arm == "treatment")
    assert treatment.rate > FALLBACK_ALARM
    assert treatment.is_alarming
    rendered = "\n".join(render_series(windows))
    assert "exceeded" in rendered and "INCIDENTS" in rendered


def test_a_window_under_the_alarm_is_not_flagged():
    windows = fallback_series([_record(0, "treatment", 95, 5)], window=200)
    assert not next(w for w in windows if w.arm == "treatment").is_alarming


# --- the interpretation travels with the numbers --------------------------------


def test_a_stable_rate_says_the_bias_is_constant():
    records = [_record(i, "treatment", 95, 5) for i in range(0, 600, 3)]
    rendered = "\n".join(render_series(fallback_series(records, window=200)))
    assert "stable" in rendered
    assert "constant" in rendered


def test_a_rising_rate_says_the_bias_is_NOT_constant():
    """5% closing is consistent with 5% throughout and with 1% rising to 12%.
    Those are different claims about the bias, so the series says which."""
    records = [_record(i, "treatment", 99, 1) for i in range(0, 200, 2)]
    records += [_record(i, "treatment", 80, 20) for i in range(400, 600, 2)]
    rendered = "\n".join(render_series(fallback_series(records, window=200)))
    assert "rose" in rendered
    assert "NOT constant" in rendered


def test_an_empty_checkpoint_renders_a_sentence_rather_than_an_empty_table():
    assert render_series([]) == ["_no completed subscriptions_"]


def test_a_missing_checkpoint_is_empty_rather_than_an_error(tmp_path):
    assert read_checkpoint(tmp_path / "nope.jsonl") == []


def test_a_torn_final_line_is_skipped(tmp_path):
    """A kill mid-write leaves partial JSON. Treating that as corruption would
    mean an interrupted run could never be analysed."""
    path = tmp_path / "cp.jsonl"
    path.write_text(
        '{"subscription_id": "sub_sim_1_000001", "stats": {"arm": "control"}}\n'
        '{"subscription_id": "sub_sim_1_00',
        encoding="utf-8",
    )
    assert len(read_checkpoint(path)) == 1


def test_the_window_size_and_alarm_are_stated_constants():
    """Thresholds chosen after seeing a series are not thresholds."""
    assert WINDOW > 0
    assert 0.0 < FALLBACK_ALARM < 1.0
    assert isinstance(Window(1, 200, "treatment", 10, 1).rate, float)
