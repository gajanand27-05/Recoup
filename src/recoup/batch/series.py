"""The fallback rate over the run, per arm, per window.

WHY A SERIES AND NOT A CLOSING NUMBER
--------------------------------------
The fallback rate is the input to the toward-null bias argument in
`EXPERIMENT.md` Addendum 2: a schema violation drives a `DETERMINISTIC`-labelled
fallback, which behaves like a control action, so violations pull measured lift
toward null.

That argument needs the rate to be *characterised*, not summarised. A closing
figure of 5% is consistent with a run that sat at 5% throughout and with one that
began at 1% and ended at 12% — and those are different claims about the bias. A
rising rate means the treatment arm was progressively becoming the control arm,
and the second half of the run measures something different from the first.

So: per arm, per window, printed in the report. The control calls no model, so
its rate is structurally zero — kept in the table rather than dropped, because a
control arm that ever shows a non-zero fallback rate means something has gone
badly wrong with arm assignment.

WHY IT ORDERS BY SUBMISSION INDEX AND NOT BY COMPLETION
--------------------------------------------------------
The checkpoint is written in **completion** order, and the first version of this
module windowed on it. That was wrong, and wrong in a way that produced a
plausible table:

```
      1-200   control=94   treatment=106
    201-400   control=191  treatment=9
    401-600   control=200  treatment=0     <-- no treatment at all
    601-800   control=200  treatment=0
```

Assignment is fine — 48.2% treatment across all 2,000 scenarios. The skew is
entirely an artifact of *duration*. A control subscription makes no model calls
and finishes in milliseconds; a treatment subscription makes about seven and
takes twenty seconds. So control drains through the queue while treatment lags,
and a window of 200 *completions* is a window of whichever arm is faster.

Ordering by the **submission index** — parsed from `sub_sim_<seed>_<index>` —
restores the thing "over the run" was supposed to mean. This is the
INC-005 shape: a series that was registered, computed and rendered, whose
ordering was not what its label said.
"""

import json
from dataclasses import dataclass
from pathlib import Path

#: ASSUMPTION: 200 subscriptions per window. Small enough that a drift within the
#: run is visible, large enough that a single subscription does not move the rate
#: by more than half a point. Chosen before looking at the series. Range 100..500.
WINDOW = 200

#: ASSUMPTION: a window above this is a finding rather than noise, and gets an
#: INCIDENTS entry. At 10% one treatment action in ten is a control action, which
#: is enough to matter to a lift figure whose MDE is 6.23pp. Range 0.05..0.25.
FALLBACK_ALARM = 0.10


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    arm: str
    model_decided: int
    fallbacks: int

    @property
    def total(self) -> int:
        return self.model_decided + self.fallbacks

    @property
    def rate(self) -> float:
        return self.fallbacks / self.total if self.total else 0.0

    @property
    def is_alarming(self) -> bool:
        return self.total > 0 and self.rate > FALLBACK_ALARM


def read_checkpoint(path: str | Path) -> list[dict]:
    """Completed subscriptions in completion order. Torn final lines are skipped.

    A kill mid-write leaves a partial JSON line; treating that as corruption
    would mean an interrupted run could never be analysed, which is the opposite
    of what the checkpoint is for.
    """
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def submission_index(subscription_id: str) -> int:
    """The scenario's position in the generated batch, from `sub_sim_<seed>_<i>`.

    Returns -1 for an id that does not carry one, so an unparseable id sorts
    first and is visible rather than silently interleaved.
    """
    tail = subscription_id.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def fallback_series(records: list[dict], window: int = WINDOW) -> list[Window]:
    """Per-arm fallback counts for each window of `window` subscriptions.

    Ordered by SUBMISSION index, not by completion — see the module docstring.
    Sorting here rather than asking the caller to: a caller who forgets gets a
    table that looks right and means something else.
    """
    # BUCKET BY INDEX, not by rank among the completed records. Sorting alone was
    # not enough and the difference is invisible in the output: with the run in
    # progress the completed set is not a contiguous prefix, so slicing the
    # sorted list into chunks of 200 gives windows whose boundaries are ranks
    # while their LABELS say index ranges. Two windows then showed zero treatment
    # subscriptions, which read as an assignment failure and was a labelling one.
    buckets: dict[int, dict[str, list[int]]] = {}
    for record in records:
        index = submission_index(record["subscription_id"])
        if index < 0:
            continue
        stats = record.get("stats") or {}
        arm = stats.get("arm")
        if arm is None:
            continue
        by_arm = buckets.setdefault(index // window, {})
        counts = by_arm.setdefault(arm, [0, 0])
        counts[0] += int(stats.get("model_decided", 0))
        counts[1] += int(stats.get("fallbacks", 0))

    out: list[Window] = []
    for bucket in sorted(buckets):
        for arm in sorted(buckets[bucket]):
            decided, fallbacks = buckets[bucket][arm]
            out.append(
                Window(
                    start=bucket * window + 1,
                    end=(bucket + 1) * window,
                    arm=arm,
                    model_decided=decided,
                    fallbacks=fallbacks,
                )
            )
    return out


def render_series(windows: list[Window]) -> list[str]:
    """Markdown rows, plus a line saying what the series shows.

    The interpretation is printed with the numbers rather than left to a reader,
    because "5%" and "1% rising to 12%" look identical in a closing figure.
    """
    if not windows:
        return ["_no completed subscriptions_"]

    lines = ["| subscriptions | arm | model-decided | fallbacks | rate |", "|---|---|---|---|---|"]
    for w in windows:
        flag = " (!)" if w.is_alarming else ""
        rate = "n/a — no model" if w.total == 0 else f"{w.rate:.1%}{flag}"
        lines.append(
            f"| {w.start}–{w.end} | {w.arm} | {w.model_decided} | {w.fallbacks} | {rate} |"
        )

    treatment = [w for w in windows if w.arm == "treatment" and w.total > 0]
    if len(treatment) >= 2:
        first, last = treatment[0].rate, treatment[-1].rate
        drift = last - first
        lines.append("")
        if abs(drift) < 0.02:
            lines.append(
                f"**The rate is stable** across the run: {first:.1%} to {last:.1%}. "
                f"The toward-null bias is roughly constant, so it applies evenly "
                f"to the whole figure."
            )
        else:
            direction = "rose" if drift > 0 else "fell"
            lines.append(
                f"**The rate {direction}** across the run: {first:.1%} to {last:.1%} "
                f"({drift:+.1%}). The toward-null bias is therefore NOT constant — "
                f"the later part of the run had a treatment arm that was "
                f"{'more' if drift > 0 else 'less'} often behaving as the control."
            )

    alarming = [w for w in windows if w.is_alarming]
    if alarming:
        lines.append("")
        lines.append(
            f"**(!) {len(alarming)} window(s) exceeded {FALLBACK_ALARM:.0%}** — recorded "
            f"in `INCIDENTS.md`, not left in a table."
        )
    return lines
