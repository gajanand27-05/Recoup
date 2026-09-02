"""Shared types."""

from datetime import datetime

from pydantic import BaseModel, Field


class Action(BaseModel):
    """A proposed outreach action.

    This is what the agent emits and what the policy engine vetoes. Note there is
    no `charge` action type: post-halt the system never initiates a debit (D-030).
    """

    action_type: str = Field(pattern="^(send_message|create_link|escalate|wait|stop)$")
    channel: str = Field(default="whatsapp", pattern="^(whatsapp|sms|email|voice|none)$")
    body: str = ""
    send_at: datetime
    attempt_no: int = 1
    cost_paise: int = 0
    wa_template_category: str = "UTILITY"
    dlt_template_id: str | None = None
    dlt_template_approved: bool = False

    # Asserted by whoever rendered the body. Defaults to False so that a message
    # built without going through template rendering is vetoed by DLT-008 rather
    # than waved through: a rule that can never be false is decorative, and the
    # safe default for "did this match the registered template?" is "prove it".
    #
    # CARRIED: Task 19's template renderer must COMPUTE this rather than assert
    # it. Until then it is a caller promise, which is weaker than a check.
    body_matches_registered_template: bool = False

    uses_rzp_reminder: bool = False
    rationale: str = ""

    # Which model decided this, or `deterministic` when nothing did. Carried on
    # the action rather than inferred later, because by report time a fallback
    # and a model decision are indistinguishable -- both are just an Action that
    # got sent. `require_real_model()` refuses to report over a mixture, so a run
    # where the model kept failing schema cannot be presented as a model's work.
    #
    # None means "not set by anyone", which is different from `deterministic`
    # ("nothing decided this, and we know") and is refused just as loudly.
    model_source: str | None = None

    # How many times this action has already been re-proposed after a veto. A
    # real field rather than something the planner keeps on the side: it has to
    # survive being handed back through the policy engine, and a counter that
    # lives in the agent would reset every time the batch reconstructs one.
    replans: int = 0
