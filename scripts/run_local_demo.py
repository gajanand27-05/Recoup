"""Run the ingest server on localhost for a live walkthrough.

    python scripts/run_local_demo.py            # terminal 1 -- the server
    python scripts/send_demo_event.py           # terminal 2 -- post a webhook

Then open http://localhost:8000/docs

WHY THIS IS NOT `run_ingest.py`
--------------------------------
`run_ingest.py` declares `transport="real"`, because it is the one entry point
that knows bytes arrived from Razorpay over a live tunnel. Pointing it at a
hand-built payload would write ledger rows labelled `real` that Razorpay never
sent -- manufactured evidence, and the exact INC-006 failure this repository
exists to prevent. So this server declares `transport="sim"` and says so on
the console, and `require_declared_split()` will refuse to pool these rows with
any real ones.

The demo secret below is a LOCAL DEMO CONSTANT, not a credential. It is not the
Razorpay webhook secret, it protects nothing, and it is committed on purpose so
the sender and the server agree without anyone editing `.env` before a demo.
"""

import sys
from pathlib import Path

import uvicorn

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from recoup.ingest.app import create_app  # noqa: E402

DEMO_SECRET = "local-demo-secret-not-a-credential"  # noqa: S105 - see module docstring
DEMO_DB = REPO / "runs" / "demo" / "localhost.db"


def build():
    """Build the app. Deliberately NOT called at import time.

    The sender imports DEMO_SECRET and DEMO_DB from this module. If building
    happened at import, that import would delete the database out from under the
    running server -- so the side effect lives behind __main__ and importing
    this module does nothing.
    """
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    if DEMO_DB.exists():
        DEMO_DB.unlink()  # a fresh chain each demo, so seq 1 is genuinely seq 1
    return create_app(
        db_path=str(DEMO_DB),
        webhook_secret=DEMO_SECRET,
        run_id="localhost-demo",
        transport="sim",
    )


if __name__ == "__main__":
    app = build()
    print("=" * 74)
    print("  recoup ingest -- LOCAL DEMO SERVER")
    print("=" * 74)
    print("  transport : sim   <- these rows are NOT labelled real, by design")
    print(f"  database  : {DEMO_DB}")
    print("  docs      : http://localhost:8000/docs")
    print("  health    : http://localhost:8000/health")
    print()
    print("  In another terminal:  python scripts/send_demo_event.py")
    print("=" * 74)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
