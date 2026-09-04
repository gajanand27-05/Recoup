"""The lift figure never appears without the code that produced it.

CLAUDE.md section 4: a long-running process is pinned to the code it loaded, so
"every place the figure appears must name THAT commit, not HEAD." Until the
freeze sweep on 2026-09-03 that was a rule nothing enforced -- README stated
+1.45 pp in its headline block and named the pins fifty-eight lines later, under
a different heading. Presence is satisfied by a section further down; a reader
looking at the number is not.

Same reasoning as tests/test_claims_uncompressed.py: PROXIMITY, not presence.

WALKS THE MANIFEST, NOT A LIST OF COMMITS
-----------------------------------------
The pins come from `runs/batch-2000.provenance.json`. When a fourth pin is added
-- as a third one was, after INC-012 -- this checks for whatever the manifest
says rather than for three strings someone typed here. A guard that enumerates a
fixed subset of what it protects protects only what it happened to list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "runs" / "batch-2000.provenance.json"

#: Documents that state the figure to a reader. Local-only ones are checked when
#: present and skipped when not, like the compression guard's candidate list.
CANDIDATES = ("README.md", "EVAL_RESULTS.md", "VIDEO.md", "SUBMISSION.md",
              "INCIDENTS.md", "LOGS.md")

#: Wide enough to span a headline block and the line under it, narrow enough that
#: a section further down does not count. Chosen before running the sweep.
PROXIMITY_CHARS = 900

_LIFT = re.compile(r"\+1\.45\s*pp")


def _pins() -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [p["short"] for p in data["code_pins"]]


PINS = _pins()


def test_the_manifest_still_has_pins_to_look_for():
    """A guard whose subject does not exist has never been shown to fire. If the
    manifest lost its pins, every check below would pass on nothing."""
    assert len(PINS) >= 2, (
        f"the run manifest lists {len(PINS)} code pin(s). If the run genuinely "
        f"has one pin this file should be simplified deliberately, not left "
        f"green over a provenance claim it is no longer testing."
    )


def _provenance_pattern() -> re.Pattern:
    """Any pin, or an explicit pointer to the manifest. Naming one pin is enough:
    a reader who sees `487fc45` beside the number knows the figure is pinned and
    where to look. Requiring all three would fail prose that is doing its job."""
    return re.compile(
        "|".join([*map(re.escape, PINS), r"provenance\.json", r"code pins?"]),
        re.IGNORECASE,
    )


def _orphans(text: str) -> list[str]:
    pattern = _provenance_pattern()
    out = []
    for match in _LIFT.finditer(text):
        lo = max(0, match.start() - PROXIMITY_CHARS)
        hi = min(len(text), match.end() + PROXIMITY_CHARS)
        if pattern.search(text[lo:hi]):
            continue
        out.append(f"line {text[: match.start()].count(chr(10)) + 1}")
    return out


def _present() -> list[str]:
    return [n for n in CANDIDATES if (REPO / n).exists()]


@pytest.mark.parametrize("name", _present())
def test_the_lift_never_appears_without_its_pins(name):
    orphans = _orphans((REPO / name).read_text(encoding="utf-8"))
    assert not orphans, (
        f"{name} states +1.45 pp with no code pin and no pointer to "
        f"runs/batch-2000.provenance.json within {PROXIMITY_CHARS} characters: "
        f"{orphans}.\nThe run spans {len(PINS)} pins ({', '.join(PINS)}); a "
        f"figure quoted without them reads as HEAD's, and it is not."
    )


def test_at_least_one_document_actually_states_the_figure():
    """Otherwise every check above passes over a corpus that never mentions it."""
    stating = [n for n in _present() if _LIFT.search((REPO / n).read_text(encoding="utf-8"))]
    assert stating, "no shipped document states +1.45 pp, so this guard is vacuous"


def test_an_unpinned_figure_is_caught():
    """PLANT, and the message must name the RIGHT problem -- not merely raise.

    Two texts, identical but for the pin. If the guard fires on both, it is
    testing the presence of the figure rather than the presence of its
    provenance, and would have been just as green before this rule existed.
    """
    pinned = (
        f"**Difference +1.45 pp**\n\n*Produced by `{PINS[0]}` (subscriptions "
        f"1-1153) and others, see runs/batch-2000.provenance.json.*"
    )
    assert not _orphans(pinned), (
        "a correctly pinned figure was flagged; the guard is matching the "
        "figure rather than its provenance"
    )

    bare = "**Difference +1.45 pp - 95% CI [-2.59, +5.49] pp - p = 0.4830**"
    assert _orphans(bare) == ["line 1"], (
        f"an unpinned figure was NOT caught: {_orphans(bare)}"
    )

    # And the qualifier must be NEAR it, not merely somewhere in the file.
    distant = bare + "\n" + ("filler. " * 200) + f"\nProduced by `{PINS[0]}`."
    assert _orphans(distant) == ["line 1"], (
        "a pin 1,600 characters away satisfied the check, so this is a presence "
        "test wearing a proximity test's name -- which is the exact defect it "
        "was written to prevent"
    )
