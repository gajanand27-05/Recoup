"""Analysis over the ledger.

READ THIS BEFORE ADDING A MODULE HERE
=====================================

This package has one constraint that matters more than anything in it, and it is
enforced by **import structure** rather than by care (D-011):

    `lift.py` must never read `would_self_recover`, directly or transitively.

`would_self_recover` is the simulator's ground truth about whether a customer
would have paid without any intervention. It is the counterfactual. A measurement
module that can see it is not measuring anything -- it is reading the answer, and
every number it produces is unfalsifiable.

The rules, concretely:

* **`lift.py`** computes the reported effect. It may read arm assignment,
  outcomes and money. It may not read `would_self_recover`, and it may not import
  `diagnostics.py`.
* **`diagnostics.py`** is the ONLY module permitted to read `would_self_recover`.
  It exists to characterise the simulator (false-positive cost, randomisation
  balance), not to produce reported effects. It must not be imported by `lift.py`.
* **Anything else added here** must state which side of that line it is on, in
  its own docstring, before it has any code.

There is a test that walks the import graph and the source text to enforce this.
If it fails, the fix is never to relax the test.

Why this file says so at all
----------------------------
`transport_split.py` was written ahead of its task, so for a while this package
existed with one module and no `lift.py` -- a directory whose most important
constraint was unrepresented in it. The rule is written down here so the first
person to add the second module meets it before writing code rather than after.
"""
