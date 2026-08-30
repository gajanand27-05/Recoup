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

Registry key: `day_offset_curve`.

**Key structural fact:** recovery falls **~2.7x** between day 7 and day 15 (11.51% → 4.22%)
while open rate barely moves (32.7% → 28.2%). The decay is **intent**, not deliverability. The
simulator models it that way — a message delivered on day 20 is read and ignored, not
undelivered.

> An earlier draft of this line said "~3x". The measured ratio is 2.727. Rounding a
> load-bearing structural fact up to the next whole number is the kind of small overstatement
> that gets checked, so it is stated as measured.

Independently corroborated: Recurly — *"90% of successful recoveries occur within the first
10 days."*

Note the curve is **not monotonic**: day 30 (4.20%) exceeds day 20 (3.83%). That is in the
source and is preserved rather than smoothed. Do not "fix" it.

---

## Per-attempt decay — `DERIVED`

Churnkey incremental recovery per email: 2.8%, 1.9%, 1.7%, 1.5%, 1.5%
https://churnkey.co/blog/involuntary-churn-benchmarks/ — 6M failed payments, CY2024

Registry key: `attempt_decay`.

Derivation, stated so it can be checked: each value divided by the first.
`[2.8, 1.9, 1.7, 1.5, 1.5] / 2.8` → `[1.00, 0.68, 0.61, 0.54, 0.54]`

### `attempt_decay_compounding = 1.00` — `ASSUMPTION`, swept **0.00 – 1.00**

Registry key: `attempt_decay_compounding`.

**These two sources may be measuring the same decline twice.** Baremetrics reports recovery
by day offset *within a dunning sequence*, so its later days are also its later attempts.
Churnkey reports incremental recovery by email index. Both encode "a later contact recovers
less", and multiplying them applies that discount twice.

Neither source states how its dimensions relate, so this cannot be settled from the published
figures. Rather than leave it as an unexamined multiplication, it is an explicit parameter:

* `1.00` — full compounding, **the default**. Produces lower modelled recovery in both arms
  and therefore a smaller lift. Where the modelling is ambiguous, the default claims less.
* `0.00` — timing only; attempt number adds no further penalty beyond the day-offset curve.

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
Registry key: `channel_multiplier_email`.
The normalisation anchor. Every other channel is expressed relative to email. This is a
choice of units, not a finding, and it is not evidence for anything.

### `channel_multiplier_sms = 0.60` — `ASSUMPTION`, swept **0.07 – 1.50**
Registry key: `channel_multiplier_sms`.
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
Registry key: `channel_multiplier_whatsapp`.
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

Registry key: `decay_beyond_curve`.

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

Registry key: `hard_decline_codes`.

Cross-referenced against the Churnkey decline mix: **~21% of failures are hard declines** —
the nudge-only segment. As modelled the figure is 21.51%.

Registry key: `hard_decline_multiplier`.

`hard_decline_multiplier = 0.60` — `ASSUMPTION`, swept **0.30 – 1.00**. Hard declines should
respond less to outreach because the customer must take a larger action (add a new card)
rather than a smaller one (top up a balance). The *direction* is well founded; the magnitude
is not measured anywhere we could find. Upper endpoint 1.00 is "no penalty at all", which the
sweep must be able to reach in order to be a real test.

---

## Decline reason mix — `MEASURED` shares, `DERIVED` residual

Churnkey, 5M failures. https://churnkey.co/blog/involuntary-churn-benchmarks/
Registry keys: `sourced_reason_shares` (MEASURED), `reason_mix` (DERIVED).

insufficient_funds 40.56% · transaction_not_allowed 8.83% · highest_risk_level 7.99% ·
do_not_honor 7.56% · previously_declined_do_not_retry 6.44% · generic_decline 5.78% ·
incorrect_number 4.69% · try_again_later 4.13% · partner_insufficient_funds 3.68% ·
invalid_account 2.71% · expired_card 1.14% · card_velocity_exceeded 1.05%

**These twelve sum to 0.9456**, so `other` is the residual **0.0544**, computed rather than
typed so it cannot drift from the figures it is the residual of.

> **Correction, 2026-08-30.** `PLAN.md` set `other: 0.1544`, a digit error making the weights
> total **1.1000**. Nothing would have crashed — `random.choices` normalises — so every
> sourced share would simply have been rescaled, running `insufficient_funds` at 36.87% while
> this document cited 40.56%. Recorded rather than deleted.

### `residual_hard_fraction = 0.00` — `ASSUMPTION`, swept **0.00 – 0.30**

Registry key: `residual_hard_fraction`.

Six of Stripe's hard-decline codes — `lost_card`, `stolen_card`, `pickup_card`,
`authentication_required`, and the two revocation codes — do not appear in Churnkey's
published table at all. They therefore sit inside `other` (5.44%), which defaults to soft.

The sweep asks what happens if up to 30% of that residual is really hard. At `0.00` the
hard-decline share is 21.51%, against the ~21% cross-reference below.

> **Correction, 2026-08-30.** This was declared as a swept `ASSUMPTION` and **implemented
> nowhere**. The sensitivity analysis would have varied it, observed no change, and reported
> the result as insensitive — manufacturing evidence of robustness for a parameter that was
> never wired up. It is now read by `generate_scenarios`, and its roll is drawn
> unconditionally so that sweeping it cannot also reshuffle the rest of the batch.

---

## The counterfactual — `ASSUMPTION`, and the most consequential one here

Registry keys: `self_recovery_rate_soft`, `self_recovery_rate_hard`.

`would_self_recover` is the ground-truth label: whether a customer would have paid with **no
intervention at all**. It defines the baseline the entire lift claim is measured against, and
it is **not measured anywhere**. Nothing published gives a post-halt, no-outreach recovery
rate — post-halt means Razorpay has stopped retrying, so any recovery is the customer acting
unprompted, and merchants who do nothing at that point do not publish what happens next.

| Parameter | Value | Sweep | Reasoning |
|---|---|---|---|
| `self_recovery_rate_soft` | 0.18 | 0.05 – 0.35 | Swept wide because we have no measurement of it |
| `self_recovery_rate_hard` | 0.03 | 0.00 – 0.10 | A hard decline needs a new payment method, so unprompted recovery should be rare. 0.00 is "never recovers alone" |

If any number in this project has to be honest about being invented, it is this pair. They
are the first thing the sensitivity analysis should move, and the first thing a reader should
be told about.

This is also the column `eval/lift.py` is forbidden from reading (D-011). It exists to
measure the cost of acting on a payment that would have recovered anyway — which is a
diagnostic question, not a measurement one.

---

## Amounts — `ASSUMPTION`

Registry keys: `amount_distribution`, `amount_weights`.

| Price point (paise) | 29900 | 49900 | 79900 | 99900 | 149900 | 249900 | 499900 |
|---|---|---|---|---|---|---|---|
| Weight | 0.22 | 0.26 | 0.18 | 0.14 | 0.10 | 0.06 | 0.04 |

Plausible Indian SaaS subscription price points; no sourced distribution exists. Weights sum
to 1.00 and are checked by a test, because `random.choices` normalises silently — the same
mechanism that let the reason mix reach 1.1000 without failing.

**This affects money-weighted figures only, never recovery rates.** Rate and rupee figures
are reported side by side precisely so a reader can see which claims depend on this table and
which do not.

---

## Baseline — `MEASURED`

Registry key: `baseline_recovery_rate`.

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
