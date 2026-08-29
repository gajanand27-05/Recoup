import hashlib
import hmac
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from recoup.clock import utc_now_iso
from recoup.ingest.app import create_app, mark_processed

SECRET = "whsec_test_123"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "ingest.db")


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path, webhook_secret=SECRET)


@pytest.fixture
def client(app):
    return TestClient(app)


def _post(client, body: dict, event_id: str, secret: str = SECRET):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhook",
        content=raw,
        headers={
            "X-Razorpay-Signature": sig,
            "x-razorpay-event-id": event_id,
            "Content-Type": "application/json",
        },
    )


HALTED = {
    "entity": "event",
    "event": "subscription.halted",
    "contains": ["subscription"],
    "payload": {"subscription": {"entity": {"id": "sub_001", "status": "halted"}}},
    "created_at": 1756400000,
}


# --- the contract Razorpay imposes -------------------------------------------


def test_a_valid_webhook_is_accepted_with_202(client):
    r = _post(client, {"event": "subscription.halted", "payload": {}}, "evt_001")
    assert r.status_code == 202


def test_a_bad_signature_is_rejected_with_400(client):
    r = _post(client, {"event": "subscription.halted"}, "evt_002", secret="wrong")
    assert r.status_code == 400


def test_a_missing_event_id_is_rejected(client):
    raw = json.dumps({"event": "subscription.halted"}).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=raw, headers={"X-Razorpay-Signature": sig})
    assert r.status_code == 400


def test_a_duplicate_event_id_is_acked_but_not_processed_twice(client, app):
    body = {"event": "subscription.halted", "payload": {}}
    first = _post(client, body, "evt_dup")
    mark_processed(app, "evt_dup")
    second = _post(client, body, "evt_dup")

    assert first.status_code == 202
    assert second.status_code == 202  # still ACK -- Razorpay must not retry
    assert second.json()["duplicate"] is True
    assert first.json()["duplicate"] is False
    assert app.state.queue.qsize() == 1


def test_health_endpoint_exists(client):
    assert client.get("/health").status_code == 200


# --- fail closed --------------------------------------------------------------


def test_an_unconfigured_secret_rejects_everything(tmp_path):
    # A blank RZP_WEBHOOK_SECRET must not degrade into "accept anything".
    blind = TestClient(create_app(db_path=str(tmp_path / "b.db"), webhook_secret=""))
    raw = b'{"event":"subscription.halted"}'
    for sig in ("", "0" * 64, hmac.new(b"", raw, hashlib.sha256).hexdigest()):
        r = blind.post(
            "/webhook",
            content=raw,
            headers={"X-Razorpay-Signature": sig, "x-razorpay-event-id": "evt_x"},
        )
        assert r.status_code == 400


def test_signature_is_checked_before_the_event_id(client):
    # An unauthenticated caller must not be able to probe dedupe state or write
    # rows to seen_events by omitting the header.
    r = client.post(
        "/webhook",
        content=b'{"event":"subscription.halted"}',
        headers={"X-Razorpay-Signature": "deadbeef"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid signature"


def test_a_rejected_webhook_leaves_no_trace_in_seen_events(client, db_path):
    _post(client, {"event": "subscription.halted"}, "evt_bad", secret="wrong")
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT count(*) FROM seen_events").fetchone()[0] == 0


# --- the raw body, end to end -------------------------------------------------


def test_the_queued_bytes_are_exactly_what_arrived(client, app):
    raw = json.dumps(HALTED).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    client.post(
        "/webhook",
        content=raw,
        headers={"X-Razorpay-Signature": sig, "x-razorpay-event-id": "evt_raw"},
    )
    queued = app.state.queue.get_nowait()
    assert queued["raw"] == raw, "the worker must see the bytes the signature covers"
    assert queued["event_id"] == "evt_raw"


def test_a_reserialised_body_fails_even_though_the_json_is_equal(client):
    # The signature covers bytes, not meaning. This is the failure the whole
    # raw-body discipline exists to prevent, exercised over HTTP.
    raw = json.dumps(HALTED).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    reserialised = json.dumps(HALTED, sort_keys=True, indent=2).encode()
    assert json.loads(reserialised) == json.loads(raw)

    r = client.post(
        "/webhook",
        content=reserialised,
        headers={"X-Razorpay-Signature": sig, "x-razorpay-event-id": "evt_rs"},
    )
    assert r.status_code == 400


# --- at-least-once, unordered -------------------------------------------------


def test_unordered_delivery_is_accepted_in_any_sequence(client):
    # Razorpay does not guarantee order. `halted` arriving before the charge
    # failures that caused it must not be rejected at the door.
    for eid, ev in (
        ("evt_c", "subscription.halted"),
        ("evt_a", "subscription.charged"),
        ("evt_b", "subscription.pending"),
    ):
        assert _post(client, {"event": ev, "payload": {}}, eid).status_code == 202


def test_an_event_seen_but_never_processed_is_redelivered(client, app, db_path):
    """The crash window. Dedupe keyed on arrival loses events.

    If the process dies between recording an event id and the worker finishing
    it, the in-memory queue goes with it. Razorpay retries, we say "duplicate",
    and the event is gone for good -- silently, and only under the crash that
    also destroyed the logs.

    So `seen_events` records status, and only a PROCESSED event is a duplicate.
    An event still marked `received` is re-enqueued. That risks processing twice,
    which is safe: state transitions are required to be idempotent and
    commutative anyway, because delivery is at-least-once and unordered.
    Re-processing is recoverable. Silent loss is not.
    """
    body = {"event": "subscription.halted", "payload": {}}
    first = _post(client, body, "evt_crash")
    assert first.json()["duplicate"] is False

    # Simulate the crash: the row survives, the queue does not.
    app.state.queue.get_nowait()
    assert app.state.queue.qsize() == 0

    second = _post(client, body, "evt_crash")
    assert second.status_code == 202
    assert second.json()["duplicate"] is False
    assert second.json()["redelivered"] is True
    assert app.state.queue.qsize() == 1, "a lost event must come back"


def test_a_processed_event_is_never_redelivered(client, app):
    body = {"event": "subscription.halted", "payload": {}}
    _post(client, body, "evt_done")
    app.state.queue.get_nowait()
    mark_processed(app, "evt_done")

    for _ in range(3):
        r = _post(client, body, "evt_done")
        assert r.status_code == 202
        assert r.json()["duplicate"] is True
    assert app.state.queue.qsize() == 0


def test_dedupe_survives_a_restart(db_path):
    # seen_events is on disk, so a restarted process must still refuse a
    # processed event. An in-memory set would forget.
    app1 = create_app(db_path=db_path, webhook_secret=SECRET)
    c1 = TestClient(app1)
    _post(c1, {"event": "subscription.halted"}, "evt_persist")
    mark_processed(app1, "evt_persist")

    app2 = create_app(db_path=db_path, webhook_secret=SECRET)
    c2 = TestClient(app2)
    r = _post(c2, {"event": "subscription.halted"}, "evt_persist")
    assert r.json()["duplicate"] is True
    assert app2.state.queue.qsize() == 0


# --- timestamps ---------------------------------------------------------------


def test_stored_timestamps_are_utc_with_a_trailing_z(client, db_path):
    _post(client, {"event": "subscription.halted"}, "evt_ts")
    conn = sqlite3.connect(db_path)
    first_seen = conn.execute("SELECT first_seen FROM seen_events").fetchone()[0]
    assert first_seen.endswith("Z"), first_seen
    assert "+00:00" not in first_seen


def test_utc_now_iso_ends_in_z_not_offset():
    ts = utc_now_iso()
    assert ts.endswith("Z")
    assert "+" not in ts
    assert "T" in ts
