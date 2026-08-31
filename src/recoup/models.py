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
