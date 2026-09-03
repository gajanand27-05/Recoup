import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT, MARGIN, SIZE } from "./theme";

/** A gentle fade so nothing pops. Never a transition that hides text mid-read. */
export const FadeIn: React.FC<{ delay?: number; children: React.ReactNode }> = ({
  delay = 0,
  children,
}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame - delay, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <div style={{ opacity }}>{children}</div>;
};

export const Slide: React.FC<{
  kicker?: string;
  title?: string;
  children: React.ReactNode;
}> = ({ kicker, title, children }) => (
  <div
    style={{
      flex: 1,
      backgroundColor: COLORS.bg,
      color: COLORS.text,
      fontFamily: FONT.sans,
      padding: MARGIN,
      display: "flex",
      flexDirection: "column",
      gap: 24,
    }}
  >
    {kicker ? (
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: SIZE.label,
          color: COLORS.accent,
          letterSpacing: 2,
          textTransform: "uppercase",
        }}
      >
        {kicker}
      </div>
    ) : null}
    {title ? (
      <div style={{ fontSize: SIZE.heading, fontWeight: 700, lineHeight: 1.15 }}>
        {title}
      </div>
    ) : null}
    {children}
  </div>
);

/**
 * A protected sentence. Rendered whole, never split across cards.
 *
 * `lines` are laid out together in one block so both halves of a paired sentence
 * are simultaneously visible — a sentence split across two frames that are never
 * on screen at once is a compressed sentence (STEP 2a).
 */
export const Sentence: React.FC<{
  lines: string[];
  size?: number;
  color?: string;
  delay?: number;
}> = ({ lines, size = SIZE.body, color = COLORS.text, delay = 0 }) => (
  <FadeIn delay={delay}>
    <div style={{ fontSize: size, lineHeight: 1.45, color, maxWidth: 1720 }}>
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </div>
  </FadeIn>
);

export const Stat: React.FC<{
  label: string;
  value: string;
  color?: string;
}> = ({ label, value, color = COLORS.text }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
    <div style={{ fontFamily: FONT.mono, fontSize: SIZE.label, color: COLORS.dim }}>
      {label}
    </div>
    <div style={{ fontFamily: FONT.mono, fontSize: SIZE.heading, color }}>{value}</div>
  </div>
);

export const Row: React.FC<{ children: React.ReactNode; gap?: number }> = ({
  children,
  gap = 64,
}) => <div style={{ display: "flex", gap, alignItems: "flex-start" }}>{children}</div>;

/**
 * Captured terminal output, typed on. The text comes from a file written by
 * actually running the command — captured output may be rendered, mocked output
 * may not.
 *
 * THE BOX IS SIZED BY THE TEXT, NOT BY A NUMBER SOMEONE CHOSE.
 * It used to take a `height` and clip with `overflow: hidden`, and three of the
 * four call sites were under-sized: the veto scene lost its last five lines —
 * the replanned message, `allowed: True`, the rules that fired and the ledger
 * write, which is the entire payoff of the scene — and both verify boxes cut a
 * line through the middle of its glyphs. A frame that renders 16 of 21 lines is
 * an artifact whose label ("the captured output") does not describe its contents.
 *
 * So height is no longer an input. The full text is laid out invisibly to
 * reserve exactly the space it needs, and the revealed prefix is painted over
 * it — which also stops the box growing under the typewriter. Clipping is now
 * structurally impossible rather than tuned away.
 */
const TERMINAL_PAD = 28;

export const Terminal: React.FC<{
  text: string;
  startFrame?: number;
  charsPerFrame?: number;
  fontSize?: number;
}> = ({ text, startFrame = 0, charsPerFrame = 6, fontSize = SIZE.terminal }) => {
  const frame = useCurrentFrame();
  const shown = Math.max(0, Math.floor((frame - startFrame) * charsPerFrame));
  const type = {
    fontFamily: FONT.mono,
    fontSize,
    lineHeight: 1.5,
    whiteSpace: "pre-wrap" as const,
  };
  return (
    <div
      style={{
        backgroundColor: "#010409",
        border: `1px solid ${COLORS.rule}`,
        borderRadius: 10,
        padding: TERMINAL_PAD,
        color: COLORS.text,
        position: "relative",
      }}
    >
      {/* reserves the full height so nothing reflows and nothing is cut */}
      <div style={{ ...type, visibility: "hidden" }}>{text}</div>
      <div
        style={{
          ...type,
          position: "absolute",
          top: TERMINAL_PAD,
          left: TERMINAL_PAD,
          right: TERMINAL_PAD,
        }}
      >
        {text.slice(0, shown)}
      </div>
    </div>
  );
};

export const Bullets: React.FC<{ items: string[]; size?: number }> = ({
  items,
  size = SIZE.small,
}) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    {items.map((item, i) => (
      <FadeIn key={i} delay={i * 4}>
        <div style={{ display: "flex", gap: 16, fontSize: size, lineHeight: 1.4 }}>
          <div style={{ color: COLORS.accent }}>—</div>
          <div style={{ maxWidth: 1660 }}>{item}</div>
        </div>
      </FadeIn>
    ))}
  </div>
);
