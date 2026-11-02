import { STRONG_FROM, WEAK_BELOW } from "@/lib/analytics-core";
import { STATUS } from "@/components/analytics/colors";

// A meter: one ratio against 100. The fill carries severity in the reserved
// status colours (good / warning / critical — each checked at >= 3:1 on the
// app's panel surface with the dataviz validator); the track is a faint wash
// of the same hue, so the state reads across the whole bar. The percentage is
// always printed beside it, so colour never carries the value alone.
const FILL = STATUS;

export default function ScoreBar({ percentage, label }: { percentage: number; label?: string }) {
  const width = Math.max(0, Math.min(100, percentage));
  const color =
    percentage >= STRONG_FROM ? FILL.good : percentage >= WEAK_BELOW ? FILL.warning : FILL.critical;
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(width)}
      aria-label={label}
      title={label}
      className="h-2 w-full overflow-hidden rounded-full"
      style={{ backgroundColor: `${color}2e` }}
    >
      <div className="h-full rounded-full" style={{ width: `${width}%`, backgroundColor: color }} />
    </div>
  );
}
