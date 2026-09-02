"""The model id is a claim about the outside world, so it needs evidence.

`gpt-oss:120b` is a tag on someone else's server. It can be repointed without
notice, and a model-id string comparison cannot see that happen. These tests pin
the states, the pooling key, and the refusal.
"""

import pytest

from recoup.agent.identity import (
    ASSERTED,
    CONFIRMED,
    ModelIdentity,
    ModelIdentityError,
    capture_ollama_identity,
    require_one_identity,
)

REAL = ModelIdentity(
    model_id="gpt-oss:120b",
    confirmation=CONFIRMED,
    digest="d98fe6ba01e6",
    size_bytes=65290180781,
    modified_at="2025-08-05T00:00:00Z",
    captured_at="2026-09-02T14:41:48Z",
)


def test_a_confirmed_identity_is_checkable_by_a_third_party():
    assert REAL.is_checkable
    described = REAL.describe()
    assert "d98fe6ba01e6" in described
    assert CONFIRMED in described


def test_an_asserted_identity_says_it_proves_nothing():
    """The `INFERRED` state of manifest(), wearing different clothes. It must not
    read like a confirmed one."""
    weak = ModelIdentity(model_id="gpt-oss:120b", confirmation=ASSERTED)
    assert not weak.is_checkable
    described = weak.describe()
    assert "NOT CONFIRMED BY RESPONSE" in described
    assert "nothing here proves which weights ran" in described


def test_the_pooling_key_includes_the_digest():
    """THE POINT. A repointed tag keeps its id and changes its bytes."""
    repointed = ModelIdentity(
        model_id="gpt-oss:120b", confirmation=CONFIRMED, digest="ffffffffffff"
    )
    assert REAL.model_id == repointed.model_id
    assert REAL.pooling_key != repointed.pooling_key


def test_one_identity_passes():
    assert require_one_identity([REAL, REAL], run_id="run-1") is REAL


def test_a_repointed_tag_is_refused_even_though_the_id_matches():
    """The plant this module exists for: same model id, different digest."""
    repointed = ModelIdentity(
        model_id="gpt-oss:120b", confirmation=CONFIRMED, digest="ffffffffffff"
    )
    with pytest.raises(ModelIdentityError, match="repointed"):
        require_one_identity([REAL, repointed], run_id="run-repointed")


def test_two_different_models_are_refused():
    other = ModelIdentity(
        model_id="gpt-oss:20b", confirmation=CONFIRMED, digest="05afbac4bad6"
    )
    with pytest.raises(ModelIdentityError, match="two instruments"):
        require_one_identity([REAL, other], run_id="run-mixed")


def test_no_identity_at_all_is_refused():
    with pytest.raises(ModelIdentityError, match="no model identity"):
        require_one_identity([], run_id="run-empty")


# --- capture, with the registry unavailable --------------------------------------


def test_an_unreachable_registry_degrades_to_asserted_rather_than_failing(monkeypatch):
    """A run that cannot confirm its model SAYS SO. It does not stop, and it does
    not quietly claim confirmation."""
    import httpx

    def boom(*a, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", boom)
    identity = capture_ollama_identity(
        "gpt-oss:120b", "k", "https://ollama.com", now_iso="2026-09-02T00:00:00Z"
    )
    assert identity.confirmation == ASSERTED
    assert not identity.is_checkable
    assert "unreachable" in identity.note


def test_a_tag_missing_from_the_registry_is_asserted_not_confirmed(monkeypatch):
    import httpx

    class _R:
        @staticmethod
        def json():
            return {"models": [{"name": "something-else", "digest": "abc"}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _R())
    identity = capture_ollama_identity(
        "gpt-oss:120b", "k", "https://ollama.com", now_iso="2026-09-02T00:00:00Z"
    )
    assert identity.confirmation == ASSERTED
    assert "not listed" in identity.note


def test_a_registry_entry_without_a_digest_is_asserted(monkeypatch):
    """A digest field that is present but empty must not read as confirmation."""
    import httpx

    class _R:
        @staticmethod
        def json():
            return {"models": [{"name": "gpt-oss:120b", "digest": "", "size": 1}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _R())
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _R())
    identity = capture_ollama_identity(
        "gpt-oss:120b", "k", "https://ollama.com", now_iso="2026-09-02T00:00:00Z"
    )
    assert identity.confirmation == ASSERTED
    assert "no digest" in identity.note
