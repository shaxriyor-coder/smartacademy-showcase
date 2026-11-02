import { bandOf, type Band, type Rate } from "@/lib/analytics-core";
import ScoreBar from "@/components/ScoreBar";

// Mastery label beside every meter: an icon and a word, so the band never
// rests on the bar's colour.
const BAND: Record<Band, { icon: string; label: string; className: string }> = {
  strong: { icon: "✓", label: "Yaxshi", className: "bg-emerald-400/10 text-emerald-300" },
  developing: { icon: "◐", label: "O'rtacha", className: "bg-amber-400/10 text-amber-200" },
  weak: { icon: "!", label: "Zaif", className: "bg-red-400/10 text-red-300" },
};

export type RateRow = Rate & {
  key: string;
  name: string;
  hint?: string;
  children?: (Rate & { key: string; name: string })[];
};

function RateLine({ row, compact = false }: { row: Rate & { name: string; hint?: string }; compact?: boolean }) {
  const band = BAND[bandOf(row.percentage)];
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <span className={`min-w-0 ${compact ? "text-xs" : "text-sm"}`}>
          {row.name}
          {row.hint && <span className="ml-1.5 text-xs text-muted">{row.hint}</span>}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {!compact && (
            <span className={`tag ${band.className}`}>
              <span aria-hidden>{band.icon}</span>
              {band.label}
            </span>
          )}
          <span className="text-sm font-semibold tabular-nums text-ivory">{row.percentage}%</span>
          <span className="w-12 text-right text-xs tabular-nums text-muted">
            {row.correct}/{row.total}
          </span>
        </span>
      </div>
      <ScoreBar
        percentage={row.percentage}
        label={`${row.name}: ${row.percentage}% (${row.correct}/${row.total}) — ${band.label}`}
      />
    </div>
  );
}

export default function RateList({ rows, empty }: { rows: RateRow[]; empty: string }) {
  if (rows.length === 0) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={row.key}>
          <RateLine row={row} />
          {row.children && row.children.length > 0 && (
            <details className="mt-1.5">
              <summary className="cursor-pointer text-xs text-muted hover:text-ivory">
                Ichki mavzular ({row.children.length})
              </summary>
              <ul className="mt-2 space-y-2 border-l border-white/10 pl-3">
                {row.children.map((child) => (
                  <li key={child.key}>
                    <RateLine row={child} compact />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}
