# Measured results

Every number here was produced by a run that actually happened, on the date stated, with the
model named. Nothing on this page is projected, extrapolated, or carried over from an earlier
configuration.

Where a run has **not** happened, it says so rather than being omitted.

---

## Reply understanding — Task 19

**Run 2026-09-02 · `gpt-oss:120b` via Ollama Cloud · 60 hand-labelled fixtures**

The fixtures were labelled by hand **before any model was called**, and the labels are pinned
by `test_the_fixture_is_well_formed_and_labelled_before_any_model_ran`.

| | value | 95% CI (Wilson) |
|---|---|---|
| **Intent accuracy** | **94.2%** (49/52) | **[84.4%, 98.0%]** |
| **Promise-date extraction** | **90.9%** (10/11) | **[62.3%, 98.4%]** |
| Deterministic opt-out matcher | 100% (8/8) | — |

Pre-registered bars: intent ≥ 85%, date ≥ 80%. Both point estimates clear them.

### Read the intervals before quoting the point estimates

**The intent CI's lower bound is 84.4%, which is below the 85% bar.** The point estimate
clears it; the interval does not exclude values that fail it. With n = 52 that is what the
evidence supports, and the honest statement is *"94.2%, and the data are consistent with true
accuracy anywhere from 84% to 98%"* — not "94% accurate".

**The date-extraction interval is [62.3%, 98.4%] on n = 11.** That is close to uninformative.
It is reported because it was measured and pre-registered, not because 11 items establish
anything. Do not put this number in a headline.

### Why 52 and not 60

`deterministic_opt_out()` runs **upstream of the model** — a regulatory hard stop must not
depend on a model's reading comprehension, and `test_every_labelled_opt_out_is_caught_without_the_model`
pins that every labelled opt-out is reachable without a key.

So 8 fixtures never reach the model. An accuracy figure over all 60 would pool the opt-out
matcher's results with the model's and report the total as the model's — the same category
error as pooling `sim` and `real` transports. `require_real_model()` refused the pooled
figure, which is how this was found: the first version of the eval computed over all 60 and
was rejected by its own provenance gate.

### Every miss

| reply | labelled | model said |
|---|---|---|
| `I never signed up for this` | `dispute` | `wrong_number` |
| `maine kabhi subscribe nahi kiya` | `dispute` | `wrong_number` |
| `cancel kar do, main nahi chahta` | `dispute` | `opt_out` |
| `give me till friday` (from Tue 2026-09-01) | `2026-09-04` | `2026-09-03` |

Two of the three intent misses are the same case in two languages: *"I never signed up for
this"* read as `wrong_number` rather than `dispute`. That reading is defensible — someone who
never signed up may well be the wrong person — and the fixture label is the stricter one. It
is left as a miss rather than relabelled: adjusting ground truth after seeing the prediction
is how an eval stops measuring anything.

The date miss is a genuine model error. 2026-09-04 **is** a Friday; the model answered
Thursday. The label is correct and stands.

### What this does not measure

Whether the model is right when nobody labelled the answer. The fixtures are 60 replies
chosen to cover six intents and to include Hinglish; they are not a sample of any real
customer population, because no real customer replies exist to sample from.

### A caveat specific to this provider

Ollama Cloud **accepts a JSON schema and ignores it** (A-024) — both `format=` and
`response_format: {strict: true}` return HTTP 200 and invent their own keys. The schema is
therefore spelled into the prompt, and conformance rests on instruction-following rather than
constrained decoding. Output is still validated by Pydantic at the boundary, so a
non-conforming answer is a caught failure and never a silently accepted one.

Across this run every response parsed and validated — the schema-violation rate was **0/52**.
That is a property of this model on this task and should not be assumed to hold for another.

---

## Recovery lift — Task 22

**NOT RUN.** The batch runner is not built. There is no lift figure, no confidence interval,
and no cost-per-recovery number.

This section exists so that its absence is stated rather than inferred from a missing heading.

---

## A/A instrument validation — Task 13

**Run 2026-08-31 · seed 20260831 · 1,000 per arm · pre-registered and pushed before the run.**

| | value |
|---|---|
| arm A | 513/1000 |
| arm B | 510/1000 |
| difference | −0.30 pp |
| 95% CI | [−4.67, +4.07] pp |
| p-value | 0.8932 |

Both arms ran identical policy. If the harness manufactured lift, it would appear here.

**Scope, which must travel with the result:** a pass rules out harness bias larger than about
**6.23 percentage points**. It does **not** establish an unbiased harness.

Run **once**. The result is pinned in `tests/test_aa.py` and is not re-run —
re-running until a p-value pleases is optional stopping.
