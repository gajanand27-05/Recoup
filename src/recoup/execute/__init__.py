"""Execution: the transport boundary between a decision and the world.

`SimTransport` is the counterfactual customer and draws from the frozen response
curve. `RealTransport` issues genuine Razorpay test-mode Payment Links.

They are never pooled in a reported number, and they differ in what they can
know: the simulator returns whether the payment was recovered, because it is the
customer; the real transport always returns `recovered=False`, because a created
link says nothing about whether anyone paid it. See `transport.py`.
"""
