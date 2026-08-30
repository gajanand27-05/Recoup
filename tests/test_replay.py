import itertools
import random

import pytest

from recoup.ledger.replay import (
    ReplayConflict,
    SubscriptionState,
    count_unattributable,
    replay,
)


def _rows():
    return [
        {"seq": 1, "event_type": "webhook.received", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": None, "transport": "sim",
         "payload": {"event": "subscription.halted", "amount_paise": 49900}},
        {"seq": 2, "event_type": "arm.assigned", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": "treatment", "transport": "sim", "payload": {}},
        {"seq": 3, "event_type": "action.executed", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": "treatment", "transport": "sim",
         "payload": {"channel": "whatsapp", "cost_paise": 12, "attempt_no": 1}},
        {"seq": 4, "event_type": "action.executed", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": "treatment", "transport": "sim",
         "payload": {"channel": "sms", "cost_paise": 15, "attempt_no": 2}},
        {"seq": 5, "event_type": "outcome.recovered", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": "treatment", "transport": "sim",
         "payload": {"amount_paise": 49900}},
    ]


def _row(seq, event_type, **kw):
    base = {"seq": seq, "event_type": event_type, "subscription_id": "sub_1",
            "customer_id": "cust_1", "arm": "treatment", "transport": "sim",
            "payload": {}}
    base.update(kw)
    return base


def _all_orders(rows, n=25):
    yield rows
    for seed in range(n):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        yield shuffled


# --- the base contract --------------------------------------------------------


def test_replay_builds_state_from_rows():
    state = replay(_rows())
    s = state["sub_1"]
    assert s.arm == "treatment"
    assert s.attempts == 2
    assert s.spend_paise == 27
    assert s.recovered_paise == 49900
    assert s.status == "recovered"


def test_replay_is_order_independent():
    """Razorpay does not guarantee webhook ordering, so neither can we."""
    canonical = replay(_rows())
    for shuffled in _all_orders(_rows()):
        assert replay(shuffled) == canonical


def test_replay_is_order_independent_over_every_permutation():
    """Not a sample. 5! = 120 orders, all of them.

    Random shuffles test that shuffling is survivable; they do not establish the
    property. This does, for a row set small enough to enumerate.
    """
    canonical = replay(_rows())["sub_1"]
    for perm in itertools.permutations(_rows()):
        assert replay(list(perm))["sub_1"] == canonical


def test_order_independence_survives_duplicated_rows():
    # At-least-once delivery means the real input has repeats in arbitrary
    # positions, not just a clean set in a scrambled order.
    noisy = _rows() + [_rows()[2], _rows()[4], _rows()[1]]
    canonical = replay(noisy)["sub_1"]
    for perm in itertools.islice(itertools.permutations(noisy), 500):
        assert replay(list(perm))["sub_1"] == canonical


def test_state_equality_ignores_dict_insertion_order():
    """`spend_by_attempt` is a dict, so its insertion order follows arrival order.

    Dict equality does not care, which is why the tests above hold. Anything that
    SERIALISES a state must sort keys, or two identical runs will produce
    different bytes. Pinned here because the mistake looks like a real
    order-dependence bug and is not one -- it cost a debugging round already.
    """
    a = replay(_rows())["sub_1"]
    b = replay(list(reversed(_rows())))["sub_1"]
    assert a == b
    assert list(a.spend_by_attempt) != list(b.spend_by_attempt) or len(a.spend_by_attempt) < 2


def test_replay_of_a_prefix_is_the_state_at_that_point():
    state = replay(_rows()[:4])
    s = state["sub_1"]
    assert s.attempts == 2
    assert s.recovered_paise == 0
    assert s.status == "in_progress"


def test_promise_to_pay_is_recorded():
    rows = _rows()[:3] + [_row(4, "ptp_hold", payload={"promised_date": "2026-09-03"})]
    assert replay(rows)["sub_1"].ptp_date == "2026-09-03"


def test_the_latest_promise_wins_regardless_of_arrival_order():
    rows = _rows()[:3] + [
        _row(4, "ptp_hold", payload={"promised_date": "2026-09-03"}),
        _row(5, "ptp_hold", payload={"promised_date": "2026-09-07"}),
    ]
    for shuffled in _all_orders(rows):
        assert replay(shuffled)["sub_1"].ptp_date == "2026-09-07"


def test_duplicate_rows_do_not_double_count():
    """Idempotent transitions: applying the same action row twice is once."""
    rows = _rows()
    doubled = rows + [rows[2]]
    assert replay(doubled)["sub_1"].attempts == 2
    assert replay(doubled)["sub_1"].spend_paise == 27


def test_a_duplicated_recovery_is_not_counted_twice():
    rows = _rows() + [_rows()[4]]
    assert replay(rows)["sub_1"].recovered_paise == 49900


# --- order independence where it actually breaks ------------------------------
# Shuffling a fixture whose rows never disagree proves nothing: every scalar
# assignment is last-write-wins, and with no conflicting values there is no last
# write to observe. The lines that can break order independence are the ones that
# ASSIGN rather than accumulate -- arm, customer_id, amount_paise, and the
# per-attempt cost. Each is tested here with rows that genuinely disagree.
#
# Conflicts raise rather than resolve. Picking a winner by arrival position is
# how a subscription silently ends up in whichever arm happened to land last.


def test_two_arms_for_one_subscription_is_refused_not_resolved():
    rows = [
        _row(1, "arm.assigned", arm="treatment"),
        _row(2, "arm.assigned", arm="control"),
    ]
    for shuffled in _all_orders(rows, n=5):
        with pytest.raises(ReplayConflict, match="arm"):
            replay(shuffled)


def test_a_conflicting_customer_id_is_refused():
    rows = [
        _row(1, "webhook.received", customer_id="cust_1"),
        _row(2, "webhook.received", customer_id="cust_2"),
    ]
    for shuffled in _all_orders(rows, n=5):
        with pytest.raises(ReplayConflict, match="customer_id"):
            replay(shuffled)


def test_a_conflicting_amount_is_refused():
    rows = [
        _row(1, "webhook.received", payload={"amount_paise": 49900}),
        _row(2, "webhook.received", payload={"amount_paise": 99900}),
    ]
    for shuffled in _all_orders(rows, n=5):
        with pytest.raises(ReplayConflict, match="amount_paise"):
            replay(shuffled)


def test_the_same_attempt_with_two_different_costs_is_refused():
    rows = [
        _row(1, "action.executed", payload={"attempt_no": 1, "cost_paise": 12}),
        _row(2, "action.executed", payload={"attempt_no": 1, "cost_paise": 15}),
    ]
    for shuffled in _all_orders(rows, n=5):
        with pytest.raises(ReplayConflict, match="cost_paise"):
            replay(shuffled)


def test_identical_repeats_of_a_scalar_are_fine():
    # Only DISAGREEMENT is a conflict. At-least-once delivery means the same row
    # arriving five times must be ordinary.
    rows = [_row(i, "arm.assigned", arm="treatment") for i in range(1, 6)]
    assert replay(rows)["sub_1"].arm == "treatment"


def test_a_none_arm_never_overwrites_a_real_one():
    rows = [
        _row(1, "webhook.received", arm=None),
        _row(2, "arm.assigned", arm="treatment"),
        _row(3, "webhook.received", arm=None),
    ]
    for shuffled in _all_orders(rows, n=5):
        assert replay(shuffled)["sub_1"].arm == "treatment"


def test_conflicts_name_the_subscription_and_both_values():
    rows = [_row(1, "arm.assigned", arm="treatment"), _row(2, "arm.assigned", arm="control")]
    with pytest.raises(ReplayConflict) as exc:
        replay(rows)
    msg = str(exc.value)
    assert "sub_1" in msg and "treatment" in msg and "control" in msg


# --- opt-out and outcome are different questions ------------------------------


def test_opt_out_is_recorded_and_terminal_for_outreach():
    rows = _rows()[:3] + [_row(4, "opt_out")]
    s = replay(rows)["sub_1"]
    assert s.opted_out is True
    assert s.status == "opted_out"


def test_a_customer_who_paid_then_opted_out_still_counts_as_recovered():
    """Opting out of future messaging does not un-pay an invoice.

    `opted_out` is an operational flag meaning "send nothing more". `status` is
    the outcome. Conflating them would drop a genuine recovery from the numerator
    because the customer later asked to be left alone.
    """
    rows = _rows() + [_row(6, "opt_out")]
    for shuffled in _all_orders(rows):
        s = replay(shuffled)["sub_1"]
        assert s.opted_out is True
        assert s.recovered_paise == 49900
        assert s.status == "recovered"


# --- rows that belong to nobody -----------------------------------------------


def test_rows_without_a_subscription_id_are_counted_not_silently_dropped():
    # An unparseable webhook, or one whose entity shape we did not recognise,
    # has no subscription_id. Dropping it silently shortens the denominator the
    # same way a given-up event does.
    rows = _rows() + [
        {"seq": 6, "event_type": "webhook.received", "subscription_id": None,
         "customer_id": None, "arm": None, "transport": "sim",
         "payload": {"unparseable": True}},
    ]
    assert len(replay(rows)) == 1
    assert count_unattributable(rows) == 1


def test_a_clean_run_has_nothing_unattributable():
    assert count_unattributable(_rows()) == 0


# --- equality is total --------------------------------------------------------


def test_states_differing_only_in_amount_are_not_equal():
    # The order-independence test compares states, so anything excluded from
    # equality is a field that test cannot see.
    a = SubscriptionState(subscription_id="s", amount_paise=100)
    b = SubscriptionState(subscription_id="s", amount_paise=200)
    assert a != b
