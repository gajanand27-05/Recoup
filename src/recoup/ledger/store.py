"""Append-only, hash-chained ledger.

Chain rule:  hash = sha256(prev_hash + canonical_json(row_without_hash_fields))

Append-only is enforced by SQLite triggers, not by convention. A ledger that is
only append-only because the application promises not to UPDATE is not an audit
trail; it is a table.
"""

import hashlib
import json
import sqlite3
from typing import Any

GENESIS = "0" * 64

# The fields folded into the hash. Adding or removing one breaks every existing
# chain -- pinned by test_the_hash_of_a_known_row_never_changes.
#
# The ORDER here does not affect the hash: canonical_json sorts keys, so only
# membership matters. The tuple is kept ordered for readability and pinned by
# test_the_hashed_field_set_is_frozen, so a reordering still names itself in CI
# rather than passing silently and implying order is load-bearing when it is not.
#
# To record something new, put it in `payload`. Do not extend this tuple.
_HASHED_FIELDS = (
    "run_id",
    "ts",
    "event_type",
    "subscription_id",
    "customer_id",
    "arm",
    "transport",
    "payload",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    ts              TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    subscription_id TEXT,
    customer_id     TEXT,
    arm             TEXT,
    transport       TEXT NOT NULL CHECK (transport IN ('real', 'sim')),
    payload         TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    hash            TEXT NOT NULL UNIQUE
);

CREATE TRIGGER IF NOT EXISTS ledger_no_update
BEFORE UPDATE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only');
END;

CREATE TRIGGER IF NOT EXISTS ledger_no_delete
BEFORE DELETE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only');
END;

CREATE INDEX IF NOT EXISTS idx_ledger_run ON ledger(run_id);
CREATE INDEX IF NOT EXISTS idx_ledger_sub ON ledger(subscription_id);
"""


def canonical_json(obj: Any) -> str:
    """Deterministic JSON. Any change here invalidates every stored hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _material(row: dict) -> dict:
    """Project a row onto exactly the hashed fields, normalised.

    Two callers reach this with different shapes: `append()` gets a caller-built
    dict, `verify_chain()` gets a row out of `rows()` carrying seq/hash/prev_hash
    and a payload that has been through JSON. Both must land on identical
    material or the ledger accuses itself of tampering. Sharing one projection is
    what makes that structural rather than a convention.

    `payload` defaults to `{}` and not `None`, because `{}` is what gets stored.
    """
    material = {k: row.get(k) for k in _HASHED_FIELDS}
    if material["payload"] is None:
        material["payload"] = {}
    return material


def compute_hash(prev_hash: str, row: dict) -> str:
    return hashlib.sha256(
        (prev_hash + canonical_json(_material(row))).encode("utf-8")
    ).hexdigest()


class Ledger:
    def __init__(self, db_path: str) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def head_hash(self) -> str:
        cur = self.conn.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
        return row["hash"] if row else GENESIS

    def append(self, row: dict) -> str:
        prev = self.head_hash()
        # Store from the same projection that is hashed -- never from `row` directly.
        material = _material(row)
        h = hashlib.sha256(
            (prev + canonical_json(material)).encode("utf-8")
        ).hexdigest()
        self.conn.execute(
            """INSERT INTO ledger
               (run_id, ts, event_type, subscription_id, customer_id,
                arm, transport, payload, prev_hash, hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                material["run_id"],
                material["ts"],
                material["event_type"],
                material["subscription_id"],
                material["customer_id"],
                material["arm"],
                material["transport"],
                canonical_json(material["payload"]),
                prev,
                h,
            ),
        )
        self.conn.commit()
        return h

    def rows(self, run_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM ledger"
        args: tuple = ()
        if run_id is not None:
            sql += " WHERE run_id = ?"
            args = (run_id,)
        sql += " ORDER BY seq"
        out = []
        for r in self.conn.execute(sql, args):
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out
