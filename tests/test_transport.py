from datetime import UTC, datetime

import httpx
import pytest

from recoup.execute.real import RealTransport, reference_id
from recoup.execute.sim import SimTransport
from recoup.execute.transport import ActionResult
from recoup.models import Action


def _action(**kw):
    base = dict(
        action_type="send_message", channel="whatsapp",
        body="Payment failed. Pay here: {link}",
        send_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        attempt_no=1, cost_paise=12,
    )
    base.update(kw)
    return Action(**base)


def _ctx(**kw):
    base = {
        "day_offset": 3, "is_hard_decline": False, "amount_paise": 49900,
        "subscription_id": "sub_1",
    }
    base.update(kw)
    return base


# --- SimTransport ------------------------------------------------------------------


def test_sim_transport_is_named_sim():
    assert SimTransport(seed=1).name == "sim"


def test_sim_transport_is_deterministic_given_a_seed():
    a = [SimTransport(seed=5).execute(_action(), _ctx()) for _ in range(1)]
    b = [SimTransport(seed=5).execute(_action(), _ctx()) for _ in range(1)]
    assert a == b


def test_sim_returns_a_synthetic_provider_ref():
    result = SimTransport(seed=1).execute(_action(), _ctx())
    assert result.provider_ref.startswith("plink_sim_")


def test_sim_charges_the_action_cost():
    assert SimTransport(seed=1).execute(_action(cost_paise=15), _ctx()).cost_paise == 15


def test_recovery_rate_tracks_the_frozen_curve():
    """Aggregate behaviour must match the sourced curve, not just be random."""
    from recoup.simulator.curve import recovery_probability

    expected = recovery_probability(3, "whatsapp", 1, False)
    n = 20000
    recovered = sum(
        SimTransport(seed=i).execute(_action(), _ctx()).recovered for i in range(n)
    )
    assert abs(recovered / n - expected) < 0.02


def test_later_day_offsets_recover_less():
    n = 8000
    early = sum(SimTransport(seed=i).execute(_action(), _ctx(day_offset=0)).recovered
                for i in range(n))
    late = sum(SimTransport(seed=i).execute(_action(), _ctx(day_offset=20)).recovered
               for i in range(n))
    assert late < early


def test_hard_declines_recover_less():
    n = 8000
    soft = sum(SimTransport(seed=i).execute(_action(), _ctx(is_hard_decline=False)).recovered
               for i in range(n))
    hard = sum(SimTransport(seed=i).execute(_action(), _ctx(is_hard_decline=True)).recovered
               for i in range(n))
    assert hard < soft


def test_a_wait_action_costs_nothing_and_recovers_nothing():
    result = SimTransport(seed=1).execute(_action(action_type="wait", cost_paise=0), _ctx())
    assert result.cost_paise == 0
    assert result.recovered is False


# --- reference_id (A-009) ------------------------------------------------------------


def test_reference_id_is_deterministic_and_within_the_length_limit():
    a = reference_id("sub_1", "send_message", 1)
    b = reference_id("sub_1", "send_message", 1)
    assert a == b
    assert len(a) == 40


@pytest.mark.parametrize(
    "args",
    [("sub_2", "send_message", 1), ("sub_1", "create_link", 1), ("sub_1", "send_message", 2)],
)
def test_reference_id_changes_with_every_component(args):
    assert reference_id(*args) != reference_id("sub_1", "send_message", 1)


def test_reference_ids_do_not_collide_across_a_realistic_batch():
    """The input shape a real run produces: generator ids, five attempts each."""
    from recoup.simulator.generator import generate_scenarios

    refs = {
        reference_id(s.subscription_id, "send_message", n)
        for s in generate_scenarios(n=2000, seed=17)
        for n in range(1, 6)
    }
    assert len(refs) == 2000 * 5


# --- RealTransport, against a mock that behaves like Razorpay ------------------------


def _transport(handler) -> RealTransport:
    return RealTransport(
        key_id="rzp_test_x", key_secret="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler), auth=("a", "b")),
    )


def test_real_transport_is_named_real():
    assert _transport(lambda r: httpx.Response(200, json={})).name == "real"


def test_credentials_are_required_at_construction():
    # Failing on the first call would mean failing after the run had started.
    with pytest.raises(ValueError, match="key_id"):
        RealTransport(key_id="", key_secret="s")


def test_a_created_link_is_reported_but_never_as_recovered():
    """A link being created says nothing about whether anyone paid it.

    The answer arrives later as a `payment_link.paid` webhook. A real transport
    that claimed to know the outcome synchronously would be lying about the one
    thing this boundary exists to make honest.
    """
    def handler(request):
        assert request.url.path == "/v1/payment_links"
        return httpx.Response(200, json={"id": "plink_ABC123", "status": "created"})

    result = _transport(handler).execute(_action(), _ctx())
    assert result.ok is True
    assert result.provider_ref == "plink_ABC123"
    assert result.recovered is False
    assert result.cost_paise == 12


def test_the_payload_carries_the_deterministic_reference_id():
    seen = {}

    def handler(request):
        import json as _json
        seen.update(_json.loads(request.content))
        return httpx.Response(200, json={"id": "plink_1"})

    _transport(handler).execute(_action(attempt_no=3), _ctx())
    assert seen["reference_id"] == reference_id("sub_1", "send_message", 3)


def test_the_payload_uses_checkout_upi_and_never_upi_link():
    """A-010: `upi_link: true` is live mode only and would fail in test mode."""
    seen = {}

    def handler(request):
        import json as _json
        seen.update(_json.loads(request.content))
        return httpx.Response(200, json={"id": "plink_1"})

    _transport(handler).execute(_action(), _ctx())
    assert "upi_link" not in seen
    assert seen["options"]["checkout"]["method"]["upi"] == "1"


def test_razorpays_own_notifications_are_disabled():
    """We send our own messages, through the policy engine. Razorpay's would
    double-message and would bypass every veto in `rules.yaml`."""
    seen = {}

    def handler(request):
        import json as _json
        seen.update(_json.loads(request.content))
        return httpx.Response(200, json={"id": "plink_1"})

    _transport(handler).execute(_action(), _ctx())
    assert seen["notify"] == {"sms": False, "email": False}
    assert seen["reminder_enable"] is False


def test_a_duplicate_reference_id_is_fetched_not_recreated():
    """A-009: collisions REJECT, they do not replay. Success-and-fetch.

    Razorpay rejects a repeated `reference_id` with a 400. Treating that as a
    failure would make the caller retry; treating it as success without fetching
    would lose the provider ref. Neither is acceptable, so we fetch.
    """
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(400, json={
                "error": {"description": "reference_id already exists for this account"}
            })
        return httpx.Response(200, json={"payment_links": [{"id": "plink_EXISTING"}]})

    result = _transport(handler).execute(_action(), _ctx())
    assert result.ok is True
    assert result.deduplicated is True
    assert result.provider_ref == "plink_EXISTING"
    assert result.cost_paise == 0, "nothing new was sent, so nothing new was spent"
    assert [m for m, _ in calls] == ["POST", "GET"]


def test_a_timeout_fetches_before_it_would_ever_retry():
    """Never blind-retry a create — that is how you charge someone twice."""
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"payment_links": [{"id": "plink_LANDED"}]})

    result = _transport(handler).execute(_action(), _ctx())
    assert result.ok is True
    assert result.deduplicated is True
    assert result.provider_ref == "plink_LANDED"
    assert calls == ["POST", "GET"], "the GET must happen, and no second POST"


def test_a_timeout_with_nothing_created_reports_failure_rather_than_retrying():
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"payment_links": []})

    result = _transport(handler).execute(_action(), _ctx())
    assert result.ok is False
    assert "not created" in result.error
    assert calls.count("POST") == 1


def test_an_ordinary_api_error_is_reported_not_swallowed():
    def handler(request):
        return httpx.Response(401, json={"error": {"description": "Authentication failed"}})

    result = _transport(handler).execute(_action(), _ctx())
    assert result.ok is False
    assert "401" in result.error
    assert "Authentication failed" in result.error


def test_a_wait_action_makes_no_http_call_at_all():
    def handler(request):  # pragma: no cover - must never run
        raise AssertionError("wait must not touch the network")

    result = _transport(handler).execute(_action(action_type="wait", cost_paise=0), _ctx())
    assert result.ok is True
    assert result.cost_paise == 0


def test_no_code_path_here_initiates_a_debit():
    """D-030. Post-halt there is no mandate to debit, and nothing here could.

    Checked against the artifact: the only endpoint this module names is
    payment_links.
    """
    import re

    from recoup.execute import real

    source = __import__("pathlib").Path(real.__file__).read_text(encoding="utf-8")
    endpoints = set(re.findall(r"BASE_URL\}/([a-z_]+)", source))
    assert endpoints == {"payment_links"}, endpoints
    for forbidden in ("/payments", "capture", "charge", "mandate", "debit"):
        assert f"{{BASE_URL}}/{forbidden}" not in source


# --- the two transports are not interchangeable ---------------------------------------


def test_the_two_transports_differ_in_what_they_can_know():
    """Not a style difference. The simulator IS the customer, so it knows the
    outcome; the real transport cannot, and says so by always returning False."""
    def handler(request):
        return httpx.Response(200, json={"id": "plink_1"})

    sim_results = [SimTransport(seed=i).execute(_action(), _ctx()) for i in range(200)]
    assert any(r.recovered for r in sim_results)

    real_t = _transport(handler)
    assert not any(
        real_t.execute(_action(attempt_no=i), _ctx()).recovered for i in range(1, 20)
    )


def test_both_transports_satisfy_the_same_protocol():
    def handler(request):
        return httpx.Response(200, json={"id": "plink_1"})

    for t in (SimTransport(seed=1), _transport(handler)):
        assert t.name in ("real", "sim")
        assert isinstance(t.execute(_action(), _ctx()), ActionResult)
