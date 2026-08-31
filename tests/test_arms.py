import hashlib
from collections import Counter

import pytest

from recoup.assign.arms import CONTROL, TREATMENT, assign_arm

SALT = "recoup-2026-08"


def test_assignment_is_deterministic():
    assert assign_arm("cust_001", SALT) == assign_arm("cust_001", SALT)


def test_only_two_arms_are_possible():
    for i in range(500):
        assert assign_arm(f"cust_{i}", SALT) in (CONTROL, TREATMENT)


def test_the_split_is_approximately_balanced():
    counts = Counter(assign_arm(f"cust_{i:06d}", SALT) for i in range(10000))
    assert 0.47 < counts[CONTROL] / 10000 < 0.53


def test_a_different_salt_reshuffles_the_assignment():
    a = [assign_arm(f"cust_{i}", "salt-a") for i in range(500)]
    b = [assign_arm(f"cust_{i}", "salt-b") for i in range(500)]
    assert a != b


def test_assignment_survives_replay():
    """Replay must reproduce allocation exactly, which is why this is a hash
    of the customer id and not a random draw."""
    first = [assign_arm(f"cust_{i}", SALT) for i in range(100)]
    second = [assign_arm(f"cust_{i}", SALT) for i in range(100)]
    assert first == second


# --- the input shape a real run actually produces ---------------------------------


def test_it_is_balanced_on_the_ids_the_generator_really_emits():
    """The plan's balance test uses `cust_000000`-style ids. The generator emits
    `cust_sim_<seed>_<index>`, which is a different string space.

    A hash is not guaranteed to be balanced on *any* input family just because it
    is balanced on one. This checks the family that will actually be assigned.
    """
    from recoup.simulator.generator import generate_scenarios

    scenarios = generate_scenarios(n=10000, seed=4242)
    counts = Counter(assign_arm(s.customer_id, SALT) for s in scenarios)
    share = counts[CONTROL] / len(scenarios)
    assert 0.47 < share < 0.53, f"control share {share:.4f} on real generator ids"


def test_balance_holds_across_several_generator_seeds():
    from recoup.simulator.generator import generate_scenarios

    for seed in (1, 2, 3, 99, 20260831):
        scenarios = generate_scenarios(n=4000, seed=seed)
        share = Counter(assign_arm(s.customer_id, SALT) for s in scenarios)[CONTROL] / 4000
        assert 0.45 < share < 0.55, f"seed {seed}: control share {share:.4f}"


def test_assignment_is_independent_of_the_ground_truth_label():
    """The assignment must not correlate with who would have recovered anyway.

    If it did, the arms would differ before any treatment was applied and the
    measured lift would be an artifact of allocation. This is the exact failure
    the A/A is supposed to catch and — per A-018 — the statistical A/A cannot,
    because it never touches assignment. So it is checked directly here.
    """
    from recoup.simulator.generator import generate_scenarios

    scenarios = generate_scenarios(n=20000, seed=7)
    by_arm = {CONTROL: [0, 0], TREATMENT: [0, 0]}
    for s in scenarios:
        bucket = by_arm[assign_arm(s.customer_id, SALT)]
        bucket[0] += s.would_self_recover
        bucket[1] += 1

    rate_c = by_arm[CONTROL][0] / by_arm[CONTROL][1]
    rate_t = by_arm[TREATMENT][0] / by_arm[TREATMENT][1]
    assert abs(rate_c - rate_t) < 0.02, (
        f"self-recovery rate differs by arm before any treatment: "
        f"control {rate_c:.4f} vs treatment {rate_t:.4f}"
    )


def test_assignment_is_independent_of_decline_hardness():
    from recoup.simulator.generator import generate_scenarios

    scenarios = generate_scenarios(n=20000, seed=8)
    hard = {CONTROL: [0, 0], TREATMENT: [0, 0]}
    for s in scenarios:
        bucket = hard[assign_arm(s.customer_id, SALT)]
        bucket[0] += s.is_hard_decline
        bucket[1] += 1
    share_c = hard[CONTROL][0] / hard[CONTROL][1]
    share_t = hard[TREATMENT][0] / hard[TREATMENT][1]
    assert abs(share_c - share_t) < 0.02, (share_c, share_t)


# --- inputs -----------------------------------------------------------------------


def test_an_empty_salt_is_refused():
    """An unset EXPERIMENT_SALT must not silently produce a valid-looking split.

    `Settings.experiment_salt` has a default, but a caller passing "" would get a
    deterministic assignment on the customer id alone — reproducible, and not the
    pre-registered allocation.
    """
    with pytest.raises(ValueError, match="salt"):
        assign_arm("cust_1", "")


def test_an_empty_customer_id_is_refused():
    with pytest.raises(ValueError, match="customer_id"):
        assign_arm("", SALT)


def test_the_assignment_rule_is_the_one_experiment_md_pre_registered():
    """EXPERIMENT.md says: sha256(customer_id + salt), low bit.

    Pinned, because the pre-registration describes the mechanism and a different
    mechanism producing a similar split would still be a different experiment.
    """
    for cid in ("cust_1", "cust_sim_1_000042", "x"):
        digest = hashlib.sha256(f"{cid}{SALT}".encode()).digest()
        expected = TREATMENT if digest[0] & 1 else CONTROL
        assert assign_arm(cid, SALT) == expected
