import { SERIES } from "./colors";

// A count beside its bar, for comparing sizes within one column (questions per
// subject). One series, one colour; the number next to it is the readable
// value, so the bar itself is hidden from screen readers.
export default function CountBar({ value, max }: { value: number; max: number }) {
  const width = max > 0 ? Math.max((value / max) * 100, value > 0 ? 2 : 0) : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 text-right text-sm font-semibold tabular-nums text-ivory">{value}</span>
      <div className="h-2 flex-1 rounded-[3px] bg-white/[0.06]" aria-hidden>
        <div className="h-full rounded-[3px]" style={{ width: `${width}%`, backgroundColor: SERIES.context }} />
      </div>
    </div>
  );
}
