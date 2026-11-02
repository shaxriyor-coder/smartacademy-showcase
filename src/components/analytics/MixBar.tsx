import type { ReactNode } from "react";

export type MixSegment = {
  key: string;
  label: string;
  icon: string;
  color: string;
  value: number;
};

// Part-to-whole bar: segments separated by 2px surface gaps, and a legend with
// icon + label + count + share — the legend is the readable form, the bar only
// shows proportions. Callers order segments so that only validated neighbours
// touch (see colors.ts).
export default function MixBar({ segments, note }: { segments: MixSegment[]; note?: ReactNode }) {
  const total = segments.reduce((n, s) => n + s.value, 0);
  const share = (n: number) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div>
      {/* flex-grow keeps the gaps inside the full width */}
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-[4px] bg-white/[0.04]" aria-hidden>
        {segments
          .filter((s) => s.value > 0)
          .map((s) => (
            <div
              key={s.key}
              title={`${s.label}: ${s.value} (${share(s.value)}%)`}
              style={{ flexGrow: s.value, flexBasis: 0, backgroundColor: s.color }}
            />
          ))}
      </div>
      <ul className="mt-3 grid gap-1.5 text-sm sm:grid-cols-3">
        {segments.map((s) => (
          <li key={s.key} className="flex items-baseline gap-2">
            <span className="h-2.5 w-2.5 shrink-0 translate-y-px rounded-[2px]" style={{ backgroundColor: s.color }} />
            <span className="text-muted">
              <span aria-hidden>{s.icon}</span> {s.label}
            </span>
            <span className="font-semibold tabular-nums text-ivory">{s.value}</span>
            <span className="text-xs tabular-nums text-muted">{share(s.value)}%</span>
          </li>
        ))}
      </ul>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}
