// Chart colours for the app's dark panel surface (glass panel over ink,
// ≈ #1a163b), all checked with the dataviz validator against that surface.

// Reserved status steps: each >= 3:1 on the surface. Only ever shown with an
// icon and a label. Where they touch in a part-to-whole bar, neighbours must
// be good↔warning or warning↔critical (ΔE 27.6 normal / 11.3 CVD); warning
// next to "serious" orange falls below the normal-vision floor, so that step
// isn't used in bars.
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  critical: "#d03b3b",
} as const;

// Emphasis form: one accent series, one context series (ΔE 21.9 normal /
// 21.6 CVD, both >= 3:1).
export const SERIES = {
  accent: "#c98500",
  context: "#a79fd6",
} as const;

export const CHROME = {
  surface: "#1a163b",
  grid: "rgba(255,255,255,0.08)",
  axisText: "#a79fd6", // muted ink, 7.0:1
} as const;
