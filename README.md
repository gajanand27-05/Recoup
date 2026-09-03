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

### On the `eval()` in the policy engine

Rules live in [`rules.yaml`](src/recoup/policy/rules.yaml) as predicates, and the engine
evaluates them. That is a deliberate choice, and the reasoning is here rather than buried
because `eval` is a word people react to before they read.

**Injection is not the threat model.** `rules.yaml` is repo-controlled and version-tracked;
anyone able to edit it can edit `engine.py` just as easily. There is no untrusted input path
into it — webhook bodies, LLM output and customer replies are all *data the rules run against*,
never rules themselves.

**What the engine does instead of trusting:**

- **An explicit namespace**, no builtins. `CONTEXT_SCHEMA` declares exactly which names a
  predicate may reference and, for each, exactly which attributes.
- **Validation at load, not first use.** Every predicate is checked against that contract when
  the engine is constructed. A typo in a rarely-hit rule fails at startup rather than halfway
  through a 2,000-subscription batch — or never.
- **A narrow grammar.** Comprehensions, chained attributes, and calls to anything but the
  declared helpers are refused.

**The alternative is worse, and we shipped it first.** The original engine hard-coded every
rule in Python beside a YAML file carrying predicate strings that nothing evaluated — so
`rules.yaml` looked like the enforcement surface while being decorative, and a rule could have
been edited or plainly wrong with no effect on behaviour. That defect is written up as **A-019**.
It also concealed a live one: `RBI-005` read `not msg.is_coercive` while nothing defined
`is_coercive`, so half that rule could never be false. Load-time name checking turns that class
of mistake into a startup error.

**3. Every number is recomputable from this repository.**
The ledger is append-only and hash-chained. `recoup verify-ledger` recomputes the chain and
prints the head hash.

## Verifying the freeze

The simulator was frozen before the agent was written. To check that rather than take it:

```bash
python tasks.py verify-sim     # recomputes sha256(simulator/), fails on any drift
git log --all --diff-filter=A --format='%h %ai' -- src/recoup/agent/ | tail -1
git log --all --diff-filter=A --format='%h %ai' -- PARAMS.lock.json  | tail -1
```

`--diff-filter=A` finds the commit that *added* each path, so it is not fooled by a file that
was created and later deleted. CI runs both checks on every push.

**The `sim-freeze-v1` tag is not the evidence.** An annotated tag's date is written by whoever
creates it and can be set to anything. What is load-bearing is the pushed commit history and
GitHub's own record of when those commits arrived and when CI ran on them. The tag is a
convenient label pointing at evidence that stands without it.

If a defect is found in the simulator after freezing, the tag is **not** moved — a
`sim-freeze-v2` is cut and both are kept, with the reason in
[`INCIDENTS.md`](INCIDENTS.md). This has already happened once *before* the tag was public
(INC-004: the hash was computed with a platform-dependent file ordering and was not
reproducible off Windows).

## Results

**Two findings. The second matters more than the first.**

Full detail, including every miss and every not-run item, is in
[`EVAL_RESULTS.md`](EVAL_RESULTS.md). Nothing here is projected or carried over from an earlier
configuration.

---

## Finding 1 — the agent did not beat the control

**The experiment did not detect a difference.**

| arm | recovered | n | rate |
|---|---|---|---|
| control | 310 | 1,035 | 29.95% |
| treatment | 303 | 965 | 31.40% |

**+1.45 pp · 95% CI [−2.59, +5.49] pp · p = 0.4830 · achieved MDE 6.24 pp · N = 2,000**

The interval spans zero. An observed +1.45 pp sits well inside what this run, powered for
6.24 pp at the arms it actually produced, can resolve.

**That is not the same as there being no difference.** This run rules out effects *larger* than
the MDE at the stated power. It does **not** rule out a real effect smaller than 6.24 pp, and it
does **not** establish that the two arms are equivalent — a null result and a demonstration of
equivalence are different claims, and only the first was run.

> **Two MDEs, and they are different quantities (A-029).** **6.24 pp** is the **achieved** MDE — the harmonic-mean effective N of the arms that actually ran, 1,035 / 965, effective N 998. **6.23 pp** is the **pre-registered** MDE at the designed 1,000 per arm, pinned in [`EXPERIMENT.md`](EXPERIMENT.md)'s power table before the run. The result of *this run* is quoted against the achieved figure; claims about what the *design* could ever detect are quoted against the pre-registered one, which is also the smaller of the two and therefore the weaker version of that claim.

### The control was made strong on purpose, before any number existed

A null against a strawman is worthless. A null against a competent process is a finding, and
this distinction is the reason the result is worth reporting at all.

The control arm was strengthened during Task 18 (A-021), **before any lift figure existed**:
the schedule was front-loaded from `(0, 2, 5, 9, 14)` to `(0, 2, 4, 7, 10)` after measuring it
against the frozen curve, it stops the moment the customer pays, and it uses the full five
attempts `STOP-001` permits. Two *tighter* schedules scored higher still and are recorded in
`baseline/fixed.py` rather than quietly discarded.

So the finding is: **an LLM agent choosing template, channel and timing did not beat a
well-tuned fixed schedule on this cohort.** That is a useful thing to know, and it says the
decisioning is not where the value is.

### The ordering is the evidence

Each of these was fixed *before* the thing it constrains, and the git history is what makes
that checkable rather than assertable:

| when | what |
|---|---|
| at 12 of 2,000 subscriptions | all three outcome rules pre-registered ([`EXPERIMENT.md`](EXPERIMENT.md) Addendum 3) — including that a control win would be reported as the result |
| before the batch | schema violations declared to pull lift **toward null** (Addendum 2) |
| before the figure existed | fallback counter verified live by five forced schema violations, each driving it 0% → 100% (A-027) |
| after the run | fallback rate **0.0%** across 3,637 model decisions |

Because the violation rate is zero, the toward-null bias is **nil, not small** — so the one
excuse that could have argued the true effect is larger than measured is unavailable, and it
was made unavailable in advance rather than after seeing the number.

### One sign flip, reported as pre-registered

`attempt_decay_compounding` at the low end of its declared range takes the lift to **−0.10 pp**.
[`EXPERIMENT.md`](EXPERIMENT.md) pre-registers a sign flip as falsifying, so it is stated rather
than narrowed away.

And the second half, which travels with it: **this is a −0.10 pp swing on a measurement whose
interval already spans zero**, so it is consistent with the headline finding rather than the
reversal of a real effect. Both sentences are true; neither is reported without the other.

`self_recovery_rate_soft` and `self_recovery_rate_hard` are **declared NOT SWEPT**. They define
`would_self_recover` and therefore the denominator of the whole claim, and a sweep that replays
fixed actions cannot reach scenario generation. Reporting them as swept-and-flat would be the
most reassuring possible result in the emptiest possible place.

### Provenance

Pinned to **three commits** — `487fc45` (1–1153), `7dbe2c0` (1154–1354), `25ad9c4` (1355–2000)
— across two resumes forced by a provider account quota and one network timeout, at three
concurrency settings. The pins and settings were **demonstrated** output-equivalent, not
argued: the batch was re-run under each and every ledger row compared identical. See
`runs/batch-2000.provenance.json`.

---

## Finding 2 — the experiment could not have detected what it was testing

**This is the more useful of the two findings, and it outranks the lift figure.**

Computed over the frozen response curve, the difference between the most aggressive schedule
`STOP-001` permits and the one the control uses is **1.53 pp**:

| schedule | cumulative recovery |
|---|---|
| `(0,1,2,3,4)` | 0.3536 ← the most aggressive five attempts allow |
| `(0,1,3,5,7)` | 0.3513 |
| **`(0,2,4,7,10)`** | **0.3383** ← the control |
| `(0,2,5,9,14)` | 0.3176 ← the original plan's schedule |
| `(0,3,7,15,30)` | 0.2897 |

**The pre-registered minimum detectable effect is 6.23 pp, at the designed 1,000 per arm.
The largest difference any legitimate schedule change can produce is 1.53 pp — roughly a
quarter of it.**

So the experiment was **structurally incapable of detecting the intervention it was built to
test**. A null was close to the *expected* outcome for any agent operating on schedule, channel
or timing, whatever the agent did, because the frozen curve does not make those levers worth
6 percentage points. Detecting a 1.53 pp effect at this power needs roughly **33,000
subscriptions**, seventeen times the N that ran.

### The ordering, which is not flattering

The build's discipline is that sequence is evidence. Here the sequence is unflattering, and
softening it would be exactly the compression this project spends its guards preventing:

**This was computable from the frozen curve on Day 2.** `SCHEDULE_ALTERNATIVES` and their
cumulative recoveries have been in `baseline/fixed.py` since Task 8 — the 1.53 pp gap is
arithmetic over numbers that were already committed, and `mde_at_n()` has been able to return
the pre-registered 6.23 pp for just as long. Nothing compared the two.

It was found on Day 6, **after** the harness, the control arm, the pre-registration, three
restarts of the batch and 2,000 subscriptions of provider quota — and then only as a side
effect of asking whether the A/A could detect anything at all.

The power analysis fixed the MDE from a baseline rate and a target power. It never asked the
other question: *what effect sizes can this intervention actually produce?* That question was
available at every point and was not asked.

### It was not acted on, deliberately

A reader will wonder why the answer is not simply to re-run at 33,000. Because
[`EXPERIMENT.md`](EXPERIMENT.md) Addendum 3 fixed the stopping rule at 12 of 2,000
subscriptions, before any figure existed: **this batch is the run**, and re-running at a larger
N after seeing a null is optional stopping however good the reason sounds. The power
calculation above was done *after* the result and is reported as a finding, not used as grounds
to go again.

### What it means for the null

It does not excuse the null, and it does not convert it into anything else. The agent still did
not beat the control. What it says is that this experiment could not have distinguished a good
agent from a bad one at this lever, so the null is weak evidence about the agent and strong
evidence about the design.

If the work continued, the next step is not a bigger N. It is an intervention with more room in
it than schedule choice.

---

---

## Supporting measurements

### Reply understanding — measured

**Run 2026-09-02 · `gpt-oss:120b` via Ollama Cloud, digest `d98fe6ba01e6` · 60 hand-labelled
fixtures, labelled before any model was called.**

| | value | 95% CI (Wilson) |
|---|---|---|
| Intent accuracy | **94.2%** (49/52) | **[84.4%, 98.0%]** |
| Promise-date extraction | 90.9% (10/11) | [62.3%, 98.4%] |

**Read the interval before quoting the point estimate.** The intent CI's lower bound is
**84.4%, below the 85% pre-registered bar**. The point estimate clears it; the interval does
not exclude values that fail it. The honest sentence is *"94.2%, and the data are consistent
with true accuracy anywhere from 84% to 98%"*.

The denominator is 52, not 60: `deterministic_opt_out()` runs upstream of the model, so 8
opt-out fixtures never reach it. An accuracy over all 60 would pool the matcher's correctness
with the model's and report the total as the model's.

### A/A instrument validation — measured

**Run 2026-08-31 · seed 20260831 · 1,000 per arm · pre-registered and pushed before the run.**
Difference **−0.30 pp**, 95% CI [−4.67, +4.07], **p = 0.8932**.

**The A/A test passed**, and the next sentence is not optional: a pass rules out harness bias
larger than about **6.23 percentage points**. It does **not** establish an unbiased harness. An
effect smaller than 6.23 pp could sit in the harness unseen.

### Full-pipeline A/A — measured

**Both arms on the identical control policy through the real path**, seed 20260904 from outside
the powered N. Difference −2.71 pp, 95% CI [−6.69, +1.30], p = 0.1848.

**The A/A test passed**, with the scope that must travel with it: a pass rules out harness bias
larger than about **6.23 percentage points**. It does **not** establish an unbiased harness.

It was shown capable of detecting something first — a known effect was injected and the
pipeline reported it (+4.21 pp, p = 0.0451). A test that passes by finding nothing is worthless
until it has been shown able to find something.

### Not run, and declared

The `llm`-marked half of the adversarial eval, which needs live model calls the provider's
quota is better spent elsewhere. It has its own heading in
[`EVAL_RESULTS.md`](EVAL_RESULTS.md) rather than being omitted.

---

## Limitations

Stated here rather than left to be found. This section grows as the build does; nothing is
removed from it.

### The figure is pinned to the code that produced it, which is not always HEAD

A long-running batch executes the version it loaded. This run spans two commits and three
concurrency settings across two resumes, recorded in `runs/batch-2000.provenance.json` with the
subscription range each produced — the figure is pinned to a *set*, not a commit.

The pins were shown to be output-equivalent rather than argued to be: the batch was run under
both, and under concurrency 1, 2 and 4, and every ledger row compared identical. Draws are keyed
on `(seed, subscription_id, attempt_no, day_offset)` rather than taken from a shared RNG, which
is what makes concurrency-invariance demonstrable instead of hopeful.

### The ledger cannot reconstruct its own run

A hash-chained append-only ledger that cannot replay itself is a boundary of the instrument,
not a bug in the replay. Stated because a reader who understands ledgers will ask.

Of the five fields a faithful replay needs, **two are stored and three are not**:

| field | where it comes from |
|---|---|
| `channel`, `attempt_no` | the row's payload ✅ |
| `day_offset` | **derived** from the row's `ts`, relative to that subscription's first row |
| `is_hard_decline` | **regenerated** from `(n, seed)` — a property of the scenario, not of the action |
| `amount_paise` | **not stored anywhere** |
| `reason_code`, `send_at` | not stored |

Every derivation is a place a reconstruction can silently diverge, and one did: the sensitivity
sweep's first run defaulted `day_offset` and `is_hard_decline`, produced a baseline of −2.02 pp
against a measured +1.45, and rendered **five false "SIGN FLIPPED" verdicts** — headed for the
falsification section. It was caught only because the baseline disagreed with the known figure.
`verify_replay_reproduces()` now refuses to sweep a replay that does not reproduce the run
(INC-013).

**The blast radius, unsoftened.** `scripts/report.py` built every view with one flat
`amount_paise` of 49,900 across all 2,000 subscriptions. The cohort's real amounts run from
₹299 to ₹4,999 — **correct for 506 subscriptions and wrong for 1,494.**

The headline recovery rate counts *subscriptions*, so **+1.45 pp never depended on it.** The
recovered-amount difference and its bootstrap interval did, and were wrong. They were not
rendered in the report — **which is luck, not a control.** Nothing prevented them from being
rendered; they simply were not. Amounts are now regenerated per subscription, and any that
cannot be are counted and reported with the consequence stated.

Not fixed by widening the payload: the batch has run, and adding fields now would change the
hash chain's contents for a completed run already pinned to three commits.

### The schema is requested, not enforced

Ollama accepts a JSON schema and ignores it — both `format=` and
`response_format: {strict: true}` return HTTP 200 and invent their own keys (A-024, measured
across three routes). The schema is therefore spelled into the prompt, and output is validated
by Pydantic at the boundary, so a non-conforming answer is a caught failure rather than a
silently accepted one. What is gone is constrained decoding.

### The counterfactual is assumed, not measured

The headline claim is a *difference* between two arms, so it rests on what would have happened
with no intervention at all. In the simulator that is `would_self_recover`, generated from two
numbers:

| Parameter | Value | Swept over |
|---|---|---|
| `self_recovery_rate_soft` | 0.18 | 0.05 – 0.35 |
| `self_recovery_rate_hard` | 0.03 | 0.00 – 0.10 |

**Neither is sourced.** Nothing published gives a post-halt, no-outreach recovery rate — post-halt
means the processor has stopped retrying, so any recovery is the customer acting unprompted, and
merchants who do nothing at that point do not publish what happens next.

These two numbers set the denominator of the entire lift claim. They are swept first and widest
in the sensitivity analysis, and the analysis reports the **sign** of the effect across the full
range, not only its magnitude: if there is any corner of the declared ranges where the treatment
arm loses, that is reported rather than excluded.

### Most of the simulator's parameters are assumptions

Of 17 frozen generative parameters: **4 MEASURED** (published figure, stated population, URL),
**10 ASSUMPTION** (not sourced, each with a declared sweep range), 3 derived or definitional.

That ratio is on the face of [`SIMULATOR_FREEZE.md`](SIMULATOR_FREEZE.md), and every parameter's
class, source and reasoning — including figures that were located and **deliberately rejected** —
is in [`src/recoup/simulator/PARAMS.md`](src/recoup/simulator/PARAMS.md).

### Two sources may measure the same decay twice

The day-offset recovery curve (Baremetrics, by day within a dunning sequence) and the per-attempt
decay (Churnkey, by email index) are not independent axes: position in a sequence and days elapsed
are the same underlying thing measured two ways. Multiplying both almost certainly double-counts
some of the decline, and how much is unrecoverable from published aggregates.

We did not resolve this. We made it a swept parameter (`attempt_decay_compounding`) and defaulted
it to **full compounding**, which lowers modelled recovery in both arms and therefore shrinks our
own reported effect. The claim is "we chose the parameterisation that reduces our result", not
"we established the correct one".

### One webhook payload shape is inferred, not observed

The real-transport demo issues genuine Razorpay test-mode Payment Links against genuine
subscriptions. It cannot produce a genuine `subscription.halted`, because test mode will not
simulate a *failed* subscription charge — so that one event is **replayed from a fixture built
by reading the documentation**.

That matters because the ingest's id-extraction is then validated against our reading of the
docs rather than against a payload Razorpay actually sent. It is stated rather than engineered
around, and narrowed as far as it can be: the other three shapes *are* obtainable in test mode
and are captured on first sight.

<!-- BEGIN generated: capture-manifest -->
| Event | Payload shape |
|---|---|
| `subscription.halted` | INFERRED (not capturable in test mode — see D-033 branch (b)) |
| `subscription.activated` | INFERRED (capturable — run the demo against test mode) |
| `subscription.charged` | INFERRED (capturable — run the demo against test mode) |
| `payment_link.paid` | INFERRED (capturable — run the demo against test mode) |
<!-- END generated: capture-manifest -->

This table is **generated from the filesystem**, not maintained by hand, and is compared
against a fresh render by `tests/test_capture.py`. It cannot go stale: the moment a payload is
captured, that test fails until the table is regenerated.

### The subscription context is synthetic

A read-only API probe on 2026-09-01 found `plans` and `subscriptions` returning **401** while
`payment_links`, `orders`, `customers`, `payments`, `items`, `invoices` and `settlements` all
returned **200** — on the same client, with the same credentials. That is endpoint-level
authorisation, not a credential fault: the Subscriptions product is not enabled on the
account.

A Payment Link is a standalone object and needs no Subscription, so the links the demo issues
are genuinely real. The subscription they represent is not.

**The claim the demo supports, stated exactly:** *Payment Links were really issued against
Razorpay — real auth, real `reference_id` collision behaviour, real error envelopes. The
subscription they represent, and the failure sequence that triggers outreach, were both
replayed.*

That is weaker than "the loop ran end-to-end against Razorpay", and it is not rounded up.
See `DECISION.md` A-020.

### Simulated outcomes are never pooled with real ones

Every ledger row carries `transport` — `real` or `sim` — and the two are never combined in a
reported figure. The label is declared by the caller and defaults to `sim`, because the two
mistakes are not symmetric: calling a fixture `real` manufactures evidence that the system ran
against a live processor, while calling a real event `sim` only forfeits a claim we were entitled
to make.

#### The two transports cannot know the same things

That is a policy, and a reader is entitled to ask whether we would have kept it if the numbers
had come out differently. So here is the same conclusion from a direction that does not depend
on trusting us.

**`SimTransport.execute()` returns whether the payment was recovered. `RealTransport.execute()`
always returns `recovered=False`** — and not because nothing was recovered.

The simulator can answer, because it *is* the customer: it draws from the frozen response curve
and that draw is the outcome. The real transport cannot answer, because a created Payment Link
says nothing whatever about whether anyone paid it. That arrives later, asynchronously, as a
`payment_link.paid` webhook — possibly days later, possibly never.

So the two arms' data sources differ in **what they are capable of knowing**, not merely in how
they were implemented:

| | Outcome available | When | From |
|---|---|---|---|
| `sim` | yes | at execution | the draw itself |
| `real` | no | later, or never | an inbound webhook |

Pooling them would average a synchronous oracle with an asynchronous observation, and the two
are not the same measurement even when they agree. A real transport that returned an outcome
synchronously would be *inventing* one — which is why the type returns `False` rather than
`None` or a guess.

This is an argument about the data, not about our intentions. It holds whether or not you
believe the paragraph above it.

## Status

Built for the 5 September 2026 deadline. What is measured is under **Results** with its
intervals; what is not measured says so under its own heading, in this file and in
[`EVAL_RESULTS.md`](EVAL_RESULTS.md).

The incident log is [`INCIDENTS.md`](INCIDENTS.md) and it is not a formality: eleven entries,
written when each defect was found rather than reconstructed afterwards. Three of them
(INC-007, INC-009, and the fallback-series windowing) are one class — an artifact that is
computed, rendered and entirely plausible whose *label does not describe what it contains*.
Each would have produced a confident wrong number rather than an error.

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
