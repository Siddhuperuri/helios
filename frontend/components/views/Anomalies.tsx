'use client';

import { useState } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
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
  severityTone,
} from '@/components/ui';
import { isoDateTime, num, signed } from '@/lib/format';

const DETECTOR_LABEL: Record<string, string> = {
  physical: 'Physical range',
  clear_sky: 'Clear-sky ceiling',
  residual: 'Model residual',
  ramp: 'Rapid change',
  gap: 'Record gap',
};

export function AnomaliesView({ analysisId }: { analysisId: string }) {
  const [sigma, setSigma] = useState(4);
  const [detector, setDetector] = useState<string | null>(null);
  const anomalies = useAsync(() => api.anomalies(analysisId, sigma), [analysisId, sigma]);

  if (anomalies.error) {
    return <ErrorState message={anomalies.error.message} onRetry={anomalies.reload} />;
  }
  if (!anomalies.data) return <LoadingPanel message="Scanning for irregularities…" />;

  const a = anomalies.data;
  const filtered = detector ? a.anomalies.filter((x) => x.detector === detector) : a.anomalies;
  const detectors = Object.keys(a.summary.by_detector);

  return (
    <div className="space-y-14">
      <Section
        label="Anomaly detection"
        title="Irregularities in the data and in model residuals"
        description={a.summary.scope_note}
        actions={
          <div className="flex items-center gap-2">
            <label htmlFor="sigma" className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-3">
              Threshold
            </label>
            <select
              id="sigma"
              value={sigma}
              onChange={(e) => setSigma(Number(e.target.value))}
              className="border border-line-strong bg-surface-2 px-2 py-1 text-xs text-ink-1
                focus:border-solar focus:outline-none"
            >
              {[3, 4, 5, 6].map((s) => (
                <option key={s} value={s}>
                  {s}σ
                </option>
              ))}
            </select>
          </div>
        }
      >
        <MetricGrid cols={4}>
          <Metric label="Total detected" value={num(a.summary.total, 0)} size="lg" />
          <Metric
            label="High severity"
            value={num(a.summary.by_severity.high ?? 0, 0)}
            tone={(a.summary.by_severity.high ?? 0) > 0 ? 'critical' : 'positive'}
            size="lg"
          />
          <Metric
            label="Medium"
            value={num(a.summary.by_severity.medium ?? 0, 0)}
            tone="warning"
            size="lg"
          />
          <Metric label="Low" value={num(a.summary.by_severity.low ?? 0, 0)} size="lg" />
        </MetricGrid>

        <div className="mt-6 flex flex-wrap gap-1.5">
          <button
            onClick={() => setDetector(null)}
            aria-pressed={detector === null}
            className={`border px-2.5 py-1 text-2xs transition-colors ${
              detector === null
                ? 'border-solar text-solar'
                : 'border-line text-ink-3 hover:border-line-bright hover:text-ink-1'
            }`}
          >
            All ({a.summary.total})
          </button>
          {detectors.map((d) => (
            <button
              key={d}
              onClick={() => setDetector(d)}
              aria-pressed={detector === d}
              className={`border px-2.5 py-1 text-2xs transition-colors ${
                detector === d
                  ? 'border-solar text-solar'
                  : 'border-line text-ink-3 hover:border-line-bright hover:text-ink-1'
              }`}
            >
              {DETECTOR_LABEL[d] ?? d} ({a.summary.by_detector[d]})
            </button>
          ))}
        </div>
      </Section>

      <Section label="Detected events">
        {filtered.length === 0 ? (
          <Callout tone="positive" title="Nothing flagged">
            No anomalies matched the current filter at a {sigma}σ threshold.
          </Callout>
        ) : (
          <div className="space-y-3">
            {filtered.slice(0, 40).map((x, i) => (
              <Panel key={`${x.timestamp}-${i}`}>
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Tag tone={severityTone(x.severity)}>{x.severity}</Tag>
                    <Tag tone="neutral">{DETECTOR_LABEL[x.detector] ?? x.detector}</Tag>
                    <span className="num text-2xs text-ink-3">{isoDateTime(x.timestamp)}</span>
                  </div>
                  {x.deviation_sigma != null ? (
                    <span className="num text-xs text-ink-1">
                      {signed(x.deviation_sigma, 1)}σ
                    </span>
                  ) : null}
                </div>
                <p className="text-xs leading-relaxed text-ink-1">{x.description}</p>

                {x.expected_low != null || x.expected_high != null ? (
                  <dl className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-2 text-2xs">
                    {x.observed != null ? (
                      <div className="flex gap-1.5">
                        <dt className="text-ink-4">Observed</dt>
                        <dd className="num text-ink-1">{num(x.observed, 1)}</dd>
                      </div>
                    ) : null}
                    {x.expected != null ? (
                      <div className="flex gap-1.5">
                        <dt className="text-ink-4">Expected</dt>
                        <dd className="num text-ink-1">{num(x.expected, 1)}</dd>
                      </div>
                    ) : null}
                    <div className="flex gap-1.5">
                      <dt className="text-ink-4">Plausible range</dt>
                      <dd className="num text-ink-1">
                        {num(x.expected_low, 1)} – {num(x.expected_high, 1)}
                      </dd>
                    </div>
                  </dl>
                ) : null}

                <details className="mt-2.5">
                  <summary className="cursor-pointer text-2xs text-ink-4 hover:text-ink-2">
                    Possible causes ({x.possible_causes.length}) · confidence {x.confidence}
                  </summary>
                  <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-2xs leading-relaxed text-ink-3">
                    {x.possible_causes.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </details>
              </Panel>
            ))}
            {filtered.length > 40 ? (
              <p className="text-2xs text-ink-4">
                Showing the 40 most severe of {num(filtered.length, 0)} matching events.
              </p>
            ) : null}
          </div>
        )}
      </Section>

      <Section
        label="Distribution shift"
        title="Does the evaluation period resemble the training period?"
        description={a.distribution_shift_note}
      >
        {a.distribution_shift.length === 0 ? (
          <Callout tone="positive" title="Stable">
            No variable showed meaningful distributional drift between the training and
            evaluation periods.
          </Callout>
        ) : (
          <>
            <DataTable
              columns={[
                { key: 'variable', label: 'Variable' },
                { key: 'train', label: 'Training mean', numeric: true },
                { key: 'test', label: 'Evaluation mean', numeric: true },
                { key: 'smd', label: 'Std. difference', numeric: true },
                { key: 'ks', label: 'KS statistic', numeric: true },
                { key: 'severity', label: 'Severity' },
              ]}
              rows={a.distribution_shift.map((d) => ({
                variable: `${d.display_name}${d.unit ? ` (${d.unit})` : ''}`,
                train: num(d.train_mean, 2),
                test: num(d.test_mean, 2),
                smd: signed(d.standardised_mean_difference, 2),
                ks: num(d.ks_statistic, 3),
                severity: <Tag tone={severityTone(d.severity)}>{d.severity}</Tag>,
              }))}
              caption="Distribution shift between training and evaluation periods"
            />
            <p className="mt-3 text-2xs leading-relaxed text-ink-4">
              A standardised mean difference above 0.5 is a substantial shift. Because the split
              is chronological, some seasonal drift is expected and is not in itself a defect —
              but it does bound how far the reported accuracy generalises to other periods.
            </p>
          </>
        )}
      </Section>
    </div>
  );
}
