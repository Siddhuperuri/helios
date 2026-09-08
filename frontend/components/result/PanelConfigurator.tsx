'use client';

import { useEffect, useState } from 'react';

import { Icon } from '@/components/site/Icon';
import { EstimateError, estimateApi, type EstimateResult } from '@/lib/estimate';

/**
 * The panel configuration, and the control that changes it (§4).
 *
 * The rule this component exists to honour: **changing the number of panels re-runs the
 * prediction, it does not rescale a number in the browser.** Output is not linear in
 * capacity — a larger array clips harder against the same inverter, and the loss stack and
 * temperature model both act per hour — so multiplying the previous answer by a ratio
 * would produce a figure that no physical system corresponds to. Every step of the counter
 * therefore goes back to the server and the whole chain runs again on the cached weather.
 *
 * That costs about a second, which is why the count is committed on Apply rather than on
 * every keystroke: a stepper that fired a full recalculation per click would queue up work
 * nobody asked for.
 *
 * What is displayed is always `count × watts`, recomputed by the backend. The capacity
 * shown is the capacity modelled — there is no path here where the headline figure belongs
 * to a different array than the one described.
 */

interface Props {
  result: EstimateResult;
  onUpdated: (updated: EstimateResult) => void;
}

export function PanelConfigurator({ result, onUpdated }: Props) {
  const panels = result.system.panels;
  // §13: "DC" is only meaningful next to "AC", which beginners are never shown.
  const capacityUnit = result.mode === 'detailed' ? 'kW DC' : 'kW';
  const [count, setCount] = useState(panels.count);
  const [watts, setWatts] = useState(panels.watts);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<EstimateError | null>(null);

  // A recalculation returns a new configuration; the controls follow it rather than
  // holding the value the user typed before the server had its say.
  useEffect(() => {
    setCount(panels.count);
    setWatts(panels.watts);
  }, [panels.count, panels.watts]);

  const pending = count !== panels.count || watts !== panels.watts;
  const previewKwp = (count * watts) / 1000;
  const canEdit = Boolean(result.estimate_id && result.input);

  async function apply() {
    if (!result.estimate_id || !pending) return;
    setBusy(true);
    setError(null);
    try {
      onUpdated(
        await estimateApi.update(result.estimate_id, {
          system: { panel_count: count, panel_watts: watts },
        }),
      );
    } catch (err) {
      setError(
        err instanceof EstimateError
          ? err
          : new EstimateError('The estimate could not be recalculated.', 500),
      );
      // Put the controls back to what is actually modelled, so the numbers on screen and
      // the numbers in the control never disagree.
      setCount(panels.count);
      setWatts(panels.watts);
    } finally {
      setBusy(false);
    }
  }

  const sourceLabel =
    panels.source === 'existing_system'
      ? 'Your existing array'
      : panels.source === 'user_specified'
        ? 'Your chosen configuration'
        : 'Our recommendation';

  return (
    <section className="border border-line bg-surface-1">
      <div className="border-b border-line p-5 sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <p className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
            {sourceLabel}
          </p>
          {!panels.watts_known ? (
            <span className="tag border-warning/50 text-warning">Wattage assumed</span>
          ) : null}
        </div>

        <p className="num mt-3 text-2xl font-medium text-ink-1">
          {panels.count} × {panels.watts} W
          <span className="ml-3 text-ink-3">
            ≈ {panels.capacity_kwp.toFixed(2)} {capacityUnit}
          </span>
        </p>
        <p className="mt-2 max-w-2xl text-xs leading-relaxed text-ink-2">{panels.note}</p>
        {panels.model ? (
          <p className="mt-1.5 text-xs text-ink-3">Panel: {panels.model}</p>
        ) : null}
      </div>

      {canEdit ? (
        <div className="p-5 sm:p-6">
          <div className="flex flex-wrap items-end gap-5">
            {/* ------------------------------------------------------- panel count */}
            <div>
              <label
                htmlFor="panel-count"
                className="mb-1.5 block text-xs font-medium text-ink-1"
              >
                Number of panels
              </label>
              <div className="flex items-stretch">
                <button
                  type="button"
                  onClick={() => setCount((c) => Math.max(1, c - 1))}
                  disabled={busy || count <= 1}
                  aria-label="One fewer panel"
                  className="tap flex items-center justify-center border border-line-strong
                    px-3 text-lg text-ink-1 transition-colors hover:border-solar
                    hover:text-solar disabled:opacity-40"
                >
                  −
                </button>
                <input
                  id="panel-count"
                  type="number"
                  min={1}
                  max={1000000}
                  value={count}
                  disabled={busy}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    if (Number.isFinite(next) && next >= 1) setCount(Math.floor(next));
                  }}
                  className="num w-24 border-y border-line-strong bg-surface-1 px-3 py-2.5
                    text-center text-base text-ink-1 focus:border-solar focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => setCount((c) => c + 1)}
                  disabled={busy}
                  aria-label="One more panel"
                  className="tap flex items-center justify-center border border-line-strong
                    px-3 text-lg text-ink-1 transition-colors hover:border-solar
                    hover:text-solar disabled:opacity-40"
                >
                  +
                </button>
              </div>
            </div>

            {/* ----------------------------------------------------- panel wattage */}
            <div>
              <label
                htmlFor="panel-watts"
                className="mb-1.5 block text-xs font-medium text-ink-1"
              >
                Watts per panel
              </label>
              <div className="flex items-stretch">
                <input
                  id="panel-watts"
                  type="number"
                  min={50}
                  max={1000}
                  step={10}
                  value={watts}
                  disabled={busy}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    if (Number.isFinite(next)) setWatts(Math.round(next));
                  }}
                  className="num w-24 border border-line-strong bg-surface-1 px-3 py-2.5
                    text-base text-ink-1 focus:border-solar focus:outline-none"
                />
                <span className="flex items-center border border-l-0 border-line-strong
                  bg-surface-2 px-3 text-sm text-ink-2">
                  W
                </span>
              </div>
            </div>

            {/* ---------------------------------------------------------- pending */}
            {pending ? (
              <div className="animate-fade-rise">
                <p className="mb-1.5 text-xs font-medium text-ink-1">That would be</p>
                <p className="num py-2.5 text-base text-solar">
                  {previewKwp.toFixed(2)} {capacityUnit}
                </p>
              </div>
            ) : null}

            <button
              type="button"
              onClick={() => void apply()}
              disabled={busy || !pending}
              className="tap inline-flex items-center gap-2 border border-solar bg-solar px-5
                py-2.5 text-sm font-medium text-base transition-opacity hover:opacity-90
                disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? 'Recalculating…' : 'Recalculate'}
              {!busy ? <Icon name="arrow-right" size={16} /> : null}
            </button>
          </div>

          <p className="mt-4 max-w-2xl text-xs leading-relaxed text-ink-3">
            Changing the number of panels recalculates the system capacity and re-runs the
            full generation model against your location&apos;s weather — it does not simply
            scale the figures on this page. Output is not exactly proportional to size,
            because a larger array clips harder against the same inverter.
          </p>

          {error ? (
            <p role="alert" className="mt-3 flex items-start gap-2 text-sm text-critical">
              <Icon name="alert" size={16} className="mt-0.5" />
              <span>
                {error.message}
                {error.remedy ? ` ${error.remedy}` : ''}
              </span>
            </p>
          ) : null}
        </div>
      ) : (
        <p className="p-5 text-xs leading-relaxed text-ink-3 sm:p-6">
          This estimate was saved before panel configuration was editable. Run a new one to
          adjust it.
        </p>
      )}
    </section>
  );
}
