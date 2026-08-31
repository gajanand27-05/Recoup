"""Did the pre-registration actually precede the numbers?

`EXPERIMENT.md` carries its own date, and that date proves nothing — it is written
by whoever writes the file. What is checkable is **the commit that added it**,
compared against the timestamps of rows in any ledger that exists.

This is the same reasoning as the simulator freeze tag: the label is convenient,
the pushed history is the evidence. And it is cheap now and impossible to
reconstruct later — once a run has happened, no amount of care recovers an
ordering that was never established.

This module is in `eval/` because it is about the validity of the measurement.
It reads nothing from the simulator and touches no ground-truth label (D-011).
"""

import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PreregResult:
    ok: bool
    verified: bool
    reason: str
    cutoff: str | None = None
    rows_before: list[tuple[str, int, str]] = field(default_factory=list)


def experiment_commit_time(repo_root: Path) -> datetime | None:
    """When `EXPERIMENT.md` was first committed, as an aware datetime.

    `--diff-filter=A` finds the commit that *added* it, so a file deleted and
    re-added cannot quietly reset its own pre-registration date. `tail -1`
    equivalent: the oldest add wins.
    """
    try:
        out = subprocess.run(
            [
                "git", "log", "--all", "--diff-filter=A", "--format=%aI",
                "--", "EXPERIMENT.md",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        return None
    if out.returncode != 0:
        return None

    stamps = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    if not stamps:
        return None
    return datetime.fromisoformat(stamps[-1])  # oldest add


def _ledger_rows(db_path: Path) -> list[tuple[int, str]]:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:  # pragma: no cover
        return []
    try:
        return list(conn.execute("SELECT seq, ts FROM ledger ORDER BY seq"))
    except sqlite3.Error:
        return []  # not a recoup ledger
    finally:
        conn.close()


def check_prereg_order(repo_root: Path, runs_dir: Path) -> PreregResult:
    """Fail if any ledger row predates the `EXPERIMENT.md` commit.

    `ok` and `verified` are separate on purpose. A repository where
    `EXPERIMENT.md` was never committed would otherwise report `ok=True` on the
    strength of having nothing to compare against — the strongest possible
    reading of the weakest possible evidence. Silence must not read as success.
    """
    cutoff = experiment_commit_time(Path(repo_root))
    runs = Path(runs_dir)
    ledgers = sorted(runs.glob("*.db")) if runs.exists() else []

    if cutoff is None:
        if ledgers:
            return PreregResult(
                ok=False,
                verified=False,
                reason=(
                    f"{len(ledgers)} run artifact(s) exist and no EXPERIMENT.md commit "
                    "was found. Either this is not a git repository, or numbers were "
                    "produced before anything was pre-registered."
                ),
            )
        return PreregResult(
            ok=False,
            verified=False,
            reason=(
                "cannot verify: no EXPERIMENT.md commit found. Nothing has been run, "
                "so nothing is wrong yet -- but the ordering is unestablished."
            ),
        )

    offenders: list[tuple[str, int, str]] = []
    for db in ledgers:
        for seq, ts in _ledger_rows(db):
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if when < cutoff:
                offenders.append((str(db), seq, ts))

    if offenders:
        return PreregResult(
            ok=False,
            verified=True,
            reason=(
                f"{len(offenders)} ledger row(s) are timestamped before EXPERIMENT.md "
                f"was committed at {cutoff.isoformat()}. The pre-registration does not "
                "cover those numbers."
            ),
            cutoff=cutoff.isoformat(),
            rows_before=offenders,
        )

    return PreregResult(
        ok=True,
        verified=True,
        reason=(
            f"{len(ledgers)} ledger(s) checked; all rows postdate the EXPERIMENT.md "
            f"commit at {cutoff.isoformat()}"
        ),
        cutoff=cutoff.isoformat(),
    )
