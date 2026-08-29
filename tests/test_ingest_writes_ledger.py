import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from recoup.ingest.app import STATUS_RECEIVED, create_app, drain, process_one
from recoup.ledger.store import Ledger
from recoup.ledger.verify import verify_chain

SECRET = "whsec_test_123"

HALTED = {
    "entity": "event",
    "event": "subscription.halted",
    "payload": {
        "subscription": {
            "entity": {"id": "sub_test_001", "customer_id": "cust_test_001"}
        }
    },
}


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "fl.db")
    app = create_app(db_path=db, webhook_secret=SECRET)
    return TestClient(app), db, app


def _send(client, body: dict, event_id: str):
    raw = json.dumps(body).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhook",
        content=raw,
        headers={"X-Razorpay-Signature": sig, "x-razorpay-event-id": event_id},
    )


# --- the ledger row -----------------------------------------------------------


def test_an_accepted_webhook_lands_in_the_ledger(env):
    client, db, app = env
    assert _send(client, HALTED, "evt_fl_001").status_code == 202

    # The handler ACKs and enqueues; the worker writes. Nothing durable-but-slow
    # happens inside the 5s budget.
    assert drain(app) == 1

    rows = Ledger(db).rows()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "webhook.received"
    assert rows[0]["subscription_id"] == "sub_test_001"
    assert rows[0]["customer_id"] == "cust_test_001"
    assert rows[0]["payload"]["event"] == "subscription.halted"
    assert rows[0]["payload"]["event_id"] == "evt_fl_001"


def test_nothing_is_written_before_the_worker_runs(env):
    client, db, app = env
    _send(client, HALTED, "evt_fl_early")
    assert Ledger(db).rows() == []


def test_a_duplicate_does_not_write_a_second_ledger_row(env):
    client, db, app = env
    _send(client, HALTED, "evt_fl_dup")
    drain(app)
    _send(client, HALTED, "evt_fl_dup")
    drain(app)
    assert len(Ledger(db).rows()) == 1


def test_the_timestamp_is_utc_with_a_z(env):
    client, db, app = env
    _send(client, HALTED, "evt_fl_ts")
    drain(app)
    assert Ledger(db).rows()[0]["ts"].endswith("Z")


def test_the_chain_still_verifies_after_ingest(env):
    client, db, app = env
    for i in range(5):
        _send(client, HALTED, f"evt_fl_chain_{i}")
    drain(app)
    result = verify_chain(Ledger(db))
    assert result.ok is True
    assert result.rows_checked == 5


# --- transport: the field that must never be guessed --------------------------
# `real` and `sim` are never pooled in any reported number. The ingest cannot
# tell a live Razorpay webhook from a replayed fixture -- the bytes are identical
# by design, that being the point of the fixture. So it must be TOLD, and the
# default must be the one that understates rather than overstates.


def test_transport_defaults_to_sim_not_real(env):
    client, db, app = env
    _send(client, HALTED, "evt_fl_tr")
    drain(app)
    assert Ledger(db).rows()[0]["transport"] == "sim", (
        "an unlabelled event must not claim to have come from Razorpay"
    )


def test_transport_real_is_recorded_when_explicitly_declared(tmp_path):
    db = str(tmp_path / "real.db")
    app = create_app(db_path=db, webhook_secret=SECRET, transport="real")
    _send(TestClient(app), HALTED, "evt_fl_real")
    drain(app)
    assert Ledger(db).rows()[0]["transport"] == "real"


def test_an_invalid_transport_is_refused_at_construction(tmp_path):
    with pytest.raises(ValueError, match="transport"):
        create_app(db_path=str(tmp_path / "x.db"), webhook_secret=SECRET, transport="mock")


def test_run_id_is_recorded_and_configurable(tmp_path):
    db = str(tmp_path / "r.db")
    app = create_app(db_path=db, webhook_secret=SECRET, run_id="run-2026-08-29-a")
    _send(TestClient(app), HALTED, "evt_fl_run")
    drain(app)
    assert Ledger(db).rows()[0]["run_id"] == "run-2026-08-29-a"


# --- tolerant id extraction ---------------------------------------------------


def test_ids_are_extracted_from_a_payment_entity(env):
    client, db, app = env
    body = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": "pay_1", "customer_id": "cust_9"}}},
    }
    _send(client, body, "evt_fl_pay")
    drain(app)
    row = Ledger(db).rows()[0]
    assert row["subscription_id"] == "pay_1"
    assert row["customer_id"] == "cust_9"


def test_a_payload_with_no_recognisable_entity_still_records(env):
    # Razorpay nests differently per event type and ordering is not guaranteed.
    # An unknown shape must never cost us the audit row.
    client, db, app = env
    _send(client, {"event": "something.new", "payload": {"mystery": {}}}, "evt_fl_odd")
    drain(app)
    row = Ledger(db).rows()[0]
    assert row["subscription_id"] is None
    assert row["customer_id"] is None
    assert row["payload"]["body"]["event"] == "something.new"


def test_a_body_that_is_not_json_does_not_take_the_server_down(env):
    # The signature proves the bytes came from Razorpay, not that they parse.
    client, db, app = env
    raw = b"not json at all"
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = client.post(
        "/webhook",
        content=raw,
        headers={"X-Razorpay-Signature": sig, "x-razorpay-event-id": "evt_fl_junk"},
    )
    assert r.status_code == 202
    assert drain(app) == 1
    row = Ledger(db).rows()[0]
    assert row["payload"]["unparseable"] is True
    assert row["subscription_id"] is None


# --- atomicity and recovery ---------------------------------------------------


def test_the_ledger_write_and_the_status_update_are_one_transaction(env, monkeypatch):
    """A half-applied event is the one outcome that must not be possible.

    If the ledger row committed but the status did not, the startup sweep would
    replay it and append a second row for the same event. If the status committed
    but the row did not, the event is marked done and its audit record is gone.
    Both go through one connection and one commit, so neither can happen.
    """
    client, db, app = env
    _send(client, HALTED, "evt_fl_atomic")

    import recoup.ingest.app as appmod

    def boom(*a, **kw):
        raise RuntimeError("worker died between the two writes")

    monkeypatch.setattr(appmod, "mark_processed", boom)

    with pytest.raises(RuntimeError):
        process_one(app, app.state.queue.get_nowait())

    assert Ledger(db).rows() == [], "the ledger row must not survive a failed transaction"
    status = app.state.conn.execute(
        "SELECT status FROM seen_events WHERE event_id = ?", ("evt_fl_atomic",)
    ).fetchone()[0]
    assert status == STATUS_RECEIVED, "still recoverable by the next sweep"


def test_a_recovered_job_does_not_duplicate_its_ledger_row(tmp_path):
    db = str(tmp_path / "rec.db")
    app1 = create_app(db_path=db, webhook_secret=SECRET)
    _send(TestClient(app1), HALTED, "evt_fl_recover")
    drain(app1)
    assert len(Ledger(db).rows()) == 1

    # Crash after the work was done but with the queue still holding nothing:
    # a fresh boot must not re-append what is already recorded.
    app2 = create_app(db_path=db, webhook_secret=SECRET)
    assert app2.state.recovered_on_boot == 0
    drain(app2)
    assert len(Ledger(db).rows()) == 1


def test_work_lost_to_a_crash_is_written_on_the_next_boot(tmp_path):
    db = str(tmp_path / "lost.db")
    app1 = create_app(db_path=db, webhook_secret=SECRET)
    _send(TestClient(app1), HALTED, "evt_fl_lost")
    # Process dies before draining. Razorpay already got its 202.
    del app1
    assert Ledger(db).rows() == []

    app2 = create_app(db_path=db, webhook_secret=SECRET)
    assert app2.state.recovered_on_boot == 1
    assert drain(app2) == 1
    rows = Ledger(db).rows()
    assert len(rows) == 1
    assert rows[0]["payload"]["event_id"] == "evt_fl_lost"


def test_the_background_worker_writes_without_anyone_calling_drain(tmp_path):
    """The production path. `drain()` is a test and startup affordance; a running
    server must write the ledger on its own or mark_processed never fires and the
    sweep replays the whole history on every boot.
    """
    db = str(tmp_path / "w.db")
    app = create_app(db_path=db, webhook_secret=SECRET, transport="real")
    with TestClient(app) as client:  # entering the context starts the lifespan
        _send(client, HALTED, "evt_fl_worker")
        for _ in range(200):
            if Ledger(db).rows():
                break
            time.sleep(0.01)

    rows = Ledger(db).rows()
    assert len(rows) == 1
    assert rows[0]["transport"] == "real"
    assert app.state.worker_errors == []
    status = app.state.conn.execute(
        "SELECT status FROM seen_events WHERE event_id = ?", ("evt_fl_worker",)
    ).fetchone()[0]
    assert status == "processed"


def test_a_worker_failure_does_not_kill_the_worker(tmp_path, monkeypatch):
    db = str(tmp_path / "we.db")
    app = create_app(db_path=db, webhook_secret=SECRET)

    import recoup.ingest.app as appmod

    calls = {"n": 0}
    real = appmod.process_one

    def flaky(a, job):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first one explodes")
        return real(a, job)

    monkeypatch.setattr(appmod, "process_one", flaky)

    with TestClient(app) as client:
        _send(client, HALTED, "evt_fl_boom")
        _send(client, HALTED, "evt_fl_ok")
        for _ in range(200):
            if Ledger(db).rows():
                break
            time.sleep(0.01)

    assert len(Ledger(db).rows()) == 1, "the second event still got through"
    assert app.state.worker_errors and app.state.worker_errors[0][0] == "evt_fl_boom"


def test_draining_marks_processed_so_the_sweep_stops_replaying(env):
    # mark_processed() having no caller would make every event replay forever.
    client, db, app = env
    _send(client, HALTED, "evt_fl_mark")
    drain(app)
    status = app.state.conn.execute(
        "SELECT status FROM seen_events WHERE event_id = ?", ("evt_fl_mark",)
    ).fetchone()[0]
    assert status == "processed"
