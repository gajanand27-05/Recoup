"""Which decision module runs for each arm.

A registry rather than an `if arm == "control"` at the call site, so that
"every arm" is something a test can enumerate. INC-007 was an arm that silently
did nothing: the control's actions were vetoed by DLT-008 on every send, so the
control sent nothing, recovered nothing, and the measured lift would have been
enormous and meaningless. Nothing failed. The suite was green.

The defence is `tests/test_arm_policy_coverage.py`, which walks THIS dict and
puts each arm's real action through the real policy engine. An arm added later
without policy coverage fails that test rather than passing by omission -- which
is the only reason the registry exists as data instead of a branch.
"""

from recoup.assign.arms import CONTROL, TREATMENT
from recoup.baseline.fixed import FixedIntervalOutreach


def _control():
    return FixedIntervalOutreach()


def _treatment(client=None):
    # Imported lazily: `agent/` must not be imported by anything that runs
    # before the freeze checks, and the control path has no business pulling in
    # a model client.
    from recoup.agent.planner import RecoveryAgent

    return RecoveryAgent(client=client)


DECIDERS = {
    CONTROL: _control,
    TREATMENT: _treatment,
}

#: Every arm the experiment assigns to. Kept next to DECIDERS so a mismatch is a
#: one-line assertion rather than something a reader has to notice.
ALL_ARMS = frozenset({CONTROL, TREATMENT})


def decider_for(arm: str, client=None):
    if arm not in DECIDERS:
        raise KeyError(
            f"arm {arm!r} has no decision module. Known: {sorted(DECIDERS)}. "
            f"An arm that cannot decide sends nothing, and an arm that sends "
            f"nothing makes the other arm's lift look enormous (INC-007)."
        )
    factory = DECIDERS[arm]
    return factory(client=client) if arm == TREATMENT else factory()
