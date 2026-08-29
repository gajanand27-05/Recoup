# INCIDENTS

Live build log. Entries are written **when the thing happens**, not reconstructed
afterwards. Timestamps are IST (UTC+05:30) because that is the clock the build ran on;
everything inside the system itself is UTC.

Nothing here is edited to look better in hindsight. Failures that were my own fault are
recorded as my own fault.

---

## INC-001 — The ledger accused itself of tampering

**2026-08-29 19:47 IST** · severity: high (silent, would have surfaced on camera) · status: fixed

**What happened**

Task 3 shipped `Ledger.append()` and `compute_hash()` with a hash-chained, append-only
store. All eight tests passed. A code review question — *does `compute_hash(prev, row)`
project correctly when handed a full row out of `rows()`, which is a different shape than
what `append()` passes in?* — turned out to have a bad answer.

`append()` hashed the row via `row.get("payload")`, which is `None` when the key is absent,
but *stored* the column via `row.get("payload", {})`, which is `{}`. So a row appended
without a `payload` key was hashed as `null` and persisted as `{}`.

On read-back, `rows()` parses the column and returns `{}`. Recomputing the hash then yields
a different digest than the one stored. That row can never verify. Not once, not ever.

**Why it mattered more than it looks**

`verify_chain()` reports this as `hash mismatch at seq N`. That is the exact message the
ledger emits when someone has tampered with a row. There is no way, from the output, to tell
a self-inflicted projection bug from an actual attack.

The intended demo is running `recoup verify-ledger` on camera and reading out the head hash.
The failure mode was: one webhook lands without a payload, the chain reports tampering, and
the thing being demonstrated as an integrity guarantee is the thing that breaks.

**How it was found**

Not by the test suite. The eight Task 3 tests all constructed rows through a `_row()` helper
that always set `payload`, so the divergent shape was never exercised. It was found by a
reviewer asking whether two callers with different input shapes could disagree.

**Fix**

Both callers now go through a single `_material(row)` projection, which normalises a missing
payload to `{}`. `append()` writes its columns *from that projection* rather than from the
caller's dict, so the hashed bytes and the stored bytes come from the same object. The two
paths cannot diverge by construction; it is no longer a convention that has to hold.

Commit `ce577e1`.

**What was added so it cannot come back**

- Round-trip tests over six row shapes — missing payload, explicit `None` optionals, nested
  dicts, non-ASCII — each asserting a row read back out of `rows()` rehashes to its stored hash
- A golden-hash pin: a fixed row asserted against a literal 64-char digest
- A frozen `_HASHED_FIELDS` tuple pin

**Second finding, from testing the fix**

Verifying that the golden pin could actually fail, by swapping two entries in
`_HASHED_FIELDS`, showed the hash *did not change*. `canonical_json` sorts keys, so field
**order** is not load-bearing — only membership is. The source comment claimed otherwise
("Fields hashed, in this order"), which would have misled anyone reasoning about the chain
rule later. Comment corrected.

A pin test that is never watched failing is an assumption wearing a test's clothes.

**Lesson kept**

A test helper that only ever builds one row shape tests one row shape. The bug lived in the
gap between what the helper produced and what the system would actually receive.
