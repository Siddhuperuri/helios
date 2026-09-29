'use client';

import { useEffect, useMemo, useState } from 'react';

import { LocationStep } from '@/components/estimate/LocationStep';
import { MapPicker } from '@/components/estimate/map/MapPicker';
import { OperatingConditionCards } from '@/components/insights/OperatingConditions';
import {
  Button,
  Callout,
  ErrorState,
  Field,
  Metric,
  MetricGrid,
  Panel,
  Section,
  Select,
  TextInput,
} from '@/components/ui';
import { ApiError, api, type PointForecastResponse } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import type { Draft } from '@/lib/draft';
import { num } from '@/lib/format';

/**
 * A place, a date, an hour — and the energy that array made in it.
 *
 * The reference application had a date and a time control that changed nothing: the same
 * figure came back whatever you picked. This page is the opposite claim, and it has to earn
 * it. The hour is sent to the server, a model is trained on data ending strictly before that
 * hour, and the answer for 09:00 is a different number from the answer for 15:00.
 *
 * Two decisions worth stating.
 *
 * **The date range is bounded by what exists, not by the calendar.** The prediction is made
 * from reanalysis weather, which is published about a week behind. The picker's maximum is
 * therefore the archive's own last date, read from `/api/meta/limits` rather than hardcoded,
 * so it stays correct as the archive advances. Offering today and failing on submit would be
 * a worse interface than not offering it.
 *
 * **The four base models are shown individually.** The ensemble's number is the headline,
 * but a single figure with no working is exactly what this project set out not to build.
 * Each base model's own answer and the weight the meta-learner gave it are on the page, so
 * the blend is visible rather than asserted.
 */

const MODEL_OPTIONS = [
  { key: 'xgboost_plants', label: 'XGBoost (project model)' },
  { key: 'ensemble_four', label: 'Baseline: four-model stacking ensemble' },
  { key: 'random_forest', label: 'Baseline: Random Forest' },
  { key: 'hist_gradient_boosting', label: 'Baseline: Histogram Gradient Boosting' },
  { key: 'extra_trees', label: 'Baseline: Extremely Randomised Trees' },
  { key: 'ridge', label: 'Baseline: Ridge Regression' },
];

/** Whole hours only: the weather archive is hourly, so half past is not a real choice. */
const HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`);

export function PredictView() {
  const [location, setLocation] = useState<Draft['location']>(undefined);
  const [day, setDay] = useState('');
  const [hour, setHour] = useState('13:00');
  const [modelKey, setModelKey] = useState('xgboost_plants');

  const [result, setResult] = useState<PointForecastResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const limits = useAsync(() => api.limits(), []);
  const latestDate = (limits.data?.latest_archive_date as string | undefined) ?? '';

  // Open on the most recent date the archive covers. Deliberately not today: today has no
  // reanalysis yet, and a date the server will reject is not a helpful default.
  useEffect(() => {
    if (latestDate && !day) setDay(latestDate);
  }, [latestDate, day]);

  const ready = Boolean(location?.latitude != null && location?.longitude != null && day);

  async function run() {
    if (!ready || !location) return;
    setRunning(true);
    setError(null);
    try {
      setResult(
        await api.pointForecast({
          location: { latitude: location.latitude, longitude: location.longitude },
          target_datetime: `${day}T${hour}:00`,
          model_key: modelKey,
        }),
      );
    } catch (err) {
      setResult(null);
      setError(
        err instanceof ApiError ? err : new ApiError(String(err), 500),
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 sm:py-14">
      <header className="mb-10 max-w-3xl">
        <p className="eyebrow mb-2">Point prediction</p>
        <h1 className="text-3xl font-medium tracking-tight text-ink-1">
          Energy for one hour, at one place, on one date
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-ink-2">
          Choose where the panels are and which hour you want. Irradiance, air temperature and
          wind are fetched for that place and time, the NOCT model estimates panel temperature
          from them, and an XGBoost model trained on measured output from two solar plants
          predicts what a 5 kW reference system produces.
        </p>
      </header>

      <div className="space-y-14">
        <Section
          label="Step 1"
          title="Where are the panels?"
          description="Search for the place, share your location, or point to it on the map."
        >
          <LocationStep value={location} onChange={setLocation} />
        </Section>

        <Section
          label="Step 2"
          title="Which hour?"
          description={
            latestDate
              ? `Any hour up to ${latestDate}. The prediction is made from reanalysis weather, which is published about a week behind, so more recent dates are not available yet.`
              : 'Any hour the weather archive covers.'
          }
        >
          <Panel>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Date" htmlFor="predict-date">
                <TextInput
                  id="predict-date"
                  type="date"
                  value={day}
                  max={latestDate || undefined}
                  onChange={(event) => setDay(event.target.value)}
                />
              </Field>
              <Field label="Time" htmlFor="predict-hour" hint="Local time at the location.">
                <Select
                  id="predict-hour"
                  value={hour}
                  onChange={(event) => setHour(event.target.value)}
                >
                  {HOURS.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="Model"
                htmlFor="predict-model"
                hint="XGBoost is the project model; the others are comparison baselines."
              >
                <Select
                  id="predict-model"
                  value={modelKey}
                  onChange={(event) => setModelKey(event.target.value)}
                >
                  {MODEL_OPTIONS.map((m) => (
                    <option key={m.key} value={m.key}>
                      {m.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="flex items-end">
                <Button variant="primary" onClick={run} disabled={!ready || running}>
                  {running ? 'Predicting…' : 'Predict this hour'}
                </Button>
              </div>
            </div>
            {running ? (
              <p className="mt-4 text-xs leading-relaxed text-ink-3" role="status">
                Fetching weather and predicting. Baseline models are trained per request and
                can take up to a minute; XGBoost answers as soon as the weather arrives.
              </p>
            ) : null}
          </Panel>
        </Section>

        {error ? (
          <ErrorState
            title="Could not make that prediction"
            message={error.message}
            remedy={error.remedy}
            detail={error.detail}
            onRetry={run}
          />
        ) : null}

        {result ? <PredictionResult result={result} /> : null}
      </div>
    </div>
  );
}

/** Exported so the rendering promises can be tested against a payload directly. */
export function PredictionResult({ result }: { result: PointForecastResponse }) {
  const localHour = result.target.resolved_local.slice(11, 16);
  const localDay = result.target.resolved_local.slice(0, 10);
  const interval =
    result.interval.lower_kwh != null && result.interval.upper_kwh != null
      ? `${num(result.interval.lower_kwh, 2)}–${num(result.interval.upper_kwh, 2)} kWh at ${Math.round(
          result.interval.nominal_coverage * 100,
        )}% confidence`
      : 'No interval could be formed from the validated residuals.';

  return (
    <div className="space-y-14">
      <Section
        label="Prediction"
        title={`${localHour} on ${localDay} · ${result.resolved_place_name}`}
        description={`Predicted by ${result.model_display_name} for the declared ${num(
          result.system.dc_capacity_kwp,
          1,
        )} kWp array.`}
      >
        <MetricGrid cols={4}>
          <Metric
            label="Energy this hour"
            value={num(result.kwh_hour, 2)}
            unit="kWh"
            tone="accent"
            size="lg"
            hint={interval}
          />
          <Metric
            label="Energy that day"
            value={num(result.kwh_day, 1)}
            unit="kWh"
            hint={`Summed over ${result.hours_in_day} hours of the local day.`}
          />
          <Metric
            label="Specific yield"
            value={num(result.kwh_day / result.system.dc_capacity_kwp, 2)}
            unit="kWh/kWp"
            hint="The day's energy per kilowatt-peak installed, for comparison across sizes."
          />
          <Metric
            label="Hold-out error"
            value={num(result.training.hold_out_rmse_kwh, 3)}
            unit="kWh RMSE"
            hint={`Measured on ${result.training.n_test} hours the model never saw.`}
          />
        </MetricGrid>
      </Section>

      <Section
        label="Conditions"
        title="The inputs that drive it"
        description="Sunlight supplies the energy; temperature takes some of it back through the module's temperature coefficient; wind gives it back by cooling the module."
      >
        <MetricGrid cols={result.module_temperature_c != null ? 4 : 3}>
          <Metric
            label="Sun intensity"
            value={num(result.ghi_wm2, 0)}
            unit="W/m²"
            hint="Global horizontal irradiance for this hour."
          />
          <Metric
            label="Wind speed"
            value={num(result.wind_speed_ms, 1)}
            unit="m/s"
            hint="Convective cooling of the modules."
          />
          <Metric
            label="Air temperature"
            value={num(result.air_temperature_c, 1)}
            unit="°C"
            hint="Ambient air, not the module surface."
          />
          {result.module_temperature_c != null ? (
            <Metric
              label="Panel temperature"
              value={num(result.module_temperature_c, 1)}
              unit="°C"
              hint="Estimated by the NOCT model, with wind cooling."
            />
          ) : null}
        </MetricGrid>
      </Section>

      <Section
        label="Location"
        description={
          <>
            {num(result.latitude, 4)}, {num(result.longitude, 4)} · times shown in{' '}
            {result.target.timezone}.{' '}
            <span className="text-ink-3">Time zone {result.target.timezone_source}.</span>
          </>
        }
      >
        <MapPicker
          label={`Map showing ${result.resolved_place_name}`}
          center={{ lat: result.latitude, lon: result.longitude }}
          zoom={11}
          mode="pin"
          pin={{ lat: result.latitude, lon: result.longitude }}
          height={280}
        />
      </Section>

      <ModelBreakdown result={result} />

      {result.operating_conditions.length ? (
        <Section
          label="Insights"
          title="What the conditions mean for the array"
          description="Every note states the quantity, the threshold it is measured against, and the physical consequence. Nothing here is a verdict without its criteria."
        >
          <OperatingConditionCards notes={result.operating_conditions} />
        </Section>
      ) : null}

      <Section label="Provenance" title="Where this number comes from">
        <div className="space-y-3">
          <Callout
            tone={result.model_key === 'xgboost_plants' ? 'info' : 'warning'}
            title={result.model_key === 'xgboost_plants' ? 'Trained on measured output' : 'Modelled, not metered'}
          >
            {result.label_provenance}
          </Callout>
          <Callout tone="info" title={result.model_key === 'xgboost_plants' ? 'How it was validated' : 'No future data was used'}>
            {result.training.leakage_rule}
          </Callout>
          <Callout tone="info" title="Interval">
            {result.interval.method}
          </Callout>
          {result.warnings.map((w, i) => (
            <Callout key={i} tone="warning" title="Note" compact>
              {w}
            </Callout>
          ))}
        </div>
      </Section>
    </div>
  );
}

/**
 * What each model said, and what the ensemble did with it.
 *
 * The bars are scaled to the largest single figure on show rather than to the inverter
 * rating, because the interesting thing here is how far the four models disagree with each
 * other — and at a rating-scaled width four near-identical short bars would show nothing.
 */
function ModelBreakdown({ result }: { result: PointForecastResponse }) {
  const rows = result.per_model;
  const peak = useMemo(
    () => Math.max(result.kwh_hour, ...rows.map((r) => r.kwh_hour), 0.001),
    [result.kwh_hour, rows],
  );

  if (!rows.length) {
    return (
      <Section label="Model" title="How this prediction was made">
        <Callout tone="info" title={result.model_display_name}>
          {result.per_model_note}
        </Callout>
        {result.baselines?.length ? (
          <Panel>
            <p className="mb-3 text-xs text-ink-3">
              Held-out week, scored on the same data (kWh per 15 minutes).
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-2xs text-ink-4">
                  <th className="pb-2 font-normal">Model</th>
                  <th className="pb-2 text-right font-normal">R²</th>
                  <th className="pb-2 text-right font-normal">MAE</th>
                </tr>
              </thead>
              <tbody>
                {result.baselines.map((b) => (
                  <tr key={b.model} className={b.is_project_model ? 'font-medium text-solar' : 'text-ink-2'}>
                    <td className="py-1">{b.display_name}</td>
                    <td className="num py-1 text-right tabular-nums">{num(b.r2, 3)}</td>
                    <td className="num py-1 text-right tabular-nums">{num(b.mae_kwh, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.cross_plant?.length ? (
              <p className="mt-4 border-t border-line pt-3 text-xs leading-relaxed text-ink-2">
                On a plant it was not trained on, XGBoost scores lower:{' '}
                {result.cross_plant
                  .map((c) => `Plant ${c.train_plant} → ${c.test_plant}: R² ${num(c.r2, 2)}`)
                  .join(' · ')}
                .
              </p>
            ) : null}
          </Panel>
        ) : null}
      </Section>
    );
  }

  const spread = Math.max(...rows.map((r) => r.kwh_hour)) - Math.min(...rows.map((r) => r.kwh_hour));

  return (
    <Section
      label="Model"
      title="What each model predicted"
      description="The four base models see the identical features for this hour. The ensemble is not their average: a meta-learner fitted the weights below on out-of-fold predictions, so a model gets weight where it is actually right."
    >
      <Panel>
        <ul className="space-y-4">
          {rows.map((row) => (
            <li key={row.model}>
              <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="text-sm text-ink-1">{row.display_name}</span>
                <span className="num text-sm tabular-nums text-ink-1">
                  {num(row.kwh_hour, 3)} <span className="text-ink-4">kWh</span>
                </span>
              </div>
              <div className="h-1.5 w-full bg-surface-2">
                <div
                  className="h-full bg-ink-3"
                  style={{ width: `${Math.max(1, (row.kwh_hour / peak) * 100)}%` }}
                />
              </div>
              <p className="mt-1 font-mono text-2xs text-ink-4">
                weight {row.weight >= 0 ? '+' : ''}
                {num(row.weight, 3)}
                {row.weight_share != null
                  ? ` · ${Math.round(row.weight_share * 100)}% of the blend`
                  : ''}
              </p>
            </li>
          ))}

          <li className="border-t border-line pt-4">
            <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <span className="text-sm font-medium text-solar">{result.model_display_name}</span>
              <span className="num text-sm font-medium tabular-nums text-solar">
                {num(result.kwh_hour, 3)} <span className="text-ink-4">kWh</span>
              </span>
            </div>
            <div className="h-1.5 w-full bg-surface-2">
              <div
                className="h-full bg-solar"
                style={{ width: `${Math.max(1, (result.kwh_hour / peak) * 100)}%` }}
              />
            </div>
            <p className="mt-1 font-mono text-2xs text-ink-4">
              the blended prediction · base models disagree by {num(spread, 3)} kWh
            </p>
          </li>
        </ul>

        <p className="mt-5 border-t border-line pt-3 text-xs leading-relaxed text-ink-2">
          {result.per_model_note}
        </p>
      </Panel>
    </Section>
  );
}
