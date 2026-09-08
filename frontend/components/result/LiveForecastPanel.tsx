'use client';

import { useEffect, useState } from 'react';

import { Icon } from '@/components/site/Icon';
import { formatEnergy } from '@/lib/i18n';
import {
  fetchLiveForecast,
  type LiveForecastDay,
  type LiveForecastResponse,
} from '@/lib/liveForecast';

/**
 * The days ahead, beside the typical year.
 *
 * The annual figure above answers "is this worth installing?". This answers a different
 * question — "what will it actually do this week?" — and the two are deliberately not
 * merged into one number, because averaging a forecast into a climatology would produce a
 * figure that answers neither.
 *
 * Three rules this screen follows, all inherited from the rest of the product:
 *
 * - **It never blocks the answer.** The fetch runs in this component's own effect, after
 *   the estimate has rendered. If the weather service is unreachable the panel renders
 *   nothing at all rather than showing an error — the result page is the primary content
 *   and must not look broken because a secondary feature failed.
 * - **The backend's wording is shown verbatim.** The `note` field explains why there is no
 *   range here, and it is rendered as written rather than paraphrased.
 * - **A partial day is labelled, not hidden.** An operational forecast begins at the
 *   current day's first hour, so today's bar is usually short because the day is partly
 *   over. Saying so is cheaper than having somebody wonder why today looks bad.
 *
 * The chart is drawn here rather than imported. `MonthlyChart` in `charts.tsx` takes a
 * lower/upper band on every bar, which this data deliberately does not have — reusing it
 * would mean inventing an interval, which is the one thing this feature must not do.
 */
export function LiveForecastPanel({ estimateId }: { estimateId: string }) {
  const [data, setData] = useState<LiveForecastResponse | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    fetchLiveForecast(estimateId, 168, controller.signal)
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setState(payload.daily.length ? 'ready' : 'failed');
      })
      .catch(() => {
        // Deliberately silent. See the component docstring.
        if (!cancelled) setState('failed');
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [estimateId]);

  // Renders nothing on failure, so a weather outage costs this panel and nothing else.
  if (state === 'failed') return null;

  if (state === 'loading' || !data) {
    return (
      <section className="mt-8 border border-line bg-surface-1 p-5" aria-busy="true">
        <p className="eyebrow mb-4">The week ahead</p>
        <div role="status">
          <span className="sr-only">Loading the forecast for the days ahead…</span>
          <div className="h-[132px] animate-pulse bg-surface-2" />
        </div>
      </section>
    );
  }

  const total = formatEnergy(data.total_kwh);

  return (
    <section className="mt-8 border border-line bg-surface-1">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-line p-5">
        <div className="min-w-0">
          <p className="eyebrow mb-3">The week ahead</p>
          <h2 className="text-lg font-medium tracking-tight text-ink-1">
            What this system should produce over the next {data.daily.length} days
          </h2>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-2">
            Based on the current weather forecast for your exact location — not a seasonal
            average.
          </p>
        </div>
        <dl className="shrink-0">
          <dt className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
            Total expected
          </dt>
          <dd className="num mt-0.5 text-2xl font-medium text-ink-1">
            {total.value}
            <span className="ml-1.5 text-xs text-ink-3">{total.unit}</span>
          </dd>
        </dl>
      </div>

      <div className="p-5">
        <DailyBars days={data.daily} />

        {/*
          The backend's own explanation of what this number is and is not. Rendered as
          written — replacing it with a shorter paraphrase would drop the part that matters,
          which is why there is no range here.
        */}
        <p className="mt-5 border-l-2 border-line-strong pl-3 text-xs leading-relaxed text-ink-3">
          {data.note}
        </p>

        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-4">
          <span className="flex items-center gap-1.5">
            <Icon name="info" size={12} />
            {data.provenance.source}
          </span>
          <span>{data.provenance.model_chain}</span>
          <span>
            Issued{' '}
            {new Date(data.issued_at).toLocaleString(undefined, {
              day: 'numeric',
              month: 'short',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </p>
      </div>
    </section>
  );
}

/**
 * A bar per day.
 *
 * No interval whiskers, unlike the monthly chart — this data has no range, and drawing one
 * would be inventing it. The table beneath carries the same figures for screen readers,
 * matching how every other chart in this product is built.
 */
function DailyBars({ days }: { days: LiveForecastDay[] }) {
  const max = Math.max(...days.map((d) => d.energy_kwh), 0.001);

  return (
    <>
      <ul className="flex items-end gap-1.5" style={{ height: 132 }} aria-hidden="true">
        {days.map((day) => {
          const partial = day.hours < 24;
          const heightPct = Math.max((day.energy_kwh / max) * 100, 1.5);
          return (
            <li key={day.date} className="flex min-w-0 flex-1 flex-col justify-end">
              <span className="num mb-1 truncate text-center text-2xs text-ink-3">
                {day.energy_kwh.toFixed(1)}
              </span>
              <span
                className={`w-full ${partial ? 'bg-solar/40' : 'bg-solar'}`}
                style={{ height: `${heightPct}%` }}
                title={
                  partial
                    ? `${day.date}: ${day.energy_kwh} kWh (partial day — ${day.hours} h)`
                    : `${day.date}: ${day.energy_kwh} kWh`
                }
              />
              <span className="mt-1.5 truncate text-center text-2xs text-ink-4">
                {new Date(`${day.date}T12:00:00`).toLocaleDateString(undefined, {
                  weekday: 'short',
                })}
              </span>
            </li>
          );
        })}
      </ul>

      {days.some((d) => d.hours < 24) ? (
        <p className="mt-2 text-2xs text-ink-4">
          A paler bar is a partial day — the forecast starts partway through it.
        </p>
      ) : null}

      {/* The same figures, readable by a screen reader and by anyone who wants the numbers. */}
      <table className="sr-only">
        <caption>Expected generation for each of the next days, in kWh</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Expected generation (kWh)</th>
            <th scope="col">Hours forecast</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.date}>
              <td>{day.date}</td>
              <td>{day.energy_kwh}</td>
              <td>{day.hours}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
