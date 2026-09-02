"""Two sentences must never be compressed. This checks the compression, not the words.

WHY PROXIMITY AND NOT PRESENCE
-------------------------------
The A-020 sweep began as "does the file mention A-020 anywhere" and missed both
plants, because a document can state a strong claim in its headline and qualify
it three paragraphs later. Presence is satisfied by a footnote; the reader is
not.

So each rule here is: **wherever the number appears, its qualifier must appear
within N characters of it.** A caveat in a different section fails, which is the
point — that is exactly how a strong claim survives a sweep that only checks
whether the caveat exists somewhere.

THE TWO SENTENCES
-----------------
1. **The A/A scope.** A pass rules out harness bias larger than ~6.23 pp. It does
   NOT establish an unbiased harness. Compressed to "the A/A passed", it becomes
   a claim the test cannot support.

2. **The intent accuracy.** 94.2%, on an interval of [84.4%, 98.0%] whose lower
   bound is BELOW the 85% pre-registered bar. Compressed to "94% accurate", it
   drops both the uncertainty and the fact that the interval does not exclude
   failing the bar.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Files that state these claims to a reader. Local-only files are checked when
#: present and skipped when not — a shipped test may not require a gitignored
#: file (the 59061cd failure).
CANDIDATES = (
    "README.md", "EVAL_RESULTS.md", "EXPERIMENT.md", "VIDEO.md",
    "SUBMISSION.md", "INCIDENTS.md",
)

#: ASSUMPTION: a qualifier this far from its number is still read as attached to
#: it. 600 characters is roughly a long paragraph. Chosen before running the
#: sweep, so it was not tuned to make the current documents pass. Range 300..1200.
PROXIMITY_CHARS = 600


def _present() -> list[str]:
    return [name for name in CANDIDATES if (REPO / name).exists()]


def _documents():
    for name in _present():
        yield name, (REPO / name).read_text(encoding="utf-8")


#: Markdown emphasis characters, blanked before matching.
#:
#: `It does **not** establish an unbiased harness` does not match
#: `does\s+not\s+establish` — the asterisks sit between the words. A guard that
#: cannot read the document's own formatting flags correct text, and a guard that
#: flags correct text gets switched off.
#:
#: Replaced with SPACES rather than removed, so every offset is preserved and the
#: reported line numbers still point at the real line.
_EMPHASIS = str.maketrans({"*": " ", "_": " ", "`": " "})


def _read(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8").translate(_EMPHASIS)


def _raw(name: str) -> str:
    """Unnormalised, for checks that care about the literal bytes."""
    return (REPO / name).read_text(encoding="utf-8")


def _near(text: str, anchor: re.Pattern, required: re.Pattern) -> list[str]:
    """Every anchor occurrence with no `required` match within PROXIMITY_CHARS."""
    orphans = []
    for match in anchor.finditer(text):
        lo = max(0, match.start() - PROXIMITY_CHARS)
        hi = min(len(text), match.end() + PROXIMITY_CHARS)
        if not required.search(text[lo:hi]):
            line = text[: match.start()].count("\n") + 1
            orphans.append(f"line {line}: {match.group(0)!r}")
    return orphans


# --- 1. the A/A scope sentence ----------------------------------------------------

_AA_CLAIM = re.compile(r"A/A\s+(?:test\s+)?(?:PASSED|passed|pass\b)", re.IGNORECASE)
#: Two phrasings of one sentence. VIDEO.md says "does not establish that the
#: harness is unbiased"; EXPERIMENT.md says "does not establish an unbiased
#: harness". Matching only one would fail a document that is correct, and a guard
#: that flags correct text gets switched off.
_AA_SCOPE = re.compile(
    r"(?:does\s+not|not)\s+establish\s+"
    r"(?:an?\s+unbiased\s+harness|that\s+the\s+harness\s+is\s+unbiased)",
    re.IGNORECASE,
)

#: Phrases marking the text as a QUOTED WRONG VERSION rather than an assertion.
#: Without this the guard fires on documents that exist precisely to warn against
#: the compression — `VIDEO.md` labels "the A/A passed" as the short false
#: version, and `EVAL_RESULTS.md` writes `not "94% accurate"`. Flagging those is
#: not strictness, it is the guard failing to read.
_NEGATION = re.compile(r"\bnot\b|\bnever\b|\bwrong\b", re.IGNORECASE)

# The word boundaries above are load-bearing and were briefly not there: an
# earlier edit went through a shell heredoc, which turned every \b into a
# literal backspace (0x08). The pattern then searched for "<BS>not<BS>" and
# matched nothing, so every disavowal read as an assertion. grep renders 0x08
# invisibly, so the file looked correct; printing .pattern is what showed it.
# Asserted at import rather than trusted:
assert "\b" not in _NEGATION.pattern, (
    "the negation pattern holds a literal backspace instead of a word boundary; "
    "it would match nothing and every disavowal would read as a claim"
)

#: ASSUMPTION: a disavowal only governs a phrase if it is this close. 48 chars is
#: about half a line. Range 24..96.
#:
#: It was 160 and that was too loose, found by planting: appending "The A/A test
#: passed. The classifier is 94% accurate." to a document did NOT fire the
#: accuracy check, because an unrelated "is not re-run" sat ~100 chars earlier.
#: "not" is one of the commonest words in English, so a wide window means almost
#: any assertion can find a nearby negation and excuse itself.
DISAVOWAL_CHARS = 48

#: A disavowed phrase is nearly always QUOTED — you put the wrong wording in
#: quotes to point at it. An unquoted phrase reads as the document's own voice,
#: so it needs a strong marker rather than a stray negation.
_STRONG_DISAVOWAL = re.compile(
    r"(?:short\s+)?false\s+version|rather\s+than|instead\s+of|"
    r"do\s+not\s+(?:say|let|use)|never\s+say",
    re.IGNORECASE,
)
_QUOTE_CHARS = "\"'`*“”‘’"


def _is_quoted(text: str, start: int, end: int) -> bool:
    """Is the match wrapped in quote-ish characters?"""
    before = text[max(0, start - 3) : start].strip()
    after = text[end : end + 3].strip()
    return bool(before and after and before[-1] in _QUOTE_CHARS and after[0] in _QUOTE_CHARS)


def _is_disavowed(text: str, start: int, end: int) -> bool:
    """Is this occurrence quoted as wrong rather than asserted?

    Two ways to qualify, and a bare nearby "not" is not one of them:

    * a STRONG marker nearby — "the short false version is ...", "rather than",
      "instead of";
    * the phrase is QUOTED and a negation sits within `DISAVOWAL_CHARS` — which
      is the `not "94% accurate"` shape.
    """
    near_before = text[max(0, start - DISAVOWAL_CHARS) : start]
    near_after = text[end : end + DISAVOWAL_CHARS]

    if _STRONG_DISAVOWAL.search(near_before) or _STRONG_DISAVOWAL.search(near_after):
        return True
    if _is_quoted(text, start, end) and _NEGATION.search(near_before):
        return True
    return False


_AA_MAGNITUDE = re.compile(r"6\.23")


@pytest.mark.parametrize("name", _present())
def test_an_aa_pass_is_never_stated_without_its_scope(name):
    text = _read(name)
    orphans = _near(text, _AA_CLAIM, _AA_SCOPE)
    assert not orphans, (
        f"{name} states the A/A passed without 'does not establish an unbiased "
        f"harness' within {PROXIMITY_CHARS} chars:\n  " + "\n  ".join(orphans)
    )


@pytest.mark.parametrize("name", _present())
def test_an_aa_pass_carries_the_magnitude_it_rules_out(name):
    text = _read(name)
    """'It does not establish an unbiased harness' without the number is a
    disclaimer. With 6.23 pp it is a measurement."""
    orphans = _near(text, _AA_CLAIM, _AA_MAGNITUDE)
    assert not orphans, (
        f"{name} states the A/A passed without the ~6.23 pp bound nearby:\n  "
        + "\n  ".join(orphans)
    )


# --- 2. the intent accuracy sentence ----------------------------------------------

_ACCURACY = re.compile(r"94\.2\s?%|49/52")
_INTERVAL = re.compile(r"84\.4|\[?\s*84\.4\s*%?\s*,\s*98\.0")

#: Phrasings that drop the interval entirely. These are refused wherever they
#: appear, regardless of what is nearby.
_COMPRESSED = (
    r"94%\s+accurate",
    r"94\.2%\s+accurate",
    r"accuracy\s+of\s+94%",
    r"\b94%\s+intent",
)


@pytest.mark.parametrize("name", _present())
def test_the_accuracy_never_appears_without_its_interval(name):
    text = _read(name)
    orphans = _near(text, _ACCURACY, _INTERVAL)
    assert not orphans, (
        f"{name} quotes the intent accuracy without its 95% CI lower bound "
        f"(84.4%) within {PROXIMITY_CHARS} chars. The interval's lower bound is "
        f"BELOW the 85% bar, so the point estimate alone overstates it:\n  "
        + "\n  ".join(orphans)
    )


@pytest.mark.parametrize("name", _present())
def test_no_document_says_94_percent_accurate(name):
    text = _read(name)
    # finditer, not search. `search` returns only the FIRST occurrence, and this
    # document's first is the legitimate disavowed one — `not "94% accurate"`. A
    # `search`-based check skipped it as disavowed and never looked further, so
    # planting an ASSERTED occurrence later in the same file did not fire. Found
    # by planting; the guard passed on a document that contained exactly the
    # sentence it exists to forbid.
    offenders = []
    for pattern in _COMPRESSED:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if _is_disavowed(text, match.start(), match.end()):
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"line {line}: {match.group(0)!r}")

    assert not offenders, (
        f"{name} asserts a compressed accuracy claim:\n  " + "\n  ".join(offenders)
        + "\nThe measurement is 94.2% on 52 items with a 95% CI of "
        "[84.4%, 98.0%] — a lower bound below the 85% bar. 'accurate' without "
        "the interval is not what was measured."
    )


# --- the guard must be able to fail ------------------------------------------------


def test_the_proximity_check_actually_rejects_a_distant_qualifier():
    """A presence check would pass this text. That is the whole difference."""
    text = (
        "The A/A test PASSED with p = 0.8932.\n\n"
        + ("filler paragraph. " * 80)
        + "\n\nSeparately, it does not establish an unbiased harness."
    )
    assert _near(text, _AA_CLAIM, _AA_SCOPE), (
        "the qualifier is far from the claim and the check did not fire — this "
        "is a presence check wearing proximity's clothes"
    )


def test_the_proximity_check_accepts_an_adjacent_qualifier():
    text = (
        "The A/A test PASSED (p = 0.8932). A pass rules out harness bias larger "
        "than about 6.23 pp; it does not establish an unbiased harness."
    )
    assert not _near(text, _AA_CLAIM, _AA_SCOPE)
    assert not _near(text, _AA_CLAIM, _AA_MAGNITUDE)


def test_at_least_one_document_actually_states_each_claim():
    """Otherwise every test above passes vacuously — a guard whose subject does
    not exist has never been shown to fire."""
    docs = list(_documents())
    assert any(_AA_CLAIM.search(t) for _, t in docs), (
        "no document states the A/A passed; the scope guard is vacuous"
    )
    assert any(_ACCURACY.search(t) for _, t in docs), (
        "no document quotes the intent accuracy; the interval guard is vacuous"
    )


def test_a_stray_negation_nearby_does_not_excuse_an_assertion():
    """The window was 160 chars and let this through.

    Planting "The A/A test passed. The classifier is 94% accurate." at the end of
    a document did not fire, because an unrelated "is not re-run" sat about 100
    characters earlier. "not" is one of the commonest words in English, so a wide
    window means almost any assertion can find a negation to hide behind.
    """
    text = (
        "The result is pinned and is not re-run, because re-running until a "
        "p-value pleases is optional stopping.\n\n"
        "## Summary\n\nThe classifier is 94% accurate.\n"
    )
    match = re.search(r"94%\s+accurate", text, re.IGNORECASE)
    assert match is not None
    assert not _is_disavowed(text, match.start(), match.end()), (
        "a stray 'not' 100 characters away excused an unquoted assertion"
    )


def test_a_quoted_phrase_with_an_adjacent_negation_is_disavowed():
    """The shape that IS legitimate: `... — not "94% accurate".`"""
    text = 'the honest form carries its interval, not "94% accurate" on its own.'
    match = re.search(r"94%\s+accurate", text, re.IGNORECASE)
    assert _is_disavowed(text, match.start(), match.end())


def test_a_strong_marker_disavows_even_unquoted():
    text = "Do not say the classifier is 94% accurate."
    match = re.search(r"94%\s+accurate", text, re.IGNORECASE)
    assert _is_disavowed(text, match.start(), match.end())
