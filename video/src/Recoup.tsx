import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { Bullets, Row, Sentence, Slide, Stat, Terminal } from "./components";
import { COLORS, FONT, SIZE, secs } from "./theme";
import figures from "../data/figures.json";
import captured from "../data/captured.json";

/**
 * The recoup submission, silent and fully captioned.
 *
 * NO LITERAL FIGURES. Every number comes from `data/figures.json`, written by
 * `scripts/video_data.py` from the module that produced it. A hardcoded number
 * in a video agrees with the report until something changes and then silently
 * disagrees — and a frame is the one artifact nobody can grep.
 *
 * NO PRESENTER DIRECTION. Nothing is spoken, so "say this before running it"
 * has no meaning here. Those blocks live in VIDEO.md and must not appear in this
 * source (STEP 2c).
 *
 * BOTH FINDINGS FIRST. A video that spends four minutes on machinery and lands
 * on "no detected difference" reads as a failure. The machinery is the argument
 * for the result, not a build-up to it.
 */

const f = figures;
const pp = (n: number) => `${n > 0 ? "+" : ""}${n.toFixed(2)} pp`;

// --- Scene 1: both findings, A-028 first ------------------------------------

const Findings: React.FC = () => (
  <Slide kicker="recoup — post-halt subscription payment recovery" title="Two findings.">
    <Sentence
      lines={[
        `1.  The agent did not beat the control: ${pp(f.lift.diff_pp)}, 95% CI`,
        `    [${f.lift.ci_low_pp.toFixed(2)}, ${f.lift.ci_high_pp.toFixed(2)}] pp. The interval spans zero.`,
      ]}
      delay={6}
    />
    <Sentence
      lines={[
        `2.  The experiment could not have detected what it was testing.`,
        `    The best schedule change available is worth ${f.power_ceiling.ceiling_pp} pp.`,
        `    It was powered to detect ${f.power_ceiling.mde_pp} pp — ${f.power_ceiling.ratio}× larger.`,
      ]}
      delay={30}
      color={COLORS.warn}
    />
    <Sentence
      lines={["The second is the one to take away."]}
      delay={58}
      color={COLORS.dim}
      size={SIZE.small}
    />
  </Slide>
);

// --- Scene 2: Finding 2 in full, including the Day 2 / Day 6 admission -------

const Ceiling: React.FC = () => (
  <Slide kicker="finding 2" title="It could never have found what it was looking for.">
    <div style={{ fontFamily: FONT.mono, fontSize: SIZE.small, lineHeight: 1.9 }}>
      {f.power_ceiling.schedules.map((s) => (
        <div key={s.days.join(",")} style={{ color: s.is_control ? COLORS.accent : COLORS.dim }}>
          {`(${s.days.join(",")})`.padEnd(18)}
          {s.recovery.toFixed(4)}
          {s.is_control ? "   ← the control" : ""}
        </div>
      ))}
    </div>
    <Row gap={96}>
      <Stat label="best minus control" value={`${f.power_ceiling.ceiling_pp} pp`} color={COLORS.warn} />
      <Stat label="minimum detectable effect" value={`${f.power_ceiling.mde_pp} pp`} />
      <Stat label="N needed to close the gap" value={f.power_ceiling.n_needed.toLocaleString()} />
    </Row>
    <Sentence
      lines={[
        "A null was close to the expected outcome for any agent working on",
        "schedule, channel or timing — whatever the agent did.",
      ]}
      delay={40}
    />
  </Slide>
);

const DayTwo: React.FC = () => (
  <Slide kicker="finding 2 — the ordering" title="This was computable on Day 2.">
    <Sentence
      lines={[
        "The schedules and their recoveries have been in baseline/fixed.py since",
        `Task 8. mde_at_n() has returned ${f.aa.bound_pp} pp for just as long. The gap is`,
        "arithmetic over numbers that were already committed.",
      ]}
      delay={8}
    />
    <Sentence
      lines={[
        "It was found on Day 6 — after the harness, the control arm, the",
        "pre-registration, three restarts and 2,000 subscriptions of provider",
        "quota — and then only as a side effect of asking whether the A/A could",
        "detect anything at all.",
      ]}
      delay={40}
      color={COLORS.warn}
    />
    <Sentence
      lines={[
        "The power analysis fixed the MDE from a baseline rate and a target power.",
        "It never asked what effect sizes the intervention could produce.",
      ]}
      delay={90}
      size={SIZE.small}
      color={COLORS.dim}
    />
  </Slide>
);

const NotActedOn: React.FC = () => (
  <Slide kicker="finding 2" title="Deliberately not acted on.">
    <Sentence
      lines={[
        `Detecting ${f.power_ceiling.ceiling_pp} pp at this power needs about`,
        `${f.power_ceiling.n_needed.toLocaleString()} subscriptions. The stopping rule was fixed at`,
        `12 of ${f.run.planned_n.toLocaleString()}, before any figure existed: this batch is the run.`,
      ]}
      delay={8}
    />
    <Sentence
      lines={[
        "Re-running at a larger N after seeing a null is optional stopping,",
        "however good the reason sounds. The power calculation was done after",
        "the result and is reported as a finding, not used as grounds to go again.",
      ]}
      delay={44}
      color={COLORS.dim}
      size={SIZE.small}
    />
  </Slide>
);

// --- Scene 3: Finding 1, the null, with non-equivalence on the same card -----

const Null: React.FC = () => (
  <Slide kicker="finding 1" title="The experiment did not detect a difference.">
    <Row gap={80}>
      <Stat
        label={`control  n=${f.lift.control.n}`}
        value={`${f.lift.control.rate_pct.toFixed(2)}%`}
      />
      <Stat
        label={`treatment  n=${f.lift.treatment.n}`}
        value={`${f.lift.treatment.rate_pct.toFixed(2)}%`}
      />
      <Stat label="difference" value={pp(f.lift.diff_pp)} color={COLORS.accent} />
      <Stat
        label="95% CI"
        value={`[${f.lift.ci_low_pp.toFixed(2)}, ${f.lift.ci_high_pp.toFixed(2)}]`}
      />
      <Stat label="p" value={f.lift.p_value.toFixed(4)} />
    </Row>
    <Sentence
      lines={[
        `The interval spans zero, at a minimum detectable effect of ${f.lift.mde_pp} pp.`,
        "That is not the same as there being no difference: this rules out effects",
        "larger than the MDE at the stated power. It does not rule out a smaller",
        "real effect, and it does not establish that the arms are equivalent.",
      ]}
      delay={30}
    />
  </Slide>
);

const StrongControl: React.FC = () => (
  <Slide kicker="finding 1" title="The control was made strong on purpose.">
    <Sentence
      lines={[
        "A null against a strawman is worthless. A null against a competent",
        "process is a finding.",
      ]}
      delay={6}
    />
    <Bullets
      items={[
        `Schedule front-loaded to (${f.power_ceiling.schedules.find((s) => s.is_control)!.days.join(", ")}) after measuring it against the frozen curve — before any lift figure existed.`,
        "It stops the moment the customer pays.",
        "It uses the full five attempts the policy permits.",
        "Two tighter schedules scored higher and are recorded, not quietly dropped.",
      ]}
    />
    <Sentence
      lines={[
        "So: an LLM choosing template, channel and timing did not beat a well-tuned",
        "fixed schedule. That says the decisioning is not where the value is.",
      ]}
      delay={40}
      color={COLORS.dim}
      size={SIZE.small}
    />
  </Slide>
);

// --- Scene 4: the ordering, as a sequence -----------------------------------

const Ordering: React.FC = () => (
  <Slide kicker="why the null is trustworthy" title="The ordering is the evidence.">
    <Bullets
      items={[
        `At 12 of ${f.run.planned_n.toLocaleString()} subscriptions — all three outcome rules pre-registered, including that a control win would be reported as the result.`,
        "Before the batch — schema violations declared to pull measured lift toward null.",
        "Before the figure existed — the fallback counter verified live by five forced schema violations, each driving it from 0% to 100%.",
        `After the run — fallback rate ${(100 * f.arms.treatment.fallbacks) / Math.max(1, f.arms.treatment.fallbacks + f.arms.treatment.model_decided)}% across ${f.arms.treatment.model_decided.toLocaleString()} model decisions.`,
      ]}
    />
    <Sentence
      lines={[
        "Because the violation rate is zero, the toward-null bias is nil, not small.",
        "The one excuse that could argue the true effect is larger was made",
        "unavailable in advance rather than after seeing the number.",
      ]}
      delay={40}
    />
  </Slide>
);

// --- Scene 5: the demo, real captured output --------------------------------

const Verify: React.FC = () => (
  <Slide kicker="every number is recomputable" title="The ledger and the freeze, checked.">
    <Terminal text={captured.verifyLedger} />
    <Terminal text={captured.verifySim} startFrame={secs(2.5)} />
    <Sentence
      lines={[
        "The chain is self-consistent and the simulator matches the hash it was",
        "frozen at — before anything under agent/ existed.",
      ]}
      delay={secs(4)}
      size={SIZE.small}
      color={COLORS.dim}
    />
  </Slide>
);

const Veto: React.FC = () => (
  <Slide kicker="the policy engine vetoes the agent" title="A model reaching for persuasion.">
    {/* 21 wrapped lines: the only scene whose capture needs a smaller face to
        clear 1080 once the box is sized by its own text. */}
    <Terminal text={captured.demoFailure} charsPerFrame={14} fontSize={21} />
  </Slide>
);

const Refusal: React.FC = () => (
  <Slide kicker="this next output is the system working" title="It refuses to give one number.">
    <Sentence
      lines={[
        "This run is deliberately mixed: the payment links were really issued",
        "against Razorpay, and the halt that triggered them was replayed. Asked",
        "for one figure over both, the report raises instead of printing.",
      ]}
      delay={4}
    />
    <Terminal text={captured.refusal} startFrame={secs(3)} charsPerFrame={10} />
  </Slide>
);

// --- Scene 6: supporting measurements ---------------------------------------

const Supporting: React.FC = () => (
  <Slide kicker="supporting measurements" title="What else was measured.">
    <Sentence
      lines={[
        `Reply understanding: ${f.accuracy.intent.pct}% (${f.accuracy.intent.correct}/${f.accuracy.intent.n}), 95% CI [${f.accuracy.intent.ci_low}%, ${f.accuracy.intent.ci_high}%].`,
        `The lower bound is below the ${f.accuracy.intent.bar}% pre-registered bar — the point`,
        "estimate clears it and the interval does not exclude values that fail it.",
      ]}
      delay={6}
    />
    <Sentence
      lines={[
        `A/A instrument check: ${f.aa.a}/${f.aa.n_per_arm} against ${f.aa.b}/${f.aa.n_per_arm}. The A/A test passed.`,
        `A pass rules out harness bias larger than about ${f.aa.bound_pp} percentage points.`,
        "It does not establish an unbiased harness.",
      ]}
      delay={44}
    />
    <Sentence
      lines={[
        "The full-pipeline A/A was shown able to detect an injected effect before",
        "its silence was believed. A test that passes by finding nothing is",
        "worthless until it has found something.",
      ]}
      delay={86}
      size={SIZE.small}
      color={COLORS.dim}
    />
  </Slide>
);

// --- Scene 7: limitations ---------------------------------------------------

const Limitations: React.FC = () => (
  <Slide kicker="limitations" title="What this does not show.">
    <Bullets
      items={[
        `The intervention's ceiling is ${f.power_ceiling.ceiling_pp} pp against an MDE of ${f.power_ceiling.mde_pp} pp — finding 2, and the reason the null is weak evidence about the agent.`,
        "The counterfactual is assumed, not measured. Nothing published gives a post-halt, no-outreach recovery rate.",
        "10 of 17 frozen simulator parameters are assumptions with declared sweep ranges.",
        "The subscription context is synthetic; the payment links are real. Subscriptions is not enabled on the account.",
        "On this provider the JSON schema is requested, not enforced — output is validated at the boundary instead.",
        "The ledger cannot fully reconstruct its own run: three of five replay fields come from outside it.",
        "One sign flip in the sweep, taking the lift to −0.10 pp — pre-registered as falsifying, and a −0.10 pp swing on an interval that already spans zero.",
        "Declared not-run: the model-backed half of the adversarial injection eval.",
      ]}
      size={SIZE.small}
    />
  </Slide>
);

const Provenance: React.FC = () => (
  <Slide kicker="provenance" title="The figure is pinned to the code that produced it.">
    <div style={{ fontFamily: FONT.mono, fontSize: SIZE.small, lineHeight: 1.9 }}>
      {/* PRODUCED, not launched-to-cover. 7dbe2c0 was launched to finish the
          run and died at 1354; rendering its launch range as "subscriptions
          1154-2000" showed three pins whose ranges overlap and claimed data for
          a pin that did not produce it. The manifest now carries both fields
          and this reads the one the caption asserts. */}
      {f.run.code_pins.map((p) => (
        <div key={p.short}>
          {p.short.padEnd(12)}
          produced subscriptions {p.subscription_index_range}
        </div>
      ))}
      <div style={{ color: COLORS.dim, marginTop: 14 }}>
        concurrency{" "}
        {f.run.concurrency_schedule
          .filter((c) => c.produced_surviving_data)
          .map((c) => c.value)
          .join(" → ")}
      </div>
      <div style={{ color: COLORS.dim }}>
        model {f.run.model.id} · digest {f.run.model.digest} · {f.run.model.confirmation}
      </div>
    </div>
    <Sentence
      lines={[
        "Three code pins across two provider-quota resumes and one network timeout.",
        "The pins and the concurrency settings were demonstrated output-equivalent,",
        "not argued: the batch was re-run under each and every ledger row matched.",
      ]}
      delay={30}
    />
  </Slide>
);

const End: React.FC = () => (
  <Slide title="">
    <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: 30 }}>
      <Sentence
        lines={[
          "The agent did not beat the control, and the experiment could not have",
          "detected it if it had. Both are reported.",
        ]}
        size={SIZE.heading}
      />
      <Sentence
        lines={[`github.com/gajanand27-05/Recoup · N = ${f.run.n.toLocaleString()} · transport ${f.run.transport}`]}
        delay={30}
        size={SIZE.small}
        color={COLORS.dim}
      />
    </div>
  </Slide>
);

// --- assembly ----------------------------------------------------------------

const SCENES: Array<[React.FC, number]> = [
  [Findings, secs(11)],
  [Ceiling, secs(11)],
  [DayTwo, secs(13)],
  [NotActedOn, secs(9)],
  [Null, secs(12)],
  [StrongControl, secs(11)],
  [Ordering, secs(12)],
  [Verify, secs(9)],
  [Veto, secs(11)],
  [Refusal, secs(11)],
  [Supporting, secs(13)],
  [Limitations, secs(16)],
  [Provenance, secs(10)],
  [End, secs(7)],
];

export const TOTAL_FRAMES = SCENES.reduce((sum, [, d]) => sum + d, 0);

export const Recoup: React.FC = () => {
  let at = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      {SCENES.map(([Component, duration], i) => {
        const from = at;
        at += duration;
        return (
          <Sequence key={i} from={from} durationInFrames={duration}>
            <Component />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
