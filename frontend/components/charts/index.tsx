'use client';

import { useMemo } from 'react';

import {
  AxisBottom,
  AxisLeft,
  ChartDataTable,
  ChartFrame,
  ChartTooltip,
  DEFAULT_MARGIN,
  EmptyChart,
  Legend,
  SERIES,
  TooltipRow,
  extent,
  linearScale,
  niceTicks,
  padDomain,
  useAnimatedReveal,
  useMeasure,
  usePointerIndex,
} from './core';
import { hourLabel, isoDate, num } from '@/lib/format';

/* ==================================================================== */
/* Time series with optional uncertainty band                            */
/* ==================================================================== */

export interface TimeSeriesDatum {
  t: string;
  observed?: number | null;
  predicted?: number | null;
  lower?: number | null;
  upper?: number | null;
  reference?: number | null;
}

export function TimeSeriesChart({
  data,
  title,
  subtitle,
  unit,
  height = 260,
  observedLabel = 'Observed',
  predictedLabel = 'Predicted',
  referenceLabel = 'Clear-sky ceiling',
  intervalLabel,
  footnote,
  actions,
  zeroBase = true,
}: {
  data: TimeSeriesDatum[];
  title: string;
  subtitle?: string;
  unit: string;
  height?: number;
  observedLabel?: string;
  predictedLabel?: string;
  referenceLabel?: string;
  intervalLabel?: string;
  footnote?: string;
  actions?: React.ReactNode;
  zeroBase?: boolean;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const margin = DEFAULT_MARGIN;
  const plotWidth = Math.max(10, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;
  const revealed = useAnimatedReveal([data.length, title]);

  const hasObserved = data.some((d) => d.observed != null);
  const hasPredicted = data.some((d) => d.predicted != null);
  const hasInterval = data.some((d) => d.lower != null && d.upper != null);
  const hasReference = data.some((d) => d.reference != null);

  const { x, y, yTicks, xTicks } = useMemo(() => {
    const values: number[] = [];
    for (const d of data) {
      if (d.observed != null) values.push(d.observed);
      if (d.predicted != null) values.push(d.predicted);
      if (d.lower != null) values.push(d.lower);
      if (d.upper != null) values.push(d.upper);
      if (d.reference != null) values.push(d.reference);
    }
    const domain = padDomain(extent(values), 0.08, { zeroBase });
    const yScale = linearScale(domain, [plotHeight, 0]);
    const xScale = linearScale([0, Math.max(1, data.length - 1)], [0, plotWidth]);
    return {
      x: xScale,
      y: yScale,
      yTicks: niceTicks(domain[0], domain[1], 5),
      xTicks: pickTimeTicks(data.length, plotWidth),
    };
  }, [data, plotWidth, plotHeight, zeroBase]);

  const { index, pointer, onMove, onLeave, onKeyDown } = usePointerIndex(
    data.length,
    margin.left,
    plotWidth,
  );

  if (!data.length) return <EmptyChart message="No data available for this period." />;

  const path = (key: keyof TimeSeriesDatum) =>
    buildPath(data, (d) => d[key] as number | null | undefined, x, y);

  const band = hasInterval ? buildBand(data, x, y) : '';
  const active = index != null ? data[index] : undefined;

  const legendItems = [
    hasInterval && intervalLabel
      ? { label: intervalLabel, color: SERIES.interval, kind: 'area' as const }
      : null,
    hasObserved ? { label: observedLabel, color: SERIES.observed } : null,
    hasPredicted ? { label: predictedLabel, color: SERIES.predicted } : null,
    hasReference
      ? { label: referenceLabel, color: SERIES.clearSky, kind: 'dash' as const }
      : null,
  ].filter(Boolean) as { label: string; color: string; kind?: 'line' | 'area' | 'dash' }[];

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      legend={<Legend items={legendItems} />}
      actions={actions}
      footnote={footnote}
    >
      <div
        ref={ref}
        className="relative select-none"
        onPointerMove={onMove}
        onPointerLeave={onLeave}
        onKeyDown={onKeyDown}
        tabIndex={0}
        role="application"
        aria-label={`${title}. Use left and right arrow keys to inspect values.`}
      >
        {width > 0 ? (
          <svg width={width} height={height} className="overflow-visible">
            <g transform={`translate(${margin.left},${margin.top})`}>
              <AxisLeft
                scale={y}
                ticks={yTicks}
                width={plotWidth}
                format={(v) => num(v, Math.abs(v) < 10 ? 1 : 0)}
                label={unit}
              />
              <AxisBottom
                scale={x}
                ticks={xTicks}
                height={plotHeight}
                format={(i) => {
                  const d = data[Math.round(i)];
                  return d ? formatTick(d.t, data.length) : '';
                }}
              />

              {band ? <path d={band} fill={SERIES.interval} stroke="none" /> : null}

              {hasReference ? (
                <path
                  d={path('reference')}
                  fill="none"
                  stroke={SERIES.clearSky}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                />
              ) : null}

              {hasObserved ? (
                <path
                  d={path('observed')}
                  fill="none"
                  stroke={SERIES.observed}
                  strokeWidth={1.4}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  style={{
                    opacity: revealed ? 1 : 0,
                    transition: 'opacity 320ms ease-out',
                  }}
                />
              ) : null}

              {hasPredicted ? (
                <path
                  d={path('predicted')}
                  fill="none"
                  stroke={SERIES.predicted}
                  strokeWidth={1.6}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  style={{
                    opacity: revealed ? 1 : 0,
                    transition: 'opacity 320ms ease-out 60ms',
                  }}
                />
              ) : null}

              {index != null && data[index] ? (
                <g>
                  <line
                    x1={x(index)}
                    x2={x(index)}
                    y1={0}
                    y2={plotHeight}
                    stroke="rgba(255,255,255,0.28)"
                    strokeWidth={1}
                    shapeRendering="crispEdges"
                  />
                  {data[index]!.observed != null ? (
                    <circle
                      cx={x(index)}
                      cy={y(data[index]!.observed!)}
                      r={3}
                      fill={SERIES.observed}
                      stroke="#0A0B0D"
                      strokeWidth={1.5}
                    />
                  ) : null}
                  {data[index]!.predicted != null ? (
                    <circle
                      cx={x(index)}
                      cy={y(data[index]!.predicted!)}
                      r={3}
                      fill={SERIES.predicted}
                      stroke="#0A0B0D"
                      strokeWidth={1.5}
                    />
                  ) : null}
                </g>
              ) : null}
            </g>
          </svg>
        ) : (
          <div style={{ height }} />
        )}

        {active && pointer ? (
          <ChartTooltip x={pointer.x} y={pointer.y} containerWidth={width}>
            <div className="mb-1 border-b border-line pb-1 font-mono text-ink-3">
              {isoDate(active.t)} · {hourLabel(active.t)}
            </div>
            {active.observed != null ? (
              <TooltipRow
                label={observedLabel}
                value={`${num(active.observed, 1)} ${unit}`}
                color={SERIES.observed}
              />
            ) : null}
            {active.predicted != null ? (
              <TooltipRow
                label={predictedLabel}
                value={`${num(active.predicted, 1)} ${unit}`}
                color={SERIES.predicted}
              />
            ) : null}
            {active.lower != null && active.upper != null ? (
              <TooltipRow
                label="Interval"
                value={`${num(active.lower, 0)} – ${num(active.upper, 0)}`}
              />
            ) : null}
            {active.observed != null && active.predicted != null ? (
              <TooltipRow
                label="Error"
                value={`${num(active.observed - active.predicted, 1)} ${unit}`}
              />
            ) : null}
          </ChartTooltip>
        ) : null}
      </div>

      <ChartDataTable
        caption={`${title}. Values in ${unit}.`}
        columns={['Time', observedLabel, predictedLabel].filter(Boolean)}
        rows={data.map((d) => [
          d.t,
          d.observed != null ? num(d.observed, 1) : '—',
          d.predicted != null ? num(d.predicted, 1) : '—',
        ])}
      />
    </ChartFrame>
  );
}

function buildPath(
  data: TimeSeriesDatum[],
  accessor: (d: TimeSeriesDatum) => number | null | undefined,
  x: ReturnType<typeof linearScale>,
  y: ReturnType<typeof linearScale>,
): string {
  let d = '';
  let pen = false;
  data.forEach((datum, i) => {
    const v = accessor(datum);
    if (v == null || !Number.isFinite(v)) {
      pen = false;
      return;
    }
    // A gap in the data breaks the line rather than interpolating across it.
    d += `${pen ? 'L' : 'M'}${x(i).toFixed(2)},${y(v).toFixed(2)}`;
    pen = true;
  });
  return d;
}

function buildBand(
  data: TimeSeriesDatum[],
  x: ReturnType<typeof linearScale>,
  y: ReturnType<typeof linearScale>,
): string {
  const upper: string[] = [];
  const lower: string[] = [];
  data.forEach((d, i) => {
    if (d.lower == null || d.upper == null) return;
    upper.push(`${x(i).toFixed(2)},${y(d.upper).toFixed(2)}`);
    lower.push(`${x(i).toFixed(2)},${y(d.lower).toFixed(2)}`);
  });
  if (!upper.length) return '';
  return `M${upper.join('L')}L${lower.reverse().join('L')}Z`;
}

function pickTimeTicks(count: number, width: number): number[] {
  const target = Math.max(2, Math.min(8, Math.floor(width / 90)));
  const step = Math.max(1, Math.floor(count / target));
  const ticks: number[] = [];
  for (let i = 0; i < count; i += step) ticks.push(i);
  return ticks;
}

function formatTick(iso: string, total: number): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(5, 10);
  // Under three days, the hour is the informative part; beyond that, the date is.
  return total <= 72
    ? `${d.toISOString().slice(11, 16)}`
    : `${d.toISOString().slice(5, 10)}`;
}

/* ==================================================================== */
/* Observed vs predicted scatter                                         */
/* ==================================================================== */

export function ScatterChart({
  points,
  title,
  subtitle,
  unit,
  height = 300,
  footnote,
}: {
  points: { x: number; y: number; group?: string }[];
  title: string;
  subtitle?: string;
  unit: string;
  height?: number;
  footnote?: string;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const margin = { ...DEFAULT_MARGIN, left: 56, bottom: 40 };
  const plotWidth = Math.max(10, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;

  const groupColors: Record<string, string> = {
    sunny: SERIES.predicted,
    cloudy: SERIES.observed,
    other: SERIES.cyan,
  };

  const { xs, ys, ticks } = useMemo(() => {
    const all = points.flatMap((p) => [p.x, p.y]);
    const [lo, hi] = extent(all);
    const domain: [number, number] = [Math.min(0, lo), hi * 1.02];
    return {
      xs: linearScale(domain, [0, plotWidth]),
      ys: linearScale(domain, [plotHeight, 0]),
      ticks: niceTicks(domain[0], domain[1], 5),
    };
  }, [points, plotWidth, plotHeight]);

  if (!points.length) return <EmptyChart message="No paired observations to plot." />;

  const groups = Array.from(new Set(points.map((p) => p.group ?? 'all')));

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      legend={
        <Legend
          items={groups.map((g) => ({
            label: g === 'all' ? 'Observations' : g,
            color: groupColors[g] ?? SERIES.observed,
            kind: 'dot' as const,
          }))}
        />
      }
      footnote={footnote}
    >
      <div ref={ref} className="relative">
        {width > 0 ? (
          <svg width={width} height={height} role="img" aria-label={`${title}. Scatter of observed against predicted values in ${unit}.`}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              <AxisLeft
                scale={ys}
                ticks={ticks}
                width={plotWidth}
                format={(v) => num(v, 0)}
                label={`Predicted (${unit})`}
              />
              <AxisBottom
                scale={xs}
                ticks={ticks}
                height={plotHeight}
                format={(v) => num(v, 0)}
              />
              {/* The 1:1 line. A perfect model puts every point on it, which makes
                  systematic over- or under-prediction visible at a glance. */}
              <line
                x1={xs(ticks[0] ?? 0)}
                y1={ys(ticks[0] ?? 0)}
                x2={xs(ticks[ticks.length - 1] ?? 1)}
                y2={ys(ticks[ticks.length - 1] ?? 1)}
                stroke="rgba(255,255,255,0.3)"
                strokeWidth={1}
                strokeDasharray="4 3"
              />
              <text
                x={plotWidth - 6}
                y={ys(ticks[ticks.length - 1] ?? 1) + 14}
                textAnchor="end"
                className="fill-ink-4 font-mono"
                style={{ fontSize: 9 }}
              >
                1:1
              </text>
              {points.map((p, i) => (
                <circle
                  key={i}
                  cx={xs(p.x)}
                  cy={ys(p.y)}
                  r={1.7}
                  fill={groupColors[p.group ?? 'all'] ?? SERIES.observed}
                  fillOpacity={0.42}
                />
              ))}
              <text
                x={plotWidth / 2}
                y={plotHeight + 32}
                textAnchor="middle"
                className="fill-ink-4 font-mono uppercase"
                style={{ fontSize: 9, letterSpacing: '0.1em' }}
              >
                Observed ({unit})
              </text>
            </g>
          </svg>
        ) : (
          <div style={{ height }} />
        )}
      </div>
    </ChartFrame>
  );
}

/* ==================================================================== */
/* Histogram                                                             */
/* ==================================================================== */

export function HistogramChart({
  counts,
  edges,
  title,
  subtitle,
  unit,
  height = 200,
  markerValue,
  markerLabel,
  footnote,
}: {
  counts: number[];
  edges: number[];
  title: string;
  subtitle?: string;
  unit: string;
  height?: number;
  markerValue?: number;
  markerLabel?: string;
  footnote?: string;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const margin = { ...DEFAULT_MARGIN, left: 44 };
  const plotWidth = Math.max(10, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;

  const { x, y, yTicks, xTicks } = useMemo(() => {
    const xDomain: [number, number] = [edges[0] ?? 0, edges[edges.length - 1] ?? 1];
    const yDomain: [number, number] = [0, Math.max(...counts, 1)];
    return {
      x: linearScale(xDomain, [0, plotWidth]),
      y: linearScale(yDomain, [plotHeight, 0]),
      yTicks: niceTicks(0, yDomain[1], 4),
      xTicks: niceTicks(xDomain[0], xDomain[1], 6),
    };
  }, [counts, edges, plotWidth, plotHeight]);

  if (!counts.length) return <EmptyChart message="No residuals to summarise." />;

  return (
    <ChartFrame title={title} subtitle={subtitle} footnote={footnote}>
      <div ref={ref} className="relative">
        {width > 0 ? (
          <svg width={width} height={height} role="img" aria-label={`${title}. Distribution histogram in ${unit}.`}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              <AxisLeft scale={y} ticks={yTicks} width={plotWidth} format={(v) => num(v, 0)} />
              <AxisBottom scale={x} ticks={xTicks} height={plotHeight} format={(v) => num(v, 0)} />
              {counts.map((c, i) => {
                const x0 = x(edges[i] ?? 0);
                const x1 = x(edges[i + 1] ?? 0);
                const w = Math.max(1, x1 - x0 - 1);
                const h = plotHeight - y(c);
                // Bars straddling zero error are neutral; the tails are where the
                // interesting failures live, so they carry the accent colour.
                const centre = ((edges[i] ?? 0) + (edges[i + 1] ?? 0)) / 2;
                return (
                  <rect
                    key={i}
                    x={x0}
                    y={y(c)}
                    width={w}
                    height={Math.max(0, h)}
                    fill={Math.abs(centre) < (edges[1]! - edges[0]!) * 1.5 ? SERIES.observed : SERIES.predicted}
                    fillOpacity={0.55}
                  />
                );
              })}
              {markerValue != null ? (
                <g>
                  <line
                    x1={x(markerValue)}
                    x2={x(markerValue)}
                    y1={0}
                    y2={plotHeight}
                    stroke={SERIES.critical}
                    strokeWidth={1}
                    strokeDasharray="3 2"
                  />
                  {markerLabel ? (
                    <text
                      x={x(markerValue) + 4}
                      y={10}
                      className="fill-ink-3 font-mono"
                      style={{ fontSize: 9 }}
                    >
                      {markerLabel}
                    </text>
                  ) : null}
                </g>
              ) : null}
            </g>
          </svg>
        ) : (
          <div style={{ height }} />
        )}
      </div>
    </ChartFrame>
  );
}

/* ==================================================================== */
/* Horizontal bars                                                       */
/* ==================================================================== */

export function BarChart({
  items,
  title,
  subtitle,
  unit,
  footnote,
  valueFormat = (v: number) => num(v, 3),
  color = SERIES.predicted,
  showError = false,
}: {
  items: { label: string; value: number; error?: number; sublabel?: string }[];
  title: string;
  subtitle?: string;
  unit?: string;
  footnote?: string;
  valueFormat?: (v: number) => string;
  color?: string;
  showError?: boolean;
}) {
  const max = Math.max(...items.map((i) => Math.abs(i.value) + (i.error ?? 0)), 1e-9);

  if (!items.length) return <EmptyChart message="Nothing to display." />;

  return (
    <ChartFrame title={title} subtitle={subtitle} footnote={footnote}>
      <ul className="space-y-2">
        {items.map((item) => {
          const pctWidth = Math.max(0, (Math.abs(item.value) / max) * 100);
          const errPct = item.error ? (item.error / max) * 100 : 0;
          return (
            <li key={item.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
              <div className="min-w-0">
                <div className="mb-1 flex items-baseline justify-between gap-3">
                  <span className="truncate text-xs text-ink-2">{item.label}</span>
                  {item.sublabel ? (
                    <span className="shrink-0 text-2xs text-ink-4">{item.sublabel}</span>
                  ) : null}
                </div>
                <div className="relative h-1.5 w-full bg-surface-3">
                  <div
                    className="absolute inset-y-0 left-0 transition-[width] duration-500 ease-out"
                    style={{ width: `${pctWidth}%`, background: color }}
                  />
                  {showError && errPct > 0 ? (
                    <div
                      className="absolute inset-y-0"
                      style={{
                        left: `${Math.max(0, pctWidth - errPct)}%`,
                        width: `${errPct * 2}%`,
                        background:
                          'repeating-linear-gradient(90deg, rgba(255,255,255,0.28) 0 1px, transparent 1px 3px)',
                      }}
                      aria-hidden="true"
                    />
                  ) : null}
                </div>
              </div>
              <span className="num shrink-0 text-xs text-ink-1">
                {valueFormat(item.value)}
                {unit ? <span className="ml-1 text-ink-4">{unit}</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
    </ChartFrame>
  );
}

/* ==================================================================== */
/* Grouped column chart (error by hour / month)                          */
/* ==================================================================== */

export function ColumnChart({
  items,
  title,
  subtitle,
  unit,
  height = 190,
  footnote,
  color = SERIES.predicted,
}: {
  items: { label: string; value: number; n?: number }[];
  title: string;
  subtitle?: string;
  unit: string;
  height?: number;
  footnote?: string;
  color?: string;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const margin = { top: 12, right: 8, bottom: 26, left: 46 };
  const plotWidth = Math.max(10, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;

  const { y, yTicks, bandWidth } = useMemo(() => {
    const max = Math.max(...items.map((i) => i.value), 1e-9);
    const domain: [number, number] = [0, max * 1.08];
    return {
      y: linearScale(domain, [plotHeight, 0]),
      yTicks: niceTicks(0, domain[1], 4),
      bandWidth: plotWidth / Math.max(1, items.length),
    };
  }, [items, plotWidth, plotHeight]);

  if (!items.length) return <EmptyChart message="Nothing to display." />;

  return (
    <ChartFrame title={title} subtitle={subtitle} footnote={footnote}>
      <div ref={ref} className="relative">
        {width > 0 ? (
          <svg width={width} height={height} role="img" aria-label={`${title}, in ${unit}.`}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              <AxisLeft scale={y} ticks={yTicks} width={plotWidth} format={(v) => num(v, 0)} label={unit} />
              {items.map((item, i) => {
                const w = Math.max(2, bandWidth * 0.62);
                const x0 = i * bandWidth + (bandWidth - w) / 2;
                const h = plotHeight - y(item.value);
                return (
                  <g key={item.label}>
                    <rect
                      x={x0}
                      y={y(item.value)}
                      width={w}
                      height={Math.max(0, h)}
                      fill={color}
                      fillOpacity={0.72}
                    >
                      <title>
                        {item.label}: {num(item.value, 1)} {unit}
                        {item.n ? ` (n=${item.n})` : ''}
                      </title>
                    </rect>
                  </g>
                );
              })}
              <line
                x1={0}
                x2={plotWidth}
                y1={plotHeight}
                y2={plotHeight}
                stroke={SERIES.axis}
                shapeRendering="crispEdges"
              />
              {items.map((item, i) =>
                items.length <= 14 || i % 2 === 0 ? (
                  <text
                    key={`l-${item.label}`}
                    x={i * bandWidth + bandWidth / 2}
                    y={plotHeight + 15}
                    textAnchor="middle"
                    className="fill-ink-3 font-mono"
                    style={{ fontSize: 9 }}
                  >
                    {item.label}
                  </text>
                ) : null,
              )}
            </g>
          </svg>
        ) : (
          <div style={{ height }} />
        )}
      </div>
      <ChartDataTable
        caption={`${title}, in ${unit}.`}
        columns={['Group', `Value (${unit})`]}
        rows={items.map((i) => [i.label, num(i.value, 2)])}
      />
    </ChartFrame>
  );
}

/* ==================================================================== */
/* Line chart for partial dependence                                     */
/* ==================================================================== */

export function LineChart({
  points,
  title,
  subtitle,
  xLabel,
  yLabel,
  height = 170,
  footnote,
}: {
  points: { x: number; y: number }[];
  title: string;
  subtitle?: string;
  xLabel: string;
  yLabel: string;
  height?: number;
  footnote?: string;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const margin = { top: 12, right: 14, bottom: 30, left: 50 };
  const plotWidth = Math.max(10, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;

  const { x, y, xTicks, yTicks, path } = useMemo(() => {
    const xd = padDomain(extent(points.map((p) => p.x)), 0.02);
    const yd = padDomain(extent(points.map((p) => p.y)), 0.12);
    const xs = linearScale(xd, [0, plotWidth]);
    const ys = linearScale(yd, [plotHeight, 0]);
    return {
      x: xs,
      y: ys,
      xTicks: niceTicks(xd[0], xd[1], 4),
      yTicks: niceTicks(yd[0], yd[1], 3),
      path: points
        .map((p, i) => `${i ? 'L' : 'M'}${xs(p.x).toFixed(2)},${ys(p.y).toFixed(2)}`)
        .join(''),
    };
  }, [points, plotWidth, plotHeight]);

  if (!points.length) return <EmptyChart message="No curve available." />;

  return (
    <ChartFrame title={title} subtitle={subtitle} footnote={footnote}>
      <div ref={ref} className="relative">
        {width > 0 ? (
          <svg width={width} height={height} role="img" aria-label={`${title}. ${yLabel} against ${xLabel}.`}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              <AxisLeft scale={y} ticks={yTicks} width={plotWidth} format={(v) => num(v, 2)} />
              <AxisBottom scale={x} ticks={xTicks} height={plotHeight} format={(v) => num(v, Math.abs(v) < 10 ? 1 : 0)} />
              <path d={path} fill="none" stroke={SERIES.predicted} strokeWidth={1.6} strokeLinejoin="round" />
              <text
                x={plotWidth / 2}
                y={plotHeight + 26}
                textAnchor="middle"
                className="fill-ink-4 font-mono uppercase"
                style={{ fontSize: 9, letterSpacing: '0.08em' }}
              >
                {xLabel}
              </text>
            </g>
          </svg>
        ) : (
          <div style={{ height }} />
        )}
      </div>
    </ChartFrame>
  );
}
