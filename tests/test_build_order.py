"""The ordering claim, enforced instead of remembered.

Task 26 Step 2 puts this on camera: the measuring instrument existed before the
thing it measures, and `git log` is the evidence rather than the assertion. The
check that gets run is

    git log --diff-filter=A -- src/recoup/agent/

against the commit that introduced the simulator freeze.

`--diff-filter=A` finds the ADD. It does not care that the file was empty, and it
does not care that the file was deleted afterwards. So a single premature commit
touching `src/recoup/agent/` -- a stub, an `__init__.py`, a file created and
removed in the same hour -- permanently falsifies a claim made on camera six days
later. There is no recovery short of rewriting published history.

That makes it the one irreversible mistake available during Day 2, which is
exactly the kind of thing that should fail a test rather than rely on someone
remembering. If these fail, the fix is never to relax them.
"""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AGENT = REPO / "src" / "recoup" / "agent"
FREEZE = REPO / "PARAMS.lock.json"


def _git(*args: str) -> str | None:
    """Run git, or return None where git is unavailable."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        return None
    return out.stdout if out.returncode == 0 else None


def test_agent_does_not_exist_before_the_simulator_is_frozen():
    """No `agent/` until PARAMS.lock.json exists. Not even an empty package."""
    if FREEZE.exists():
        pytest.skip("simulator is frozen; agent/ is allowed from here on")
    assert not AGENT.exists(), (
        f"{AGENT} exists but the simulator is not frozen. Committing anything here "
        "now permanently breaks the ordering claim in Task 26 Step 2, because "
        "`git log --diff-filter=A` records the add regardless of the file's "
        "contents or later deletion. Delete it and finish the freeze first."
    )


def test_no_commit_has_ever_added_a_file_under_agent_before_the_freeze():
    """The claim as it will actually be checked, run against real history.

    Filesystem absence is not enough: a file added and deleted yesterday leaves
    no trace on disk and a permanent one in `git log`.
    """
    adds = _git("log", "--all", "--diff-filter=A", "--format=%H", "--", "src/recoup/agent/")
    if adds is None:
        pytest.skip("git unavailable")

    agent_commits = [line for line in adds.splitlines() if line.strip()]
    if not agent_commits:
        return  # nothing has ever been added there

    freeze_adds = _git(
        "log", "--all", "--diff-filter=A", "--format=%H", "--", "PARAMS.lock.json"
    )
    assert freeze_adds and freeze_adds.strip(), (
        f"{len(agent_commits)} commit(s) added files under src/recoup/agent/ and "
        "PARAMS.lock.json has never been committed. The ordering claim is false: "
        "the agent predates the frozen instrument."
    )

    # Both exist -- the freeze must be the ancestor.
    freeze_first = freeze_adds.splitlines()[-1].strip()
    agent_first = agent_commits[-1].strip()
    ancestor = _git("merge-base", "--is-ancestor", freeze_first, agent_first)
    assert ancestor is not None, (
        f"the freeze ({freeze_first[:8]}) is not an ancestor of the first agent "
        f"commit ({agent_first[:8]}); the instrument did not come first"
    )


def test_the_simulator_is_not_imported_by_anything_it_measures():
    # Cheap structural echo of the same idea: if `simulator/` ever imports from
    # `agent/`, the instrument depends on the thing being measured.
    sim = REPO / "src" / "recoup" / "simulator"
    if not sim.exists():
        pytest.skip("simulator not built yet")
    offenders = [
        p.relative_to(REPO)
        for p in sim.rglob("*.py")
        if "recoup.agent" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"simulator imports from agent: {offenders}"
