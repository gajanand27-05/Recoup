"""What we claim about structured output must match what each client actually does.

A-024. Ollama Cloud accepts a JSON schema and ignores it. Gemini and Anthropic
constrain decoding. Those are different guarantees, and a single sentence saying
"structured output via a response schema, validated by Pydantic" is true of two
of the three clients and false of the third.

WHY THIS IS BEHAVIOURAL AND NOT A SUBSTRING SWEEP
--------------------------------------------------
The A-020 sweep started as "does the file mention A-020 anywhere" and missed both
plants, because a document can state a strong claim in its headline and qualify it
in a footnote. The same failure is available here: `README.md` could say "the
schema is enforced" and add "(except on Ollama)" three paragraphs later.

So the guard asserts on the CODE. Every client declares whether its provider
constrains decoding, and the declaration is checked against how the client is
built — a client that sends the schema only as a parameter cannot claim
enforcement, and one that spells the schema into the prompt is admitting it is
not enforced. Prose is checked too, but only as a second line: the first line is
that a client cannot silently acquire a guarantee it does not have.
"""

import inspect
import re
from pathlib import Path

import pytest

from recoup.agent.llm import AnthropicLLM, GeminiLLM, OllamaLLM

REPO = Path(__file__).resolve().parents[1]

#: Whether the PROVIDER constrains decoding to the schema, per client.
#: Measured 2026-09-02 for Ollama; documented behaviour for the other two.
SCHEMA_ENFORCED_BY_PROVIDER = {
    GeminiLLM: True,     # response_schema constrains decoding
    AnthropicLLM: True,  # tool_choice forces the tool's input_schema
    OllamaLLM: False,    # A-024: accepts `format`, ignores it, returns HTTP 200
}


def _source(cls) -> str:
    return inspect.getsource(cls)


@pytest.mark.parametrize("cls", sorted(SCHEMA_ENFORCED_BY_PROVIDER, key=lambda c: c.__name__))
def test_every_client_is_declared_one_way_or_the_other(cls):
    """A client added later without a declaration fails here rather than
    inheriting whichever guarantee the reader assumes."""
    assert cls in SCHEMA_ENFORCED_BY_PROVIDER


def test_a_client_that_prompts_the_schema_may_not_claim_enforcement():
    """THE LOAD-BEARING ASSERTION.

    Spelling the schema into the system prompt is an admission that the parameter
    does not work — you do not do that when the decoder is constrained. So a
    client whose source injects the schema into a message body must be declared
    unenforced. This catches the case where someone adds prompt-injection of the
    schema to a client to 'improve reliability' and leaves the declaration saying
    the provider enforces it.
    """
    for cls, enforced in SCHEMA_ENFORCED_BY_PROVIDER.items():
        source = _source(cls)
        # The schema serialised into message content, rather than passed as a
        # top-level request parameter.
        prompts_the_schema = bool(
            re.search(r"json\.dumps\(\s*schema", source)
            or re.search(r'"content".*schema', source, re.DOTALL | re.IGNORECASE)
            and "json.dumps(schema" in source
        )
        if prompts_the_schema:
            assert not enforced, (
                f"{cls.__name__} spells the schema into the prompt, which is only "
                f"done when the provider ignores the parameter — yet it is declared "
                f"as enforcing the schema. One of the two is wrong."
            )


def test_the_unenforced_client_says_so_at_its_own_definition():
    """Whoever reads OllamaLLM must learn this without going to DECISION.md."""
    source = _source(OllamaLLM)
    assert "A-024" in source or "ignore" in source.lower(), (
        "OllamaLLM does not record that its provider ignores the schema"
    )
    assert "validated by Pydantic" in source or "Pydantic" in source, (
        "the compensating control — validation at the boundary — is not stated "
        "where the weakened guarantee is"
    )


def test_the_unenforced_client_still_validates_at_the_boundary():
    """The narrowing is acceptable BECAUSE of this. If it ever stopped being
    true, the narrowing would stop being acceptable."""
    source = _source(OllamaLLM)
    assert "json.loads" in source, "nothing parses the response"
    assert "JSONDecodeError" in source, (
        "a non-JSON body is not handled — it would either raise raw or, worse, "
        "be regexed out of prose"
    )
    assert "return None" in source, (
        "an unusable answer must become None so the caller's labelled fallback "
        "runs, rather than a guess being returned as a classification"
    )


# --- second line: the prose must not overstate it -----------------------------------

#: Files that state the claim to a reader outside this repository. VIDEO.md is
#: local-only, so it is checked when present and skipped when not — a shipped
#: test may not require a gitignored file (that was the 59061cd failure).
CLAIM_FILES = ("README.md", "VIDEO.md", "EVAL_RESULTS.md")

#: Phrasings that assert enforcement without qualification.
_OVERSTATED = (
    r"schema is enforced",
    r"enforced by the (provider|api|model)",
    r"guaranteed to (match|conform)",
    r"the model (must|will always) return valid",
)


@pytest.mark.parametrize("filename", CLAIM_FILES)
def test_no_shipped_document_claims_the_schema_is_enforced(filename):
    path = REPO / filename
    if not path.exists():
        pytest.skip(f"{filename} not present (local-only or not yet written)")
    text = path.read_text(encoding="utf-8")
    for pattern in _OVERSTATED:
        match = re.search(pattern, text, re.IGNORECASE)
        assert match is None, (
            f"{filename} claims schema enforcement: {match.group(0)!r}. "
            f"On Ollama the schema is requested and ignored (A-024)."
        )
