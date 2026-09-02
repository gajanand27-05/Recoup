"""Message rendering from registered templates.

Deliberately outside both `agent/` and `baseline/`: both arms render through it,
and a control arm importing from `agent/` would make the two arms differ by more
than their decision module (D-015).
"""
