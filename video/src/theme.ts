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
  title: 66,
  heading: 46,
  body: 34,
  small: 27,
  terminal: 24,
  label: 22,
};

export const MARGIN = 72;

/** Seconds -> frames, so scene lengths read as durations in the source. */
export const secs = (s: number) => Math.round(s * FPS);
