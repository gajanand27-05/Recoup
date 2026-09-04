"""The rendered video is tied to the sources it was made from.

WHY THIS EXISTS
---------------
INC-014. `out/recoup.mp4` opened with `+9.99 pp` where the lift is `+1.45 pp` --
a fabricated headline on the first card a judge sees, beside a correct interval,
which is what made it read as a measurement rather than as an error.

Every guard in this repository checked the SOURCE or the DATA and passed:
`test_video_no_literals` proves no number is typed into a caption,
`test_mde_labelling` proves both MDEs are labelled, `scripts/video_data.py`
proves each figure came from the module that computes it. All 1,082 tests were
green while the artifact was wrong. **Nothing read the artifact.**

WHAT THIS CAN AND CANNOT DO
---------------------------
It cannot render a video in CI -- there is no node there, and a render is four
minutes. What it can do is refuse to let the RECORDED provenance go stale: the
hashes in `build-provenance.json` are of the files that fed the render, so if a
source moves and nobody re-renders, the recorded hash stops matching the
committed file and this says so.

That is a real but partial guarantee, and it is worth naming the gap rather than
implying the artifact is verified: **this proves the recorded inputs are current,
not that the MP4 was built from them.** The only thing that establishes the
second is opening the file and reading frames, which is done by hand at render
time and written into `verified_frames`.

CONTENT, NOT BYTES
------------------
Hashes are over LF-normalised content, the same normalisation
`simulator/freeze.py` uses and for the same reason: a CRLF checkout must not read
as a stale render, because a false alarm here trains someone to ignore it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import video_cards

#: video/ is not tracked, so on a fresh checkout (and in CI) there is no
#: render and no source to compare it against. Skipped explicitly and
#: loudly: this guard exists because of INC-014, and a guard that silently
#: stops running is how INC-014 happened in the first place.
pytestmark = pytest.mark.skipif(
    not video_cards.AVAILABLE, reason=video_cards.SKIP_REASON
)

REPO = Path(__file__).resolve().parents[1]
PROVENANCE = REPO / "video" / "build-provenance.json"


def _doc() -> dict:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _recorded_inputs() -> dict[str, str]:
    """The recorded input hashes, or nothing at all when video/ is not here.

    `pytest.mark.skipif` runs at CALL time and this is read at COLLECTION time,
    so a module-level skip does not stop this from being evaluated on a checkout
    that has no `video/`. It errored the whole collection, and
    `test_ships_standalone` caught it -- the suite must pass against tracked
    files alone, and video/ is no longer among them.

    Returning `{}` makes the parametrisation empty; the skipif above is what
    states, out loud, that these checks did not run.
    """
    if not video_cards.AVAILABLE or not PROVENANCE.exists():
        return {}
    return _doc()["inputs_sha256"]


def test_the_record_names_inputs_to_check():
    """A guard whose subject is empty has never been shown to fire."""
    inputs = _recorded_inputs()
    assert len(inputs) >= 5, (
        f"build-provenance.json records {len(inputs)} input hash(es); every check "
        f"below would pass over almost nothing"
    )
    assert "video/src/Recoup.tsx" in inputs, (
        "the file that lays out every card is not among the recorded inputs, so a "
        "change to it would not make the render read as stale"
    )
    assert "video/data/figures.json" in inputs, (
        "the file every figure on screen is interpolated from is not recorded -- "
        "which is exactly the surface INC-014 came through"
    )


@pytest.mark.parametrize("relpath", sorted(_recorded_inputs()))
def test_every_recorded_input_still_matches_the_committed_file(relpath: str):
    path = REPO / relpath
    assert path.exists(), f"{relpath} is recorded as a render input and is missing"
    assert _sha(path) == _recorded_inputs()[relpath], (
        f"{relpath} has changed since video/out/recoup.mp4 was rendered.\n"
        f"The render is STALE: re-render, then verify the artifact rather than the "
        f"command's exit path -- sha256, size, frame count, and frames sampled and "
        f"read. See INC-014, where the artifact was wrong while every source-level "
        f"guard was green."
    )


def test_the_record_covers_every_file_that_can_change_a_frame():
    """Walk the directories, do not trust the list.

    A source file added later -- a new card component, a new data file -- would
    change what renders and would not be recorded, so the staleness check would
    quietly stop covering it. That is the fixed-list failure this build has hit
    repeatedly, and the fix is always to walk the registry.
    """
    live = {
        p.relative_to(REPO).as_posix()
        for p in (REPO / "video" / "src").rglob("*")
        if p.is_file() and p.suffix in {".tsx", ".ts"}
    } | {
        p.relative_to(REPO).as_posix()
        for p in (REPO / "video" / "data").glob("*.json")
    }
    # Smoke.tsx is the toolchain check kept from before any content existed. It
    # renders its own composition and cannot alter a frame of `recoup`.
    live.discard("video/src/Smoke.tsx")

    missing = live - set(_recorded_inputs())
    assert not missing, (
        f"these files can change what the video shows and are not recorded as "
        f"render inputs: {sorted(missing)}. A render made before they changed "
        f"would still read as current."
    )


def _frames_the_source_would_render() -> int:
    """The frame count implied by the SCENES array, from the source itself.

    This used to be the literal 4680. It was correct for a 156s cut and it was a
    fixed number standing in for a computed one: extending the video to 268s made
    the guard fail as though the RECORD were wrong, when the record was the only
    thing that had been updated. A check that must be hand-edited every time its
    subject legitimately changes gets hand-edited without being read.

    Two producers again: this walks the source, `doc["frames"]` is what the render
    was recorded as, and they have to agree.
    """
    source = (REPO / "video" / "src" / "Recoup.tsx").read_text(encoding="utf-8")
    scenes = source[source.index("const SCENES") :]
    seconds = sum(int(n) for n in re.findall(r"secs\((\d+)\)", scenes))
    fps = int(re.search(r"FPS\s*=\s*(\d+)", (REPO / "video" / "src" / "theme.ts")
                        .read_text(encoding="utf-8")).group(1))
    assert seconds > 0, "no scene durations found in SCENES; the parse has drifted"
    return seconds * fps


def test_the_artifact_identity_is_recorded():
    """Not verification -- identification. Which bytes were watched and uploaded."""
    doc = _doc()
    assert len(doc["artifact_sha256"]) == 64
    assert doc["artifact_bytes"] > 1_000_000
    expected = _frames_the_source_would_render()
    assert doc["frames"] == expected, (
        f"the recorded frame count ({doc['frames']}) is not what the SCENES array "
        f"would render ({expected}). Either the video changed length and was not "
        f"re-rendered, or this record is of a different render."
    )


def test_the_frames_that_were_read_by_hand_are_named():
    """`verified_frames` is the only part of this file that says anything about
    the CONTENT of the render, and it is a human's reading rather than a check.
    Recorded so the claim is attributable, and asserted so it cannot quietly
    become an empty dict that reads like a verified artifact."""
    verified = _doc()["verified_frames"]
    assert verified, "no frame was recorded as read; the artifact is unverified"
    assert any("1.45" in note for note in verified.values()), (
        "no recorded frame check names the headline figure. INC-014 was a wrong "
        "headline that every other guard missed; if this stops being read, the "
        "one check that would have caught it is gone."
    )


def test_a_changed_input_is_caught():
    """PLANT. Mutates a recorded hash and confirms the check fires on THAT file.

    Runs the same comparison the live check runs, against a doctored record,
    rather than reasoning that it would fire.
    """
    inputs = dict(_recorded_inputs())
    target = "video/src/Recoup.tsx"
    inputs[target] = "0" * 64

    stale = [p for p, h in inputs.items() if _sha(REPO / p) != h]
    assert stale == [target], (
        f"corrupting the recorded hash for {target} reported {stale!r}; the check "
        f"does not name the file that actually drifted"
    )
