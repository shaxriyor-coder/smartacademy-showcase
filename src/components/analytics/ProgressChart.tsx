"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { CHROME, SERIES } from "./colors";

// Score over time: the main series is the accent, the optional class average
// is context (the "emphasis" form; colours in ./colors). With no context values
// it is a single series and needs no legend. Callers put a table view under it.
const ACCENT = SERIES.accent;
const CONTEXT = SERIES.context;
const SURFACE = CHROME.surface;
const GRID = CHROME.grid;
const AXIS_TEXT = CHROME.axisText;

const HEIGHT = 220;
const PAD = { top: 16, right: 48, bottom: 28, left: 40 };
const Y_TICKS = [0, 25, 50, 75, 100];

export type ProgressPoint = {
  id: string;
  title: string;
  subjectName: string;
  // Formatted on the server (formatTashkentDay / formatTashkentDate): formatting
  // here would differ between Node's and the browser's ICU and break hydration.
  dayLabel: string;
  dateLabel: string;
  percentage: number;
  classAverage: number | null;
};

export default function ProgressChart({
  seriesLabel,
  points,
  noun = "test",
}: {
  seriesLabel: string;
  points: ProgressPoint[];
  // What one point is, for the screen-reader summary ("test", "hafta").
  noun?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.max(280, Math.round(entry.contentRect.width)));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const last = points.length - 1;
  const x = (i: number) => PAD.left + (last === 0 ? plotW / 2 : (i / last) * plotW);
  const y = (v: number) => PAD.top + (1 - v / 100) * plotH;

  const studentPath = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.percentage)}`).join(" ");
  // The class average may be missing for some tests (too few classmates checked):
  // the line breaks there rather than bridging the gap.
  const classPath = points
    .map((p, i) => {
      if (p.classAverage == null) return "";
      const joined = i > 0 && points[i - 1].classAverage != null;
      return `${joined ? "L" : "M"}${x(i)},${y(p.classAverage)}`;
    })
    .join(" ")
    .trim();
  const hasClass = points.some((p) => p.classAverage != null);

  // X labels: as many as fit (~80px each), the first and the last, and one
  // label per day when several tests fall on the same day.
  const every = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 80))));
  const xTicks = points
    .map((_, i) => i)
    .filter((i) => i % every === 0 || i === last)
    .filter((i, idx, all) => i === last || all[idx + 1] === undefined || all[idx + 1] - i >= every / 2 + 0.5)
    .filter((i, idx, all) => idx === 0 || points[i].dayLabel !== points[all[idx - 1]].dayLabel);

  function nearest(clientX: number) {
    const rect = wrap.current?.getBoundingClientRect();
    if (!rect) return null;
    const px = clientX - rect.left;
    let best = 0;
    points.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    });
    return best;
  }

  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    const current = active ?? last;
    const next =
      e.key === "ArrowLeft" ? Math.max(0, current - 1)
      : e.key === "ArrowRight" ? Math.min(last, current + 1)
      : e.key === "Home" ? 0
      : e.key === "End" ? last
      : null;
    if (next == null) return;
    e.preventDefault();
    setActive(next);
  }

  const point = active == null ? null : points[active];
  const tooltipLeft = active == null ? 0 : Math.min(Math.max(x(active) - 90, 0), width - 180);

  return (
    <div>
      {hasClass && (
        <ul className="mb-3 flex flex-wrap gap-4 text-xs text-muted" aria-label="Chiziqlar">
          <li className="flex items-center gap-2">
            <span className="h-0.5 w-5 rounded-full" style={{ backgroundColor: ACCENT }} />
            {seriesLabel}
          </li>
          <li className="flex items-center gap-2">
            <span className="h-0.5 w-5 rounded-full" style={{ backgroundColor: CONTEXT }} />
            Sinf o&apos;rtachasi
          </li>
        </ul>
      )}

      <div ref={wrap} className="relative w-full">
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          tabIndex={0}
          aria-label={`Natija dinamikasi: ${points.length} ta ${noun}, oxirgisi ${points[last].percentage}%. Chap/o'ng tugmalari bilan yuring.`}
          className="block rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-gold/60"
          onPointerMove={(e: PointerEvent<SVGSVGElement>) => setActive(nearest(e.clientX))}
          onPointerLeave={() => setActive(null)}
          onFocus={() => setActive(last)}
          onBlur={() => setActive(null)}
          onKeyDown={onKey}
        >
          {Y_TICKS.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={PAD.left + plotW} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill={AXIS_TEXT} style={{ fontVariantNumeric: "tabular-nums" }}>
                {t}%
              </text>
            </g>
          ))}
          {xTicks.map((i) => (
            <text key={i} x={x(i)} y={HEIGHT - 8} textAnchor="middle" fontSize={11} fill={AXIS_TEXT} style={{ fontVariantNumeric: "tabular-nums" }}>
              {points[i].dayLabel}
            </text>
          ))}

          {active != null && (
            <line x1={x(active)} x2={x(active)} y1={PAD.top} y2={PAD.top + plotH} stroke="rgba(255,255,255,0.35)" strokeWidth={1} />
          )}

          {classPath && (
            <path d={classPath} fill="none" stroke={CONTEXT} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          )}
          {/* A class average with no neighbour has no segment to draw — mark it. */}
          {points.map((p, i) =>
            p.classAverage != null &&
            points[i - 1]?.classAverage == null &&
            points[i + 1]?.classAverage == null ? (
              <circle key={`class-${p.id}`} cx={x(i)} cy={y(p.classAverage)} r={4} fill={CONTEXT} stroke={SURFACE} strokeWidth={2} />
            ) : null,
          )}
          <path d={studentPath} fill="none" stroke={ACCENT} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {point?.classAverage != null && active != null && (
            <circle cx={x(active)} cy={y(point.classAverage)} r={4} fill={CONTEXT} stroke={SURFACE} strokeWidth={2} />
          )}
          {points.map((p, i) => (
            <circle key={p.id} cx={x(i)} cy={y(p.percentage)} r={i === active ? 5.5 : 4} fill={ACCENT} stroke={SURFACE} strokeWidth={2} />
          ))}

          {/* Direct label on the one value the story is about: the latest. */}
          <text x={x(last) + 10} y={y(points[last].percentage) + 4} fontSize={12} fontWeight={600} fill="#f4f2ff">
            {points[last].percentage}%
          </text>
        </svg>

        {point && active != null && (
          <div
            className="pointer-events-none absolute top-2 z-10 w-[180px] rounded-lg border border-white/15 bg-[#140f33]/95 px-3 py-2 text-xs shadow-xl"
            style={{ left: tooltipLeft }}
            role="status"
          >
            <p className="text-muted">{point.dateLabel}</p>
            <p className="mb-1.5 truncate text-ivory" title={point.title}>
              {point.title}
            </p>
            <p className="flex items-center gap-2">
              <span className="h-0.5 w-3 rounded-full" style={{ backgroundColor: ACCENT }} />
              <b className="text-sm text-ivory">{point.percentage}%</b>
              <span className="truncate text-muted">{seriesLabel}</span>
            </p>
            {point.classAverage != null && (
              <p className="flex items-center gap-2">
                <span className="h-0.5 w-3 rounded-full" style={{ backgroundColor: CONTEXT }} />
                <b className="text-sm text-ivory">{point.classAverage}%</b>
                <span className="text-muted">sinf o&apos;rtachasi</span>
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
