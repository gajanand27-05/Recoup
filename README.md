# recoup

**Post-halt subscription payment recovery, with a measured holdout arm.**

Razorpay AI Buildathon 2026 · Track 03 — AI Revenue Recovery

---

## The problem

When a subscription payment fails, Razorpay retries it three times — T+1, T+2, T+3 days — on a
fixed schedule that cannot be configured. If all three fail it marks the subscription `halted`.
Invoices keep generating. **No further charge is ever attempted.**

Everything after `subscription.halted` is the merchant's problem.

`recoup` starts exactly there. It cannot charge anyone — post-halt there is no mandate left to
debit — so it works by reaching out: choosing a channel, choosing a time, writing the message,
issuing a payment link, reading the reply, and deciding whether to press again or stop.

## What makes it a claim rather than a demo

**1. It is measured against a fair comparison.**
Half the customers get the agent. The other half get what a competent merchant does by hand — a
payment link on a fixed schedule with fixed copy. The reported number is the difference, with a
confidence interval. That is the gap between "recovered ₹X" and "recovered ₹X *more than doing
the obvious thing*", and only the second one is a claim.

**2. The rules are not inside the agent.**
A separate policy engine vetoes actions before they execute. Every rule carries a source URL and
a legal classification — binding law, industry practice, or best-practice-by-analogy — because
asserting a convention as a regulation is the fastest way to lose credibility with payments
engineers.

**3. Every number is recomputable from this repository.**
The ledger is append-only and hash-chained. `recoup verify-ledger` recomputes the chain and
prints the head hash.

## Status

Under construction for the 5 September 2026 deadline. This README is expanded as the build
progresses; architecture, reproduction steps and a full limitations section land before submission.

## Development

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # Windows
# .venv/bin/pip install -e ".[dev]"        # POSIX

python tasks.py test        # or: make test
python tasks.py lint
```

`tasks.py` mirrors the `Makefile` for machines without `make`.

## Licence

MIT
