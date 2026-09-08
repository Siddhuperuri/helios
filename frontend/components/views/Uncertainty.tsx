'use client';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import { TimeSeriesChart } from '@/components/charts';
import {
  Callout,
  DataTable,
  ErrorState,
  LoadingPanel,
  Metric,
  MetricGrid,
  Panel,
  Section,
  Tag,
} from '@/components/ui';
import { REGIME_LABEL, num, signed } from '@/lib/format';

/**
 * Interval calibration.
 *
 * Coverage and width are presented together throughout, because neither means anything
 * alone: an interval spanning the entire observed range achieves perfect coverage and is
 * useless, while a very sharp interval that covers 40% of observations is misleading.
 */
export function UncertaintyView({ analysisId }: { analysisId: string }) {
  const perf = useAsync(() => api.performance(analysisId), [analysisId]);
  const preds = useAsync(() => api.predictions(analysisId, 336), [analysisId]);

  if (perf.error) {
    return <ErrorState message={perf.error.message} onRetry={perf.reload} />;
  }
  if (!perf.data) return <LoadingPanel message="Loading interval diagnostics…" />;

  const p = perf.data;
  const im = p.interval_metrics ?? {};
  const decomp = p.uncertainty_decomposition ?? {};

  if (!im.picp) {
    return (
      <Section label="Uncertainty" title="Prediction intervals">
        <Callout tone="warning" title="Not computed">
          Prediction intervals were not computed for this analysis. Re-run with intervals
          enabled to see calibration diagnostics.
        </Callout>
      </Section>
    );
  }

  const nominal = Number(im.nominal_coverage ?? 0.8);
  const picp = Number(im.picp);
  const coverageError = picp - nominal;
  const wellCalibrated = Math.abs(coverageError) <= 0.05;

  const series = (preds.data?.series ?? []).slice(-336).map((d) => ({
    t: d.timestamp,
    observed: d.observed_ghi_wm2,
    predicted: d.predicted_ghi_wm2 ?? null,
    lower: d.lower_wm2 ?? null,
    upper: d.upper_wm2 ?? null,
  }));

  return (
    <div className="space-y-14">
      <Section
        label="Calibration"
        title="Do the intervals mean what they claim?"
        description="An 80% prediction interval should contain the observation about 80% of the time. Anything else means the stated confidence is wrong, in one direction or the other."
      >
        <MetricGrid cols={4}>
          <Metric
            label="Nominal coverage"
            value={num(nominal * 100, 0)}
            unit="%"
            hint="What the interval claims."
          />
          <Metric
            label="Empirical coverage"
            value={num(picp * 100, 1)}
            unit="%"
            size="lg"
            tone={wellCalibrated ? 'positive' : Math.abs(coverageError) > 0.1 ? 'critical' : 'warning'}
            hint="PICP — the fraction of observations that actually fell inside."
          />
          <Metric
            label="Coverage error"
            value={signed(coverageError * 100, 1)}
            unit="pp"
            tone={wellCalibrated ? 'positive' : 'warning'}
            hint={coverageError < 0 ? 'Negative: intervals are too narrow.' : 'Positive: intervals are wider than needed.'}
          />
          <Metric
            label="Mean width"
            value={num(Number(im.mean_width), 1)}
            unit="W/m²"
            hint={`PINAW ${num(Number(im.pinaw), 3)} — width as a fraction of the observed range.`}
          />
        </MetricGrid>

        <div className="mt-6">
          <Callout tone={wellCalibrated ? 'positive' : 'warning'} title="Assessment">
            {wellCalibrated ? (
              <>
                Empirical coverage of {num(picp * 100, 1)}% sits within 5 percentage points of
                the {num(nominal * 100, 0)}% nominal level, so the stated interval can be taken
                at face value. Conformal calibration guarantees this marginally; the per-regime
                breakdown below shows whether it also holds within each condition.
              </>
            ) : (
              <>
                Empirical coverage of {num(picp * 100, 1)}% departs from the{' '}
                {num(nominal * 100, 0)}% nominal level by {num(Math.abs(coverageError) * 100, 1)}{' '}
                percentage points. Conformal prediction assumes calibration and test points are
                exchangeable — an assumption a strongly seasonal series only approximately
                satisfies. Read the measured coverage, not the nominal label.
              </>
            )}
          </Callout>
        </div>
      </Section>

      <Section
        label="Conditional coverage"
        title="Does calibration hold in every condition?"
        description="The conformal guarantee is marginal: it holds on average across all hours, not necessarily within each weather regime. A model can hit 80% overall while badly under-covering the cloudy hours that matter most operationally."
      >
        {im.by_regime ? (
          <DataTable
            columns={[
              { key: 'regime', label: 'Regime' },
              { key: 'picp', label: 'Coverage', numeric: true },
              { key: 'delta', label: 'vs nominal', numeric: true },
              { key: 'width', label: 'Mean width (W/m²)', numeric: true },
              { key: 'n', label: 'n', numeric: true },
            ]}
            rows={Object.entries(im.by_regime as Record<string, any>).map(([k, v]) => {
              const d = v.picp - nominal;
              return {
                regime: REGIME_LABEL[k] ?? k,
                picp: num(v.picp * 100, 1) + '%',
                delta: (
                  <span className={Math.abs(d) <= 0.05 ? 'text-positive' : 'text-warning'}>
                    {signed(d * 100, 1)} pp
                  </span>
                ),
                width: num(v.mean_width, 1),
                n: num(v.n, 0),
              };
            })}
            caption="Interval coverage by weather regime"
          />
        ) : (
          <Callout tone="info">Per-regime coverage was not computed for this run.</Callout>
        )}
        <p className="mt-3 text-2xs leading-relaxed text-ink-4">
          Interval width should differ by regime. Narrow intervals under clear skies and wide
          ones under precipitation mean the model has learned <em>when</em> it is uncertain,
          which is most of the value of a probabilistic forecast.
        </p>
      </Section>

      <Section label="Intervals in context">
        {preds.loading ? (
          <LoadingPanel message="Loading predictions…" />
        ) : (
          <TimeSeriesChart
            data={series}
            title="Prediction intervals against observations"
            subtitle="Final two weeks of the test period"
            unit="W/m²"
            intervalLabel={`${num(nominal * 100, 0)}% interval`}
            height={300}
            footnote="Observations falling outside the band are expected at roughly the complement of the nominal rate. Clusters of exceedances in one period indicate the calibration does not transfer to that regime."
          />
        )}
      </Section>

      <Section
        label="Probabilistic scores"
        title="Beyond coverage"
        description="Coverage alone can be gamed by widening the interval. These scores reward sharpness and calibration together."
      >
        <MetricGrid cols={3}>
          <Metric
            label="Pinball loss"
            value={num(Number(im.pinball_mean), 3)}
            hint="Mean quantile loss across levels. Lower is better; zero is perfect."
          />
          <Metric
            label="CRPS"
            value={num(Number(im.crps), 2)}
            unit="W/m²"
            hint="Scores the whole predictive distribution; reduces to MAE for a point forecast."
          />
          <Metric
            label="PINAW"
            value={num(Number(im.pinaw), 4)}
            hint="Mean width ÷ observed range. Lower means sharper."
          />
        </MetricGrid>
      </Section>

      <Section label="Method" title="What these intervals do and do not represent">
        <div className="space-y-4">
          {p.interval ? (
            <Panel>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Tag tone="accent">{String(p.interval.method)}</Tag>
                {String(p.interval.method).includes('conformal') ? (
                  <Tag tone="info">enhancement — not from the source papers</Tag>
                ) : null}
              </div>
              <p className="text-xs leading-relaxed text-ink-2">
                {String(p.interval.method_description)}
              </p>
              {p.interval.caveat ? (
                <p className="mt-3 border-t border-line pt-3 text-2xs leading-relaxed text-ink-3">
                  {String(p.interval.caveat)}
                </p>
              ) : null}
            </Panel>
          ) : null}

          {decomp.interpretation ? (
            <Callout tone="info" title="Does width adapt to conditions?">
              {decomp.interpretation} Mean width is{' '}
              <span className="num text-ink-1">{num(decomp.mean_interval_width, 1)} W/m²</span>{' '}
              against{' '}
              <span className="num text-ink-1">
                {num(decomp.homoscedastic_reference_width, 1)} W/m²
              </span>{' '}
              for a constant-variance assumption.
            </Callout>
          ) : null}

          {decomp.not_covered ? (
            <Callout tone="warning" title="Not represented">
              {decomp.not_covered}
            </Callout>
          ) : null}

          {decomp.sources_covered ? (
            <Callout tone="info" title="What is represented">
              {decomp.sources_covered}
            </Callout>
          ) : null}

          <Callout tone="info" title="Terminology">
            These are <strong>prediction intervals</strong>, not confidence intervals. A
            prediction interval describes where a future observation is expected to fall; a
            confidence interval describes where a parameter lies. Conflating them overstates
            what the model knows.
          </Callout>
        </div>
      </Section>
    </div>
  );
}
