# SOURCES.md — where every number came from, and what was thrown away

This file is the index. **The numbers themselves live with the code that reads them**, so there
is one producer per figure and nothing here can drift out of step with a value in use:

| What | Where it lives |
|---|---|
| Every simulator parameter — value, class, source URL, population | [`src/recoup/simulator/PARAMS.md`](src/recoup/simulator/PARAMS.md) |
| Every policy rule — `class`, `source_url`, `retrieved` | [`src/recoup/policy/rules.yaml`](src/recoup/policy/rules.yaml) |
| The frozen parameter set and its hash | [`PARAMS.lock.json`](PARAMS.lock.json), [`SIMULATOR_FREEZE.md`](SIMULATOR_FREEZE.md) |
| What the run measured, and what it did not | [`EVAL_RESULTS.md`](EVAL_RESULTS.md), [`README.md`](README.md) |

Every parameter carries a **class** — `MEASURED`, `DERIVED`, `DEFINITIONAL` or `ASSUMPTION` —
because a number whose status is implicit gets read as stronger than it is. **10 of the 17
frozen parameters are `ASSUMPTION`**: not sourced, declared as such, and swept in the
sensitivity analysis.

---

## Rejected figures — this section is a deliverable, not an appendix

Research into this domain surfaced figures that are near-universal in vendor content and do
not survive being traced. They are listed **because their absence is a decision rather than an
oversight**, and because a figure this repo does not use is evidence about how the ones it does
use were chosen.

### Traceable fabrications

| Rejected figure | Why |
|---|---|
| **WhatsApp 98% open rate / 45–60% CTR** | Traces to MessengerPeople vendor copy. No methodology, sample or window ever published. Structurally impossible — read receipts systematically undercount. No Meta-published 98% figure exists |
| **Cart email 5.2% / 4.5% / 2.6% by delay bucket** | The canonical timing table. Its origin page was deleted roughly seven years ago, it is absent from the publisher's current content, and no methodology ever existed |
| **"3-email sequence = $24.9M vs $3.8M"** | Zero occurrences in the cited vendor's own pages. A mutation of a different statistic — revenue by email *position* — from a deleted page |
| **"SMS payment links: 45% response vs email 6%"** | Attributed to Razorpay by third parties; absent from every Razorpay page fetched directly |
| **Cashfree "15% higher success rate"** | The identical sentence appears across six or more syndication sites with no primary publication behind any of them |

### Figures rejected as unsound rather than fabricated

| Rejected figure | Why |
|---|---|
| "SMS opens 90%+ / 98% vs email 20–30%" | Uncited, and contradicts the same vendor's own measured 41.29% email open rate |
| UPI "99.2% success rate" | An unsound inversion of NPCI's *technical* decline rate; excludes business declines. Razorpay's own 90–95% is the defensible figure |
| Razorpay Optimizer uplift | Published as 5%, ~10%, and 10–15% across three of their own pages; the docs make no claim at all |
| Barilliance 18.64% vs Klaviyo 3.33% | Not comparable. Barilliance's denominator is *opened* emails, not sends. Never averaged, never placed side by side |
| SMS effectiveness = 0.071 (Churnkey share ratio) | Share of recoveries is not per-message effectiveness, and send volumes are unpublished. Used **only** as a sweep endpoint, never as a value |

Also noted, and the reason two otherwise-usable sources are used narrowly: Baremetrics
contradicts itself on pre-dunning open rate (a claimed "73%+" against its own measured 47.41%);
Razorpay publishes UPI success at both 90–95% and 99.2% one month apart; Klaviyo's and
Omnisend's cart figures use different denominators and are not reconcilable.

---

## Folklore corrected — three beliefs that were about to be encoded as law

These are not rejected *numbers*. They are rules this project nearly implemented because they
are repeated everywhere, and each is wrong in a way that would have changed the code.

**1. The permitted messaging window is 10:00–21:00 IST, not 09:00–21:00.**
TCCCPR Schedule-II §3(1) sets the default-OFF bands as 00:00–06:00, 06:00–08:00, **08:00–10:00**
and 21:00–24:00. The 09:00 figure appears in many blogs and is simply incorrect — an hour that
does not exist in the regulation.

**2. That window does not apply to this traffic at all.** Service-Implicit and Transactional
messages are exempt — all-day, DND-irrespective. Applying 10:00–21:00 to SI dunning traffic
would have been a self-inflicted, non-legal constraint. Encoded in `rules.yaml` where it
belongs: on the classification, not on the clock.

**3. There is no RBI retry cap.** The E-Mandate Framework (RBI/DPSS/2026-27/396) was searched
directly and contains no retry or re-presentment provision. What *does* bind is indirect: a
T-24h pre-debit notice per debit, which structurally allows about one retry per day per
mandate. The UPI Autopay cap that does exist — 1 original + 3 retries — is an NPCI rule
carried by secondary sources, and is classed `INDUSTRY_PRACTICE` for exactly that reason.

**4. RBI's 08:00–19:00 recovery-agent contact window does not bind a merchant.**
RBI/2022-23/108 is addressed to Commercial Banks, RRBs, Co-op Banks, NBFCs, ARCs, AIFIs and
their outsourced recovery agents. A SaaS merchant chasing a failed subscription charge is not a
regulated entity under it. Encoding it as `HARD_LAW` would have been the single most likely
error in a dunning compliance document, so it ships as `BEST_PRACTICE_BY_ANALOGY` (`RBI-005`),
applied to voice contact only.

---

## What no one publishes, and what the design therefore assumes

Stated here rather than left as a silence, because the largest assumption in this project sits
in this list:

- **A post-halt, no-outreach recovery rate.** Nothing published gives one. It is the
  counterfactual the entire lift claim is measured against, and it is an `ASSUMPTION`
  (`self_recovery_rate_soft`, `self_recovery_rate_hard`), declared **NOT SWEPT** — not as a
  principle but as a limit of reach: the sweep replays the run's own actions, and these two act
  at scenario generation, which a replay holding actions fixed cannot touch. Reporting them as
  swept-and-flat would claim a robustness nobody tested.
- **Payment-link conversion rate** — no provider publishes one, anywhere.
- **Any controlled WhatsApp-vs-SMS-vs-email test for payment reminders.**
- **The lift from offering UPI after a card decline in India** — the exact question this
  system is about, and there is no published isolation of it.
- **SMS/DLT per-message cost** at merchant scale, which is why the cost basis in the report is
  given two ways rather than one.

## The strongest causal evidence that does exist

Recorded because it shaped the message templates, and because it argues against the thing this
project was built to test:

- **Cadena & Schoar, NBER WP 17020 (2011)**, RCT with a Ugandan microlender: a monthly SMS
  reminder is worth **+7–9 pp** on on-time payment — about as effective as a 25% interest-rate
  cut.
- **Karlan, Morten & Zinman, NBER WP 17952 (2012)**, RCT across two microlenders: reminders
  robustly work **only when they carry the loan officer's name**. **Framing and timing did
  not matter.**

The second finding is uncomfortable for an agent whose job is choosing template, channel and
timing — and it points the same way [Finding 1](README.md#finding-1--the-agent-did-not-beat-the-control)
eventually did.
