"""Analysis over the ledger.

Nothing in here may read `would_self_recover` except `diagnostics.py`. `lift.py`
must not import `diagnostics.py`. The firewall is enforced by an import test, not
by discipline.
"""
