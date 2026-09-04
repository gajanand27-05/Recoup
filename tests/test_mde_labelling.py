"""Every MDE on a page or a card says WHICH MDE it is.

WHY
---
There are two, they differ in the second decimal place, and until 2026-09-03
nothing distinguished them:

| figure | producer | knowable |
|---|---|---|
| 6.23 pp | `mde_at_n(0.51, 1000)` -- the PRE-REGISTERED design | Day 2 |
| 6.24 pp | `mde_at_n(0.51, 998)` -- ACHIEVED at 1,035 / 965 | after the run |

Both are correct. Neither is a defect. But four artifacts showed one or the
other with no qualifier, one pair made the same claim with different numbers,
and two numbers for what reads as one quantity is indistinguishable from an
error to a careful reader -- who is exactly the reader that matters.

A-029 fixes which claim takes which: finding 1 (what THIS RUN measured) takes
the achieved figure; finding 2 (what the DESIGN could ever detect) takes the
pre-registered one, which is also the smaller of the two and therefore the
weaker version of a criticism of our own design.

WHY A DEDICATED CHECK
---------------------
The distinction now appears on two video cards, in README.md and in
EVAL_RESULTS.md -- four copies of something that did not exist an hour before
the freeze, which is four chances to have got one wrong. The stale-state sweep
would not notice: every copy is individually well-formed prose.

So this walks EVERY occurrence of either number in everything that ships and
requires the qualifier beside it. It does not sample and it does not spot-check.

THE SOURCE OF TRUTH IS THE PRODUCER, NOT THIS FILE
--------------------------------------------------
`test_the_two_figures_are_what_the_producer_computes` recomputes both from
`recoup.eval.power` rather than hardcoding them here. If the design or the arm
split ever changes, this file fails rather than silently checking for numbers
nobody produces any more -- the `aa.bound_pp` mistake in a different costume.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: The realised arms. From runs/batch-2000.summary.json, and asserted against it
#: below rather than trusted.
CONTROL_N, TREATMENT_N = 1035, 965
PREREG_N_PER_ARM = 1000

#: A qualifier this close is read as attached. Same constant and same reasoning
#: as tests/test_claims_uncompressed.py, which is the guard this one specialises.
PROXIMITY_CHARS = 220

#: WHAT THE QUALIFIER HAS TO CONVEY: the N the figure was computed at. Not one
#: particular wording.
#:
#: The first version of this required "pre-registered|by design", and flagged ten
#: passages that were already correct -- because 6.23 pp appears in a THIRD
#: context: the A/A's own power, which is `mde_at_n(0.51, 1000)` too. Same
#: arithmetic, different instrument. Those passages say "at 1,000 per arm", which
#: is the qualifier a reader needs; they just did not say the word.
#:
#: A guard that flags correct text gets switched off, so it matches the fact
#: rather than the phrasing. What it still refuses is a bare figure with no N and
#: no basis anywhere near it -- which is what the video card and README had.
_PREREG = re.compile(
    r"pre-?registered|\bdesign\b|1,000 per arm|1,000/arm|A/A", re.IGNORECASE
)
_ACHIEVED = re.compile(
    r"achieved|harmonic|this run|the arms that (?:ran|actually ran)|1,035|1035",
    re.IGNORECASE,
)

#: Documents that ship and may state an MDE. Walked, not enumerated:
#: `test_the_document_list_covers_everything_that_ships` rebuilds it from git.
DOCS = ("README.md", "EVAL_RESULTS.md", "EXPERIMENT.md", "SIMULATOR_FREEZE.md",
        "INCIDENTS.md", "SOURCES.md")


def _figures() -> tuple[str, str]:
    """Both MDEs, from the module that computes them."""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from recoup.eval.power import BASELINE_P1, mde_at_n

    harmonic = int(2 * CONTROL_N * TREATMENT_N / (CONTROL_N + TREATMENT_N))
    prereg = f"{round(mde_at_n(BASELINE_P1, PREREG_N_PER_ARM) * 100, 2):.2f}"
    achieved = f"{round(mde_at_n(BASELINE_P1, harmonic) * 100, 2):.2f}"
    return prereg, achieved


PREREG_PP, ACHIEVED_PP = _figures()


def test_the_two_figures_are_what_the_producer_computes():
    """Pins this file to `recoup.eval.power`, not to two strings someone typed.

    Without it, a change to the design or to the arms would leave these tests
    scanning for numbers that no longer exist -- passing vacuously, which is the
    failure mode this whole file is about.
    """
    assert PREREG_PP != ACHIEVED_PP, (
        "the pre-registered and achieved MDEs now round to the same value, so "
        "the distinction these tests enforce no longer has anything to enforce. "
        "Delete them deliberately rather than leaving them green over nothing."
    )
    assert PREREG_PP == "6.23" and ACHIEVED_PP == "6.24", (
        f"the MDEs moved: pre-registered {PREREG_PP}, achieved {ACHIEVED_PP}. "
        f"Every document and card carrying the old pair is now wrong."
    )


#: `runs/` is gitignored except for `*.provenance.json` (CLAUDE.md section 2), so the
#: run summary is LOCAL-ONLY. A shipped test may not require a file that stays
#: local -- that is the `59061cd` failure, and this file reproduced it: the guard
#: was green here and red in a clone, found by `test_ships_standalone`.
#:
#: Skipped rather than deleted. The drift it catches -- the arms moving while
#: these constants do not -- happens on the machine where the run lives, which is
#: exactly where the summary exists and the check runs. In a clone it is vacuous
#: and says so.
_SUMMARY = REPO / "runs" / "batch-2000.summary.json"
_NEEDS_SUMMARY = pytest.mark.skipif(
    not _SUMMARY.exists(),
    reason=f"{_SUMMARY.name} is local-only (CLAUDE.md section 2); the arm split "
           f"cannot be checked against the run from a clone",
)


@_NEEDS_SUMMARY
def test_the_arm_split_is_what_the_run_actually_produced():
    """The achieved MDE is a function of the arms. If they are not these, the
    figure this file calls 'achieved' was achieved by a different run."""
    import json

    summary = json.loads(_SUMMARY.read_text(encoding="utf-8"))
    assert summary["arms"]["control"]["subscriptions"] == CONTROL_N
    assert summary["arms"]["treatment"]["subscriptions"] == TREATMENT_N


def _orphans(text: str, figure: str, qualifier: re.Pattern) -> list[str]:
    out = []
    for match in re.finditer(rf"(?<![\d.]){re.escape(figure)}(?![\d])", text):
        lo = max(0, match.start() - PROXIMITY_CHARS)
        hi = min(len(text), match.end() + PROXIMITY_CHARS)
        if qualifier.search(text[lo:hi]):
            continue
        line = text[: match.start()].count("\n") + 1
        out.append(f"line {line}: {text[max(0, match.start() - 70): hi][:150]!r}")
    return out


def _shipped_docs() -> list[str]:
    return [d for d in DOCS if (REPO / d).exists()]


@pytest.mark.parametrize("name", _shipped_docs())
def test_every_preregistered_mde_in_a_document_says_so(name):
    text = (REPO / name).read_text(encoding="utf-8")
    orphans = _orphans(text, PREREG_PP, _PREREG)
    assert not orphans, (
        f"{name} states {PREREG_PP} pp without saying it is the PRE-REGISTERED "
        f"MDE at {PREREG_N_PER_ARM:,} per arm. The achieved figure is "
        f"{ACHIEVED_PP} pp and the two are a decimal place apart (A-029):\n  "
        + "\n  ".join(orphans)
    )


@pytest.mark.parametrize("name", _shipped_docs())
def test_every_achieved_mde_in_a_document_says_so(name):
    text = (REPO / name).read_text(encoding="utf-8")
    orphans = _orphans(text, ACHIEVED_PP, _ACHIEVED)
    assert not orphans, (
        f"{name} states {ACHIEVED_PP} pp without saying it is the ACHIEVED MDE "
        f"at {CONTROL_N:,} / {TREATMENT_N:,}. The pre-registered figure is "
        f"{PREREG_PP} pp (A-029):\n  " + "\n  ".join(orphans)
    )


def test_the_document_list_covers_everything_that_ships():
    """Walk the registry. A new shipped document stating an MDE would otherwise
    be unchecked, and nothing would announce it (CLAUDE.md, the seventh
    instance)."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    top_level = {t for t in tracked if "/" not in t}
    uncovered = {
        t for t in top_level - set(DOCS)
        if PREREG_PP in (REPO / t).read_text(encoding="utf-8")
        or ACHIEVED_PP in (REPO / t).read_text(encoding="utf-8")
    }
    assert not uncovered, (
        f"these shipped documents state an MDE but are not in DOCS, so no test "
        f"checks which one they mean: {sorted(uncovered)}"
    )
