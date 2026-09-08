'use client';

import { useMemo } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import { ColumnChart, HistogramChart, ScatterChart, TimeSeriesChart } from '@/components/charts';
import {
  Callout,
  DataTable,
  ErrorState,
  Info,
  LoadingPanel,
  Metric,
  MetricGrid,
  Section,
  Tag,
} from '@/components/ui';
import { REGIME_LABEL, num, signed } from '@/lib/format';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function PerformanceView({ analysisId }: { analysisId: string }) {
  const perf = useAsync(() => api.performance(analysisId), [analysisId]);
  const preds = useAsync(() => api.predictions(analysisId, 1500), [analysisId]);

  // An energy-target run publishes no predicted irradiance, so a point with nothing on the
  // y axis is dropped rather than plotted at zero. This console only creates clear-sky-index
  // analyses, so in practice the filter passes everything; it exists so the chart cannot be
  // fed an undefined coordinate if that ever changes.
  const scatter = useMemo(
    () =>
      (preds.data?.series ?? [])
        .filter((d) => d.predicted_ghi_wm2 != null)
        .map((d) => ({
          x: d.observed_ghi_wm2,
          y: d.predicted_ghi_wm2 as number,
          group: d.weather_regime,
        })),
    [preds.data],
  );

  if (perf.error) {
    return <ErrorState message={perf.error.message} remedy={perf.error.remedy} onRetry={perf.reload} />;
  }
  if (!perf.data) return <LoadingPanel message="Loading evaluation…" />;

  const p = perf.data;
  const m = p.test_metrics_physical;
  const train = p.train_metrics;
  const cv = p.cv_summary;

  const overfitRatio =
    train.rmse > 0 ? p.test_metrics_target_space.rmse / train.rmse : null;

  const hourItems = Object.entries(p.by_hour)
    .map(([h, v]) => ({ label: `${h}`, value: v.rmse, n: v.n }))
    .sort((a, b) => Number(a.label) - Number(b.label));

  const monthItems = Object.entries(p.by_month)
    .map(([mo, v]) => ({ label: MONTHS[Number(mo) - 1] ?? mo, value: v.rmse, n: v.n }))
    .sort((a, b) => MONTHS.indexOf(a.label) - MONTHS.indexOf(b.label));

  return (
    <div className="space-y-14">
      <Section
        label="Hold-out performance"
        title="Accuracy on data the model never saw"
        description="The test set is the most recent portion of the record, separated from training by an embargo gap. This is the only arrangement that reflects how the model would actually be used."
      >
        <MetricGrid cols={4}>
          <Metric label="RMSE" value={num(m.rmse, 2)} unit="W/m²" hint="Penalises large errors quadratically." />
          <Metric label="MAE" value={num(m.mae, 2)} unit="W/m²" hint="Typical absolute error." />
          <Metric label="R²" value={num(m.r2, 4)} hint="Variance explained. Identical to Nash–Sutcliffe Efficiency." />
          <Metric label="rRMSE" value={num(m.rrmse, 2)} unit="%" hint="RMSE ÷ mean observation." />
          <Metric label="Bias (MBE)" value={signed(m.mbe, 2)} unit="W/m²" hint="Positive = over-forecast." />
          <Metric label="sMAPE" value={num(m.smape, 2)} unit="%" hint="Bounded percentage error." />
          <Metric label="Observations" value={num(m.n, 0)} hint="Daylight hours evaluated." />
          <Metric
            label="Observed mean"
            value={num(m.observed_mean, 1)}
            unit="W/m²"
            hint={`Range ${num(m.observed_min, 0)}–${num(m.observed_max, 0)} W/m².`}
          />
        </MetricGrid>

        {m.notes?.length ? (
          <div className="mt-6 space-y-2">
            {m.notes.map((n, i) => (
              <Callout key={i} tone="info" compact>
                {n}
              </Callout>
            ))}
          </div>
        ) : null}

        <div className="mt-6">
          <Callout tone={overfitRatio && overfitRatio > 2 ? 'warning' : 'info'} title="Train vs test">
            Training RMSE is{' '}
            <span className="num text-ink-1">{num(train.rmse, 4)}</span> and test RMSE is{' '}
            <span className="num text-ink-1">{num(p.test_metrics_target_space.rmse, 4)}</span> in
            the modelling target's own units — a ratio of{' '}
            <span className="num text-ink-1">{overfitRatio ? num(overfitRatio, 2) : '—'}×</span>.
            Training-set metrics are shown only alongside test metrics, never alone: for a
            distance-weighted or unpruned model they approach perfection by construction and
            say nothing about generalisation.
          </Callout>
        </div>
      </Section>

      <Section
        label="Cross-validation"
        title="Rolling-origin folds"
        description="Each fold trains on everything before a cut point and validates on the block immediately after it, so the model is never fitted on data that postdates its own validation set."
      >
        {p.cv_folds.length ? (
          <>
            <MetricGrid cols={4}>
              <Metric
                label="Mean RMSE"
                value={num(Number(cv.rmse_mean), 2)}
                unit="W/m²"
                hint={`Standard deviation ${num(Number(cv.rmse_std), 2)} across ${cv.n_folds} folds.`}
              />
              <Metric label="Mean R²" value={num(Number(cv.r2_mean), 4)} hint={`± ${num(Number(cv.r2_std), 4)}`} />
              <Metric label="Best fold" value={num(Number(cv.rmse_min), 2)} unit="W/m²" tone="positive" />
              <Metric label="Worst fold" value={num(Number(cv.rmse_max), 2)} unit="W/m²" tone="warning" />
            </MetricGrid>

            <div className="mt-6">
              <DataTable
                columns={[
                  { key: 'fold', label: 'Fold', numeric: true },
                  { key: 'period', label: 'Validation period' },
                  { key: 'ntrain', label: 'Train n', numeric: true },
                  { key: 'ntest', label: 'Test n', numeric: true },
                  { key: 'rmse', label: 'RMSE', numeric: true },
                  { key: 'mae', label: 'MAE', numeric: true },
                  { key: 'r2', label: 'R²', numeric: true },
                ]}
                rows={p.cv_folds.map((f) => ({
                  fold: String(f.fold),
                  period: `${f.test_start.slice(0, 10)} → ${f.test_end.slice(0, 10)}`,
                  ntrain: num(f.n_train, 0),
                  ntest: num(f.n_test, 0),
                  rmse: num(f.metrics.rmse, 2),
                  mae: num(f.metrics.mae, 2),
                  r2: num(f.metrics.r2, 4),
                }))}
                caption="Rolling-origin cross-validation folds"
              />
            </div>
            <p className="mt-3 text-2xs leading-relaxed text-ink-4">
              Spread across folds is itself a result: it measures how much performance depends
              on which period is evaluated. A single hold-out number cannot show this.
            </p>
          </>
        ) : (
          <Callout tone="warning">Cross-validation did not run for this analysis.</Callout>
        )}
      </Section>

      <Section label="Agreement" title="Observed against predicted">
        <div className="grid gap-10 lg:grid-cols-2">
          {preds.loading ? (
            <LoadingPanel message="Loading predictions…" />
          ) : (
            <ScatterChart
              points={scatter}
              title="Observed vs predicted"
              subtitle="Every daylight hour in the test set, coloured by weather regime"
              unit="W/m²"
              height={320}
              footnote="Points above the 1:1 line are over-forecasts. Systematic departure from the diagonal indicates bias; vertical spread indicates random error."
            />
          )}

          {preds.data ? (
            <HistogramChart
              counts={preds.data.residual_histogram.counts}
              edges={preds.data.residual_histogram.edges}
              title="Residual distribution"
              subtitle="Observed minus predicted"
              unit="W/m²"
              height={320}
              markerValue={0}
              markerLabel="zero error"
              footnote={
                preds.data.residual_summary.skew != null
                  ? `Skew ${num(preds.data.residual_summary.skew, 2)}, kurtosis ${num(preds.data.residual_summary.kurtosis, 2)}. A symmetric, centred distribution indicates the model is not systematically wrong in one direction.`
                  : undefined
              }
            />
          ) : null}
        </div>
      </Section>

      <Section
        label="Error decomposition"
        title="Where the error concentrates"
        description="Aggregate accuracy averages over conditions that behave very differently. These breakdowns show which ones carry the error."
      >
        <div className="grid gap-4 sm:grid-cols-3">
          {Object.entries(p.by_regime)
            .sort((a, b) => b[1].rmse - a[1].rmse)
            .map(([regime, v]) => (
              <div key={regime} className="panel p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-xs text-ink-1">{REGIME_LABEL[regime] ?? regime}</h3>
                  <Tag
                    tone={regime === 'sunny' ? 'positive' : regime === 'cloudy' ? 'warning' : 'critical'}
                  >
                    n={num(v.n, 0)}
                  </Tag>
                </div>
                <dl className="space-y-1.5 text-2xs">
                  {[
                    ['RMSE', `${num(v.rmse, 1)} W/m²`],
                    ['MAE', `${num(v.mae, 1)} W/m²`],
                    ['Bias', `${signed(v.mbe, 1)} W/m²`],
                    ['R²', num(v.r2, 3)],
                    ['Mean obs.', `${num(v.observed_mean, 0)} W/m²`],
                  ].map(([k, val]) => (
                    <div key={k} className="flex justify-between">
                      <dt className="text-ink-3">{k}</dt>
                      <dd className="num text-ink-1">{val}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
        </div>
        <p className="mt-3 text-2xs leading-relaxed text-ink-4">
          Regimes follow Lyu &amp; Eftekharnejad: clear is cloud cover below 25%, precipitation
          denotes measurable rainfall, cloudy is the remainder.
        </p>

        <div className="mt-8 grid gap-8 lg:grid-cols-2">
          <ColumnChart
            items={hourItems}
            title="Error by hour of day (UTC)"
            subtitle="RMSE within each clock hour"
            unit="W/m²"
            footnote="Errors are typically largest around solar noon, when absolute irradiance — and therefore the scope for absolute error — is greatest."
          />
          <ColumnChart
            items={monthItems}
            title="Error by month"
            subtitle="RMSE within each calendar month present in the test set"
            unit="W/m²"
            footnote="Months are shown only where the test period covers them; a chronological split does not sample the year uniformly."
          />
        </div>
      </Section>

      <Section
        label="Reference forecasts"
        title="Comparison with simple rules"
        description="Skill score is 1 − RMSE_model / RMSE_reference. Zero means the model matches the reference; negative means the simpler rule is better."
      >
        <DataTable
          columns={[
            { key: 'name', label: 'Reference' },
            { key: 'rmse', label: 'RMSE (W/m²)', numeric: true },
            { key: 'mae', label: 'MAE (W/m²)', numeric: true },
            { key: 'skill', label: 'Skill', numeric: true },
            { key: 'coverage', label: 'Coverage', numeric: true },
            { key: 'source', label: 'Source' },
          ]}
          rows={p.baselines.map((b) => ({
            name: (
              <span title={b.description}>
                {b.display_name}
                {b.is_probabilistic ? <Tag tone="info">probabilistic</Tag> : null}
              </span>
            ),
            rmse: b.metrics ? num(b.metrics.rmse, 2) : '—',
            mae: b.metrics ? num(b.metrics.mae, 2) : '—',
            skill:
              b.skill_score != null ? (
                <span className={b.skill_score > 0 ? 'text-positive' : 'text-critical'}>
                  {signed(b.skill_score, 3)}
                </span>
              ) : (
                '—'
              ),
            coverage: `${num(b.coverage * 100, 0)}%`,
            source: b.source ?? '—',
          }))}
          caption="Baseline comparison"
        />
        <p className="mt-3 text-2xs leading-relaxed text-ink-4">
          Naive and smart persistence converge at a 24-hour horizon because solar geometry is
          nearly identical one day apart. They diverge sharply at intra-day horizons, where
          smart persistence recomputes the sun's position and naive persistence does not.
        </p>
      </Section>
    </div>
  );
}
