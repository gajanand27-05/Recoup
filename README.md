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

Full detail, including every miss and every not-run item, is in
[`EVAL_RESULTS.md`](EVAL_RESULTS.md). Nothing here is projected or carried over from an earlier
configuration.

### Recovery lift — the headline

**Run 2026-09-03 · N = 2,000 as pre-registered · `sim` transport.**

| arm | recovered | n | rate |
|---|---|---|---|
| control | 310 | 1,035 | 29.95% |
| treatment | 303 | 965 | 31.40% |

**Difference +1.45 pp · 95% CI [−2.59, +5.49] pp · p = 0.4830 · MDE 6.24 pp**

**The interval spans zero. This run does not distinguish the agent from the control.**

That is the result, reported as pre-registered in [`EXPERIMENT.md`](EXPERIMENT.md) Addendum 3 —
written at 12 of 2,000 subscriptions, before any number existed, precisely so this outcome
could not be described afterwards as "trending positive". An effect of +1.45 pp is well inside
what a 6.24 pp MDE can resolve. The experiment did not detect a difference; that is not the
same as there being none.

**The usual excuse is unavailable here.** Addendum 2 fixed in advance that schema violations
pull measured lift toward null. The fallback rate was **0.0%** across 3,637 model decisions, so
that bias is nil rather than small — and the counter was verified to still be counting *before*
this figure existed (A-027).

**One sign flip, reported.** `attempt_decay_compounding` at the low end of its declared range
takes the lift to −0.10 pp. `EXPERIMENT.md` pre-registers a flip as falsifying, so it is stated
rather than narrowed away — in context, a −0.10 pp swing against a measurement whose interval
already spans zero is consistent with the headline finding rather than a reversal of a real one.

**The figure is pinned to three commits**, not one: the run spans `487fc45`, `7dbe2c0` and
`25ad9c4` across two resumes forced by a provider quota and one network timeout. The pins and
the three concurrency settings were *demonstrated* output-equivalent — the batch was re-run
under each and every ledger row compared identical. See `runs/batch-2000.provenance.json`.

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

### Not run, and declared

The `llm`-marked half of the adversarial eval, and the full-pipeline A/A. Both have their own
headings in [`EVAL_RESULTS.md`](EVAL_RESULTS.md) rather than being omitted.

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
