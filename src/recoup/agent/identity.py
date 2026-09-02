"""Which model actually ran — as evidence, not as a string someone typed.

THE PROBLEM
-----------
`gpt-oss:120b` is a tag on someone else's server. Tags are mutable: the same name
can point at different weights next week, and nothing in a run would notice. A
result labelled `model_source="gpt-oss:120b"` is a claim about the outside world,
and this build's rule for those is that the ARTIFACT answers "how do you know",
not a person (INC-006, `manifest()`).

WHAT THE API ACTUALLY OFFERS — measured 2026-09-02
---------------------------------------------------
* `/api/chat` response: `model` (an **echo of the request**, not proof),
  `created_at`, timings. **No digest.** So a per-response confirmation does not
  exist on this provider.
* `/api/tags`: **`digest`** (`d98fe6ba01e6` for `gpt-oss:120b`), `size`,
  `modified_at`.
* `/api/show`: `parameter_size`, `quantization_level`, architecture.

So the digest is obtainable, but from a **separate call**, not from the response
that produced a result. That gap is the whole reason this module has states
rather than a boolean.

THE STATES
----------
`CONFIRMED_BY_REGISTRY`
    A digest and size were fetched from the provider at run start and recorded.
    The run is pinned to those bytes as far as the provider's own registry goes.

`ASSERTED_BY_REQUEST`
    The model id was sent and results came back, and nothing else identifies
    what ran. Legitimate, and it must SAY so — this is the `INFERRED` state of
    `manifest()`, wearing different clothes.

The distinction is not cosmetic. A run reporting `CONFIRMED_BY_REGISTRY` with a
digest can be checked by a third party against the provider today; a run in
`ASSERTED_BY_REQUEST` cannot be checked at all, and a reader deserves to know
which one they are holding.
"""

from dataclasses import asdict, dataclass

CONFIRMED = "CONFIRMED_BY_REGISTRY"
ASSERTED = "ASSERTED_BY_REQUEST"


class ModelIdentityError(RuntimeError):
    """Results were combined across two model identities."""


@dataclass(frozen=True)
class ModelIdentity:
    """Everything known about what produced a run's results.

    `pooling_key` is what `require_one_identity()` compares. It includes the
    digest, so a tag repointed mid-run is a different identity even though the
    model id string is unchanged — which is the failure mode a model id alone
    cannot see.
    """

    model_id: str
    confirmation: str = ASSERTED
    digest: str = ""
    size_bytes: int = 0
    modified_at: str = ""
    parameter_count: int = 0
    quantization: str = ""
    captured_at: str = ""
    #: How the digest was obtained, or why it was not. Recorded so the absence
    #: of a digest is a stated fact rather than an empty field.
    note: str = ""

    @property
    def pooling_key(self) -> tuple[str, str]:
        return (self.model_id, self.digest)

    @property
    def is_checkable(self) -> bool:
        """Can a third party verify this against the provider?"""
        return self.confirmation == CONFIRMED and bool(self.digest)

    def describe(self) -> str:
        if self.is_checkable:
            return (
                f"{self.model_id} (digest {self.digest}, {self.size_bytes} bytes, "
                f"published {self.modified_at}) — CONFIRMED_BY_REGISTRY, captured "
                f"{self.captured_at}"
            )
        return (
            f"{self.model_id} — ASSERTED_BY_REQUEST, NOT CONFIRMED BY RESPONSE. "
            f"The provider's chat response echoes the requested id and carries no "
            f"digest, so nothing here proves which weights ran"
            + (f". {self.note}" if self.note else "")
        )

    def as_dict(self) -> dict:
        return asdict(self)


def require_one_identity(identities, *, run_id: str) -> ModelIdentity:
    """Refuse to combine results produced under two model identities.

    Stricter than `require_real_model()`, which compares model id strings. Two
    runs can share an id and differ in digest — that is exactly what a repointed
    tag looks like, and it is invisible to a string comparison.
    """
    unique = {i.pooling_key: i for i in identities if i is not None}
    if not unique:
        raise ModelIdentityError(
            f"run {run_id!r} recorded no model identity; nothing to report"
        )
    if len(unique) > 1:
        described = "\n  ".join(sorted(i.describe() for i in unique.values()))
        raise ModelIdentityError(
            f"run {run_id!r} combines {len(unique)} model identities:\n  {described}\n"
            f"Two identities are two instruments. A shared model id with different "
            f"digests is a tag that was repointed mid-run, which a model-id "
            f"comparison alone cannot see."
        )
    return next(iter(unique.values()))


# --- capture --------------------------------------------------------------------


def capture_ollama_identity(
    model_id: str, api_key: str, host: str, now_iso: str, timeout: float = 30.0
) -> ModelIdentity:
    """Fetch what the provider's registry says about this tag, right now.

    Failure to reach the registry is NOT an error: it yields `ASSERTED_BY_REQUEST`
    with the reason recorded. A run that cannot confirm its model is a run that
    says so, not a run that stops.
    """
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"}
    base = dict(model_id=model_id, captured_at=now_iso)

    try:
        tags = httpx.get(f"{host}/api/tags", headers=headers, timeout=timeout).json()
        entry = next(
            (m for m in tags.get("models", []) if m.get("name") == model_id), None
        )
    except Exception as exc:  # network, auth, shape — all the same outcome here
        return ModelIdentity(
            **base, confirmation=ASSERTED, note=f"registry unreachable: {type(exc).__name__}"
        )

    if entry is None:
        return ModelIdentity(
            **base,
            confirmation=ASSERTED,
            note=f"{model_id!r} is not listed in the provider's registry",
        )

    details: dict = {}
    try:
        shown = httpx.post(
            f"{host}/api/show", headers=headers, json={"model": model_id}, timeout=timeout
        ).json()
        details = shown.get("details") or {}
        info = shown.get("model_info") or {}
    except Exception:
        info = {}

    return ModelIdentity(
        **base,
        confirmation=CONFIRMED if entry.get("digest") else ASSERTED,
        digest=entry.get("digest", ""),
        size_bytes=int(entry.get("size") or 0),
        modified_at=entry.get("modified_at", ""),
        parameter_count=int(info.get("general.parameter_count") or 0),
        quantization=details.get("quantization_level", ""),
        note="" if entry.get("digest") else "registry listed the tag but gave no digest",
    )
