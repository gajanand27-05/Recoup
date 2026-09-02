"""The shipped suite must pass against tracked files alone.

WHY
---
`tests/` ships. `CLAUDE.md`, `PLAN.md`, `DECISION.md`, `LOGS.md`, `VIDEO.md`,
`docs/superpowers/`, `.env` and `runs/` do not — they are gitignored working
artifacts. A shipped test that reads one of them passes here and fails on any
clone, which is what happened on `59061cd`: `test_claim_consistency.py` read
`DECISION.md`, CI raised `FileNotFoundError`, and the local suite could not have
caught it because locally the file is right there.

A `skipif` on the individual test was the fix for that instance. This is the
guard for the class.

HOW
---
`git clone` into a temporary directory and run the suite there. A clone contains
tracked files and history and nothing else, which is exactly what a judge gets.

Not `git archive`: the first version of this test used one, and it failed on the
eight `test_prereg.py` tests that read git history to prove `EXPERIMENT.md` was
committed before any ledger row. An archive has no `.git`, so those failed for a
reason no cloner would ever hit. A guard stricter than reality reports defects
that are not there, which costs as much trust as one that misses them.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or _git("rev-parse", "--git-dir").returncode != 0,
    reason="not a git checkout; nothing to export",
)


def _overlay_working_tree(export: Path) -> None:
    """Copy what a commit right now WOULD ship, over the cloned HEAD.

    A clone alone tests the last commit, and the work that needs checking is the
    work not yet committed. Found by planting: a shipped test reading
    `DECISION.md` was added, staged, and the guard passed — because the clone had
    never heard of it. That is the 59061cd sequence exactly: green locally,
    green here, red on CI after the push.

    The set is `--cached --others --exclude-standard`: tracked files with their
    working content, plus new files that are not gitignored. Ignored paths stay
    out, which is what makes the check mean anything.
    """
    listed = _git("ls-files", "--cached", "--others", "--exclude-standard")
    assert listed.returncode == 0, f"git ls-files failed: {listed.stderr}"

    for line in listed.stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        source = REPO / rel
        if not source.is_file():
            continue  # staged-for-deletion, or a submodule entry
        target = export / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def test_the_shipped_suite_passes_with_only_tracked_files():
    """The whole point. Runs in a subprocess against an exported tree.

    Excluded from the inner run:
      * this test — it would recurse, exporting an export.
      * test_no_side_effects — it runs the suite in a subprocess too, and nesting
        the two makes a failure impossible to attribute.
    """
    if os.environ.get("RECOUP_INNER_RUN"):
        pytest.skip("inner run: not re-entering the export")

    with tempfile.TemporaryDirectory(prefix="recoup-shipped-") as tmp:
        export = Path(tmp) / "clone"

        cloned = _git("clone", "--quiet", "--no-hardlinks", str(REPO), str(export))
        assert cloned.returncode == 0, f"git clone failed: {cloned.stderr}"

        # Proves the clone is actually restricted. Without this the test could
        # pass by copying everything, which is the shape of failure it exists to
        # catch in other guards.
        assert not (export / "CLAUDE.md").exists(), (
            "CLAUDE.md is in the clone — it is supposed to be gitignored, so "
            "either .gitignore changed or this test is looking at the wrong tree"
        )
        assert not (export / ".env").exists(), ".env reached the clone"
        assert (export / "src" / "recoup").is_dir(), "the clone has no source"
        assert (export / ".git").exists(), (
            "the clone has no history; the prereg ordering tests would fail for "
            "a reason no cloner would hit"
        )

        _overlay_working_tree(export)

        env = {
            **os.environ,
            "RECOUP_INNER_RUN": "1",
            "PYTHONPATH": str(export / "src"),
        }
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", "--no-header",
                "-p", "no:cacheprovider",
                "--deselect", f"tests/{Path(__file__).name}",
                "--deselect", "tests/test_no_side_effects.py",
            ],
            cwd=export,
            capture_output=True,
            text=True,
            env=env,
        )
        tail = (result.stdout + result.stderr)[-4000:]
        assert result.returncode == 0, (
            "the shipped suite does not pass against tracked files alone.\n"
            "A test is reading something that is not in the repository — it will "
            "fail for anyone who clones this.\n\n" + tail
        )
