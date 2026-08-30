"""`real` and `sim` are never pooled in a reported number (D-009).

The obvious way to honour that is to filter rows by transport and report each
side. That is not sufficient, and the reason is a consequence of how the label is
produced rather than anything about the filter.

`transport` defaults to `sim` and is declared `real` in exactly one place. So the
overwhelmingly likely state of any run -- especially one driven by fixtures
because the dashboard gate was never opened -- is that EVERY row says `sim`. A
report that filters correctly then finds one non-empty group and renders a single
number. It looks identical to a report where the distinction was made and one arm
happened to be empty.

Nothing was mislabelled. The split was trivially empty, and the output does not
say so. That is the failure this module exists to make impossible: the report
path must **assert it saw the split**, not merely filter on it.

A run with zero `real` rows is a legitimate, expected state. It has to be stated,
not inferred from the absence of a second column.
"""

from collections import Counter
from dataclasses import dataclass

TRANSPORTS = ("real", "sim")


@dataclass(frozen=True)
class TransportSplit:
    real: int
    sim: int

    @property
    def total(self) -> int:
        return self.real + self.sim

    @property
    def is_pooled_reporting_safe(self) -> bool:
        """True only when exactly one transport is present.

        With both present, any pooled figure mixes an outcome oracle with a real
        one and D-009 forbids it. With neither, there is nothing to report.
        """
        return self.total > 0 and (self.real == 0) != (self.sim == 0)

    @property
    def sole_transport(self) -> str | None:
        if not self.is_pooled_reporting_safe:
            return None
        return "real" if self.real else "sim"

    def caveat(self) -> str:
        """The sentence a report MUST print alongside any figure derived from it."""
        if self.total == 0:
            return "No rows. Nothing was measured."
        if self.real and self.sim:
            return (
                f"{self.real} real and {self.sim} simulated rows are present. These are "
                "never pooled: report them separately or the figure mixes a real "
                "outcome with a modelled one."
            )
        if self.sim:
            return (
                f"All {self.sim} rows are transport=sim. No event in this run came "
                "from Razorpay; every outcome is produced by the simulator. The "
                "real/sim split was not exercised."
            )
        return (
            f"All {self.real} rows are transport=real. Every outcome came from "
            "Razorpay; the simulator was not used."
        )


def summarise(rows: list[dict]) -> TransportSplit:
    counts = Counter(r.get("transport") for r in rows)
    unknown = set(counts) - set(TRANSPORTS)
    if unknown:
        raise ValueError(
            f"ledger rows carry unknown transport values {sorted(map(str, unknown))}; "
            "every row must be `real` or `sim` before anything is reported"
        )
    return TransportSplit(real=counts.get("real", 0), sim=counts.get("sim", 0))


def require_declared_split(rows: list[dict]) -> TransportSplit:
    """Gate a pooled figure. Raises unless pooling is actually legitimate.

    Call this before rendering any number computed over `rows` as a whole. It is
    deliberately awkward to bypass: the caller must either satisfy it or handle
    the exception, and either way the split has been thought about once.
    """
    split = summarise(rows)
    if not split.is_pooled_reporting_safe:
        raise ValueError(
            "refusing to pool: " + split.caveat() + " Report per transport, or "
            "state the split explicitly."
        )
    return split
