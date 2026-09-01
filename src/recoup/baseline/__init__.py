"""The control arm.

Fixed-interval outreach: a payment link on a fixed schedule with fixed copy and
no decisioning. The entire lift claim is a comparison against this, so it is
built to be a competent merchant's manual process rather than a strawman.
"""

from recoup.baseline.fixed import SCHEDULE_DAYS, FixedIntervalOutreach

__all__ = ["SCHEDULE_DAYS", "FixedIntervalOutreach"]
