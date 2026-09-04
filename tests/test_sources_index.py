"""Everything PARAMS.md rejected is still rejected in SOURCES.md.

WHY
---
The rejected-figures list now exists in two shipping documents: three rows in
`src/recoup/simulator/PARAMS.md`, next to the parameters they were rejected
*for*, and the full list in `SOURCES.md` at the repo root, where a reader who
never opens the simulator package will find it.

Two copies of one claim is the shape every mislabelled artifact in this build
started as. The copies are allowed to differ in scope -- SOURCES.md is a
superset, and deliberately so -- but a figure PARAMS.md rejects and SOURCES.md
does not mention is a figure whose rejection quietly stopped shipping.

WALKS THE TABLE, NOT A LIST OF FIGURES
--------------------------------------
The rows come from PARAMS.md itself. When a fourth figure is rejected there,
this requires it here, rather than checking for three strings someone typed
into a test file. A guard that enumerates a fixed subset of what it protects
protects only what it happened to list (CLAUDE.md).

PLANTED
-------
`test_a_figure_dropped_from_sources_is_caught` deletes a real row from a copy of
SOURCES.md, runs the same `missing_from()` the live check runs, and requires the
result to name *that* figure and no other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PARAMS = REPO / "src" / "recoup" / "simulator" / "PARAMS.md"
SOURCES = REPO / "SOURCES.md"

#: The heading PARAMS.md files its rejections under. If it is renamed, the
#: extraction below finds nothing -- which is why an empty table is a failure
#: rather than a vacuous pass.
_HEADING = "## What this table does not contain"


def _normalise(text: str) -> str:
    """Strip the emphasis and quoting that differ between the two documents."""
    text = text.replace("**", "").replace("“", '"').replace("”", '"')
    text = text.replace('"', "")
    return re.sub(r"\s+", " ", text).strip()


def rejected_figures() -> list[str]:
    """The first cell of every row in PARAMS.md's rejected-figures table."""
    body = PARAMS.read_text(encoding="utf-8").split(_HEADING, 1)
    assert len(body) == 2, (
        f"PARAMS.md no longer has a {_HEADING!r} section, so this guard has "
        "nothing to walk and would pass on an empty list"
    )
    rows: list[str] = []
    for line in body[1].splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2 or cells[0].startswith("---") or cells[0] == "Rejected figure":
            continue
        rows.append(_normalise(cells[0]))
    return rows


def test_the_table_still_has_rows_to_check():
    """A guard whose subject is empty has never been shown to fire."""
    assert len(rejected_figures()) >= 3, (
        "PARAMS.md's rejected-figures table is empty or unparseable; every "
        "assertion below would pass without checking anything"
    )


def missing_from(sources_text: str) -> list[str]:
    """Rejections PARAMS.md makes that this text does not carry.

    The check itself, lifted out of the test so the plant below can run it
    against a document rather than re-implementing it. A plant that exercises a
    copy of the logic proves the copy works.
    """
    body = _normalise(sources_text)
    return [figure for figure in rejected_figures() if figure not in body]


@pytest.mark.parametrize("figure", rejected_figures())
def test_every_rejection_survives_in_the_root_index(figure: str):
    assert figure not in missing_from(SOURCES.read_text(encoding="utf-8")), (
        f"PARAMS.md rejects {figure!r} and SOURCES.md does not mention it. A "
        "reader who opens the root index sees a shorter rejection list than "
        "the one the parameters were actually chosen against"
    )


def test_a_figure_dropped_from_sources_is_caught():
    """PLANT. Removes a real row and runs the REAL check against the result.

    The first version of this asserted that `text.replace(dropped, "")` no
    longer contained `dropped`, which is true of any substring and of any
    document -- it never called the check and never read a message, while its
    docstring claimed it had done both. That is this build's own defect class
    inside the guard written to catch it, so the plant now fires the thing it
    is a plant for.
    """
    clean = SOURCES.read_text(encoding="utf-8")
    assert not missing_from(clean), (
        "SOURCES.md is already missing a rejection, so this plant cannot "
        "distinguish the failure it injects from one that was already there"
    )

    dropped = rejected_figures()[0]
    missing = missing_from(_normalise(clean).replace(dropped, ""))

    assert missing == [dropped], (
        f"removing {dropped!r} from SOURCES.md reported {missing!r}. The guard "
        f"has not been shown to fire on the figure that was actually dropped, "
        f"which is the only thing it exists to report."
    )
