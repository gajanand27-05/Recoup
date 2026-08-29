"""Webhook ingest.

Razorpay requires a 2xx within 5 seconds; anything slower counts as a delivery
failure even if we processed the event. So: verify, dedupe, enqueue, ACK. All
real work happens on the worker side of the queue.

Delivery is at-least-once and UNORDERED. Dedupe is on `x-razorpay-event-id`,
which Razorpay documents as stable across retry attempts.
Source: https://razorpay.com/docs/webhooks/best-practices/ (retrieved 2026-08-28)

Dedupe is keyed on COMPLETION, not arrival
------------------------------------------
The obvious implementation records an event id on arrival and treats every later
delivery of that id as a duplicate. That loses events. The queue is in memory, so
if the process dies between recording the id and the worker finishing the work,
the job is gone -- and the record that says "already seen" is exactly what stops
Razorpay's retry from bringing it back.

The loss is silent, unrecoverable, and happens under the same crash that destroys
the logs that would explain it.

So `seen_events` carries a status. Only a `processed` event is a duplicate. An
event still marked `received` is re-enqueued on redelivery. That can process an
event twice, which is safe by construction: delivery is at-least-once and
unordered, so every state transition downstream has to be idempotent and
commutative regardless. Doing work twice is recoverable. Losing it is not.
"""

import asyncio
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Header, Request, Response

from recoup.clock import utc_now_iso
from recoup.ingest.signature import verify_signature

STATUS_RECEIVED = "received"
STATUS_PROCESSED = "processed"

_SEEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_events (
    event_id   TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('received', 'processed'))
);
"""


def mark_processed(app: FastAPI, event_id: str) -> None:
    """Called by the worker once an event is durably handled.

    Until this runs, a redelivery of the same id is re-enqueued rather than
    discarded. This is the only thing that makes an id a duplicate.
    """
    app.state.conn.execute(
        "UPDATE seen_events SET status = ? WHERE event_id = ?",
        (STATUS_PROCESSED, event_id),
    )
    app.state.conn.commit()


def create_app(db_path: str, webhook_secret: str) -> FastAPI:
    app = FastAPI(title="recoup ingest")
    app.state.queue = asyncio.Queue()

    parent = Path(db_path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    app.state.conn = sqlite3.connect(db_path, check_same_thread=False)
    app.state.conn.executescript(_SEEN_SCHEMA)
    app.state.conn.commit()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/webhook", status_code=202)
    async def webhook(
        request: Request,
        response: Response,
        x_razorpay_signature: str = Header(default=""),
        x_razorpay_event_id: str = Header(default=""),
    ) -> dict:
        # `await request.body()` and nothing else. The signature covers these
        # exact bytes; parsing and re-serialising changes them.
        raw = await request.body()

        # Authenticate FIRST. An unauthenticated caller must not be able to write
        # rows to seen_events or probe which event ids we have seen.
        if not verify_signature(raw, x_razorpay_signature, webhook_secret):
            response.status_code = 400
            return {"error": "invalid signature"}

        if not x_razorpay_event_id:
            response.status_code = 400
            return {"error": "missing x-razorpay-event-id"}

        # INSERT OR IGNORE is atomic, so two concurrent deliveries of the same id
        # cannot both be treated as first. rowcount tells us which one won.
        cur = app.state.conn.execute(
            "INSERT OR IGNORE INTO seen_events (event_id, first_seen, status) VALUES (?, ?, ?)",
            (x_razorpay_event_id, utc_now_iso(), STATUS_RECEIVED),
        )
        app.state.conn.commit()

        if cur.rowcount == 1:
            await app.state.queue.put({"event_id": x_razorpay_event_id, "raw": raw})
            return {"accepted": True, "duplicate": False, "redelivered": False}

        row = app.state.conn.execute(
            "SELECT status FROM seen_events WHERE event_id = ?", (x_razorpay_event_id,)
        ).fetchone()

        if row is not None and row[0] == STATUS_PROCESSED:
            # Genuinely done. ACK so Razorpay stops retrying.
            return {"accepted": True, "duplicate": True, "redelivered": False}

        # Seen but never finished -- in flight, or lost with a crashed process.
        # Re-enqueue. Duplicate work is safe; a dropped event is not.
        await app.state.queue.put({"event_id": x_razorpay_event_id, "raw": raw})
        return {"accepted": True, "duplicate": False, "redelivered": True}

    return app
