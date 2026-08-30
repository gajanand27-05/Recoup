"""Freeze protocol for the simulator.

The credibility problem this solves: the builder wrote the thing that decides
whether the agent wins. The defence is ordering, made verifiable --

  1. build the simulator from cited parameters
  2. `python tasks.py freeze` writes PARAMS.lock.json + SIMULATOR_FREEZE.md
  3. tag it:  git tag -a sim-freeze-v1
  4. `python tasks.py verify-sim` fails the build on any drift  <-- wired into CI

`git show sim-freeze-v1` then proves the tag predates every commit in agent/.

Without the CI gate the freeze is a claim. With it, drift fails the build.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from recoup.clock import utc_now_iso

SIM_DIR = Path(__file__).parent
DEFAULT_LOCK = Path(__file__).resolve().parents[3] / "PARAMS.lock.json"

# freeze.py hashes the directory, so it excludes itself: including it would make
# the hash depend on its own output and never converge.
_EXCLUDE = {"freeze.py", "__pycache__"}


def _normalise(data: bytes) -> bytes:
    """Content, not literal bytes: CRLF and CR both become LF.

    `.gitattributes` forces LF for every file type currently in this directory,
    so today the two are the same. But a file type it does not cover would arrive
    as CRLF on Windows and LF on the Linux runner, and CI would report SIMULATOR
    DRIFT with nobody having changed anything -- a false positive that reads
    exactly like the real thing. The freeze should mean "the content is
    unchanged", and that is what this makes it mean.
    """
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _hashed_files() -> list[Path]:
    """Files covered by the freeze, in a stable order.

    Includes PARAMS.md: editing a source URL after the freeze is drift, because
    the provenance document is part of what was frozen.
    """
    return sorted(
        p
        for p in SIM_DIR.rglob("*")
        if p.is_file() and not any(part in _EXCLUDE for part in p.parts)
    )


def hash_simulator_dir() -> str:
    """sha256 over the sorted, line-ending-normalised contents of simulator/."""
    h = hashlib.sha256()
    for path in _hashed_files():
        h.update(path.relative_to(SIM_DIR).as_posix().encode("utf-8"))
        h.update(_normalise(path.read_bytes()))
    return h.hexdigest()


def locked_params() -> dict[str, dict]:
    """Every registered parameter in the simulator, from every module.

    PLAN.md locked `curve.PARAMS` alone. The generator holds
    `self_recovery_rate_soft` and `_hard` -- the numbers defining the
    counterfactual the whole lift claim is measured against -- so locking only
    the curve would freeze the less consequential half.
    """
    from recoup.simulator.curve import PARAMS as CURVE_PARAMS
    from recoup.simulator.generator import PARAMS as GEN_PARAMS

    overlap = set(CURVE_PARAMS) & set(GEN_PARAMS)
    if overlap:
        raise ValueError(
            f"parameter keys defined in two modules: {sorted(overlap)}. One of them "
            "would silently win the merge and the lock would freeze the wrong value."
        )
    return {**CURVE_PARAMS, **GEN_PARAMS}


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _jsonable(obj: object) -> object:
    """Round-trip through JSON so locked and live params compare like for like."""
    return json.loads(json.dumps(obj, default=str, sort_keys=True))


def write_lock(lock_path: str | Path = DEFAULT_LOCK) -> dict:
    lock = {
        "simulator_sha256": hash_simulator_dir(),
        "frozen_at": utc_now_iso(),
        "git_commit": _git_commit(),
        "params": _jsonable(locked_params()),
    }
    path = Path(lock_path)
    path.write_text(
        json.dumps(lock, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    _write_freeze_doc(lock, path.parent)
    return lock


def _write_freeze_doc(lock: dict, out_dir: Path) -> None:
    assumptions = sorted(
        k for k, v in lock["params"].items() if v.get("class") == "ASSUMPTION"
    )
    measured = sorted(k for k, v in lock["params"].items() if v.get("class") == "MEASURED")
    rows = "\n".join(f"| `{k}` | {lock['params'][k].get('sweep')} |" for k in assumptions)

    (out_dir / "SIMULATOR_FREEZE.md").write_text(
        f"""# SIMULATOR FREEZE

The simulator was frozen **before the agent was written**. This file, the git tag,
and `verify-sim` in CI are what make that a checkable claim rather than an assertion.

| | |
|---|---|
| `sha256(simulator/)` | `{lock["simulator_sha256"]}` |
| Frozen at (UTC) | {lock["frozen_at"]} |
| Commit | `{lock["git_commit"]}` |
| Tag | `sim-freeze-v1` |
| Parameters locked | {len(lock["params"])} |

The hash covers every file in `src/recoup/simulator/` **including `PARAMS.md`**, with
line endings normalised so a CRLF checkout does not read as tampering. `freeze.py`
itself is excluded, because a file cannot hash its own output.

## Verify it yourself

```bash
python tasks.py verify-sim     # recomputes the hash, fails on drift    (make verify-sim in CI)
git show sim-freeze-v1         # tag date precedes every commit in src/recoup/agent/
git log --oneline --diff-filter=A -- src/recoup/agent/ | tail -1
```

The third command is the one that matters. `--diff-filter=A` finds the commit that
*added* each file, so it is not fooled by a file that was later deleted.

## What is frozen

**{len(measured)} MEASURED** parameters, each with a URL and a stated population.
**{len(assumptions)} ASSUMPTION** parameters — not sourced, and swept in the
sensitivity analysis rather than presented as findings:

| Parameter | Swept over |
|---|---|
{rows}

Full provenance, including the figures that were located and deliberately rejected,
is in `src/recoup/simulator/PARAMS.md`.
""",
        encoding="utf-8",
    )


def verify_lock(lock_path: str | Path = DEFAULT_LOCK) -> tuple[bool, str]:
    path = Path(lock_path)
    if not path.exists():
        return False, f"lock file not found at {path} - run `python tasks.py freeze` first"

    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return False, f"lock file at {path} is unreadable: {exc}"

    current = hash_simulator_dir()
    if lock.get("simulator_sha256") != current:
        return False, (
            f"SIMULATOR DRIFT: simulator/ has changed since the freeze.\n"
            f"  locked:  {lock.get('simulator_sha256')}\n"
            f"  current: {current}"
        )

    locked = lock.get("params", {})
    live = _jsonable(locked_params())
    if locked != live:
        # Name the parameters. "PARAMS changed" sends someone diffing a
        # seventeen-entry dict by eye at the wrong moment.
        changed = sorted(
            k for k in set(locked) | set(live) if locked.get(k) != live.get(k)
        )
        return False, f"SIMULATOR DRIFT: params changed since the freeze: {changed}"

    return True, f"simulator verified against freeze {lock['simulator_sha256'][:12]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="freeze or verify the simulator")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        ok, message = verify_lock()
        print(message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    lock = write_lock()
    print(f"frozen: {lock['simulator_sha256']}")
    print(f"params: {len(lock['params'])}")
    print("wrote:  PARAMS.lock.json, SIMULATOR_FREEZE.md")
    print("\nnow tag it:")
    print('  git add -A && git commit -m "chore(simulator): freeze"')
    print('  git tag -a sim-freeze-v1 -m "simulator frozen before agent development"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
