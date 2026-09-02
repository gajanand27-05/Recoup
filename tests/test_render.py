"""The template renderer — the thing that makes DLT-008 a check rather than a promise.

`body_matches_registered_template` gates every outbound message through DLT-008,
and until now nothing computed it. `baseline/fixed.py` sets it True by hand,
which is defensible there because the control renders one fixed template
verbatim — but the agent writes its own copy, so for the agent the same
assertion would be a false one.

That is the whole reason this module exists. The agent does not get to write
message bodies. It picks a REGISTERED template and supplies variables, and the
renderer computes whether what came out actually matches what was registered.
A body the model wrote freehand fails that check, which is correct: under DLT a
body that does not match its registered template is not sendable, whoever wrote
it and however reasonable it reads.
"""

import pytest

from recoup.render.templates import (
    TEMPLATES,
    RenderedMessage,
    TemplateError,
    body_matches,
    render,
)


def test_a_registered_template_renders_and_matches():
    msg = render("TPL_RECOUP_SMS_001", {"amount": "499", "link": "https://rzp.io/i/abc"})
    assert isinstance(msg, RenderedMessage)
    assert msg.matches_registered_template is True
    assert "499" in msg.body
    assert msg.dlt_template_id == "TPL_RECOUP_SMS_001"


def test_an_unknown_template_is_refused():
    with pytest.raises(TemplateError, match="not registered"):
        render("TPL_THE_MODEL_INVENTED_THIS", {"amount": "499"})


def test_a_missing_variable_is_refused_rather_than_left_blank():
    """A blank slot renders as a body that does not match, so fail loudly instead."""
    with pytest.raises(TemplateError, match="missing"):
        render("TPL_RECOUP_SMS_001", {"amount": "499"})  # no link


def test_an_unexpected_variable_is_refused():
    with pytest.raises(TemplateError, match="unexpected"):
        render("TPL_RECOUP_SMS_001", {"amount": "499", "link": "x", "discount": "40%"})


# --- the part that matters: the check is COMPUTED --------------------------------


def test_freehand_copy_does_not_match_any_template():
    """The exact failure this module exists to prevent.

    Reasonable, compliant-sounding, service-toned copy that no one registered.
    It must not match, because 'reads fine' is not the DLT test.
    """
    freehand = "Hi, your subscription payment could not be processed. Pay here: https://x"
    assert body_matches("TPL_RECOUP_SMS_001", freehand) is False


def test_a_body_with_extra_text_appended_does_not_match():
    """Template drift: the registered body plus a persuasive sentence."""
    msg = render("TPL_RECOUP_SMS_001", {"amount": "499", "link": "https://rzp.io/i/abc"})
    assert body_matches("TPL_RECOUP_SMS_001", msg.body + " Reply STOP to opt out.") is False


def test_variable_content_may_vary_but_fixed_text_may_not():
    a = render("TPL_RECOUP_SMS_001", {"amount": "499", "link": "https://rzp.io/i/a"})
    b = render("TPL_RECOUP_SMS_001", {"amount": "1299", "link": "https://rzp.io/i/b"})
    assert a.body != b.body
    assert a.matches_registered_template and b.matches_registered_template


def test_a_variable_cannot_smuggle_in_a_second_sentence():
    """Variables are slots, not an escape hatch.

    If a variable may contain arbitrary text, the model can put promotional copy
    inside one and the rendered body still 'matches its template'. That would
    make DLT-008 pass on a message DLT-007 exists to stop.
    """
    with pytest.raises(TemplateError, match="variable"):
        render(
            "TPL_RECOUP_SMS_001",
            {"amount": "499. Don't lose your 40% loyalty discount", "link": "https://x"},
        )


# --- every registered template must itself be legal ------------------------------


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_every_registered_template_carries_its_provenance(template_id):
    t = TEMPLATES[template_id]
    assert t.channel in {"sms", "whatsapp", "email"}
    assert t.registered_with, f"{template_id} does not say who registered it"
    assert t.source_url.startswith("http"), f"{template_id} has no source"


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_no_registered_template_is_itself_promotional(template_id):
    """A registered template containing promotional tokens would pass DLT-008 and
    fail DLT-007 — which means shipping it is a guaranteed veto, every send."""
    from recoup.policy.predicates import contains_promotional_tokens

    assert contains_promotional_tokens(TEMPLATES[template_id].pattern) is None
