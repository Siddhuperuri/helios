'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Charts for the consumer result (§21).
 *
 * Written rather than imported, for the same reason the analysis console draws its own:
 * four chart types, each doing one job, is a few hundred lines — a charting library is a
 * hundred kilobytes and a fight over styling (§41).
 *
 * The rules these follow:
 *
 * - **Every chart answers a question somebody actually asked.** Monthly generation answers
 *   "when will I get it?", the day profile answers "what time of day?", the balance answers
 *   "how much do I actually use?". Nothing is here to fill space.
 * - **Uncertainty is drawn, not implied.** The monthly chart shows the range as a whisker
 *   on every bar, because a bare bar reads as a promise.
 * - **Colour is never the only encoding.** Every series is labelled, every chart has a
 *   table underneath it for screen readers, and the amber-is-modelled convention is stated
 *   in the legend rather than assumed.
 * - **Animation is a reveal, once (§39).** Bars grow from the axis on first paint so the
 *   eye follows the shape; nothing loops, and `prefers-reduced-motion` removes it.
 */

/** Fires once when the element first enters the viewport, for the reveal. */
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (typeof IntersectionObserver === 'undefined') {
      setShown(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, shown };
}

// --------------------------------------------------------------------------------------
// Monthly generation
// --------------------------------------------------------------------------------------

export interface MonthlyDatum {
  month_name: string;
  expected_kwh: number;
  lower_kwh: number;
  upper_kwh: number;
  daily_average_kwh: number;
}

export type MonthlyUnit = 'kWh' | 'MWh' | 'daily';

export function MonthlyChart({
  data,
  unit = 'kWh',
  height = 260,
}: {
  data: MonthlyDatum[];
  unit?: MonthlyUnit;
  height?: number;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const scale = (value: number) =>
    unit === 'MWh' ? value / 1000 : unit === 'daily' ? value / 30.4 : value;
  const unitLabel = unit === 'MWh' ? 'MWh' : unit === 'daily' ? 'kWh/day' : 'kWh';

  const max = Math.max(...data.map((d) => scale(d.upper_kwh)), 1);
  const width = 720;
  const margin = { top: 16, right: 8, bottom: 34, left: 46 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const bandWidth = plotW / data.length;
  const barWidth = Math.min(bandWidth * 0.56, 46);

  const y = (value: number) => margin.top + plotH - (value / max) * plotH;
  const ticks = niceTicks(0, max, 4);

  return (
    <div ref={ref}>
      <div className="scroll-x">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full min-w-[520px]"
          role="img"
          aria-label={`Expected generation for each month, in ${unitLabel}. Full figures are in the table below.`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={margin.left}
                x2={width - margin.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--c-grid)"
              />
              <text
                x={margin.left - 8}
                y={y(tick) + 3.5}
                textAnchor="end"
                className="num"
                fill="rgb(var(--c-ink-4))"
                fontSize="10"
              >
                {formatTick(tick)}
              </text>
            </g>
          ))}

          {data.map((datum, index) => {
            const cx = margin.left + bandWidth * index + bandWidth / 2;
            const value = scale(datum.expected_kwh);
            const top = y(value);
            const barHeight = margin.top + plotH - top;
            const active = hover === index;

            return (
              <g
                key={datum.month_name}
                onPointerEnter={() => setHover(index)}
                onPointerLeave={() => setHover(null)}
              >
                {/* generous hover target, invisible */}
                <rect
                  x={margin.left + bandWidth * index}
                  y={margin.top}
                  width={bandWidth}
                  height={plotH}
                  fill="transparent"
                />
                <rect
                  x={cx - barWidth / 2}
                  y={shown ? top : margin.top + plotH}
                  width={barWidth}
                  height={shown ? barHeight : 0}
                  fill={active ? 'rgb(var(--c-solar-bright))' : 'rgb(var(--c-solar))'}
                  style={{
                    transition: `y 620ms cubic-bezier(0.22,1,0.36,1) ${index * 35}ms, height 620ms cubic-bezier(0.22,1,0.36,1) ${index * 35}ms, fill 140ms`,
                  }}
                />
                {/* the range: a promise without a whisker is a promise */}
                <line
                  x1={cx}
                  x2={cx}
                  y1={y(scale(datum.lower_kwh))}
                  y2={y(scale(datum.upper_kwh))}
                  stroke="rgb(var(--c-ink-1))"
                  strokeOpacity={shown ? 0.45 : 0}
                  strokeWidth="1.5"
                  style={{ transition: 'stroke-opacity 400ms 500ms' }}
                />
                <line
                  x1={cx - 5}
                  x2={cx + 5}
                  y1={y(scale(datum.upper_kwh))}
                  y2={y(scale(datum.upper_kwh))}
                  stroke="rgb(var(--c-ink-1))"
                  strokeOpacity={shown ? 0.45 : 0}
                  strokeWidth="1.5"
                  style={{ transition: 'stroke-opacity 400ms 500ms' }}
                />
                <text
                  x={cx}
                  y={height - 12}
                  textAnchor="middle"
                  fill={active ? 'rgb(var(--c-ink-1))' : 'rgb(var(--c-ink-4))'}
                  fontSize="10.5"
                >
                  {datum.month_name.slice(0, 3)}
                </text>
                {active ? (
                  <text
                    x={cx}
                    y={top - 7}
                    textAnchor="middle"
                    className="num"
                    fill="rgb(var(--c-ink-1))"
                    fontSize="11"
                    fontWeight="500"
                  >
                    {formatTick(value)}
                  </text>
                ) : null}
              </g>
            );
          })}

          <line
            x1={margin.left}
            x2={width - margin.right}
            y1={margin.top + plotH}
            y2={margin.top + plotH}
            stroke="var(--c-axis)"
          />
        </svg>
      </div>

      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-ink-3">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 bg-solar" aria-hidden="true" />
          Expected generation ({unitLabel})
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-px bg-ink-1/45" aria-hidden="true" />
          Likely range
        </span>
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------------------
// Day profile
// --------------------------------------------------------------------------------------

export function DayProfileChart({
  generation,
  consumption,
  height = 220,
}: {
  /** 24 hourly values, kWh. */
  generation: number[];
  /** Optional 24 hourly values of demand, to show the overlap that decides self-use. */
  consumption?: number[];
  height?: number;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>();
  const width = 720;
  const margin = { top: 16, right: 12, bottom: 30, left: 46 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;

  const max = Math.max(...generation, ...(consumption ?? [0]), 0.001);
  const x = (hour: number) => margin.left + (hour / 23) * plotW;
  const y = (value: number) => margin.top + plotH - (value / max) * plotH;

  const line = (values: number[]) =>
    values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = (values: number[]) =>
    `${line(values)} L${x(23).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z`;

  return (
    <div ref={ref}>
      <div className="scroll-x">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full min-w-[520px]"
          role="img"
          aria-label="Generation through a typical day, hour by hour, with household demand overlaid where known."
        >
          {[0, 0.5, 1].map((fraction) => (
            <line
              key={fraction}
              x1={margin.left}
              x2={width - margin.right}
              y1={y(max * fraction)}
              y2={y(max * fraction)}
              stroke="var(--c-grid)"
            />
          ))}

          <path
            d={area(generation)}
            fill="rgb(var(--c-solar) / 0.18)"
            style={{ opacity: shown ? 1 : 0, transition: 'opacity 500ms' }}
          />
          <path
            d={line(generation)}
            fill="none"
            stroke="rgb(var(--c-solar))"
            strokeWidth="2"
            strokeLinejoin="round"
            style={{ opacity: shown ? 1 : 0, transition: 'opacity 500ms 100ms' }}
          />

          {consumption ? (
            <path
              d={line(consumption)}
              fill="none"
              stroke="rgb(var(--c-steel))"
              strokeWidth="2"
              strokeDasharray="4 3"
              strokeLinejoin="round"
              style={{ opacity: shown ? 1 : 0, transition: 'opacity 500ms 200ms' }}
            />
          ) : null}

          {[0, 6, 12, 18, 23].map((hour) => (
            <text
              key={hour}
              x={x(hour)}
              y={height - 10}
              textAnchor="middle"
              className="num"
              fill="rgb(var(--c-ink-4))"
              fontSize="10"
            >
              {String(hour).padStart(2, '0')}:00
            </text>
          ))}

          <line
            x1={margin.left}
            x2={width - margin.right}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--c-axis)"
          />
        </svg>
      </div>

      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-ink-3">
        <span className="flex items-center gap-1.5">
          <span className="h-px w-4 bg-solar" aria-hidden="true" />
          Solar generation
        </span>
        {consumption ? (
          <span className="flex items-center gap-1.5">
            <span
              className="h-px w-4 border-t-2 border-dashed border-steel"
              aria-hidden="true"
            />
            Your typical demand
          </span>
        ) : null}
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------------------
// Energy balance
// --------------------------------------------------------------------------------------

export function BalanceBar({
  segments,
  total,
  label,
}: {
  segments: { key: string; label: string; value: number; className: string }[];
  total: number;
  label: string;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>();
  const safeTotal = total > 0 ? total : 1;

  return (
    <div ref={ref}>
      <p className="mb-2 text-xs text-ink-3">{label}</p>
      <div
        className="flex h-8 w-full overflow-hidden border border-line"
        role="img"
        aria-label={`${label}: ${segments
          .map((s) => `${s.label} ${Math.round((s.value / safeTotal) * 100)} percent`)
          .join(', ')}`}
      >
        {segments.map((segment, index) => (
          <div
            key={segment.key}
            className={segment.className}
            style={{
              width: shown ? `${(segment.value / safeTotal) * 100}%` : '0%',
              transition: `width 700ms cubic-bezier(0.22,1,0.36,1) ${index * 90}ms`,
            }}
          />
        ))}
      </div>
      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-center gap-1.5 text-2xs text-ink-2">
            <span className={`h-2.5 w-2.5 ${segment.className}`} aria-hidden="true" />
            {segment.label}
            <span className="num text-ink-3">
              {Math.round(segment.value).toLocaleString()} kWh
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------------------
// Cumulative cash flow
// --------------------------------------------------------------------------------------

export function CashflowChart({
  years,
  symbol,
  paybackYear,
  height = 220,
}: {
  years: { year: number; cumulative_cash_flow: number }[];
  symbol: string;
  paybackYear: number | null;
  height?: number;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>();
  if (years.length === 0) return null;

  const width = 720;
  const margin = { top: 16, right: 16, bottom: 30, left: 62 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;

  const values = years.map((y) => y.cumulative_cash_flow);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;

  const x = (year: number) => margin.left + ((year - 1) / (years.length - 1 || 1)) * plotW;
  const y = (value: number) => margin.top + plotH - ((value - min) / span) * plotH;

  const path = years
    .map((point, index) =>
      `${index === 0 ? 'M' : 'L'}${x(point.year).toFixed(1)},${y(point.cumulative_cash_flow).toFixed(1)}`,
    )
    .join(' ');

  return (
    <div ref={ref}>
      <div className="scroll-x">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full min-w-[520px]"
          role="img"
          aria-label={
            paybackYear
              ? `Cumulative savings over the system's life, crossing from negative to positive at about year ${paybackYear.toFixed(1)}.`
              : "Cumulative savings over the system's life."
          }
        >
          {/* break-even line: the only gridline that means anything here */}
          <line
            x1={margin.left}
            x2={width - margin.right}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--c-axis)"
            strokeDasharray="3 3"
          />
          <text
            x={margin.left - 8}
            y={y(0) + 3.5}
            textAnchor="end"
            className="num"
            fill="rgb(var(--c-ink-4))"
            fontSize="10"
          >
            0
          </text>

          <path
            d={path}
            fill="none"
            stroke="rgb(var(--c-solar))"
            strokeWidth="2"
            strokeLinejoin="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={shown ? 0 : 1}
            style={{ transition: 'stroke-dashoffset 900ms cubic-bezier(0.4,0,0.2,1)' }}
          />

          {paybackYear ? (
            <>
              <line
                x1={x(paybackYear)}
                x2={x(paybackYear)}
                y1={margin.top}
                y2={margin.top + plotH}
                stroke="rgb(var(--c-positive))"
                strokeWidth="1.5"
              />
              <text
                x={x(paybackYear) + 6}
                y={margin.top + 12}
                fill="rgb(var(--c-positive))"
                fontSize="10.5"
              >
                pays for itself
              </text>
            </>
          ) : null}

          {[1, Math.round(years.length / 2), years.length].map((year) => (
            <text
              key={year}
              x={x(year)}
              y={height - 10}
              textAnchor="middle"
              className="num"
              fill="rgb(var(--c-ink-4))"
              fontSize="10"
            >
              Year {year}
            </text>
          ))}
        </svg>
      </div>
      <p className="mt-2 text-2xs text-ink-3">
        Cumulative savings in {symbol}, after the cost of the system and its upkeep.
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------------------
// helpers
// --------------------------------------------------------------------------------------

function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min || 1;
  const rawStep = span / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const normalised = rawStep / magnitude;
  const step =
    (normalised >= 5 ? 5 : normalised >= 2.5 ? 2.5 : normalised >= 2 ? 2 : 1) * magnitude;
  const ticks: number[] = [];
  for (let value = 0; value <= max + step * 0.5; value += step) ticks.push(value);
  return ticks;
}

function formatTick(value: number): string {
  if (value >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (value >= 100) return value.toFixed(0);
  if (value >= 10) return value.toFixed(0);
  return value.toFixed(1);
}
