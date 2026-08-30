"""Run the ingest server. Point a zrok tunnel at this.

    python scripts/run_ingest.py                   # terminal 1
    zrok share public http://localhost:8000        # terminal 2

`transport="real"` is declared here and nowhere else. This entry point is the one
place in the system that knows the bytes are arriving from Razorpay over a live
tunnel rather than from a replayed fixture -- the handler cannot tell, because a
fixture is byte-identical by design. Anything that replays fixtures must build
its own app with `transport="sim"`, and the two are never pooled in a reported
number.

RECOUP_RUN_ID scopes the rows of one run. At the end of a run, write and COMMIT
`runs/<run_id>.head` -- the ledger's own hash chain cannot detect that rows were
removed from its end, so completeness rests on an anchor recorded in git before
those rows existed.
"""

import os

import uvicorn

from recoup.config import settings
from recoup.ingest.app import MAX_ATTEMPTS, create_app, failed_events

app = create_app(
    db_path=settings.db_path,
    webhook_secret=settings.rzp_webhook_secret,
    run_id=os.getenv("RECOUP_RUN_ID", "first-light"),
    transport="real",
)

if __name__ == "__main__":
    if not settings.rzp_webhook_secret:
        raise SystemExit(
            "RZP_WEBHOOK_SECRET is not set. The server would reject every webhook "
            "as an invalid signature, which looks identical to Razorpay sending "
            "bad ones. Set it in .env before starting."
        )
    print(f"run_id={app.state.run_id} transport={app.state.transport}")
    print(f"recovered on boot: {app.state.recovered_on_boot} unfinished event(s)")

    gave_up = failed_events(app)
    if gave_up:
        # These never reached the ledger. Any rate computed as though they had is
        # wrong, so they get announced rather than left in a column nobody reads.
        print(f"\n!! {len(gave_up)} event(s) GIVEN UP after {MAX_ATTEMPTS} attempts:")
        for e in gave_up:
            print(f"   {e['event_id']}  {e['attempts']}x  {e['last_error']}")
        print("   the denominator for this run is short by that many. Report it.\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
