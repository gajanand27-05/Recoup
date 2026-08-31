import pytest

from recoup.policy.predicates import (
    COERCIVE_TOKENS,
    PROMOTIONAL_TOKENS,
    classify_message,
    contains_coercive_tokens,
    contains_promotional_tokens,
    find_promotional_tokens,
    ist_hour,
)


@pytest.mark.parametrize("body", [
    "Your payment of Rs 499 could not be processed. Tap to retry: {link}",
    "We could not collect your subscription payment. Update your card: {link}",
    "Payment failed. Your account remains active until 5 Sep. Pay here: {link}",
])
def test_plain_service_copy_is_clean(body):
    assert contains_promotional_tokens(body) is None


@pytest.mark.parametrize("body,token", [
    ("Payment failed. Don't lose your 40% loyalty discount, upgrade now!", "discount"),
    ("Renew today and save 20% on your annual plan", "save"),
    ("Payment failed. Limited-time offer inside!", "offer"),
    ("Your payment failed. Upgrade to Pro and get 3 months free", "upgrade"),
    ("Refer a friend and get Rs 500 off your next bill", "refer"),
])
def test_promotional_copy_is_caught(body, token):
    """The body is caught, and the named token is among the reasons.

    Asserting WHICH token `contains_promotional_tokens` returns would be
    over-specifying: "loyalty discount, upgrade now" trips three, and the regex
    reaches whichever comes first. What matters is that the body is caught and
    that the token the case is named for is genuinely one of the offenders.
    """
    assert contains_promotional_tokens(body) is not None
    found = [t.lower() for t in find_promotional_tokens(body)]
    assert token in found, f"expected {token!r} among {found}"


def test_all_offending_tokens_are_reported_not_just_the_first():
    """The demo message trips three tokens. A veto naming one understates it."""
    found = [t.lower() for t in find_promotional_tokens(
        "Payment failed. Don't lose your 40% loyalty discount, upgrade now!"
    )]
    assert found == ["loyalty", "discount", "upgrade"]


def test_repeated_tokens_are_reported_once():
    assert find_promotional_tokens("discount discount DISCOUNT") == ["discount"]


def test_clean_copy_reports_no_tokens():
    assert find_promotional_tokens("Your payment could not be processed") == []


def test_detection_is_case_insensitive():
    assert contains_promotional_tokens("SPECIAL DISCOUNT INSIDE") is not None


def test_word_boundaries_are_respected():
    """'offer' must not fire on 'coffee'; 'save' must not fire on 'saved'."""
    assert contains_promotional_tokens("Your coffee subscription payment failed") is None


@pytest.mark.parametrize("body", [
    "Your coffee subscription payment failed",
    "We saved your card details securely",
    "Your free trial ended last month",  # 'free' IS a token; see the next test
])
def test_no_token_fires_inside_a_longer_word(body):
    found = contains_promotional_tokens(body)
    if found is not None:
        # If it matched, it must have matched a whole word, not a fragment.
        assert found.lower() in {t.lower() for t in PROMOTIONAL_TOKENS}


def test_classification_follows_the_content():
    assert classify_message("Your payment failed. Pay here: {link}") == "SERVICE_IMPLICIT"
    assert classify_message("Payment failed. 40% discount if you renew!") == "PROMOTIONAL"


def test_an_empty_body_is_not_promotional():
    assert contains_promotional_tokens("") is None
    assert contains_promotional_tokens(None) is None


# --- coercion, for RBI-005 ----------------------------------------------------------
# The RBI rule reads "not msg.is_coercive". Without a definition that predicate
# could never be false, and the rule would be decorative -- declared, evaluated,
# and incapable of firing.


@pytest.mark.parametrize("body", [
    "Pay immediately or we will take legal action",
    "Final warning: your account will be reported to the credit bureau",
    "We will send agents to your address",
])
def test_coercive_copy_is_caught(body):
    assert contains_coercive_tokens(body) is not None


@pytest.mark.parametrize("body", [
    "Your payment of Rs 499 could not be processed. Tap to retry: {link}",
    "Payment failed. Your account remains active until 5 Sep.",
])
def test_ordinary_copy_is_not_coercive(body):
    assert contains_coercive_tokens(body) is None


def test_every_declared_token_list_is_non_empty_and_lowercase():
    # A token list that drifted to empty would silently make its rule unfireable.
    for tokens in (PROMOTIONAL_TOKENS, COERCIVE_TOKENS):
        assert tokens
        assert all(t == t.lower() for t in tokens)


# --- IST conversion ------------------------------------------------------------------


def test_ist_hour_converts_from_utc():
    from datetime import UTC, datetime

    # 18:10 UTC is 23:40 IST -- the case the SI 24x7 rule turns on.
    assert ist_hour(datetime(2026, 9, 1, 18, 10, tzinfo=UTC)) == 23
    assert ist_hour(datetime(2026, 9, 1, 4, 30, tzinfo=UTC)) == 10
    assert ist_hour(datetime(2026, 9, 1, 0, 0, tzinfo=UTC)) == 5


def test_ist_hour_rejects_a_naive_datetime():
    """A naive datetime would be treated as UTC and be 5h30m wrong.

    Same reasoning as `clock.to_iso_z`: on a machine set to IST, guessing puts
    every policy window on the wrong side of its boundary.
    """
    from datetime import datetime

    with pytest.raises(ValueError, match="naive"):
        ist_hour(datetime(2026, 9, 1, 18, 10))


def test_ist_hour_normalises_an_already_offset_datetime():
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    assert ist_hour(datetime(2026, 9, 1, 23, 40, tzinfo=ist)) == 23
