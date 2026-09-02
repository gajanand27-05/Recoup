"""No reported figure may derive from output nothing real produced.

WHAT THIS IS FOR
----------------
By the time a number reaches `README.md`, a report or a slide, it is a float. It
does not carry where it came from. A recovery rate computed over actions a stub
proposed, or over an accuracy eval that was deselected and never ran, is the same
shape as one computed over a live model — and it is the more likely of the two,
because the conditions that produce it are the ordinary ones: no key configured,
`-m "not llm"` in CI, a placeholder in `.env`.

So the reporting path refuses, the way `manifest()` refuses a payload with no
delivery provenance and `require_declared_split()` refuses a pooled transport.
`figure()` will not construct without a provenance chain, and a chain touching a
stub, a deterministic fallback, an unset source or a test that did not run raises
`ProvenanceError` at construction rather than at review.

WHY A TYPE AND NOT A CONVENTION
--------------------------------
"Remember to check where the number came from" is the convention that failed in
INC-006, when a fabricated payload was reported as CAPTURED. A `Figure` cannot be
rendered without stating its sources, and stating a bad one raises. Somebody has
to lie on purpose rather than merely forget.
"""

from dataclasses import dataclass, field

from recoup.agent.llm import NON_MODEL_SOURCES

#: Sources that may never appear behind a reported number.
#:
#: `not_run` is the one that matters most while no key is configured: a
#: deselected accuracy test produces no output at all, and the temptation is to
#: carry the last number anyone saw. `unset` catches the figure whose provenance
#: nobody recorded, which is not the same as a figure with clean provenance and
#: must not be treated as one.
FORBIDDEN_SOURCES = frozenset(NON_MODEL_SOURCES) | {"not_run", "unset", ""}

#: Sources that are fine. Deterministic machinery is not a defect -- the ledger,
#: the frozen simulator and the policy engine are all deterministic and all
#: reportable. What is forbidden is a stand-in for something that did not happen.
SIMULATED = "simulated"
MEASURED = "measured"
DERIVED = "derived"


class ProvenanceError(RuntimeError):
    """A figure was constructed over output that may not be reported."""


@dataclass(frozen=True)
class Figure:
    """A number that knows where it came from.

    `sources` is every provenance label that fed it, including transitively. A
    lift computed from two arms carries both arms' labels: if either arm was
    produced by a stub, the lift is stub-derived even though the arithmetic that
    combined them was not.
    """

    name: str
    value: float
    unit: str
    sources: frozenset[str] = field(default_factory=frozenset)
    caveat: str = ""

    def __post_init__(self) -> None:
        if not self.sources:
            raise ProvenanceError(
                f"figure {self.name!r} declares no sources. A number with no "
                f"stated provenance is not a number that may be reported: by the "
                f"time it reaches a report it is a float and nothing about it "
                f"says whether anything real produced it."
            )
        bad = {s for s in self.sources if s in FORBIDDEN_SOURCES}
        if bad:
            raise ProvenanceError(
                f"figure {self.name!r} derives from {sorted(bad)}. Stub and "
                f"deterministic stand-ins exist to exercise plumbing, and "
                f"'not_run' is the state of every deselected eval — none of them "
                f"may stand behind a reported number. Run the thing, or report "
                f"it as not run."
            )

    def combined_with(self, *others: "Figure", name: str, value: float, unit: str,
                      caveat: str = "") -> "Figure":
        """Derive a new figure, carrying every input's provenance forward.

        The point of the whole module. Arithmetic launders provenance: subtract
        two rates and the result is a float with no history. Here the union of
        sources travels with it, so a lift over a stubbed arm is refused at the
        moment it is derived.
        """
        merged = frozenset(self.sources).union(*(o.sources for o in others))
        return Figure(name=name, value=value, unit=unit, sources=merged, caveat=caveat)

    def render(self) -> str:
        body = f"{self.name}: {self.value:.4g}{self.unit}"
        return f"{body}  [{self.caveat}]" if self.caveat else body


def require_reportable(*figures: Figure, run_id: str) -> None:
    """Last gate before rendering. Constructing a Figure already checks this;
    this exists so a report can assert over a whole set in one place and name the
    run in the error."""
    if not figures:
        raise ProvenanceError(f"run {run_id!r} produced no figures to report")
    for fig in figures:
        bad = {s for s in fig.sources if s in FORBIDDEN_SOURCES}
        if bad:
            raise ProvenanceError(
                f"run {run_id!r}: figure {fig.name!r} derives from {sorted(bad)}"
            )
