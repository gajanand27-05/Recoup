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
#: Kept in sync with the repository by
#: `test_the_candidate_list_covers_every_markdown_document_that_ships`, which
#: walks `*.md` rather than trusting this literal. SIMULATOR_FREEZE.md was
#: missing from it and that check is what found it.
CANDIDATES = (
    "README.md", "EVAL_RESULTS.md", "EXPERIMENT.md", "VIDEO.md",
    "SUBMISSION.md", "INCIDENTS.md", "SIMULATOR_FREEZE.md", "SOURCES.md",
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


#: Blockquote markers at line starts, blanked the same way and for the same
#: reason. A sentence wrapped inside a `>` quote reads as
#: `"not the same as\n> there being none"`, and `\s+` does not match `>` — so a
#: clause that IS adjacent looks absent. Found on VIDEO.md, whose script lines
#: are all blockquoted.
#:
#: Only at line starts: a bare `>` mid-line is a comparison or an arrow, and
#: `->` is a disavowal marker that must survive.
_BLOCKQUOTE = re.compile(r"^([ \t]*)>", re.MULTILINE)


def _read(name: str) -> str:
    text = (REPO / name).read_text(encoding="utf-8").translate(_EMPHASIS)
    # Length-preserving, so reported line numbers still point at the real line.
    return _BLOCKQUOTE.sub(lambda m: m.group(1) + " ", text)


def _raw(name: str) -> str:
    """Unnormalised, for checks that care about the literal bytes."""
    return (REPO / name).read_text(encoding="utf-8")


def _near(text: str, anchor: re.Pattern, required: re.Pattern) -> list[str]:
    """Every anchor occurrence with no `required` match within PROXIMITY_CHARS."""
    orphans = []
    for match in anchor.finditer(text):
        lo = max(0, match.start() - PROXIMITY_CHARS)
        hi = min(len(text), match.end() + PROXIMITY_CHARS)
        if required.search(text[lo:hi]):
            continue
        # A phrase quoted AS WRONG is not an assertion of it. Without this the
        # guard fires on the documents that exist to warn against the very
        # compression it is checking for.
        if _is_disavowed(text, match.start(), match.end()):
            continue
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
def _assert_no_literal_backspaces() -> None:
    """EVERY compiled pattern in this module, not one named variable.

    This has now happened twice. The first version of this check named
    `_NEGATION` and therefore sat and watched while the same shell heredoc did
    the same thing to `_STRONG_DISAVOWAL` an hour later — a guard that covers one
    instance of the failure it exists for.
    """
    import sys as _sys

    for name, value in vars(_sys.modules[__name__]).items():
        if isinstance(value, re.Pattern) and chr(8) in value.pattern:
            raise AssertionError(
                f"{name} holds a literal backspace instead of a word boundary; it "
                f"would match nothing and every check using it would pass "
                f"vacuously. Pattern: {value.pattern!r}"
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
    # WRONGNESS markers only. "rather than" and "instead of" were in this list
    # and were far too loose: "fixed in advance rather than after seeing the
    # number" sat one sentence away from the REAL sign-flip report and exempted
    # it, so the guard passed vacuously on the exact text it exists to check.
    # Same failure as the 160-char "not" window, one level up.
    r"(?:short\s+)?false\s+version|\bfalse\b|\bspurious\b|"
    r"do\s+not\s+(?:say|let|use)|never\s+say",
    re.IGNORECASE,
)

#: Files that REPORT a result. The result guards apply to these.
#:
#: `EXPERIMENT.md` is a pre-registration: it states the RULE ("a sweep that flips
#: the sign falsifies") before any magnitude existed, and demanding the magnitude
#: beside it would be demanding a number the document could not have had.
#: `INCIDENTS.md` is a log of defects, not a report of findings.
RESULT_FILES = ("README.md", "EVAL_RESULTS.md", "VIDEO.md", "SUBMISSION.md")


def _present_results() -> list[str]:
    return [n for n in RESULT_FILES if (REPO / n).exists()]


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


# --- 3. the null must not be dressed up as a near-miss ----------------------------

#: Framings that imply a positive result was nearly reached. The interval spans
#: zero; there is no direction to report, and language that supplies one is
#: reporting something the measurement does not contain.
_NEAR_MISS = (
    r"trending\s+positive",
    r"directionally\s+(favourable|favorable|positive)",
    r"\bsuggestive\b",
    r"promising\s+(signal|direction|result)",
    r"just\s+(short|shy)\s+of\s+significan",
    r"approaching\s+significance",
    r"nearly\s+significant",
    r"marginally\s+significant",
)


@pytest.mark.parametrize("name", _present())
def test_no_document_dresses_the_null_up_as_a_near_miss(name):
    text = _read(name)
    offenders = []
    for pattern in _NEAR_MISS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if _is_disavowed(text, match.start(), match.end()):
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"line {line}: {match.group(0)!r}")
    assert not offenders, (
        f"{name} implies a positive result was nearly reached:\n  "
        + "\n  ".join(offenders)
        + "\nThe interval spans zero. There is no direction to report, and "
        "language that supplies one reports something the measurement does not "
        "contain."
    )


# --- 4. the null does not establish equivalence -----------------------------------

_NULL_CLAIM = re.compile(
    r"did\s+not\s+detect\s+a\s+difference|no\s+detected\s+difference", re.IGNORECASE
)
_NON_EQUIVALENCE = re.compile(
    # "there being none" is the same clause as "there being no difference" -- a
    # spoken script naturally elides the noun. Matching only the long form failed
    # VIDEO.md for saying the right thing in fewer words.
    r"not\s+the\s+same\s+as\s+there\s+being\s+(?:no\s+difference|none)"
    r"|does\s+not\s+(?:rule\s+out|establish)",
    re.IGNORECASE,
)


@pytest.mark.parametrize("name", _present_results())
def test_the_null_never_appears_without_its_non_equivalence_clause(name):
    """'We did not detect a difference' compresses to 'there is no difference',
    which is a different and much stronger claim that this run cannot support."""
    orphans = _near(_read(name), _NULL_CLAIM, _NON_EQUIVALENCE)
    assert not orphans, (
        f"{name} states the null without the clause distinguishing it from "
        f"equivalence:\n  " + "\n  ".join(orphans)
    )


@pytest.mark.parametrize("name", _present_results())
def test_the_null_carries_the_mde_it_could_not_resolve_below(name):
    """A null without its power is a null about nothing."""
    orphans = _near(_read(name), _NULL_CLAIM, re.compile(r"6\.2[34]"))
    assert not orphans, (
        f"{name} states the null without the MDE nearby:\n  " + "\n  ".join(orphans)
    )


# --- 5. the sign flip's two sentences travel together -----------------------------

_FLIP = re.compile(r"sign\s+flip|SIGN\s+FLIPPED|flips?\s+the\s+sign", re.IGNORECASE)
_FLIP_CONTEXT = re.compile(
    r"already\s+spans?\s+zero|-?0\.10\s*pp|consistent\s+with\s+the\s+headline",
    re.IGNORECASE,
)


@pytest.mark.parametrize("name", _present_results())
def test_the_sign_flip_never_appears_without_its_magnitude_context(name):
    """Both sentences are true and neither may appear alone.

    'A sign flip occurred, which the pre-registration calls falsifying' without
    the magnitude overstates it. The magnitude without the flip buries it.
    """
    orphans = _near(_read(name), _FLIP, _FLIP_CONTEXT)
    assert not orphans, (
        f"{name} mentions the sign flip without the context that it is a -0.10 pp "
        f"swing on an interval already spanning zero:\n  " + "\n  ".join(orphans)
    )


def test_the_near_miss_guard_actually_rejects_the_phrasing():
    """Guards the guard: a pattern list that matches nothing passes everything."""
    text = "The result was trending positive at +1.45 pp."
    hits = [p for p in _NEAR_MISS if re.search(p, text, re.IGNORECASE)]
    assert hits, "the near-miss patterns do not match the phrasing they forbid"


def test_a_disavowed_near_miss_is_permitted():
    """VIDEO.md and CLAUDE.md name these phrasings in order to forbid them."""
    text = 'Never say "trending positive" — the interval spans zero.'
    match = re.search(r"trending\s+positive", text, re.IGNORECASE)
    assert _is_disavowed(text, match.start(), match.end())


def test_no_pattern_in_this_module_holds_a_literal_backspace():
    """Runs the module-wide check as a test, so it cannot be skipped at import."""
    _assert_no_literal_backspaces()


def test_the_candidate_list_covers_every_markdown_document_that_ships():
    """WALK THE REPOSITORY, do not name six files.

    `CANDIDATES` is a fixed list, and a document added later — a submission
    write-up, a one-pager — would carry these claims unchecked. Same shape as an
    assertion naming one compiled pattern, or a coverage test naming its arms in
    a literal instead of walking the registry.

    Directories excluded because their contents are not claims to a reader:
    `docs/` is the design spec (local-only), `src/` holds `PARAMS.md` which is a
    parameter register, and `.github/` is CI config.
    """
    shipped = {
        path.name for path in REPO.glob("*.md")
        if path.name not in {"CLAUDE.md", "PLAN.md", "DECISION.md", "LOGS.md"}
    }
    unchecked = shipped - set(CANDIDATES)
    assert not unchecked, (
        f"{sorted(unchecked)} are top-level markdown documents not in CANDIDATES, "
        f"so none of the five sentence guards apply to them. Add them, or state "
        f"why they carry no claims."
    )


def test_the_result_files_are_a_subset_of_the_candidates():
    """A result file outside CANDIDATES would be checked by the result guards and
    not by the A/A or accuracy ones — a split nobody would notice."""
    assert set(RESULT_FILES) <= set(CANDIDATES)


# --- 6. the null's two halves must sit on the SAME CARD ---------------------------
#
# A video is read one card at a time. "The interval spans zero" alone is what a
# reader compresses into "there is no difference" -- the false STRONGER claim --
# and the opening card carried exactly that while the full sentence sat on the
# dedicated finding-1 card sixty seconds later. Both satisfy "the source contains
# the clause"; only one is seen by someone who watches thirty seconds.
#
# So this checks per CARD, not per file. It walks every scene the source defines
# rather than naming the ones that happen to make the claim today.

import video_cards  # noqa: E402

_SPANS_ZERO = re.compile(r"(?:interval\s+)?spans\s+zero", re.IGNORECASE)


def _cards_asserting_the_interval_spans_zero(cards):
    return [c for c in cards if _SPANS_ZERO.search(c.text)]


@pytest.mark.parametrize("name", [c.name for c in video_cards.cards()])
def test_a_video_card_never_says_spans_zero_without_the_non_equivalence_clause(name):
    card = next(c for c in video_cards.cards() if c.name == name)
    if not _SPANS_ZERO.search(card.text):
        pytest.skip(f"{name} does not make the claim")
    assert _NON_EQUIVALENCE.search(card.text), (
        f"video card {name!r} states that the interval spans zero without the "
        f"clause distinguishing that from equivalence. Alone it compresses to "
        f"'there is no difference', which is a stronger claim than this run "
        f"supports, and a card is read on its own.\n\n{card.text}"
    )


def test_at_least_one_video_card_actually_makes_the_spans_zero_claim():
    """A test that passes by finding nothing must first be shown able to find
    something. If no card asserts it, the guard above skips every scene and is
    green over a video that says nothing at all."""
    asserting = _cards_asserting_the_interval_spans_zero(video_cards.cards())
    assert asserting, (
        "no video card asserts that the interval spans zero, so the pairing "
        "guard is vacuous. Either the null is no longer stated on screen -- "
        "which is a much bigger problem -- or the anchor pattern has drifted."
    )


def test_the_pairing_guard_rejects_a_card_with_the_clause_stripped():
    """PLANT. Strips the non-equivalence clause out of the opening card and
    confirms the guard fires, rather than reasoning that it would.

    Runs on every check, so it cannot rot into a claim about a source that has
    since changed.
    """
    text = video_cards.source()
    stripped = text.replace(
        " — which is not`,\n"
        "        `    the same as there being no difference. It does not establish`,\n"
        "        `    that the two arms are equivalent.",
        ".",
    )
    assert stripped != text, (
        "the plant no longer matches the opening card's wording, so this guard "
        "has not been shown to fire against the text it protects"
    )

    planted = video_cards.cards(stripped)
    offenders = [
        c.name
        for c in _cards_asserting_the_interval_spans_zero(planted)
        if not _NON_EQUIVALENCE.search(c.text)
    ]
    assert "Findings" in offenders, (
        "stripping the non-equivalence clause from the opening card did NOT "
        "make the guard fire. It is testing something other than the pairing."
    )


def test_the_scenes_array_and_the_defined_scenes_agree():
    """Walk the registry, do not enumerate it. A scene defined but never placed
    in SCENES renders nothing and would satisfy every guard above for free; a
    scene in SCENES but not found by the parser is invisible to all of them."""
    defined = [c.name for c in video_cards.cards()]
    rendered = video_cards.declared_scene_order()
    assert defined == rendered, (
        f"the scenes defined in the source and the scenes SCENES renders have "
        f"diverged.\n  defined:  {defined}\n  rendered: {rendered}\n"
        f"Every card guard walks the defined list; anything only in one of these "
        f"is either unchecked or unrendered."
    )
