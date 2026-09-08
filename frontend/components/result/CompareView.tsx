'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/site/Icon';
import {
  EstimateError,
  estimateApi,
  type EstimateRequestBody,
  type EstimateResult,
  type ScenarioRow,
} from '@/lib/estimate';
import { formatCurrency, formatEnergy } from '@/lib/i18n';

/**
 * Side-by-side comparison (§27).
 *
 * The value here is not the table, it is the *controlled* comparison. Every option runs
 * against the same location, the same weather record, the same tariff and the same
 * assumptions, so the differences between the rows come only from the system. That is what
 * makes "is 15 kW better than 10?" answerable rather than a matter of opinion.
 *
 * Sizes are seeded around whatever the original estimate recommended, because that is the
 * number the user is deciding about. Comparing three arbitrary sizes would be busywork.
 */
export function CompareView({ fromEstimateId }: { fromEstimateId: string | null }) {
  const [source, setSource] = useState<EstimateResult | null>(null);
  const [sizes, setSizes] = useState<number[]>([]);
  const [rows, setRows] = useState<ScenarioRow[] | null>(null);
  const [currency, setCurrency] = useState<EstimateResult['currency'] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<EstimateError | null>(null);

  useEffect(() => {
    if (!fromEstimateId) return;
    estimateApi
      .get(fromEstimateId)
      .then((result) => {
        setSource(result);
        setCurrency(result.currency);
        const base = result.system.capacity_kwp;
        // Two-thirds, as recommended, and half again: a spread wide enough to show the
        // trade-off without being a different project.
        setSizes(
          [base * 0.66, base, base * 1.5]
            .map((value) => (value < 10 ? Math.round(value * 4) / 4 : Math.round(value)))
            .filter((value, index, all) => value > 0 && all.indexOf(value) === index),
        );
      })
      .catch((err) =>
        setError(
          err instanceof EstimateError
            ? err
            : new EstimateError('We could not load that estimate.', 500),
        ),
      );
  }, [fromEstimateId]);

  const run = useCallback(async () => {
    if (!source?.input) {
      setError(
        new EstimateError('This estimate cannot be compared.', 409, {
          remedy: 'Run a new estimate, then open the Scenarios tab from its results.',
        }),
      );
      return;
    }
    setRunning(true);
    setError(null);
    try {
      // Rebuild the original request from the stored inputs, so every scenario differs
      // only in the size being tested.
      const input = source.input as Record<string, unknown>;
      const base: EstimateRequestBody = {
        user_type: (input.user_type as string) ?? 'exploring',
        mode: (input.mode as string) ?? 'quick',
        location:
          input.latitude != null && input.longitude != null
            ? { latitude: input.latitude as number, longitude: input.longitude as number }
            : { query: (input.location_query as string) ?? source.location.label },
        consumption_method: (input.consumption_method as string) ?? undefined,
        monthly_bill: (input.monthly_bill as number) ?? undefined,
        monthly_kwh: (input.monthly_kwh as number) ?? undefined,
        installation_type: (input.installation_type as string) ?? 'not_sure',
        save: false,
      };
      const { scenarios, currency: cur } = await estimateApi.compare(
        base,
        sizes.map((size) => ({ name: `${size} kW`, capacity_kwp: size })),
      );
      setRows(scenarios);
      if (cur) setCurrency(cur);
    } catch (err) {
      setError(
        err instanceof EstimateError
          ? err
          : new EstimateError('The comparison could not be run.', 500),
      );
    } finally {
      setRunning(false);
    }
  }, [source, sizes]);

  if (!fromEstimateId) {
    return (
      <div className="mx-auto max-w-xl px-5 py-16 sm:px-8">
        <p className="eyebrow mb-5">Compare</p>
        <h1 className="text-xl font-medium text-ink-1">
          Comparisons start from an existing estimate
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-ink-2">
          Run an estimate first, then open its Scenarios tab — that way every option is
          compared against the same location, weather and assumptions.
        </p>
        <Link
          href="/start"
          className="tap mt-6 inline-flex items-center gap-2 border border-solar bg-solar px-5
            py-2.5 text-sm font-medium text-base transition-opacity hover:opacity-90"
        >
          Run an estimate
          <Icon name="arrow-right" size={16} />
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 lg:py-14">
      <p className="eyebrow mb-5">Compare</p>
      <h1 className="text-2xl font-medium tracking-tight text-ink-1 sm:text-3xl">
        Which size makes sense?
      </h1>
      {source ? (
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-2">
          All options below use the same location ({source.location.label}), the same
          weather record and the same assumptions as your original estimate. Only the system
          size changes.
        </p>
      ) : null}

      {/* ------------------------------------------------------------- size inputs */}
      <div className="mt-8 flex flex-wrap items-end gap-3">
        {sizes.map((size, index) => (
          <label key={index} className="block">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.1em] text-ink-4">
              Option {index + 1}
            </span>
            <span className="flex items-stretch">
              <input
                type="number"
                min={0.5}
                step={0.5}
                value={size}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  setSizes(sizes.map((s, i) => (i === index ? next : s)));
                  setRows(null);
                }}
                className="num w-24 border border-line-strong bg-surface-1 px-3 py-2.5 text-base
                  text-ink-1 focus:border-solar focus:outline-none"
              />
              <span className="flex items-center border border-l-0 border-line-strong bg-surface-2
                px-2.5 text-sm text-ink-2">
                kW
              </span>
            </span>
          </label>
        ))}

        {sizes.length < 5 ? (
          <button
            type="button"
            onClick={() => {
              setSizes([...sizes, Math.round((sizes[sizes.length - 1] ?? 5) * 1.5)]);
              setRows(null);
            }}
            className="tap border border-line px-4 py-2.5 text-sm text-ink-2 transition-colors
              hover:border-line-bright hover:text-ink-1"
          >
            Add an option
          </button>
        ) : null}

        <button
          type="button"
          onClick={() => void run()}
          disabled={running || sizes.length < 2}
          className="tap inline-flex items-center gap-2 border border-solar bg-solar px-5 py-2.5
            text-sm font-medium text-base transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {running ? 'Running…' : 'Compare'}
          <Icon name="arrow-right" size={16} />
        </button>
      </div>

      {running ? (
        <p className="mt-6 text-sm text-ink-2" role="status">
          Running {sizes.length} full estimates against the same weather record. The weather
          is already downloaded, so this is quick.
        </p>
      ) : null}

      {error ? (
        <div role="alert" className="mt-6 border border-critical/40 bg-critical/5 p-5">
          <p className="text-sm text-ink-1">{error.message}</p>
          {error.remedy ? <p className="mt-1.5 text-sm text-ink-2">{error.remedy}</p> : null}
        </div>
      ) : null}

      {/* ------------------------------------------------------------------ table */}
      {rows && currency ? (
        <div className="scroll-x mt-10">
          <table className="data-table">
            <caption className="sr-only">System sizes compared</caption>
            <thead>
              <tr>
                <th scope="col">Option</th>
                <th scope="col" className="numeric">
                  Generation
                </th>
                <th scope="col" className="numeric">
                  Offset
                </th>
                <th scope="col" className="numeric">
                  Cost
                </th>
                <th scope="col" className="numeric">
                  Saving/yr
                </th>
                <th scope="col" className="numeric">
                  Payback
                </th>
                <th scope="col" className="numeric">
                  Space
                </th>
                <th scope="col" className="numeric">
                  CO₂/yr
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const energy = formatEnergy(row.annual_kwh);
                return (
                  <tr key={row.name}>
                    <th scope="row" className="text-left text-ink-1">
                      {row.name}
                    </th>
                    <td className="numeric text-ink-1">
                      {energy.value} {energy.unit}
                      <span className="block text-2xs text-ink-4">
                        {Math.round(row.annual_kwh_lower).toLocaleString()}–
                        {Math.round(row.annual_kwh_upper).toLocaleString()} kWh
                      </span>
                    </td>
                    <td className="numeric">
                      {row.solar_offset_pct != null ? `${Math.round(row.solar_offset_pct)}%` : '—'}
                    </td>
                    <td className="numeric">
                      {row.total_capex != null ? formatCurrency(row.total_capex, currency) : '—'}
                    </td>
                    <td className="numeric">
                      {row.annual_savings != null
                        ? formatCurrency(row.annual_savings, currency)
                        : '—'}
                    </td>
                    <td className="numeric">
                      {row.payback_years != null ? `${row.payback_years} yr` : '—'}
                    </td>
                    <td className="numeric">
                      {Math.round(row.area_required_m2).toLocaleString()} m²
                    </td>
                    <td className="numeric">
                      {row.co2_tonnes_per_year != null ? `${row.co2_tonnes_per_year} t` : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {rows ? (
        <p className="mt-5 max-w-3xl text-xs leading-relaxed text-ink-3">
          A larger system generates more but offsets proportionally less, because the extra
          output arrives at midday when it is most likely to be exported rather than used.
          Payback often improves with size up to a point and then flattens — the point where
          it flattens is usually the sensible size.
        </p>
      ) : null}

      <div className="mt-10 border-t border-line pt-6">
        <Link
          href={`/result/${fromEstimateId}`}
          className="tap inline-flex items-center gap-2 border border-line px-5 py-2.5 text-sm
            text-ink-2 transition-colors hover:border-line-bright hover:text-ink-1"
        >
          <Icon name="arrow-left" size={16} />
          Back to your estimate
        </Link>
      </div>
    </div>
  );
}
