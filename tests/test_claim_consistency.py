"""The narrowed claim must hold in EVERY file, not just the ones I looked at.

A-020 narrowed what the real transport demonstrates: the Payment Links are real,
the subscription context around them is synthetic. That sentence appears in
several places — README, VIDEO.md, DECISION.md, `real.py`, `run_real_demo.py`.

**A claim that is correct in one file and overstated in another is worse than
either**, because a reader finds the generous one first and stops.

Why this checks CLAUSES and not token presence
-----------------------------------------------
The first version of this file asserted that a file mentioning the claim also
mentioned "A-020" or "synthetic" somewhere. Planting the drift — restoring the
generous heading in `real.py` and in `README.md` — did not fail it, because both
files still contained those tokens elsewhere. A file could have stated the
generous claim in its headline and mentioned A-020 in a footnote and passed.

That is a proxy, not the artifact. This version requires the load-bearing clauses
themselves, normalised for wrapping and markdown, so removing or weakening the
sentence fails.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Files that state the claim to an outside reader. VIDEO.md is local-only and
# checked when present, because a rehearsal script drifting from the README is
# how the wrong sentence reaches the camera.
CLAIM_FILES = [
    REPO / "README.md",
    REPO / "scripts" / "run_real_demo.py",
    REPO / "src" / "recoup" / "execute" / "real.py",
    REPO / "VIDEO.md",
]

# Both halves must be present. The first alone overstates; the second is the part
# a reader needs and would not guess.
REQUIRED_CLAUSES = (
    "payment links were really issued against razorpay",
    "the subscription they represent",
    "were both replayed",
)

OVERSTATEMENTS = (
    "real payment links against real subscriptions",
    "against a real test-mode subscription",
    "the loop ran end-to-end against razorpay",
)


def normalise(text: str) -> str:
    """Collapse wrapping and markdown so a clause matches however it is typeset."""
    text = text.lower()
    text = text.replace("—", " ").replace("–", " ").replace("--", " ")
    text = re.sub(r"[`*_>#]", "", text)
    return re.sub(r"\s+", " ", text)


def _present() -> list[Path]:
    return [p for p in CLAIM_FILES if p.exists()]


@pytest.mark.parametrize("path", _present(), ids=lambda p: p.name)
@pytest.mark.parametrize("clause", REQUIRED_CLAUSES)
def test_every_claim_file_carries_the_narrowed_claim(path, clause):
    assert clause in normalise(path.read_text(encoding="utf-8")), (
        f"{path.name} does not state {clause!r}. The narrowed claim must appear "
        "wherever the claim appears, or a reader finds the generous version first."
    )


# A file may QUOTE the superseded wording while correcting it — that is how the
# narrowing is explained. It may not ASSERT it. The difference is whether a
# correction sits next to the occurrence, so the window is checked, not the file.
_CORRECTION_MARKERS = ("a-020", "earlier wording", "an earlier version", "superseded",
                       "narrowed", "historically", "no longer")
_WINDOW = 400


@pytest.mark.parametrize("path", _present(), ids=lambda p: p.name)
def test_no_claim_file_asserts_more_than_a_020_permits(path):
    body = normalise(path.read_text(encoding="utf-8"))
    for phrase in OVERSTATEMENTS:
        start = 0
        while (at := body.find(phrase, start)) != -1:
            window = body[max(0, at - _WINDOW) : at + len(phrase) + _WINDOW]
            assert any(marker in window for marker in _CORRECTION_MARKERS), (
                f"{path.name} states {phrase!r} with no correction beside it. "
                f"Quoting the superseded wording is fine; asserting it is not.\n"
                f"  ...{body[max(0, at - 120):at + 160]}..."
            )
            start = at + 1


def test_the_decision_register_keeps_its_superseded_text_with_the_correction():
    """DECISION.md is the one file that KEEPS the old wording, on purpose.

    A register that gets quietly edited stops being evidence. So the superseded
    text stays and the correction sits next to it — checked here rather than
    assumed, because "we left it and noted it" and "we left it" look identical
    in a diff nobody reads.
    """
    text = (REPO / "DECISION.md").read_text(encoding="utf-8")
    d033 = text.index("D-033 · Task 17 has two branches")
    correction = text.index("Narrowed by A-020", d033)
    superseded = text.index("What it is.", d033)

    assert correction < superseded, (
        "the A-020 correction must appear BEFORE the superseded branch (b) "
        "description, or a reader meets the generous version first"
    )
    assert "synthetic" in text[correction : correction + 900]


def test_gate_one_is_described_as_blocked_not_merely_unanswered():
    """Unanswered invites "just go and look". Blocked tells you what to do."""
    assert "blocked behind an earlier step" in (REPO / "DECISION.md").read_text(
        encoding="utf-8"
    )


# --- the probe that established the finding -------------------------------------


def test_the_probe_that_established_this_is_recorded():
    probe = REPO / "src" / "recoup" / "execute" / "fixtures" / "api_probe_2026-09-01.json"
    doc = json.loads(probe.read_text(encoding="utf-8"))

    assert doc["provenance"]["mutating"] is False
    assert doc["results"]["plans"] == 401
    assert doc["results"]["subscriptions"] == 401
    assert len([k for k, v in doc["results"].items() if v == 200]) == 7
    assert "not enabled" in doc["finding"]


def test_the_probe_records_no_secret():
    """Only the key PREFIX. The id identifies the account; the secret must never
    be written anywhere."""
    probe = REPO / "src" / "recoup" / "execute" / "fixtures" / "api_probe_2026-09-01.json"
    doc = json.loads(probe.read_text(encoding="utf-8"))
    assert doc["provenance"]["key_id_prefix"] == "rzp_test_"
    assert "key_secret" not in probe.read_text(encoding="utf-8")
