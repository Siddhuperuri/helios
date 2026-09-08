'use client';

/**
 * Chart primitives.
 *
 * These are hand-built rather than taken from a charting library, for two reasons. The
 * visual one: library defaults carry their own idiom — rounded tooltips, drop shadows,
 * default palettes — and a chart that looks bolted on undermines the impression that the
 * interface was designed as one thing. The functional one: accessibility here means every
 * chart also exposes its data as a table, which no library does by default.
 *
 * Every chart is responsive by measurement rather than by viewBox scaling, so stroke
 * widths and type stay at their intended size instead of being stretched.
 */

import {
  ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

export const SERIES = {
  observed: '#8FA8BF',
  predicted: '#F2A93B',
  interval: 'rgba(242,169,59,0.16)',
  intervalStroke: 'rgba(242,169,59,0.34)',
  clearSky: 'rgba(255,255,255,0.18)',
  grid: 'rgba(255,255,255,0.055)',
  axis: 'rgba(255,255,255,0.16)',
  cyan: '#4EC9C0',
  positive: '#46A56A',
  warning: '#D99A2B',
  critical: '#D9534F',
} as const;

export interface Margin {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const DEFAULT_MARGIN: Margin = { top: 14, right: 16, bottom: 28, left: 52 };

/** Measure a container so charts render at true device resolution. */
export function useMeasure<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

export function linearScale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  const scale = (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
  scale.invert = (p: number) => d0 + ((p - r0) / (r1 - r0)) * span;
  scale.domain = domain;
  scale.range = range;
  return scale;
}

/** "Nice" axis ticks at 1/2/5 × 10ⁿ steps. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const span = max - min;
  const rawStep = span / Math.max(1, count);
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const normalised = rawStep / magnitude;
  const step =
    (normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1) * magnitude;

  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= max + step * 1e-6; v += step) {
    ticks.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return ticks;
}

export function extent(values: number[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return [0, 1];
  return [lo, hi];
}

export function padDomain(
  [lo, hi]: [number, number],
  padFraction = 0.06,
  { zeroBase = false }: { zeroBase?: boolean } = {},
): [number, number] {
  if (zeroBase) return [Math.min(0, lo), hi + (hi - Math.min(0, lo)) * padFraction || 1];
  const span = hi - lo || Math.abs(hi) || 1;
  return [lo - span * padFraction, hi + span * padFraction];
}

/* ------------------------------------------------------------------ axes */

export function AxisLeft({
  scale,
  ticks,
  width,
  format,
  label,
}: {
  scale: ReturnType<typeof linearScale>;
  ticks: number[];
  width: number;
  format: (v: number) => string;
  label?: string;
}) {
  return (
    <g aria-hidden="true">
      {ticks.map((t) => {
        const y = scale(t);
        return (
          <g key={t} transform={`translate(0,${y})`}>
            <line x1={0} x2={width} stroke={SERIES.grid} strokeWidth={1} shapeRendering="crispEdges" />
            <text
              x={-8}
              y={0}
              dy="0.32em"
              textAnchor="end"
              className="fill-ink-3 font-mono"
              style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums' }}
            >
              {format(t)}
            </text>
          </g>
        );
      })}
      {label ? (
        <text
          transform={`translate(${-42},${scale.range[0] / 2}) rotate(-90)`}
          textAnchor="middle"
          className="fill-ink-4 font-mono uppercase"
          style={{ fontSize: 9, letterSpacing: '0.1em' }}
        >
          {label}
        </text>
      ) : null}
    </g>
  );
}

export function AxisBottom({
  scale,
  ticks,
  height,
  format,
}: {
  scale: ReturnType<typeof linearScale>;
  ticks: number[];
  height: number;
  format: (v: number) => string;
}) {
  return (
    <g transform={`translate(0,${height})`} aria-hidden="true">
      <line x1={0} x2={scale.range[1]} stroke={SERIES.axis} strokeWidth={1} shapeRendering="crispEdges" />
      {ticks.map((t, i) => (
        <g key={`${t}-${i}`} transform={`translate(${scale(t)},0)`}>
          <line y1={0} y2={4} stroke={SERIES.axis} strokeWidth={1} shapeRendering="crispEdges" />
          <text
            y={16}
            textAnchor="middle"
            className="fill-ink-3 font-mono"
            style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums' }}
          >
            {format(t)}
          </text>
        </g>
      ))}
    </g>
  );
}

/* --------------------------------------------------------------- legend */

export function Legend({
  items,
}: {
  items: { label: string; color: string; kind?: 'line' | 'area' | 'dot' | 'dash' }[];
}) {
  return (
    <ul className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-2 text-2xs text-ink-2">
          <span aria-hidden="true" className="inline-flex h-3 w-4 items-center justify-center">
            {item.kind === 'area' ? (
              <span
                className="block h-2.5 w-4"
                style={{ background: item.color, border: `1px solid ${SERIES.intervalStroke}` }}
              />
            ) : item.kind === 'dot' ? (
              <span
                className="block h-1.5 w-1.5 rounded-full"
                style={{ background: item.color }}
              />
            ) : (
              <span
                className="block h-0.5 w-4"
                style={{
                  background: item.kind === 'dash' ? 'none' : item.color,
                  borderTop: item.kind === 'dash' ? `1.5px dashed ${item.color}` : undefined,
                }}
              />
            )}
          </span>
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------- tooltip */

export function ChartTooltip({
  x,
  y,
  containerWidth,
  children,
}: {
  x: number;
  y: number;
  containerWidth: number;
  children: ReactNode;
}) {
  // Flip the tooltip to the other side of the cursor near the right edge so it never
  // gets clipped by the container.
  const flip = x > containerWidth - 190;
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none absolute z-20 min-w-[9rem] border border-line-strong
        bg-surface-2/95 px-2.5 py-2 text-2xs shadow-lg backdrop-blur-sm"
      style={{
        left: flip ? x - 12 : x + 12,
        top: Math.max(4, y - 12),
        transform: flip ? 'translateX(-100%)' : undefined,
      }}
    >
      {children}
    </div>
  );
}

export function TooltipRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-px">
      <span className="flex items-center gap-1.5 text-ink-3">
        {color ? (
          <span className="h-0.5 w-2.5" style={{ background: color }} aria-hidden="true" />
        ) : null}
        {label}
      </span>
      <span className="num text-ink-1">{value}</span>
    </div>
  );
}

/* ------------------------------------------------- accessible data table */

/**
 * Screen-reader alternative for a chart.
 *
 * Visually hidden but present in the accessibility tree, so the underlying numbers are
 * available to anyone who cannot use the graphic. A chart with an `aria-label` alone
 * conveys that a chart exists but none of its content.
 */
export function ChartDataTable({
  caption,
  columns,
  rows,
  maxRows = 60,
}: {
  caption: string;
  columns: string[];
  rows: (string | number)[][];
  maxRows?: number;
}) {
  const shown = rows.slice(0, maxRows);
  // The wrapper carries `sr-only`, not the table itself. A <table> does not honour
  // `overflow: hidden` the way a block element does, so a wide table given `sr-only`
  // directly escapes its 1px clip box and forces the page to scroll horizontally on
  // small screens - visually invisible, but very much present in the layout.
  return (
    <div className="sr-only">
    <table>
      <caption>
        {caption}
        {rows.length > maxRows
          ? ` (showing the first ${maxRows} of ${rows.length} rows)`
          : ''}
      </caption>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c} scope="col">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {shown.map((row, i) => (
          <tr key={i}>
            {row.map((cell, j) => (
              <td key={j}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

/* ------------------------------------------------------- pointer helper */

export function usePointerIndex(
  count: number,
  plotLeft: number,
  plotWidth: number,
) {
  const [index, setIndex] = useState<number | null>(null);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);

  const onMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const t = (x - plotLeft) / Math.max(1, plotWidth);
      const i = Math.round(t * (count - 1));
      if (i >= 0 && i < count) {
        setIndex(i);
        setPointer({ x, y });
      } else {
        setIndex(null);
        setPointer(null);
      }
    },
    [count, plotLeft, plotWidth],
  );

  const onLeave = useCallback(() => {
    setIndex(null);
    setPointer(null);
  }, []);

  // Keyboard access: arrow keys step the crosshair along the series.
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      setIndex((prev) => {
        const current = prev ?? 0;
        if (event.key === 'Home') return 0;
        if (event.key === 'End') return count - 1;
        const next = event.key === 'ArrowRight' ? current + 1 : current - 1;
        return Math.max(0, Math.min(count - 1, next));
      });
    },
    [count],
  );

  return { index, pointer, onMove, onLeave, onKeyDown, setIndex };
}

/* ----------------------------------------------------------- containers */

export function ChartFrame({
  title,
  subtitle,
  legend,
  children,
  actions,
  footnote,
}: {
  title: string;
  subtitle?: string;
  legend?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  footnote?: string;
}) {
  return (
    <figure className="min-w-0">
      <figcaption className="mb-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-ink-1">{title}</h3>
          {subtitle ? <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p> : null}
        </div>
        <div className="flex items-center gap-4">
          {legend}
          {actions}
        </div>
      </figcaption>
      {children}
      {footnote ? <p className="mt-2.5 text-2xs leading-relaxed text-ink-4">{footnote}</p> : null}
    </figure>
  );
}

export function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-40 items-center justify-center border border-dashed border-line text-xs text-ink-3">
      {message}
    </div>
  );
}

export function useAnimatedReveal(deps: unknown[]) {
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    setRevealed(false);
    const raf = requestAnimationFrame(() => setRevealed(true));
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return revealed;
}
