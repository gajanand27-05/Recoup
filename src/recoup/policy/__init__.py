"""The policy engine: an external veto layer.

Rules are authored against regulation, in `rules.yaml`, and evaluated outside the
agent. The agent proposes; this package disposes. That separation is the point —
a model that could edit its own constraints is not constrained by them.

Every rule carries a legal `class`. A rule asserting HARD_LAW must cite where the
law is; a SELF_IMPOSED rule must NOT cite anything, because a restraint with a
plausible citation beside it reads as externally required. Both directions are
enforced by `tests/test_policy_rules.py`.
"""
