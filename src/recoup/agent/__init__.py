"""The agent.

Everything here was written AFTER `simulator/` was frozen and tagged. That
ordering is the claim Task 26 makes on camera, and `git log --diff-filter=A` is
the evidence — `tests/test_build_order.py` and a CI job enforce it.

The model is a NAMED boundary, exactly as `sim` and `real` transports are. See
`llm.py`: every result records which model produced it, stub output may never be
reported, and there is no silent fallback when the key is missing.
"""
