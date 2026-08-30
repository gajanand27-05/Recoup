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
a retry from bringing it back.

So `seen_events` carries a status. Only a `processed` event is a duplicate.

Recovery is OURS to perform, not Razorpay's
-------------------------------------------
It is tempting to stop there and assume redelivery closes the hole. It does not.
Razorpay only retries an event it did not get a 2xx for, and the crash that
matters -- the process dying with jobs still in the queue -- happens *after* the
ACK. Those events are delivered as far as Razorpay is concerned and will never
arrive again. Nothing comes back to trigger a re-enqueue.

The window redelivery actually covers is between the INSERT and the ACK: a few
milliseconds, and largely the same window in which the row was never committed
either. As a recovery mechanism it is close to worthless.

What makes `status` load-bearing is `sweep_unfinished()`, run at startup before
the server accepts traffic: every row still marked `received` is re-enqueued from
the durable record we already wrote. `seen_events` stores the raw body precisely
so this is possible -- an id alone cannot be re-executed.

That is why no separate durable job queue is needed: `seen_events` already is
one. Without the sweep it would only be a record that work was lost.

Both paths can process an event twice. That is safe by construction: delivery is
at-least-once and unordered, so every downstream state transition has to be
idempotent and commutative regardless. Doing work twice is recoverable. Losing it
is not.
"""

import asyncio
import json
import sqlite3
import threading
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, Request, Response

from recoup.clock import utc_now_iso
from recoup.ingest.signature import verify_signature
from recoup.ledger.store import Ledger

STATUS_RECEIVED = "received"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"

TRANSPORTS = ("real", "sim")

# A job that always explodes has two bad resting places. Left `received`, the
# startup sweep re-enqueues it every boot and it re-fires forever. Marked
# `processed` on failure, the event disappears with no record -- the same short
# denominator the status column exists to prevent, and at N=2,000 one malformed
# payload quietly costs a subscription from the sample.
#
# Neither. Attempts are counted, and after MAX_ATTEMPTS the event moves to the
# terminal `failed` status, which the sweep skips and the report must account
# for. Giving up is allowed; giving up silently is not.
#
# MAX_ATTEMPTS = 3 -- class: SELF_IMPOSED. Not sourced, and not derived from
# anything; it is a choice, recorded here so the reasoning lives with the number.
#
# Why 3 and not 1 or 10: a poison payload is DETERMINISTIC. Re-running it cannot
# make it parse. So retries do not exist to eventually succeed -- they exist to
# survive transient conditions that are not about the payload at all: SQLite
# write contention, a locked database during a concurrent read, a disk blip.
# Those clear in one or two attempts or they are not transient. Anything past ~3
# is spent re-failing on the deterministic case, which is the cost this cap
# exists to bound. 1 would retire an event on a single lock contention.
#
# Coincidentally equal to Razorpay's own retry count, which is not the reason and
# should not be read as one.
MAX_ATTEMPTS = 3

_SEEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_events (
    event_id   TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('received', 'processed', 'failed')),
    raw        BLOB NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_seen_status ON seen_events(status);
"""


def _extract_ids(body: dict) -> tuple[str | None, str | None]:
    """Pull subscription and customer ids out of any of the shapes we accept.

    Razorpay nests differently per event type, so this stays tolerant: a missing
    id is None, never an exception. Ordering is not guaranteed and neither is
    payload shape across event types, and an unrecognised shape must never cost
    us the audit row.
    """
    payload = body.get("payload") or {}
    for key in ("subscription", "payment", "payment_link"):
        entity = (payload.get(key) or {}).get("entity")
        if entity:
            return entity.get("id"), entity.get("customer_id")
    return None, None


def _to_ledger_row(raw: bytes, event_id: str, *, run_id: str, transport: str) -> dict:
    """Build the `webhook.received` row.

    The signature proves these bytes came from Razorpay. It does not prove they
    parse, so a body that is not JSON is still recorded -- losing the audit row
    for a malformed event is worse than recording that it was malformed.
    """
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("top-level JSON is not an object")
    except (ValueError, UnicodeDecodeError):
        return {
            "run_id": run_id,
            "ts": utc_now_iso(),
            "event_type": "webhook.received",
            "subscription_id": None,
            "customer_id": None,
            "arm": None,
            "transport": transport,
            "payload": {
                "event": None,
                "event_id": event_id,
                "unparseable": True,
                "raw_utf8": raw.decode("utf-8", errors="replace"),
            },
        }

    sub_id, cust_id = _extract_ids(body)
    return {
        "run_id": run_id,
        "ts": utc_now_iso(),
        "event_type": "webhook.received",
        "subscription_id": sub_id,
        "customer_id": cust_id,
        "arm": None,
        "transport": transport,
        "payload": {"event": body.get("event"), "event_id": event_id, "body": body},
    }


def process_one(app: FastAPI, job: dict) -> str | None:
    """Write one queued webhook to the ledger. Returns the row hash, or None if
    the event was already recorded.

    The ledger append and the status update go through ONE connection and ONE
    commit. A half-applied event is the only outcome that must be impossible:
    a committed row with an uncommitted status would be replayed by the next
    sweep into a duplicate, and a committed status with an uncommitted row would
    mark the event done with its audit record missing.
    """
    conn = app.state.conn
    event_id = job["event_id"]

    with app.state.lock:
        row = conn.execute(
            "SELECT status FROM seen_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is not None and row[0] == STATUS_PROCESSED:
            return None  # a recovery replay of work already durably recorded

        try:
            # Inside the try: building the row is where a malformed payload fails,
            # which is the poison case the attempt counter exists for.
            record = _to_ledger_row(
                job["raw"],
                event_id,
                run_id=app.state.run_id,
                transport=app.state.transport,
            )
            h = app.state.ledger.append(record, commit=False)
            mark_processed(app, event_id, commit=False)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            _record_attempt_failure(app, event_id, exc)
            raise
    return h


def _record_attempt_failure(app: FastAPI, event_id: str, exc: BaseException) -> int:
    """Count a failed attempt and retire the event once it has had enough.

    Runs in its own committed transaction, after the rollback, because the point
    is to persist the fact that the work did NOT happen.
    """
    conn = app.state.conn
    conn.execute(
        "UPDATE seen_events SET attempts = attempts + 1, last_error = ? WHERE event_id = ?",
        (repr(exc)[:500], event_id),
    )
    attempts = conn.execute(
        "SELECT attempts FROM seen_events WHERE event_id = ?", (event_id,)
    ).fetchone()[0]
    if attempts >= MAX_ATTEMPTS:
        conn.execute(
            "UPDATE seen_events SET status = ? WHERE event_id = ?",
            (STATUS_FAILED, event_id),
        )
    conn.commit()
    return attempts


def failed_events(app: FastAPI) -> list[dict]:
    """Events this run gave up on. Must appear in the report.

    A non-empty result means the denominator is short: those subscriptions never
    reached the ledger, so any rate computed as if they had is wrong.
    """
    return [
        {"event_id": r[0], "attempts": r[1], "last_error": r[2], "first_seen": r[3]}
        for r in app.state.conn.execute(
            "SELECT event_id, attempts, last_error, first_seen FROM seen_events "
            "WHERE status = ? ORDER BY first_seen",
            (STATUS_FAILED,),
        )
    ]


def drain(app: FastAPI) -> int:
    """Process every queued job now. Returns how many ledger rows were written.

    Used by the startup path and by tests, where a background worker would make
    assertions race the thing they are asserting about.
    """
    written = 0
    while True:
        try:
            job = app.state.queue.get_nowait()
        except asyncio.QueueEmpty:
            return written
        if process_one(app, job) is not None:
            written += 1


async def _worker(app: FastAPI) -> None:
    """Drain the queue for as long as the server runs.

    This is what calls mark_processed() in production. Without it the ACK path
    would record every event as `received` and never advance it, so the startup
    sweep would replay the entire history on every boot -- dedupe failing in the
    opposite direction, and just as silently.
    """
    queue: asyncio.Queue = app.state.queue
    while True:
        job = await queue.get()
        try:
            process_one(app, job)
        except Exception as exc:  # noqa: BLE001 - a bad event must not kill the worker
            app.state.worker_errors.append((job.get("event_id"), repr(exc)))
        finally:
            queue.task_done()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.worker_task = asyncio.create_task(_worker(app))
    try:
        yield
    finally:
        app.state.worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.worker_task


def mark_processed(app: FastAPI, event_id: str, *, commit: bool = True) -> None:
    """Called by the worker once an event is durably handled.

    Until this runs the event is recoverable: a redelivery re-enqueues it, and so
    does the next startup sweep. This call is the only thing that makes an id a
    duplicate, so a worker that forgets it leaves every event replaying forever.
    """
    app.state.conn.execute(
        "UPDATE seen_events SET status = ? WHERE event_id = ?",
        (STATUS_PROCESSED, event_id),
    )
    if commit:
        app.state.conn.commit()


def sweep_unfinished(app: FastAPI) -> int:
    """Re-enqueue every event recorded but never marked processed. Returns the count.

    This is the actual crash recovery. It must run before the server accepts
    traffic: a sweep racing an inbound redelivery double-enqueues, which is
    harmless given idempotency but muddies the log at exactly the moment someone
    is reading it to find out what the crash did.

    Re-running it re-enqueues the same rows again. Deliberate -- the alternative
    is tracking in-flight state in memory, which is the thing that just died.
    """
    rows = app.state.conn.execute(
        "SELECT event_id, raw FROM seen_events WHERE status = ? ORDER BY first_seen",
        (STATUS_RECEIVED,),
    ).fetchall()
    for event_id, raw in rows:
        app.state.queue.put_nowait(
            {"event_id": event_id, "raw": bytes(raw), "recovered": True}
        )
    return len(rows)


def _assert_schema_is_current(conn: sqlite3.Connection) -> None:
    """Fail loudly on a pre-`raw` database instead of obscurely later.

    CREATE TABLE IF NOT EXISTS silently accepts an older table, and the first
    symptom would be a sweep that recovers nothing.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(seen_events)")}
    missing = {"raw", "attempts"} - cols
    if cols and missing:
        raise RuntimeError(
            f"seen_events is missing {sorted(missing)}. Without `raw` crashed jobs "
            "cannot be recovered; without `attempts` a poison job re-fires on every "
            "boot. Delete the database and start a new run."
        )


def create_app(
    db_path: str,
    webhook_secret: str,
    *,
    run_id: str = "first-light",
    transport: str = "sim",
) -> FastAPI:
    """Build the ingest app.

    `transport` must be declared and is NOT inferred. The handler cannot tell a
    live Razorpay webhook from a replayed fixture -- the bytes are identical by
    design, that being the point of a fixture. `real` and `sim` are never pooled
    in any reported number, so the value has to come from whoever knows.

    It defaults to `sim` because the two mistakes are not symmetric. Labelling a
    fixture `real` manufactures evidence that the system ran against Razorpay.
    Labelling a real event `sim` only forfeits a claim we were entitled to make.
    Default to the error that costs us something rather than the one that costs
    the reader something.
    """
    if transport not in TRANSPORTS:
        raise ValueError(f"transport must be one of {TRANSPORTS}, got {transport!r}")

    app = FastAPI(title="recoup ingest", lifespan=_lifespan)
    app.state.queue = asyncio.Queue()
    app.state.run_id = run_id
    app.state.transport = transport
    app.state.worker_errors: list[tuple[str | None, str]] = []

    # One connection for the ledger AND seen_events, so the worker can commit a
    # ledger row and its status update together. Two connections could not.
    app.state.ledger = Ledger(db_path, check_same_thread=False)
    app.state.conn = app.state.ledger.conn
    # Starlette may run the handler on a different thread than the worker, and
    # they now share one connection. Serialise every write through this.
    app.state.lock = threading.Lock()
    _assert_schema_is_current(app.state.conn)
    app.state.conn.executescript(_SEEN_SCHEMA)
    app.state.conn.commit()

    # Before anything can be served. create_app() returns to the caller who then
    # hands the app to uvicorn, so recovery is complete before the socket binds.
    app.state.recovered_on_boot = sweep_unfinished(app)

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
        with app.state.lock:
            cur = app.state.conn.execute(
                "INSERT OR IGNORE INTO seen_events (event_id, first_seen, status, raw) "
                "VALUES (?, ?, ?, ?)",
                (x_razorpay_event_id, utc_now_iso(), STATUS_RECEIVED, raw),
            )
            app.state.conn.commit()

        if cur.rowcount == 1:
            # The row is committed before the enqueue, so a crash here leaves the
            # job recoverable by the next sweep rather than lost with the queue.
            await app.state.queue.put(
                {"event_id": x_razorpay_event_id, "raw": raw, "recovered": False}
            )
            return {"accepted": True, "duplicate": False, "redelivered": False}

        with app.state.lock:
            row = app.state.conn.execute(
                "SELECT status FROM seen_events WHERE event_id = ?", (x_razorpay_event_id,)
            ).fetchone()

        if row is not None and row[0] == STATUS_PROCESSED:
            # Genuinely done. ACK so Razorpay stops retrying.
            return {"accepted": True, "duplicate": True, "redelivered": False}

        # Seen but never finished. Almost always still in flight -- a crashed job
        # is recovered by the startup sweep, not by this path, because Razorpay
        # will not redeliver an event it already got a 2xx for. Re-enqueue anyway:
        # duplicate work is safe, and a dropped event is not.
        await app.state.queue.put(
            {"event_id": x_razorpay_event_id, "raw": raw, "recovered": False}
        )
        return {"accepted": True, "duplicate": False, "redelivered": True}

    return app
