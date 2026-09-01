"""A test run must leave the repository exactly as it found it.

INC-006: the test suite wrote a fabricated `subscription.halted.json` into
`src/recoup/execute/fixtures/captured/`, and it was committed as though Razorpay
had sent it. The manifest then reported a payload shape as CAPTURED when it had
never been observed.

Every guard added afterwards addressed *that* artifact. This one addresses the
class: **anything** a test writes into the repository is a candidate for being
committed by accident and read later as evidence.

Untracked files are checked as well as modified tracked ones, deliberately. The
INC-006 file was untracked when it appeared — a check that looked only at
tracked paths would have watched it happen. `git status --porcelain` omits
gitignored paths, so `runs/`, `__pycache__` and `.pytest_cache` are correctly
invisible here.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INNER = "RECOUP_INNER_TEST_RUN"


def working_tree_state() -> set[str]:
    """Modified tracked files and new untracked files. Ignored paths excluded."""
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:  # pragma: no cover - environment dependent
        pytest.skip("git unavailable")
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


@pytest.mark.skipif(os.getenv(INNER) == "1", reason="inner run; would recurse")
def test_a_full_test_run_leaves_the_repository_unchanged():
    """Runs the whole suite in a subprocess and diffs the working tree around it.

    Expensive — it runs the suite twice — and worth it. The cheap version of this
    check is "remember not to write into the repo from a test", which is what was
    being relied on when INC-006 happened.
    """
    before = working_tree_state()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not llm"],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, INNER: "1"},
        timeout=900,
    )

    after = working_tree_state()
    appeared = after - before
    vanished = before - after

    assert not appeared and not vanished, (
        "a test run changed the working tree.\n"
        f"  appeared: {sorted(appeared)}\n"
        f"  vanished: {sorted(vanished)}\n"
        "Anything a test writes into the repository can be committed by accident "
        "and read later as evidence. That is INC-006.\n"
        f"inner run exit={result.returncode}"
    )

    # If the inner run itself failed, say so rather than reporting a clean tree
    # as success -- a suite that died early writes less, not nothing.
    assert result.returncode == 0, (
        f"the inner test run failed (exit {result.returncode}); a clean working "
        f"tree proves nothing about a run that did not finish.\n"
        f"{result.stdout[-2000:]}"
    )


def test_the_state_probe_sees_both_modified_and_untracked(tmp_path):
    """The probe must catch the shape INC-006 actually had.

    That file was UNTRACKED when it appeared. A check reading only tracked paths
    would have watched it happen and reported nothing.
    """
    probe = REPO / "_side_effect_probe.txt"
    assert not probe.exists()

    before = working_tree_state()
    probe.write_text("planted\n", encoding="utf-8")
    try:
        during = working_tree_state()
        assert during - before, "an untracked file must show up in the probe"
        assert any("_side_effect_probe" in entry for entry in during - before)
    finally:
        probe.unlink()

    assert working_tree_state() == before
