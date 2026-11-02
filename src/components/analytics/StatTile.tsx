// Stat tile: label · value · optional signed delta · note. The delta carries an
// arrow and a sign, so its direction never rests on colour alone.
export default function StatTile({
  label,
  value,
  delta,
  note,
}: {
  label: string;
  value: string;
  delta?: { value: number; suffix?: string; upIsGood?: boolean; caption: string } | null;
  note?: string;
}) {
  const upIsGood = delta?.upIsGood ?? true;
  const good = delta ? (upIsGood ? delta.value > 0 : delta.value < 0) : false;

  return (
    <div className="glass-panel min-w-0 p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ivory">{value}</p>
      {delta &&
        (delta.value === 0 ? (
          <p className="mt-1 text-xs text-muted">= {delta.caption}</p>
        ) : (
          <p className={`mt-1 text-xs font-semibold ${good ? "text-emerald-300" : "text-red-300"}`}>
            <span aria-hidden>{delta.value > 0 ? "▲" : "▼"}</span> {delta.value > 0 ? "+" : "−"}
            {Math.abs(delta.value)}
            {delta.suffix ?? ""} <span className="font-normal text-muted">{delta.caption}</span>
          </p>
        ))}
      {note && (
        <p className="mt-1 truncate text-xs text-muted" title={note}>
          {note}
        </p>
      )}
    </div>
  );
}
