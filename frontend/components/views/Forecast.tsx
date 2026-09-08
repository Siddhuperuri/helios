'use client';

import { useState } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import { TimeSeriesChart } from '@/components/charts';
import { OperatingConditionCards } from '@/components/insights/OperatingConditions';
import {
  Button,
  Callout,
  DataTable,
  ErrorState,
  KeyValue,
  LoadingPanel,
  Metric,
  MetricGrid,
  Panel,
  Section,
} from '@/components/ui';
import { REGIME_LABEL, hourLabel, isoDate, isoDateTime, num, withPrecision } from '@/lib/format';

const HORIZONS = [24, 48, 72, 120, 168];

/**
 * The forecast workspace.
 *
 * This view is the direct answer to the reference system's central defect: there, the
 * date and time controls were inert and the same figure was returned regardless of the
 * hour requested. Here the horizon selects real numerical weather prediction, the hourly
 * profile is the output, and the energy figure is stated against a declared array with an
 * explicit integration period.
 */
export function ForecastView({ analysisId }: { analysisId: string }) {
  const [horizon, setHorizon] = useState(72);
  const forecast = useAsync(() => api.forecast(analysisId, horizon), [analysisId, horizon]);

  if (forecast.error) {
    return (
      <ErrorState
        message={forecast.error.message}
        remedy={forecast.error.remedy}
        detail={forecast.error.detail}
        onRetry={forecast.reload}
      />
    );
  }
  if (!forecast.data) return <LoadingPanel message="Retrieving numerical weather prediction…" />;

  const f = forecast.data;
  const t = f.totals;
  const rmse = Number(f.provenance.model_test_rmse_wm2 ?? 0);

  // Energy precision is tied to the interval half-width, so the displayed figure never
  // implies accuracy the forecast does not have.
  const energyHalfWidth = Math.abs((t.energy_upper_kwh - t.energy_lower_kwh) / 2);

  const powerSeries = f.series.map((d) => ({
    t: d.timestamp,
    predicted: d.ac_power_kw,
    lower: d.ac_power_lower_kw,
    upper: d.ac_power_upper_kw,
  }));

  const irradianceSeries = f.series.map((d) => ({
    t: d.timestamp,
    predicted: d.ghi_wm2,
    lower: d.ghi_lower_wm2,
    upper: d.ghi_upper_wm2,
    reference: d.clear_sky_ghi_wm2,
  }));

  return (
    <div className="space-y-14">
      <Section
        label="Forecast"
        title={`${f.location.name} · next ${horizon} hours`}
        description={
          <>
            Issued {isoDateTime(f.issued_at)} from operational numerical weather prediction.
            Energy is stated for the declared{' '}
            <span className="num text-ink-1">{num(f.system.dc_capacity_kwp, 1)} kWp</span> array
            at {num(f.system.surface_tilt_deg, 0)}° tilt, {num(f.system.surface_azimuth_deg, 0)}°
            azimuth.
          </>
        }
        actions={
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Forecast horizon">
            {HORIZONS.map((h) => (
              <button
                key={h}
                onClick={() => setHorizon(h)}
                aria-pressed={h === horizon}
                className={`border px-2.5 py-1 font-mono text-2xs transition-colors ${
                  h === horizon
                    ? 'border-solar text-solar'
                    : 'border-line text-ink-3 hover:border-line-bright hover:text-ink-1'
                }`}
              >
                {h}h
              </button>
            ))}
          </div>
        }
      >
        {f.beyond_validated_horizon ? (
          <Callout tone="warning" title="Beyond validated horizon">
            Accuracy has been measured only to {f.validated_horizon_hours} hours. Figures past
            that point are produced by the same model but their error has not been quantified
            on this dataset.
          </Callout>
        ) : null}

        <div className="mt-6">
          <MetricGrid cols={4}>
            <Metric
              label={`Energy · ${horizon} h`}
              value={withPrecision(t.energy_kwh, energyHalfWidth)}
              unit="kWh"
              size="lg"
              tone="accent"
              hint={`80% interval ${num(t.energy_lower_kwh, 0)}–${num(t.energy_upper_kwh, 0)} kWh for the declared array.`}
            />
            <Metric
              label="Peak AC power"
              value={num(t.peak_power_kw, 2)}
              unit="kW"
              size="lg"
              hint={`Reached ${hourLabel(t.peak_power_at)} UTC on ${isoDate(t.peak_power_at)}.`}
            />
            <Metric
              label="Specific yield"
              value={num(t.specific_yield_kwh_per_kwp, 2)}
              unit="kWh/kWp"
              size="lg"
              hint="Energy per unit of installed DC capacity — comparable across system sizes."
            />
            <Metric
              label="Daylight hours"
              value={num(t.n_daylight_hours, 0)}
              unit={`of ${num(t.n_hours, 0)}`}
              size="lg"
              hint="Hours with the sun above 3° elevation."
            />
          </MetricGrid>
        </div>

        {f.warnings.map((w, i) => (
          <div key={i} className="mt-4">
            <Callout tone="warning" title="Note" compact>
              {w}
            </Callout>
          </div>
        ))}
      </Section>

      <Section label="Power profile">
        <TimeSeriesChart
          data={powerSeries}
          title="AC power output"
          subtitle={`Declared ${num(f.system.dc_capacity_kwp, 1)} kWp array · inverter limit ${num(f.system.ac_capacity_kw, 2)} kW`}
          unit="kW"
          predictedLabel="Forecast power"
          intervalLabel="80% interval"
          height={280}
          footnote="Zero at night by construction: the physical chain returns no output when the sun is below the horizon, regardless of what the statistical model predicts."
        />
      </Section>

      <Section
        label="Irradiance"
        description="The clear-sky ceiling is the maximum physically possible irradiance for this location, date and hour. The gap between it and the forecast is the atmosphere's attenuation — the only part the model has to predict."
      >
        <TimeSeriesChart
          data={irradianceSeries}
          title="Global horizontal irradiance"
          subtitle="Forecast against the clear-sky ceiling"
          unit="W/m²"
          predictedLabel="Forecast GHI"
          referenceLabel="Clear-sky ceiling"
          intervalLabel="80% interval"
          height={260}
        />
      </Section>

      <Section
        label="Daily totals"
        description="Only days fully covered by the forecast window are directly comparable with one another."
      >
        <DataTable
          columns={[
            { key: 'date', label: 'Date' },
            { key: 'energy', label: 'Energy (kWh)', numeric: true },
            { key: 'range', label: '80% interval', numeric: true },
            { key: 'peak', label: 'Peak (kW)', numeric: true },
            { key: 'ghi', label: 'Peak GHI (W/m²)', numeric: true },
            { key: 'hours', label: 'Daylight h', numeric: true },
          ]}
          rows={f.daily.map((d) => ({
            date: isoDate(d.date),
            energy: num(d.energy_kwh, 1),
            range: `${num(d.energy_lower_kwh, 0)}–${num(d.energy_upper_kwh, 0)}`,
            peak: num(d.peak_power_kw, 2),
            ghi: num(d.peak_ghi_wm2, 0),
            hours: num(d.daylight_hours, 0),
          }))}
          caption="Daily forecast energy totals"
        />
      </Section>

      {f.operating_conditions.length ? (
        <Section
          label="Operating conditions"
          description="Every note states the quantity, the threshold it is measured against, and the physical consequence. Nothing here is a verdict without its criteria."
        >
          <OperatingConditionCards notes={f.operating_conditions} />
        </Section>
      ) : null}

      <Section label="Provenance">
        <Callout tone="info" title="What the interval covers">
          {f.interval_scope}
        </Callout>
        <div className="mt-4">
          <KeyValue
            items={[
              { label: 'Weather source', value: String(f.provenance.weather_source ?? '—'), mono: false },
              { label: 'Weather type', value: String(f.provenance.weather_kind ?? '—'), mono: false },
              { label: 'Retrieved', value: isoDateTime(String(f.provenance.retrieved_at ?? '')) },
              { label: 'Model test RMSE', value: `${num(rmse, 1)} W/m²` },
              { label: 'PV chain', value: String(f.provenance.pv_chain ?? '—'), mono: false },
              { label: 'Interval method', value: String(f.provenance.interval_method ?? '—'), mono: false },
            ]}
            columns={2}
          />
        </div>
      </Section>
    </div>
  );
}
