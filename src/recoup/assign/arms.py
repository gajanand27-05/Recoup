"""Deterministic arm assignment.

A hash rather than a random draw, so replay reproduces allocation exactly.
Balanced 50/50: simulated events are free, statistical power is the scarce
resource, and balanced allocation maximises power (D-010).

The rule is pre-registered in `EXPERIMENT.md` as `sha256(customer_id + salt)`,
low bit. That is a description of a mechanism, not just of a split — a different
mechanism producing a similar balance would still be a different experiment, so
the rule is pinned by test.
"""

import hashlib

CONTROL = "control"
TREATMENT = "treatment"


def assign_arm(customer_id: str, salt: str) -> str:
    """Assign one customer to an arm, deterministically.

    Both arguments are required to be non-empty. An empty salt would still give a
    deterministic, balanced-looking split — on the customer id alone — which is
    reproducible and is *not* the pre-registered allocation. Failing loudly beats
    a plausible answer to the wrong question.
    """
    if not customer_id:
        raise ValueError("customer_id must be non-empty")
    if not salt:
        raise ValueError(
            "salt must be non-empty; an unset EXPERIMENT_SALT would produce a "
            "deterministic split that is not the pre-registered allocation"
        )
    digest = hashlib.sha256(f"{customer_id}{salt}".encode()).digest()
    return TREATMENT if digest[0] & 1 else CONTROL
