'use client';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import { BarChart, LineChart } from '@/components/charts';
import {
  Callout,
  ErrorState,
  LoadingPanel,
  Panel,
  Section,
  Tag,
} from '@/components/ui';
import { humanise, num } from '@/lib/format';

const FEATURE_LABEL: Record<string, string> = {
  temperature_c: 'Air temperature',
  relative_humidity_pct: 'Relative humidity',
  dew_point_c: 'Dew point',
  surface_pressure_hpa: 'Surface pressure',
  wind_speed_ms: 'Wind speed',
  wind_dir_sin: 'Wind direction (sin)',
  wind_dir_cos: 'Wind direction (cos)',
  cloud_cover_pct: 'Cloud cover',
  precipitation_mm: 'Precipitation',
  cos_zenith: 'cos(solar zenith)',
  solar_zenith_deg: 'Solar zenith angle',
  solar_elevation_deg: 'Solar elevation',
  cos_aoi: 'cos(angle of incidence)',
  aoi_deg: 'Angle of incidence',
  air_mass: 'Optical air mass',
  clear_sky_ghi_wm2: 'Clear-sky GHI',
  extraterrestrial_horizontal_wm2: 'Extraterrestrial irradiance',
  hour_sin: 'Hour (sin)',
  hour_cos: 'Hour (cos)',
  doy_sin: 'Day of year (sin)',
  doy_cos: 'Day of year (cos)',
};

const label = (f: string) => FEATURE_LABEL[f] ?? humanise(f);

export function ExplainView({ analysisId }: { analysisId: string }) {
  const explain = useAsync(() => api.explain(analysisId), [analysisId]);

  if (explain.error) {
    return <ErrorState message={explain.error.message} onRetry={explain.reload} />;
  }
  if (!explain.data) {
    return <LoadingPanel message="Computing permutation importance — this refits nothing but re-scores the model many times…" />;
  }

  const e = explain.data;
  const grouped = e.importance.grouped;
  const curves = e.partial_dependence.filter((c) => !c.error && c.grid && c.values);

  return (
    <div className="space-y-14">
      <Section
        label="Explainability"
        title="What drives the prediction"
        description={
          <>
            Importance is measured on <strong>held-out data</strong> by permutation: each
            input is shuffled and the resulting rise in error is recorded. Measuring on the
            training set would report what the model memorised rather than what actually
            carries signal.
          </>
        }
      >
        {e.narrative.length ? (
          <div className="mb-8 space-y-2">
            {e.narrative.map((line, i) => (
              <Callout key={i} tone="info" compact>
                {line}
              </Callout>
            ))}
          </div>
        ) : null}

        <BarChart
          items={grouped.map((g) => ({
            label: g.group,
            value: g.rmse_increase_mean,
            error: g.rmse_increase_std,
            sublabel: `${num(g.share * 100, 0)}% of measured effect`,
          }))}
          title="Grouped importance"
          subtitle="Whole groups of collinear features permuted together"
          valueFormat={(v) => num(v, 4)}
          showError
          footnote={e.importance.caveat}
        />
      </Section>

      <Section
        label="Per-feature"
        title="Individual permutation importance"
        description="Read alongside the grouped figures above. Where several features encode the same underlying quantity, permuting one alone lets the model recover the information from its partners, so each individually looks less important than the group truly is."
      >
        <BarChart
          items={e.importance.per_feature
            .slice(0, 14)
            .map((f) => ({
              label: label(f.feature),
              value: f.importance_mean,
              error: f.importance_std,
              sublabel: `#${f.rank}`,
            }))}
          title="Top features by increase in error when permuted"
          subtitle={`${e.importance.method}, ${e.importance.n_repeats} repeats, ${e.importance.evaluated_on}`}
          valueFormat={(v) => num(v, 5)}
          showError
        />
      </Section>

      {curves.length ? (
        <Section
          label="Partial dependence"
          title="How the prediction responds to each input"
          description="Each curve sweeps one input across its range while averaging over the others, showing the direction and magnitude of its effect on the model's output."
        >
          <div className="grid gap-8 sm:grid-cols-2">
            {curves.slice(0, 6).map((c) => (
              <LineChart
                key={c.feature}
                points={(c.grid ?? []).map((g, i) => ({ x: g, y: c.values![i]! }))}
                title={label(c.feature)}
                subtitle={`Effect size ${num(c.effect_size, 3)} in target units`}
                xLabel={label(c.feature)}
                yLabel={e.target}
                height={165}
              />
            ))}
          </div>
          <div className="mt-5">
            <Callout tone="warning" title="How to read these">
              {e.partial_dependence_caveat}
            </Callout>
          </div>
        </Section>
      ) : null}

      <Section label="Method" title="What is and is not being claimed">
        <div className="grid gap-3 sm:grid-cols-2">
          <Panel>
            <div className="mb-2">
              <Tag tone="accent">measured</Tag>
            </div>
            <h3 className="mb-1.5 text-xs font-medium text-ink-1">Permutation importance</h3>
            <p className="text-2xs leading-relaxed text-ink-2">
              Scored with {e.importance.scoring.replace(/_/g, ' ')} on the held-out test set
              across {e.importance.n_repeats} repeats. The reported standard deviation is the
              spread across those repeats, so a feature whose bar is smaller than its error bar
              has no reliably measurable effect.
            </p>
          </Panel>
          <Panel>
            <div className="mb-2">
              <Tag tone="warning">correlation, not causation</Tag>
            </div>
            <h3 className="mb-1.5 text-xs font-medium text-ink-1">Interpretation limit</h3>
            <p className="text-2xs leading-relaxed text-ink-2">
              These figures describe what the model relies on, not what physically causes
              irradiance. Temperature is predictive of sunshine because both respond to the
              same synoptic conditions — warming the air would not brighten the sun. The
              Scenarios view separates these two pathways explicitly.
            </p>
          </Panel>
        </div>
      </Section>
    </div>
  );
}
