'use client';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import { TimeSeriesChart } from '@/components/charts';
import {
  Callout,
  ErrorState,
  KeyValue,
  LoadingPanel,
  Metric,
  MetricGrid,
  Panel,
  ScoreBar,
  Section,
  StatusDot,
  Tag,
} from '@/components/ui';
import { REGIME_LABEL, isoDate, num, signed, withPrecision } from '@/lib/format';

/**
 * The executive view.
 *
 * Designed to answer, in order: is this model any good, how do I know, and where does it
 * fail. The skill score is given the most prominence — not R², which sounds impressive at
 * 0.92 while saying nothing about whether the model beats assuming tomorrow repeats today.
 */
export function OverviewView({
  analysisId,
  onNavigate,
}: {
  analysisId: string;
  onNavigate: (view: any) => void;
}) {
  const summary = useAsync(() => api.analysis(analysisId), [analysisId]);
  const perf = useAsync(() => api.performance(analysisId), [analysisId]);
  const preds = useAsync(() => api.predictions(analysisId, 336), [analysisId]);

  if (summary.error) {
    return (
      <ErrorState
        message={summary.error.message}
        remedy={summary.error.remedy}
        detail={summary.error.detail}
        onRetry={summary.reload}
      />
    );
  }
  if (!summary.data) return <LoadingPanel message="Loading analysis…" />;

  const s = summary.data;
  const p = perf.data;
  const rmse = s.headline.rmse_wm2;

  const smartSkill = s.skill_scores?.smart_persistence;
  const bestBaseline = p?.baselines
    ?.filter((b) => b.metrics)
    .sort((a, b) => (a.metrics!.rmse ?? 0) - (b.metrics!.rmse ?? 0))[0];

  const regimeEntries = Object.entries(p?.by_regime ?? {});
  const worstRegime = regimeEntries.length
    ? regimeEntries.reduce((a, b) => (a[1].rmse > b[1].rmse ? a : b))
    : null;
  const bestRegime = regimeEntries.length
    ? regimeEntries.reduce((a, b) => (a[1].rmse < b[1].rmse ? a : b))
    : null;

  const series = (preds.data?.series ?? []).map((d) => ({
    t: d.timestamp,
    observed: d.observed_ghi_wm2,
    predicted: d.predicted_ghi_wm2 ?? null,
    lower: d.lower_wm2 ?? null,
    upper: d.upper_wm2 ?? null,
  }));

  return (
    <div className="space-y-14">
      {/* -------------------------------------------------------- verdict */}
      <Section
        label="Result"
        title={`${s.model.display_name} at ${s.location.name}`}
        description={
          <>
            Trained on{' '}
            <span className="num text-ink-1">{num(Number(s.validation.n_train ?? 0), 0)}</span>{' '}
            daylight hours and tested on{' '}
            <span className="num text-ink-1">{num(s.headline.n_test, 0)}</span> later hours it
            never saw. Errors below are in watts per square metre of global horizontal
            irradiance, against an observed mean of{' '}
            <span className="num text-ink-1">{num(s.headline.observed_mean_wm2, 0)} W/m²</span>.
          </>
        }
      >
        <MetricGrid cols={4}>
          <Metric
            label="Skill vs persistence"
            value={smartSkill != null ? signed(smartSkill, 3) : '—'}
            tone={smartSkill != null && smartSkill > 0.2 ? 'positive' : smartSkill != null && smartSkill > 0 ? 'warning' : 'critical'}
            size="lg"
            hint={
              smartSkill != null
                ? `${num(smartSkill * 100, 0)}% lower error than assuming today's conditions repeat. Zero would mean no improvement.`
                : undefined
            }
          />
          <Metric
            label="RMSE"
            value={num(rmse, 1)}
            unit="W/m²"
            size="lg"
            hint={`${num(s.headline.rrmse_pct, 1)}% of the mean observation.`}
          />
          <Metric
            label="MAE"
            value={num(s.headline.mae_wm2, 1)}
            unit="W/m²"
            size="lg"
            hint="Typical absolute error."
          />
          <Metric
            label="Bias"
            value={signed(s.headline.mbe_wm2, 1)}
            unit="W/m²"
            size="lg"
            tone={Math.abs(s.headline.mbe_wm2) < rmse * 0.1 ? 'positive' : 'warning'}
            hint={
              s.headline.mbe_wm2 > 0
                ? 'Positive: the model over-forecasts on average.'
                : 'Negative: the model under-forecasts on average.'
            }
          />
        </MetricGrid>

        {s.warnings.length ? (
          <div className="mt-6 space-y-2">
            {s.warnings.map((w, i) => (
              <Callout key={i} tone="warning" title="Caution" compact>
                {w}
              </Callout>
            ))}
          </div>
        ) : (
          <div className="mt-6">
            <Callout tone="positive" title="Diagnostics" compact>
              No calibration, overfitting or skill warnings were raised for this run.
            </Callout>
          </div>
        )}
      </Section>

      {/* -------------------------------------------------------- series */}
      <Section
        label="Held-out predictions"
        description="The two most recent weeks of the test period. The model never saw any of these hours during training."
      >
        {preds.loading ? (
          <LoadingPanel message="Loading predictions…" />
        ) : preds.error ? (
          <ErrorState message={preds.error.message} onRetry={preds.reload} />
        ) : (
          <TimeSeriesChart
            data={series.slice(-336)}
            title="Observed vs predicted irradiance"
            subtitle="Hourly global horizontal irradiance, daylight hours only"
            unit="W/m²"
            intervalLabel="80% prediction interval"
            height={300}
            footnote="Night hours are excluded throughout: predicting zero after dark is trivial and would inflate every goodness-of-fit statistic."
          />
        )}
      </Section>

      {/* ------------------------------------------------------ evidence */}
      <div className="grid gap-10 lg:grid-cols-2">
        <Section label="Data foundation">
          <Panel>
            <ScoreBar
              score={s.data_quality.overall_score}
              grade={s.data_quality.grade}
              counts={s.data_quality.counts}
            />
            <button
              onClick={() => onNavigate('quality')}
              className="mt-4 text-2xs text-ink-3 underline decoration-line-bright underline-offset-4
                transition-colors hover:text-solar"
            >
              See how this score is calculated →
            </button>
          </Panel>

          <div className="mt-4">
            <KeyValue
              items={[
                { label: 'Period', value: `${isoDate(String(s.dataset.period_start))} → ${isoDate(String(s.dataset.period_end))}` },
                { label: 'Hours used', value: num(Number(s.dataset.rows_used ?? 0), 0) },
                { label: 'Resolution', value: String(s.dataset.temporal_resolution ?? 'hourly') },
                { label: 'Elevation', value: `${num(Number(s.dataset.elevation_m ?? 0), 0)} m` },
              ]}
              columns={1}
            />
          </div>
        </Section>

        <Section label="Where it fails">
          {regimeEntries.length ? (
            <>
              <ul className="space-y-2.5">
                {regimeEntries
                  .sort((a, b) => b[1].rmse - a[1].rmse)
                  .map(([regime, m]) => {
                    const share = worstRegime ? m.rmse / worstRegime[1].rmse : 0;
                    return (
                      <li key={regime} className="border-b border-line pb-2.5">
                        <div className="mb-1.5 flex items-baseline justify-between gap-3">
                          <span className="flex items-center gap-2 text-xs text-ink-1">
                            <StatusDot
                              tone={
                                regime === 'sunny'
                                  ? 'positive'
                                  : regime === 'cloudy'
                                    ? 'warning'
                                    : 'critical'
                              }
                            />
                            {REGIME_LABEL[regime] ?? regime}
                          </span>
                          <span className="num text-xs text-ink-1">
                            {num(m.rmse, 1)}{' '}
                            <span className="text-ink-4">W/m²</span>
                          </span>
                        </div>
                        <div className="h-1 w-full bg-surface-3">
                          <div
                            className="h-full bg-solar/70 transition-[width] duration-500"
                            style={{ width: `${share * 100}%` }}
                          />
                        </div>
                        <p className="mt-1 font-mono text-2xs text-ink-4">
                          n={num(m.n, 0)} · R²={num(m.r2, 3)}
                        </p>
                      </li>
                    );
                  })}
              </ul>
              {worstRegime && bestRegime && bestRegime[1].rmse > 0 ? (
                <p className="mt-3 text-2xs leading-relaxed text-ink-3">
                  Error under {REGIME_LABEL[worstRegime[0]]?.toLowerCase()} conditions is{' '}
                  <span className="num text-ink-1">
                    {num(worstRegime[1].rmse / bestRegime[1].rmse, 1)}×
                  </span>{' '}
                  that under {REGIME_LABEL[bestRegime[0]]?.toLowerCase()} conditions. A single
                  aggregate accuracy figure would conceal this.
                </p>
              ) : null}
            </>
          ) : (
            <LoadingPanel message="Loading regime breakdown…" />
          )}
        </Section>
      </div>

      {/* ------------------------------------------------------ baseline */}
      <Section
        label="Is it better than doing nothing?"
        description="A model that cannot beat a one-line rule is not a result. Skill is the fractional reduction in RMSE against each reference."
      >
        {p ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {p.baselines
              .filter((b) => b.metrics)
              .map((b) => {
                const skill = b.skill_score ?? 0;
                return (
                  <Panel key={b.name} className="flex flex-col justify-between">
                    <div>
                      <p className="mb-2 text-xs text-ink-2">{b.display_name}</p>
                      <p className="num text-xl text-ink-1">{num(b.metrics!.rmse, 1)}</p>
                      <p className="text-2xs text-ink-4">W/m² RMSE</p>
                    </div>
                    <div className="mt-3 border-t border-line pt-2">
                      <Tag tone={skill > 0.2 ? 'positive' : skill > 0 ? 'warning' : 'critical'}>
                        skill {signed(skill, 3)}
                      </Tag>
                    </div>
                  </Panel>
                );
              })}
          </div>
        ) : (
          <LoadingPanel message="Loading baselines…" />
        )}
        {bestBaseline?.metrics ? (
          <p className="mt-4 text-xs leading-relaxed text-ink-2">
            The strongest reference is{' '}
            <span className="text-ink-1">{bestBaseline.display_name}</span> at{' '}
            <span className="num text-ink-1">{num(bestBaseline.metrics.rmse, 1)} W/m²</span>. The
            model reaches <span className="num text-solar">{num(rmse, 1)} W/m²</span>, a{' '}
            <span className="num text-ink-1">
              {num((1 - rmse / bestBaseline.metrics.rmse) * 100, 0)}%
            </span>{' '}
            reduction in error.
          </p>
        ) : null}
      </Section>

      {/* ------------------------------------------------- reproducibility */}
      <Section
        label="Run information"
        description="Everything needed to reproduce these numbers exactly."
      >
        <KeyValue
          items={[
            { label: 'Analysis ID', value: s.analysis_id },
            { label: 'Experiment ID', value: s.experiment_id ?? '—' },
            { label: 'Dataset fingerprint', value: String(s.dataset.fingerprint ?? '—') },
            { label: 'Validation', value: String(s.validation.strategy ?? '—'), mono: false },
            { label: 'Embargo gap', value: `${s.validation.embargo_gap_hours} h` },
            { label: 'Fit time', value: `${num(s.timings.fit_seconds, 2)} s` },
          ]}
          columns={3}
        />
      </Section>
    </div>
  );
}
