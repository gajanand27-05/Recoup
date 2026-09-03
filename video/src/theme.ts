/**
 * Type scale derived from the LONGEST protected sentence, not chosen first.
 *
 * STEP 2a: never trim a sentence to fit a frame. The protected sentences are
 * the ones the compression guard exists to keep whole, so the frame is sized to
 * them rather than the other way round. If a sentence does not fit, the fix is a
 * smaller size or a longer hold — never fewer words.
 *
 * The longest is the intent-accuracy sentence at ~250 characters. At 1920px wide
 * with 72px side margins, 34px monospace gives ~92 characters per line, so ~250
 * characters is three lines. Everything is sized against that.
 *
 * RAISED 2026-09-03, after watching the render. Every card was using roughly the
 * top 45% of a 1080p frame and the bottom half was empty — legible fullscreen,
 * small in a laptop browser tab, which is where this will actually be judged.
 * The scale is up ~18%, chosen against the tallest cards rather than the
 * emptiest: Findings (which gained the non-equivalence clause), DayTwo and
 * Limitations are what set the ceiling.
 *
 * `SIZE.terminal` deliberately did NOT move. The veto scene's captured output is
 * 21 wrapped lines, and its box is now sized by its own text — at 24px it needs
 * 812px of a ~792px budget once the larger heading is allowed for. Growing the
 * prose and holding the monospace is the trade the content forces; a smaller
 * face there is not a compression, because no sentence is being shortened.
 */
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const FPS = 30;

export const COLORS = {
  bg: "#0d1117",
  panel: "#161b22",
  text: "#e6edf3",
  dim: "#8b949e",
  rule: "#30363d",
  good: "#3fb950",
  warn: "#d29922",
  bad: "#f85149",
  accent: "#58a6ff",
};

export const FONT = {
  mono: "'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace",
  sans: "'Segoe UI', 'Inter', system-ui, sans-serif",
};

/** Sized so the longest protected sentence fits whole on one card. */
export const SIZE = {
  title: 78,
  heading: 54,
  body: 40,
  small: 32,
  terminal: 24,
  label: 26,
};

export const MARGIN = 72;

/** Seconds -> frames, so scene lengths read as durations in the source. */
export const secs = (s: number) => Math.round(s * FPS);
