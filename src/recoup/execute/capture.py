"""Capture the webhook payload shapes Razorpay actually sends.

Why this exists (D-033 branch (b), mitigation 3a)
--------------------------------------------------
Branch (b) cannot produce a real `subscription.halted`, so that event is replayed
from a fixture built by reading the documentation. `_extract_ids()` is therefore
validated against **our reading of the docs**, not against a payload Razorpay
actually sent — which is the same proxy-not-artifact class as every guard in this
build that turned out to have a hole.

It cannot be fixed for `halted`. It *can* be narrowed: test mode really does send
`subscription.activated`, `subscription.charged` and `payment_link.paid`. Capture
those and the inferred surface shrinks to one event instead of four.

So this module records the first payload seen for each event type, and
`manifest()` reports which shapes are CAPTURED and which remain INFERRED. The
README states the same thing, and a test fails if the two disagree — because a
manifest nobody checks is a declared thing with no consumer.

The consumer is the ingest: `run_ingest.py` with `transport="real"` calls
`capture_payload()` for every verified webhook. Without that wiring this would be
a mechanism with no caller, which is the INC-005 shape.
"""

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Where the ingest WRITES. Gitignored, so nothing here is evidence yet.
CAPTURE_INBOX = Path(__file__).resolve().parents[3] / "runs" / "captured"

# Where committed evidence LIVES, and the only directory `manifest()` reads.
# A payload becomes a captured shape by being promoted here deliberately.
CAPTURED_DIR = FIXTURE_DIR / "captured"

# The event shapes `_extract_ids()` must handle. Anything here without a captured
# payload is inferred from documentation, and says so.
NEEDED_SHAPES: tuple[str, ...] = (
    "subscription.halted",
    "subscription.activated",
    "subscription.charged",
    "payment_link.paid",
)

# Capturable in Razorpay test mode without a failed subscription charge. The
# complement of this set is what branch (b) cannot obtain, and is exactly why the
# limitation is stated rather than engineered around.
CAPTURABLE_IN_TEST_MODE: frozenset[str] = frozenset({
    "subscription.activated",
    "subscription.charged",
    "payment_link.paid",
})


def _safe_name(event: str) -> str:
    return event.replace("/", "_").replace("..", "_") + ".json"


def capture_payload(event: str, raw: bytes, *, overwrite: bool = False) -> Path | None:
    """Record the first payload seen for `event` INTO THE INBOX. Never into evidence.

    First-write-wins. A later payload of the same type does not overwrite the
    captured one, so the fixture stays the thing that was actually observed
    rather than the most recent thing that happened to arrive.

    Writes to `runs/captured/`, which is gitignored. Promotion into
    `fixtures/captured/` — the directory `manifest()` reads — is a separate,
    deliberate act, because that directory is *evidence about what Razorpay
    sends*.

    That separation exists because it already failed the other way round: the
    ingest tests run with `transport="real"`, so this function fired against the
    committed fixtures directory and a hand-built test payload
    (`sub_test_001`) was committed as though it were a captured Razorpay shape.
    The manifest then reported `subscription.halted` as CAPTURED when it had
    never been observed. See INC-006.
    """
    if event not in NEEDED_SHAPES:
        return None

    CAPTURE_INBOX.mkdir(parents=True, exist_ok=True)
    path = CAPTURE_INBOX / _safe_name(event)
    if path.exists() and not overwrite:
        return None

    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None  # unparseable bodies are recorded in the ledger, not here

    path.write_text(
        json.dumps(parsed, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    return path


def is_captured(event: str) -> bool:
    """True only for a payload PROMOTED into the committed evidence directory."""
    return (CAPTURED_DIR / _safe_name(event)).exists()


def pending_captures() -> list[str]:
    """Events sitting in the inbox, observed but not yet promoted to evidence."""
    if not CAPTURE_INBOX.exists():
        return []
    return sorted(
        event
        for event in NEEDED_SHAPES
        if (CAPTURE_INBOX / _safe_name(event)).exists() and not is_captured(event)
    )


# Identifiers only this repository's own fixtures and generator produce. A payload
# containing one did not come from Razorpay.
_FABRICATED_MARKERS: tuple[str, ...] = (
    "sub_test_", "cust_test_", "sub_sim_", "cust_sim_", "evt_fl_", "evt_smoke",
    "sub_demo", "TPL_DEMO", "sub_1", "cust_1", "sub_GOLDEN",
)


def looks_fabricated(text: str) -> str | None:
    """Return the marker that gives a payload away as ours, or None."""
    for marker in _FABRICATED_MARKERS:
        if marker in text:
            return marker
    return None


def promote_capture(event: str) -> Path:
    """Move an observed payload from the inbox into committed evidence.

    Deliberately a separate call with no automatic trigger. Promoting a payload
    asserts *this is what Razorpay actually sent*, and that assertion should
    require someone to make it.

    It also refuses payloads carrying our own test identifiers. The inbox is
    written by any run with `transport="real"`, **including the test suite**, so
    it legitimately fills up with fabricated payloads — and the CLI that lists
    them will happily offer one for promotion. Catching that after the fact
    (INC-006) is worse than refusing it here.
    """
    source = CAPTURE_INBOX / _safe_name(event)
    if not source.exists():
        raise FileNotFoundError(
            f"no observed payload for {event!r} in {CAPTURE_INBOX}. Run the ingest "
            "against test mode with a tunnel first."
        )

    text = source.read_text(encoding="utf-8")
    marker = looks_fabricated(text)
    if marker is not None:
        raise ValueError(
            f"refusing to promote {event!r}: the payload contains {marker!r}, which is "
            f"one of this repository's own test identifiers. It was almost certainly "
            f"written by the test suite rather than by Razorpay. Promoting it would "
            f"make the manifest claim a shape was observed when it was invented "
            f"(INC-006). Delete {source} and capture a real one."
        )

    CAPTURED_DIR.mkdir(parents=True, exist_ok=True)
    target = CAPTURED_DIR / _safe_name(event)
    target.write_text(text, encoding="utf-8", newline="")
    return target


def manifest() -> dict[str, str]:
    """Which payload shapes are CAPTURED and which are INFERRED.

    Computed from the files that exist, never hand-maintained. A hand-written
    list would drift from reality the moment a capture landed, and the drift
    would be invisible.
    """
    out = {}
    for event in NEEDED_SHAPES:
        if is_captured(event):
            out[event] = "CAPTURED"
        elif event in CAPTURABLE_IN_TEST_MODE:
            out[event] = "INFERRED (capturable — run the demo against test mode)"
        else:
            out[event] = "INFERRED (not capturable in test mode — see D-033 branch (b))"
    return out


MANIFEST_BEGIN = "<!-- BEGIN generated: capture-manifest -->"
MANIFEST_END = "<!-- END generated: capture-manifest -->"


def manifest_markdown() -> str:
    """The README block, rendered from the filesystem.

    Delimited so a test can extract the committed block and compare it against a
    fresh render — the same treatment as the design table in `EXPERIMENT.md`, and
    for the same reason: a hand-maintained table drifts from reality the moment
    reality changes, and the drift is invisible.
    """
    lines = [MANIFEST_BEGIN, "| Event | Payload shape |", "|---|---|"]
    for event, status in manifest().items():
        lines.append(f"| `{event}` | {status} |")
    lines.append(MANIFEST_END)
    return "\n".join(lines)
