"""Control arm: fixed-interval outreach.

A-011 — the original design said "fixed-interval retries". Post-`halted` there is
no mandate left to retry, so that baseline is not merely unrealistic, it is **not
executable**. This is what a merchant actually does by hand once a subscription
halts: reissue a payment link on a fixed schedule with fixed copy.

Deliberately NOT a do-nothing strawman. A modest lift over a fair baseline reads
as honest; a large lift over nothing reads as rigged (D-007). The entire lift
claim is a comparison against this module, so every choice here was made in the
direction that makes the control **stronger**, and each is recorded with why.

It runs through the identical policy engine, executor and ledger as the agent.
Only the decision module differs (D-015). It never initiates a debit — post-halt
there is no mandate and no code path here could (D-030).

Where the control was made stronger than PLAN.md specified
-----------------------------------------------------------
1. **Schedule front-loaded** from `(0, 2, 5, 9, 14)` to `(0, 2, 4, 7, 10)`.
   Measured against the frozen curve, cumulative recovery over the whole schedule
   rises from **0.3176 → 0.3383** for a soft decline. The plan's schedule spent
   one of its five attempts at day 14, outside the window Recurly names ("90% of
   successful recoveries occur within the first 10 days").
2. **It stops when the customer pays.** The plan had no such rule, so the control
   would have kept messaging after a `payment_link.paid` — wasting spend and
   inflating its own cost-per-recovery against the agent.
3. **Five attempts**, which is the ceiling `STOP-001` permits. Going higher would
   be vetoed, so this is the most the control is allowed.

Chosen before any lift number existed. A control tuned after seeing the lift is
not a control.
"""

from datetime import datetime, timedelta

from recoup.models import Action
from recoup.render.templates import render

# --- DERIVED from the frozen curve + Recurly's 10-day window -------------------
# Cumulative recovery, soft decline, whatsapp, full attempt decay:
#   (0,1,2,3,4)  0.3536   maximally aggressive, five messages in five days
#   (0,1,3,5,7)  0.3513
#   (0,2,4,7,10) 0.3383   <- chosen
#   (0,2,5,9,14) 0.3176   PLAN.md
#   (0,3,7,15,30) 0.2897
# The two tighter schedules score higher and are NOT chosen: five messages in as
# many days is not what a competent merchant does, and TRAI's complaint threshold
# is the reason SELF-001 exists. They are in SCHEDULE_ALTERNATIVES and swept, so
# if the lift claim depends on the control not being maximally aggressive, the
# sensitivity analysis will say so rather than the choice hiding it.
SCHEDULE_DAYS: tuple[int, ...] = (0, 2, 4, 7, 10)

SCHEDULE_ALTERNATIVES: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4),
    (0, 1, 3, 5, 7),
    (0, 2, 4, 7, 10),
    (0, 2, 5, 9, 14),
    (0, 3, 7, 15, 30),
)

# --- ASSUMPTION: channel. Swept over the three the curve models. ---------------
# Not a weakening: PARAMS.md models whatsapp and email identically (both 1.00,
# email definitionally). WhatsApp is chosen because in India it is cheaper than
# Service-Implicit SMS and richer than email, both of which are sourced. SMS is
# modelled at 0.60 and would be a WEAKER control, so it is not the default.
FIXED_CHANNEL = "whatsapp"
CHANNEL_ALTERNATIVES: tuple[str, ...] = ("whatsapp", "email", "sms")

# --- MEASURED: per-message unit cost in paise, India, ex-GST -------------------
# WhatsApp Utility Rs 0.1150/msg; Service-Implicit SMS Rs 0.12-0.16; email
# ~Rs 0.009. Sources in LOGS 7g. Rounded up to whole paise, which is the
# conservative direction for the control's own cost.
COST_PAISE = {"whatsapp": 12, "sms": 15, "email": 1}

# --- ASSUMPTION: send hour, IST. Swept 9-20. ----------------------------------
# 11:00 IST sits inside Razorpay's own reminder window (11:00-12:00) and inside
# the 10:00-21:00 window that would apply if the message ever lost its
# Service-Implicit status. SI itself is 24x7, so this is not a legal constraint.
SEND_HOUR_IST = 11

FIXED_BODY = (
    "Hi, we could not process your subscription payment of Rs {amount}. "
    "Your account is on hold. You can complete the payment here: {link}"
)

# The control uses one registered template for every message, which is the whole
# point: no decisioning, so nothing to re-register.
DLT_TEMPLATE_ID = "TPL_BASELINE_001"

PARAMS: dict[str, dict] = {
    "schedule_days": {
        "constant": "SCHEDULE_DAYS",
        "value": list(SCHEDULE_DAYS),
        "class": "DERIVED",
        "source": "https://baremetrics.com/blog/dunning-email-best-practices",
        "population": "1M+ dunning emails; plus Recurly's 90%-within-10-days figure",
        "derivation": (
            "highest cumulative recovery over the frozen curve among schedules "
            "that keep every attempt inside the sourced 10-day window and do not "
            "message on consecutive days beyond the first gap"
        ),
        "alternatives": [list(s) for s in SCHEDULE_ALTERNATIVES],
    },
    "fixed_channel": {
        "constant": "FIXED_CHANNEL",
        "value": FIXED_CHANNEL,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- no sourced per-channel effectiveness figure exists",
        "choices": list(CHANNEL_ALTERNATIVES),
        "note": (
            "whatsapp and email are modelled identically (1.00); sms at 0.60 would "
            "be a weaker control, so it is not the default. Swept over all three."
        ),
    },
    "cost_paise": {
        "constant": "COST_PAISE",
        "value": COST_PAISE,
        "class": "MEASURED",
        "source": "https://www.myoperator.com/blog/whatsapp-business-api-pricing/",
        "population": "India rate cards, ex-GST: WhatsApp Utility Rs 0.1150/msg; "
                      "Service-Implicit SMS Rs 0.12-0.16; email ~Rs 0.009",
    },
    "send_hour_ist": {
        "constant": "SEND_HOUR_IST",
        "value": SEND_HOUR_IST,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- SI messages are 24x7, so no hour is required",
        "sweep": [9, 20],
        "note": (
            "11:00 IST is inside Razorpay's own reminder window and inside the "
            "10:00-21:00 window that would apply if the message lost SI status."
        ),
    },
}


class FixedIntervalOutreach:
    """No decisioning. Same channel, same copy, same schedule, every time."""

    def __init__(self, schedule_days: tuple[int, ...] | None = None) -> None:
        """`schedule_days` defaults to the measured SCHEDULE_DAYS.

        Injectable ONLY so the full-pipeline A/A can give one arm a known better
        schedule and confirm the pipeline REPORTS it. A test that passes by
        finding nothing has to be shown capable of finding something, and the
        first version of that check set an attribute this class did not read --
        so the injection was inert and the check would have failed for the wrong
        reason, reporting "cannot detect" about a pipeline that can.

        The default is the measured schedule, so a normal run cannot get a
        substituted one by accident.
        """
        self.schedule_days = schedule_days or SCHEDULE_DAYS

    def propose(self, state, context: dict, now: datetime) -> Action | None:
        # 1. Opted out is absolute. The policy engine would veto anyway, but the
        #    baseline should not propose actions it already knows are dead.
        if state.opted_out:
            return None

        # 2. STOP WHEN THEY PAY. PLAN.md had no such rule, so the control would
        #    have kept messaging after `payment_link.paid` -- spending money on a
        #    customer who had already paid and inflating its own cost per
        #    recovery against the agent. A competent merchant stops.
        if state.recovered_paise > 0:
            return None

        day_offset = context.get("day_offset", 0)
        if day_offset not in self.schedule_days:
            return None

        attempt_no = self.schedule_days.index(day_offset) + 1
        if attempt_no in state.attempts_seen:
            return None

        send_at = self._send_time(now)

        # Rendered through the registry rather than formatted here, so
        # `body_matches_registered_template` is COMPUTED. It used to be passed
        # as True with a comment saying there was nothing to compute -- which
        # was true of the body, and not true of the claim. A hand-asserted
        # compliance flag is the proxy-guard shape: it reports on the caller's
        # intention rather than on the message.
        rendered = render(
            DLT_TEMPLATE_ID,
            {"amount": str(context.get("amount_paise", 0) // 100), "link": "{link}"},
        )

        return Action(
            action_type="send_message",
            channel=FIXED_CHANNEL,
            body=rendered.body,
            send_at=send_at,
            attempt_no=attempt_no,
            cost_paise=COST_PAISE[FIXED_CHANNEL],
            wa_template_category="UTILITY",
            dlt_template_id=rendered.dlt_template_id,
            dlt_template_approved=True,
            body_matches_registered_template=rendered.matches_registered_template,
            uses_rzp_reminder=False,
            rationale="fixed schedule, no decisioning",
        )

    @staticmethod
    def _send_time(now: datetime) -> datetime:
        """SEND_HOUR_IST on the current day, in UTC. Next day if already past."""
        utc_hour = SEND_HOUR_IST - 6  # IST is UTC+5:30; 11:00 IST == 05:30 UTC
        send_at = now.replace(hour=max(utc_hour, 0), minute=30, second=0, microsecond=0)
        if send_at < now:
            send_at = send_at + timedelta(days=1)
        return send_at
