#!/usr/bin/env python
"""Task runner. Local substitute for `make`, which is not installed on this machine.

Every target here mirrors a Makefile target exactly. CI runs on ubuntu-latest where
`make` exists and uses the Makefile; this file is for the local loop on Windows.

    python tasks.py test
    python tasks.py lint
    python tasks.py freeze
    python tasks.py verify-sim
"""

import subprocess
import sys

TARGETS: dict[str, list[str]] = {
    "test": [sys.executable, "-m", "pytest", "-v"],
    "test-fast": [sys.executable, "-m", "pytest", "-q", "-m", "not llm"],
    "lint": [sys.executable, "-m", "ruff", "check", "src", "tests"],
    "fmt": [sys.executable, "-m", "ruff", "check", "--fix", "src", "tests"],
    "freeze": [sys.executable, "-m", "recoup.simulator.freeze"],
    "verify-sim": [sys.executable, "-m", "recoup.simulator.freeze", "--verify"],
    "verify-ledger": [sys.executable, "-m", "recoup.cli", "verify-ledger"],
    "demo-failure": [sys.executable, "-m", "recoup.cli", "demo-failure"],
    "ingest": [sys.executable, "scripts/run_ingest.py"],
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        print("targets:")
        for name in TARGETS:
            print(f"  {name}")
        return 0

    target = sys.argv[1]
    if target not in TARGETS:
        print(f"unknown target: {target}", file=sys.stderr)
        print(f"available: {', '.join(TARGETS)}", file=sys.stderr)
        return 2

    return subprocess.call(TARGETS[target] + sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
