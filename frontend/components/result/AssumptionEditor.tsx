'use client';

import { useState } from 'react';

import { Icon } from '@/components/site/Icon';
import { EstimateError, estimateApi, type EstimateResult } from '@/lib/estimate';

/**
 * Editing the assumptions behind a result (§28).
 *
 * The assumptions panel would be a decoration without this. Telling somebody "we assumed
 * ₹7.50 a unit and a typical installed cost" is only half the promise; the other half is
 * that they can put in their own bill and their own quote and watch every figure move.
 * That is what turns a planning estimate into *their* estimate.
 *
 * The edit re-runs the whole pipeline rather than patching figures, because the inputs are
 * not independent: a different tariff changes the savings, a different panel changes the
 * yield, and a different system size changes both plus the space required. A partial
 * recompute would produce a result whose parts disagreed with each other. It is fast
 * because the weather for the location is already cached.
 *
 * Only the assumptions worth arguing with are exposed. Panel temperature coefficients and
 * transposition models are on the page for inspection but not for editing — someone who
 * genuinely needs to vary those belongs in the analysis console, which is linked from here.
 */

interface Props {
  result: EstimateResult;
  onUpdated: (updated: EstimateResult) => void;
}

export function AssumptionEditor({ result, onUpdated }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<EstimateError | null>(null);

  const economics = result.economics;
  const [tariff, setTariff] = useState<string>(
    String(findAssumption(result, 'electricity_tariff') ?? ''),
  );
  const [systemCost, setSystemCost] = useState<string>(
    economics ? String(Math.round(economics.system_cost)) : '',
  );
  const [capacity, setCapacity] = useState<string>(String(result.system.capacity_kwp));
  const [lifetime, setLifetime] = useState<string>(
    String(economics?.lifetime_years ?? 25),
  );
  const [shading, setShading] = useState<string>(
    (result.input?.shading_level as string) ?? 'unknown',
  );

  const canEdit = Boolean(result.estimate_id && result.input);

  async function apply() {
    if (!result.estimate_id) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await estimateApi.update(result.estimate_id, {
        system: {
          capacity_kwp: numberOrNull(capacity),
          shading_level: shading,
          lifetime_years: numberOrNull(lifetime) ?? undefined,
        },
        money: {
          tariff_per_kwh: numberOrNull(tariff),
          system_cost: numberOrNull(systemCost),
        },
      });
      onUpdated(updated);
      setOpen(false);
    } catch (err) {
      setError(
        err instanceof EstimateError
          ? err
          : new EstimateError('The estimate could not be updated.', 500),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit) {
    return (
      <p className="mt-6 border border-line bg-surface-2 px-4 py-3 text-xs leading-relaxed text-ink-3">
        This estimate was saved before editing was supported. Run a new one to change its
        assumptions.
      </p>
    );
  }

  return (
    <div className="mt-8 border border-line bg-surface-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="tap flex w-full items-center justify-between gap-3 px-5 py-4 text-left
          transition-colors hover:bg-surface-2"
      >
        <span>
          <span className="block text-sm font-medium text-ink-1">
            Change these assumptions
          </span>
          <span className="mt-0.5 block text-xs text-ink-2">
            Put in your own rate, your own quote, or a different system size, and every
            figure recalculates.
          </span>
        </span>
        <Icon name={open ? 'close' : 'pencil'} size={18} className="shrink-0 text-ink-3" />
      </button>

      {open ? (
        <div className="border-t border-line p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Electricity rate"
              hint="From your bill, per unit."
              prefix={result.currency.symbol}
              value={tariff}
              onChange={setTariff}
              min={0}
              step="0.01"
            />
            <Field
              label="System cost"
              hint="From a real quote, if you have one."
              prefix={result.currency.symbol}
              value={systemCost}
              onChange={setSystemCost}
              min={0}
              step="1000"
            />
            <Field
              label="System size"
              hint="Model a different size."
              suffix="kW"
              value={capacity}
              onChange={setCapacity}
              min={0.5}
              step="0.5"
            />
            <Field
              label="System lifetime"
              hint="Used for the payback projection."
              suffix="years"
              value={lifetime}
              onChange={setLifetime}
              min={5}
              max={40}
              step="1"
            />

            <label className="block sm:col-span-2">
              <span className="mb-1.5 block text-xs font-medium text-ink-1">Shading</span>
              <select
                value={shading}
                onChange={(event) => setShading(event.target.value)}
                className="w-full border border-line-strong bg-surface-1 px-3 py-2.5 text-sm
                  text-ink-1 focus:border-solar focus:outline-none"
              >
                <option value="none">Nothing shades it</option>
                <option value="light">A little shade</option>
                <option value="moderate">Some shade</option>
                <option value="heavy">A lot of shade</option>
                <option value="unknown">Not sure</option>
              </select>
              <span className="mt-1 block text-2xs text-ink-3">
                Answering this rather than leaving it unknown also narrows the range on your
                result.
              </span>
            </label>
          </div>

          {error ? (
            <p role="alert" className="mt-4 flex items-start gap-2 text-sm text-critical">
              <Icon name="alert" size={16} className="mt-0.5" />
              <span>
                {error.message}
                {error.remedy ? ` ${error.remedy}` : ''}
              </span>
            </p>
          ) : null}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void apply()}
              disabled={busy}
              className="tap inline-flex items-center gap-2 border border-solar bg-solar px-5
                py-2.5 text-sm font-medium text-base transition-opacity hover:opacity-90
                disabled:opacity-60"
            >
              {busy ? 'Recalculating…' : 'Recalculate'}
              <Icon name="arrow-right" size={16} />
            </button>
            <p className="text-2xs leading-relaxed text-ink-3">
              This replaces the saved result at this link. The weather data is already
              downloaded, so it takes a second.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Field({
  label,
  hint,
  value,
  onChange,
  prefix,
  suffix,
  min,
  max,
  step,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  prefix?: string;
  suffix?: string;
  min?: number;
  max?: number;
  step?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-ink-1">{label}</span>
      <span className="flex items-stretch">
        {prefix ? (
          <span
            className="num flex items-center border border-r-0 border-line-strong bg-surface-2
              px-2.5 text-sm text-ink-2"
            aria-hidden="true"
          >
            {prefix}
          </span>
        ) : null}
        <input
          type="number"
          inputMode="decimal"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(event) => onChange(event.target.value)}
          className="num w-full border border-line-strong bg-surface-1 px-3 py-2.5 text-sm
            text-ink-1 focus:border-solar focus:outline-none"
        />
        {suffix ? (
          <span className="flex items-center border border-l-0 border-line-strong bg-surface-2
            px-2.5 text-sm text-ink-2">
            {suffix}
          </span>
        ) : null}
      </span>
      <span className="mt-1 block text-2xs text-ink-3">{hint}</span>
    </label>
  );
}

function numberOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function findAssumption(result: EstimateResult, key: string): string | number | null {
  const found = result.assumptions.find((a) => a.key === key);
  return found && typeof found.value !== 'boolean' ? found.value : null;
}
