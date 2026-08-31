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
    """Record the first payload seen for `event`. Returns the path, or None if kept.

    First-write-wins by default. A later payload of the same type does not
    overwrite the captured one, so the fixture stays the thing that was actually
    observed rather than the most recent thing that happened to arrive.
    """
    if event not in NEEDED_SHAPES:
        return None

    CAPTURED_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPTURED_DIR / _safe_name(event)
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
    return (CAPTURED_DIR / _safe_name(event)).exists()


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
