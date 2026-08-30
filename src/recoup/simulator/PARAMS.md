# Simulator generative parameters

Every parameter, its value, its class, its source, and the population it was measured on.

**Every parameter carries a `class`.** Same discipline as the policy engine's legal class
(A-006): a number whose status is implicit gets read as stronger than it is.

| Class | Meaning |
|---|---|
| `MEASURED` | Taken from a published figure, on a stated population, at a URL |
| `DERIVED` | Computed from a `MEASURED` figure by an arithmetic that is stated here |
| `DEFINITIONAL` | A normalisation anchor. Not a finding; a choice of units |
| `ASSUMPTION` | **Not sourced.** Swept in the sensitivity analysis (Task 23b) |

**Nothing is smoothed over** (D-012). Where we had to invent a number, it says so, and the
sweep range is declared with the reasoning for both endpoints.

---

## Day-offset recovery curve — `MEASURED`

Baremetrics, **1M+ dunning emails**, Baremetrics Recover customers (US B2B SaaS), Dec 2024.
https://baremetrics.com/blog/dunning-email-best-practices

| Day offset | Recovery rate |
|---|---|
| 0 | 13.25% |
| 3 | 11.46% |
| 7 | 11.51% |
| 15 | 4.22% |
| 20 | 3.83% |
| 30 | 4.20% |

**Key structural fact:** recovery falls ~3x between day 7 and day 15 while open rate barely
moves (32.7% → 28.2%). The decay is **intent**, not deliverability. The simulator models it
that way — a message delivered on day 20 is read and ignored, not undelivered.

Independently corroborated: Recurly — *"90% of successful recoveries occur within the first
10 days."*

Note the curve is **not monotonic**: day 30 (4.20%) exceeds day 20 (3.83%). That is in the
source and is preserved rather than smoothed. Do not "fix" it.

---

## Per-attempt decay — `DERIVED`

Churnkey incremental recovery per email: 2.8%, 1.9%, 1.7%, 1.5%, 1.5%
https://churnkey.co/blog/involuntary-churn-benchmarks/ — 6M failed payments, CY2024

Derivation, stated so it can be checked: each value divided by the first.
`[2.8, 1.9, 1.7, 1.5, 1.5] / 2.8` → `[1.00, 0.68, 0.61, 0.54, 0.54]`

---

## Channel multipliers — **all `ASSUMPTION` or `DEFINITIONAL`**

> **Correction, 2026-08-30.** An earlier draft of this table set `sms = 0.60` and cited
> Churnkey for it. That was wrong three ways and the number has been reclassified rather than
> restated. It is recorded here rather than deleted, because a provenance document that
> quietly drops its own errors is not evidence.
>
> 1. **A units error.** Churnkey reports SMS at **0.6 %**. The multiplier was written `0.60`.
> 2. **A category error.** Churnkey reports *share of recoveries*, not *per-message
>    effectiveness*. Share is a function of how much of each channel merchants **sent**, and
>    Churnkey does not publish send volumes. Converting one to the other is not possible with
>    the data cited. A literal share ratio would be 0.6 / 8.4 = **0.071**, which is also not
>    an effectiveness figure.
> 3. **It contradicted our own research log.** `LOGS.md` §6b records the caveat directly:
>    *"SMS's 0.6% is confounded by low merchant adoption — treat as a floor."*

Churnkey's published attribution, for reference — **share of recoveries, not effectiveness**:

| Channel | Share of recoveries |
|---|---|
| Precision retries | 28.1% |
| Billing contact API | 10.0% |
| Email | 8.4% |
| In-app wall | 3.5% |
| SMS | 0.6% |

### `channel_multiplier_email = 1.00` — `DEFINITIONAL`
The normalisation anchor. Every other channel is expressed relative to email. This is a
choice of units, not a finding, and it is not evidence for anything.

### `channel_multiplier_sms = 0.60` — `ASSUMPTION`, swept **0.07 – 1.50**
No defensible sourced value exists for per-message SMS effectiveness in this setting.

* **Low endpoint 0.07** — Churnkey's share ratio (0.6 / 8.4) read literally as effectiveness.
  We hold that reading to be invalid, and use it only as a pessimistic bound.
* **High endpoint 1.50** — SMS *outperforming* email. Directionally supported by the only
  rigorous causal evidence located anywhere in this research: **Cadena & Schoar, NBER WP
  17020 (May 2011)**, a randomised trial with a Ugandan microlender, finding **+7–9 pp** on
  on-time payment from a monthly SMS reminder — an effect the authors size as comparable to a
  25% interest-rate cut. India is likewise a market where SMS reach exceeds email reach.

The point estimate 0.60 sits between them and is **not claimed to be measured**.

### `channel_multiplier_whatsapp = 1.00` — `ASSUMPTION`, swept **0.50 – 1.50**
WhatsApp is absent from Churnkey's US-centric data. Modelled at email parity.

We deliberately do **not** model it higher, despite the temptation: the widely-quoted
"WhatsApp 98% open rate" traces to vendor marketing copy with no published methodology,
sample or window, and no such Meta-published figure exists (`LOGS.md`). Using it would be
exactly the kind of citation-shaped guess this document exists to prevent.

What *is* sourced about WhatsApp is **cost**, not effectiveness: WhatsApp Utility in India is
₹0.1150/msg against ₹0.12–0.16 for Service-Implicit SMS — cheaper *and* richer. That enters
the cost model, not the response curve.

---

## Beyond-curve decay — `ASSUMPTION`

`decay_beyond_curve = 0.97` per day past day 30, swept **0.90 – 1.00**.

The Baremetrics table stops at day 30. Something has to happen past it, and every option is
an invention: hold flat (1.00), decay, or drop to zero. 0.97/day is a slow decay consistent
with the source's own shape — intent falling while deliverability does not.

Swept to 1.00 (flat, no further decay) at the optimistic end. Not swept below 0.90 because a
faster decay makes late outreach worthless, which would flatter the agent's early-contact
policy rather than test it.

---

## Hard declines — `MEASURED` set, `ASSUMPTION` multiplier

Never auto-retryable; require a new payment method.
https://docs.stripe.com/declines/codes

`incorrect_number, lost_card, pickup_card, stolen_card, revocation_of_authorization,`
`revocation_of_all_authorizations, authentication_required, highest_risk_level,`
`transaction_not_allowed`

Cross-referenced against the Churnkey decline mix: **~21% of failures are hard declines** —
the nudge-only segment.

`hard_decline_multiplier = 0.60` — `ASSUMPTION`, swept **0.30 – 1.00**. Hard declines should
respond less to outreach because the customer must take a larger action (add a new card)
rather than a smaller one (top up a balance). The *direction* is well founded; the magnitude
is not measured anywhere we could find. Upper endpoint 1.00 is "no penalty at all", which the
sweep must be able to reach in order to be a real test.

---

## Decline reason mix — `MEASURED`

Churnkey, 5M failures. https://churnkey.co/blog/involuntary-churn-benchmarks/

insufficient_funds 40.56% · transaction_not_allowed 8.83% · highest_risk_level 7.99% ·
do_not_honor 7.56% · previously_declined_do_not_retry 6.44% · generic_decline 5.78% ·
incorrect_number 4.69% · try_again_later 4.13% · partner_insufficient_funds 3.68% ·
invalid_account 2.71% · expired_card 1.14% · card_velocity_exceeded 1.05%

---

## Baseline — `MEASURED`

**Stripe Smart Retries alone: 51% recovery at 5.5 days** (Churnkey, 5.4M failures).
This is the `p1` used in the power calculation (A-001).

> **Population figures differ across Churnkey citations on this page** — 6M failed payments
> (channel attribution), 5M failures (decline mix), 5.4M failures (Smart Retries baseline).
> These are separate analyses in the same source and are quoted as published. They are *not*
> reconciled here, because silently harmonising three numbers into one would be inventing a
> population none of them describe.

---

## India-specific structural fact — `MEASURED`, not a parameter

**Stripe does not retry India-issued cards at all.**
https://docs.stripe.com/billing/revenue-recovery/smart-retries

Automated card retry is structurally not a lever in this market. This does not enter the
curve as a number; it is *why* the customer-facing nudge is the whole game here.

---

## What this table does not contain

Figures that were located during research and **deliberately rejected**, so that their
absence is a decision rather than an oversight:

| Rejected figure | Why |
|---|---|
| WhatsApp 98% open rate / 45–60% CTR | Traces to vendor copy. No methodology, sample or window ever published. No Meta-published 98% figure exists |
| "SMS payment links: 45% response vs email 6%" | Attributed to Razorpay by third parties; absent from every Razorpay page fetched directly |
| SMS effectiveness = 0.071 (Churnkey share ratio) | Share of recoveries is not per-message effectiveness; send volumes are unpublished. Used only as a sweep endpoint |
