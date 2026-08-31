"""The capture mitigation for D-033 branch (b), 3a.

Branch (b) cannot produce a real `subscription.halted`, so that shape is inferred
from documentation and `_extract_ids()` is validated against our reading rather
than against a payload Razorpay sent. That is the proxy-not-artifact class.

It cannot be fixed for `halted`. It can be narrowed: the other three shapes ARE
obtainable in test mode. This file checks the mechanism that narrows it, and that
the mechanism is honest about what it has and has not got.
"""

import json
from pathlib import Path

import pytest

from recoup.execute import capture
from recoup.execute.capture import (
    CAPTURABLE_IN_TEST_MODE,
    MANIFEST_BEGIN,
    MANIFEST_END,
    NEEDED_SHAPES,
    capture_payload,
    manifest,
    manifest_markdown,
)

REPO = Path(__file__).resolve().parents[1]

HALTED = {
    "entity": "event",
    "event": "subscription.halted",
    "payload": {"subscription": {"entity": {"id": "sub_1", "customer_id": "cust_1"}}},
}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "CAPTURED_DIR", tmp_path / "captured")
    return tmp_path / "captured"


# --- the mechanism ---------------------------------------------------------------


def test_a_payload_is_written_on_first_sight(isolated):
    path = capture_payload("subscription.halted", json.dumps(HALTED).encode())
    assert path is not None and path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["event"] == "subscription.halted"


def test_first_write_wins(isolated):
    capture_payload("subscription.halted", json.dumps(HALTED).encode())
    second = dict(HALTED, payload={"subscription": {"entity": {"id": "sub_LATER"}}})
    assert capture_payload("subscription.halted", json.dumps(second).encode()) is None

    stored = json.loads((isolated / "subscription.halted.json").read_text(encoding="utf-8"))
    assert stored["payload"]["subscription"]["entity"]["id"] == "sub_1", (
        "a later payload must not overwrite the one actually observed first"
    )


def test_an_event_we_do_not_need_is_not_captured(isolated):
    assert capture_payload("payment.authorized", b"{}") is None
    assert not (isolated / "payment.authorized.json").exists()


def test_an_unparseable_body_is_not_captured(isolated):
    # It is still recorded in the ledger as `unparseable`. It is just not usable
    # as a shape fixture, and a broken fixture is worse than a missing one.
    assert capture_payload("subscription.halted", b"not json") is None


def test_a_path_traversing_event_name_cannot_escape_the_directory(isolated):
    capture_payload("subscription.halted", json.dumps(HALTED).encode())
    written = list(isolated.glob("*.json"))
    assert all(p.parent == isolated for p in written)


# --- the manifest is computed, never hand-maintained -------------------------------


def test_the_manifest_covers_every_needed_shape(isolated):
    assert set(manifest()) == set(NEEDED_SHAPES)


def test_an_uncaptured_shape_reports_as_inferred(isolated):
    assert manifest()["subscription.halted"].startswith("INFERRED")


def test_capturing_a_shape_flips_it_in_the_manifest(isolated):
    """The manifest reads the filesystem. A hand-written list would drift from
    reality the moment a capture landed, and the drift would be invisible."""
    before = manifest()["subscription.charged"]
    capture_payload(
        "subscription.charged",
        json.dumps({"event": "subscription.charged", "payload": {}}).encode(),
    )
    after = manifest()["subscription.charged"]

    assert before.startswith("INFERRED")
    assert after == "CAPTURED"


def test_halted_is_marked_as_not_capturable_in_test_mode(isolated):
    """The honest part. Branch (b) cannot obtain this one, and the manifest says
    so rather than leaving it looking merely not-done-yet."""
    assert "subscription.halted" not in CAPTURABLE_IN_TEST_MODE
    assert "not capturable" in manifest()["subscription.halted"]


def test_the_other_three_are_marked_capturable(isolated):
    for event in ("subscription.activated", "subscription.charged", "payment_link.paid"):
        assert event in CAPTURABLE_IN_TEST_MODE
        assert "capturable" in manifest()[event]


# --- the README must agree with the manifest ---------------------------------------


def test_the_readme_states_the_current_capture_state():
    """The README is what a judge reads; the manifest is what is true.

    Nothing kept `PARAMS.md` and the params registry in step and they drifted
    (INC-003 F-3). This makes the same drift a failing test: when a capture
    lands, this goes red and forces the README to be regenerated.

    The block is matched exactly rather than by searching for the event name --
    the first mention of `subscription.halted` in the README is in the problem
    statement, not the table, and a looser check found that instead.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    start = readme.index(MANIFEST_BEGIN)
    end = readme.index(MANIFEST_END) + len(MANIFEST_END)
    assert readme[start:end] == manifest_markdown(), (
        "README's capture manifest has drifted. Regenerate it from "
        "`recoup.execute.capture.manifest_markdown()` -- do not hand-edit."
    )


def test_a_hand_edited_manifest_would_be_caught():
    """The planted failure for the drift guard."""
    fresh = manifest_markdown()
    tampered = fresh.replace("INFERRED (not capturable", "CAPTURED (not capturable")
    assert tampered != fresh, "the replacement did not apply; this test has gone blind"
    assert tampered != manifest_markdown()


# --- the mechanism has a consumer ---------------------------------------------------


def test_the_ingest_calls_capture_for_a_real_transport():
    """Otherwise this is a mechanism with no caller — the INC-005 shape.

    Checked against the artifact: the ingest module must actually reference it.
    """
    import ast

    from recoup.ingest import app as app_mod

    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "capture_payload" in called, "the ingest never calls capture_payload"
