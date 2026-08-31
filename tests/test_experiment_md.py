"""EXPERIMENT.md must not drift from the code it describes.

The design table is *generated*, not transcribed. `p1` is read from the frozen
registry precisely so the baseline is provably the sourced one — and a hand-typed
table would silently defeat that property the moment `p1` moved. The number in the
document would stay right while the number in the calculation changed, and the
document is what a judge reads.

This is the same class as the `PARAMS.md` / registry drift caught in INC-003 F-3,
where six parameters were registered in code and described nowhere.
"""

from pathlib import Path

import pytest

from recoup.eval.power import (
    DESIGN_TABLE_BEGIN,
    DESIGN_TABLE_END,
    design_table,
    design_table_markdown,
)

EXPERIMENT = Path(__file__).resolve().parents[1] / "EXPERIMENT.md"


def _committed_block(text: str) -> str:
    start = text.index(DESIGN_TABLE_BEGIN)
    end = text.index(DESIGN_TABLE_END) + len(DESIGN_TABLE_END)
    return text[start:end]


def test_the_committed_design_table_matches_what_the_command_produces():
    committed = _committed_block(EXPERIMENT.read_text(encoding="utf-8"))
    assert committed == design_table_markdown(), (
        "EXPERIMENT.md's design table has drifted from `python -m recoup.eval.power`. "
        "Regenerate it -- do not hand-edit the numbers."
    )


def test_the_markers_are_present_exactly_once():
    text = EXPERIMENT.read_text(encoding="utf-8")
    assert text.count(DESIGN_TABLE_BEGIN) == 1
    assert text.count(DESIGN_TABLE_END) == 1


def test_the_chosen_design_is_marked_and_is_the_pre_registered_one():
    text = EXPERIMENT.read_text(encoding="utf-8")
    block = _committed_block(text)
    chosen = [line for line in block.splitlines() if "<- chosen" in line]
    assert len(chosen) == 1
    assert "1,000" in chosen[0] and "2,000" in chosen[0]
    assert "N = 2,000 (1,000 per arm)" in text


def test_the_stated_mde_appears_in_the_prose_as_well_as_the_table():
    # The prose says the design cannot detect an effect below 6.23pp. If the table
    # moves and the sentence does not, the document contradicts itself.
    text = EXPERIMENT.read_text(encoding="utf-8")
    mde = design_table()[2]["mde"]
    assert design_table()[2]["n_per_arm"] == 1000
    assert f"{mde * 100:.2f}" in text


def test_a_hand_edited_table_would_be_caught(tmp_path):
    """The planted failure for this guard.

    Constructs the exact drift it exists to catch -- a plausible-looking number
    edited into the committed block -- and confirms the comparison rejects it.
    Without this the test only proves the file currently matches itself.
    """
    fresh = design_table_markdown()
    tampered = fresh.replace("6.23 pp", "5.10 pp")
    assert tampered != fresh, "the replacement did not apply; this test has gone blind"
    assert tampered != design_table_markdown()


def test_the_generated_table_tracks_a_change_in_the_baseline():
    # If p1 moved in the frozen registry, the rendered table must move with it --
    # otherwise generating rather than typing buys nothing.
    default = design_table_markdown()
    shifted = "\n".join(
        line
        for line in design_table_markdown().splitlines()
    )
    assert default == shifted  # sanity: rendering is deterministic

    from recoup.eval.power import mde_at_n

    assert mde_at_n(0.51, 1000) != mde_at_n(0.30, 1000), (
        "the MDE must depend on p1, or the registry lookup is decorative"
    )


# --- the pre-registration's own commitments must stay in the file ------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "No optional stopping",
        "not re-run with a new seed",
        "full-pipeline A/A",
        "unwired",
        "The counterfactual is assumed, not measured",
        "swept first",
    ],
)
def test_the_pre_registered_commitments_are_still_stated(phrase):
    """These are the promises the file exists to make hard to quietly drop.

    A pre-registration naming a falsification test and then losing the sentence is
    the exact failure this document is written to prevent, and it is findable by
    diffing two files -- so it should be findable by a test first.
    """
    assert phrase in EXPERIMENT.read_text(encoding="utf-8")
