"""The outcome oracle.

Everything in this package is FROZEN and tagged before `src/recoup/agent/` exists.
That ordering is the claim Task 26 Step 2 makes on camera, and `git log` is the
evidence rather than the assertion -- enforced by `tests/test_build_order.py`.

The simulator must never import from `recoup.agent`. An instrument that depends
on the thing it measures is not an instrument.
"""
