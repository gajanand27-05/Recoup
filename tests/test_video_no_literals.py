"""No number on screen is an unchecked literal.

WHY
---
A hardcoded number in a video is the same class of defect as a hardcoded
fixture: it agrees with the report until something changes, and then silently
disagrees. A frame is the one artifact nobody can grep, so nobody finds out.

This is not hypothetical. `Recoup.tsx` shipped with `mde_at_n() has returned
6.23 pp` typed into the source. It was correct, it rendered identically to the
producer-sourced version, and it was found by looking at a frame -- not by any
test. That is the failure mode: a literal that is right today.

THE RULE
--------
Every digit that reaches the screen comes from one of three places:

1. an interpolation reading `figures.json` (`f.…`) or `captured.json`, both
   written by `scripts/video_data.py` from the module that produced the number;
2. a helper over those (`pp(f.lift.diff_pp)`);
3. a DECLARED EXEMPTION in `EXEMPT` below, each naming where it comes from.

An exemption list is honest. An unchecked literal is what put the 6.23 there.

WHY THERE ARE EXEMPTIONS AT ALL
-------------------------------
Some numbers on screen have no producer and inventing one would be worse than
declaring them. "10 of 17 frozen simulator parameters are assumptions" is a fact
about `PARAMS.lock.json`; wiring a loader into the video build to recompute it
would add a moving part to make a check pass, not to make the number truer.
Each exemption says where the number actually comes from, so a reader can go and
disagree with it.

WALKING vs ENUMERATING
----------------------
`test_every_exemption_is_still_used` fails when an exemption stops matching, so
the list cannot rot into a permanent licence. And the check itself walks every
card `video_cards.cards()` finds -- a new scene is covered the moment it exists,
which is the property a fixed list of scenes would not have (CLAUDE.md, the
seventh instance).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import video_cards

REPO = Path(__file__).resolve().parents[1]
FIGURES = REPO / "video" / "data" / "figures.json"

#: Any run of digits. Deliberately crude: the point is to force every one of
#: them to be accounted for, not to guess which ones look like figures.
_DIGITS = re.compile(r"\d[\d,.]*")

#: DECLARED EXEMPTIONS. Each is (pattern, where the number actually comes from).
#: These are numbers with no producer in `figures.json`, stated as prose. They
#: are NOT permitted to be figures the run computed -- those must be
#: interpolated, and `test_a_new_literal_figure_is_caught` proves a new one is.
EXEMPT: tuple[tuple[str, str], ...] = (
    (
        r"\b10 of 17\b",
        "PARAMS.lock.json: 17 frozen parameters, of which 10 are class "
        "ASSUMPTION. Stated in SIMULATOR_FREEZE.md and CLAUDE.md section 7. Not "
        "loaded into the video build -- adding a loader to satisfy a check adds "
        "a moving part without making the number truer.",
    ),
    (
        r"−0\.10 pp",
        "eval/sensitivity.py: the one sign flip, attempt_decay_compounding = "
        "0.0 taking +1.55 pp to −0.10 pp. Reported in EVAL_RESULTS.md's "
        "falsification section. The sweep is not re-run at video build time.",
    ),
    (
        r"\bthree of five\b",
        "INC-013: replay needs five fields and the ledger stores two "
        "(day_offset, is_hard_decline and amount_paise come from outside it).",
    ),
    (
        r"\b12 of\b",
        "EXPERIMENT.md Addendum 3: the stopping rule was fixed at 12 of 2,000 "
        "subscriptions. The 2,000 beside it IS interpolated (f.run.planned_n); "
        "only the 12 is prose.",
    ),
    (
        r"\bTask 8\b",
        "A task number from PLAN.md, not a measurement.",
    ),
    (
        r"\bDay [26]\b",
        "Calendar days of the build, from CLAUDE.md section 7. Not measurements.",
    ),
    (
        r"\bfinding [12]\b",
        "An ordinal naming which of the two findings a card belongs to. "
        "README.md's own section headings. Not a quantity.",
    ),
    (
        r"from 0% to 100%",
        "A-027 and INCIDENTS.md: the fallback counter was verified live by five "
        "forced schema violations, each driving it from 0% to 100%. Those are "
        "the endpoints of a proportion, not a measurement of this run -- the "
        "run's own rate is interpolated from arms.treatment.fallback_rate_pct "
        "in the same bullet list.",
    ),
    (
        r"github\.com/gajanand27-05/Recoup",
        "The repository URL from CLAUDE.md section 1. The digits are part of a "
        "GitHub username.",
    ),
    (
        r"\b95% CI\b|\b95%\b",
        "The confidence level, fixed at 0.95 in EXPERIMENT.md before the run. "
        "The interval's BOUNDS are interpolated; only the level is prose.",
    ),
    (
        r"\bfive attempts\b|\bfive forced\b|\bfive replay fields\b",
        "MAX_ATTEMPTS = 5 in the policy engine; the five forced schema "
        "violations of A-027; the five replay fields of INC-013. Spelled as "
        "words in prose, and matched here so the digit form cannot sneak in.",
    ),
    (
        r"\b1\. |\b2\. ",
        "The list numbering on the opening card. Not a quantity.",
    ),
)

#: Interpolations that are permitted to reach the screen: anything reading the
#: committed JSON, or a helper over it.
_ALLOWED_INTERPOLATION = re.compile(
    r"^\$\{\s*(?:"
    r"f\.[\w.]+.*"          # figures.json
    r"|captured\.\w+"        # captured.json
    r"|pp\(f\.[\w.]+\)"      # the +/- formatter over a figure
    r"|s\.\w+.*"             # a row of an f.* array being mapped
    r"|p\.\w+.*"             # ditto
    r"|c\.\w+.*"             # ditto
    r")\s*\}$",
    re.DOTALL,
)


def _strip_exempt(text: str) -> str:
    for pattern, _ in EXEMPT:
        text = re.sub(pattern, " ", text)
    return text


def _cards():
    return video_cards.cards()


@pytest.mark.parametrize("name", [c.name for c in video_cards.cards()])
def test_no_card_displays_a_literal_number(name):
    """Every digit on this card is interpolated from committed JSON, or declared."""
    card = next(c for c in _cards() if c.name == name)
    offenders = []
    for line in card.strings:
        remaining = _strip_exempt(line)
        for match in _DIGITS.finditer(remaining):
            offenders.append(f"{match.group(0)!r} in {line.strip()!r}")
    assert not offenders, (
        f"video card {name!r} displays a number that is neither read from "
        f"figures.json/captured.json nor a declared exemption:\n  "
        + "\n  ".join(offenders)
        + "\n\nEither interpolate it from the producer that computes it, or add "
        "it to EXEMPT with a comment naming where it comes from. A literal that "
        "is correct today is exactly what this exists to catch."
    )


@pytest.mark.parametrize("name", [c.name for c in video_cards.cards()])
def test_every_interpolation_reads_from_committed_data(name):
    """An interpolation is only a producer if it reads one. `${SOME_CONST}` is a
    literal wearing a template."""
    card = next(c for c in _cards() if c.name == name)
    bad = [i for i in card.interpolations if not _ALLOWED_INTERPOLATION.match(i)]
    assert not bad, (
        f"video card {name!r} interpolates an expression that does not read "
        f"figures.json or captured.json:\n  " + "\n  ".join(bad)
    )


def test_the_figures_file_is_committed_and_names_its_producer():
    data = json.loads(FIGURES.read_text(encoding="utf-8"))
    assert data["_generated_by"] == "scripts/video_data.py"
    assert data["lift"]["diff_pp"] is not None


def test_every_exemption_is_still_used():
    """An exemption list is a fixed list of what it permits, so it must not
    outlive the text it was written for. A stale entry is a standing licence for
    a number nobody is looking at any more."""
    text = "\n".join(c.text for c in _cards())
    unused = [p for p, _ in EXEMPT if not re.search(p, text)]
    assert not unused, (
        f"these exemptions no longer match anything on any card: {unused}. "
        f"Remove them -- a permission for text that no longer exists silently "
        f"covers whatever is written next that happens to match."
    )


def test_every_exemption_states_where_the_number_comes_from():
    """An exemption without a source is an unchecked literal with extra steps."""
    for pattern, source in EXEMPT:
        assert len(source) > 40, f"exemption {pattern!r} does not say where it comes from"


def test_a_new_literal_figure_is_caught():
    """PLANT. Puts the exact defect back -- a hardcoded MDE in a caption -- and
    confirms the check fires.

    This is the literal that shipped and was found by looking at a frame. The
    plant runs on every check so the guard cannot quietly stop covering it.
    """
    # Plant by substituting the INTERPOLATION for the value it resolves to,
    # rather than by matching a sentence. The first version quoted the Day 2
    # caption verbatim and went stale the moment that caption was reworded --
    # caught by its own staleness assertion, which is the only reason this is
    # not now a plant that silently matches nothing.
    figures = json.loads(FIGURES.read_text(encoding="utf-8"))
    literal = f"{figures['power_ceiling']['mde_pp']}"
    text = video_cards.source()
    planted = text.replace("${f.power_ceiling.mde_pp}", literal)
    assert planted != text, (
        "the Day 2 card no longer interpolates f.power_ceiling.mde_pp, so this "
        "guard has not been shown to fire against the defect it exists for"
    )

    card = next(c for c in video_cards.cards(planted) if c.name == "DayTwo")
    hits = [
        m.group(0) for line in card.strings for m in _DIGITS.finditer(_strip_exempt(line))
    ]
    assert "6.23" in hits, (
        f"re-introducing the hardcoded 6.23 did NOT trip the check; it found "
        f"{hits}. The check is not reading what it thinks it is."
    )


def test_the_plant_is_not_caught_before_it_is_planted():
    """The other half of the plant: the same card must be CLEAN unplanted.

    Without this, a check that flagged everything would pass the test above and
    look like a working guard.
    """
    card = next(c for c in _cards() if c.name == "DayTwo")
    hits = [
        m.group(0) for line in card.strings for m in _DIGITS.finditer(_strip_exempt(line))
    ]
    assert not hits, f"the unplanted DayTwo card already has literals: {hits}"
