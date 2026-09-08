'use client';

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
  StatusDot,
  Tag,
  severityTone,
} from '@/components/ui';
import { num, signed } from '@/lib/format';

/**
 * Leakage controls and the split-strategy experiment.
 *
 * The experiment is the centrepiece: rather than asserting that random splitting inflates
 * results, it fits the identical model twice on the identical data and reports both
 * numbers. That converts a methodological claim into something a reviewer can check.
 */
export function ValidationView({ analysisId }: { analysisId: string }) {
  const leak = useAsync(() => api.leakage(analysisId), [analysisId]);

  if (leak.error) {
    return (
      <ErrorState
        message={leak.error.message}
        remedy={leak.error.remedy}
        detail={leak.error.detail}
        onRetry={leak.reload}
      />
    );
  }
  if (!leak.data) {
    return (
      <LoadingPanel message="Running the split-strategy experiment — this refits the model several times…" />
    );
  }

  const { audit, experiment } = leak.data;
  const comparison = experiment?.comparison;

  return (
    <div className="space-y-14">
      <Section
        label="Leakage audit"
        title="Could the model have seen the answer?"
        description="Each route by which information can leak from the evaluation set into training, with the mechanism this platform uses to prevent it."
      >
        <div className="space-y-3">
          {audit.map((c) => (
            <Panel key={c.key}>
              <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="flex items-center gap-2 text-sm text-ink-1">
                    <StatusDot tone={severityTone(c.status)} />
                    {c.title}
                  </h3>
                  <p className="mt-0.5 text-2xs italic text-ink-4">{c.question}</p>
                </div>
                <Tag tone={severityTone(c.status)}>{c.status.replace(/_/g, ' ')}</Tag>
              </div>
              <p className="text-xs leading-relaxed text-ink-2">{c.finding}</p>
              <p className="mt-2 border-t border-line pt-2 text-2xs leading-relaxed text-ink-4">
                <span className="font-mono uppercase tracking-[0.1em]">Mechanism</span> —{' '}
                {c.mechanism}
              </p>
            </Panel>
          ))}
        </div>
      </Section>

      {experiment && comparison ? (
        <Section
          label="Split-strategy experiment"
          title="How much does the split matter?"
          description={experiment.method_note}
        >
          <MetricGrid cols={3}>
            <Metric
              label="Chronological RMSE"
              value={num(comparison.chronological_rmse, 2)}
              unit="W/m²"
              size="lg"
              tone="positive"
              hint="Honest: trained on the past, tested on the future."
            />
            <Metric
              label="Random-split RMSE"
              value={num(comparison.random_rmse, 2)}
              unit="W/m²"
              size="lg"
              tone="critical"
              hint="Optimistic: adjacent hours land on both sides of the split."
            />
            <Metric
              label="Understatement"
              value={num(comparison.rmse_understatement_pct, 1)}
              unit="%"
              size="lg"
              tone={comparison.rmse_understatement_pct > 5 ? 'critical' : 'warning'}
              hint={`R² is overstated by ${signed(comparison.r2_overstatement, 3)}.`}
            />
          </MetricGrid>

          <div className="mt-8">
            <DataTable
              columns={[
                { key: 'strategy', label: 'Strategy' },
                { key: 'rmse', label: 'RMSE (W/m²)', numeric: true },
                { key: 'mae', label: 'MAE (W/m²)', numeric: true },
                { key: 'r2', label: 'R²', numeric: true },
                { key: 'risk', label: 'Leakage risk' },
              ]}
              rows={Object.entries(experiment.strategies).map(([key, v]) => ({
                strategy: (
                  <span title={v.description}>
                    {v.name}
                    {key === 'chronological' ? <Tag tone="positive">default</Tag> : null}
                  </span>
                ),
                rmse: num(v.rmse, 2),
                mae: num(v.mae, 2),
                r2: num(v.r2, 4),
                risk: (
                  <span
                    className={
                      v.leakage_risk.startsWith('High')
                        ? 'text-critical'
                        : v.leakage_risk.startsWith('Moderate')
                          ? 'text-warning'
                          : 'text-positive'
                    }
                  >
                    {v.leakage_risk}
                  </span>
                ),
              }))}
              caption="Model performance under different data-splitting strategies"
            />
          </div>

          <div className="mt-6 space-y-3">
            <Callout tone="warning" title="Conclusion">
              {experiment.conclusion}
            </Callout>
            <Callout tone="info" title="Why it happens">
              {experiment.why_it_matters}
            </Callout>
            <Callout tone="info" title="Provenance">
              {experiment.provenance}
            </Callout>
          </div>
        </Section>
      ) : leak.data.experiment_error ? (
        <Section label="Split-strategy experiment">
          <Callout tone="warning" title="Could not complete">
            {leak.data.experiment_error}
          </Callout>
        </Section>
      ) : null}

      <Section
        label="Anticipated questions"
        title="What a reviewer is likely to ask"
        description="Each answer points to where in this platform the evidence lives."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            ['Was temporal leakage prevented?', 'Chronological split with a 24-hour embargo, plus rolling-origin cross-validation. The audit above lists each route and its control.'],
            ['How were missing values handled?', 'Incomplete rows are dropped, never imputed. No fabricated value can enter a reported metric. See Data Quality.'],
            ['How were outliers treated?', 'Physical-range validation only. The target is never truncated by a statistical rule, because that compresses the error scale.'],
            ['What horizon is supported?', 'Baselines and skill are computed at the stated horizon. The forecast view warns explicitly beyond the validated range.'],
            ['Are scenarios real observations?', 'No. Every scenario is labelled a simulation and carries its assumptions and a validity assessment.'],
            ['Can results be reproduced?', 'Each run records a dataset fingerprint, random seed and library versions. See the Model Card.'],
          ].map(([q, a]) => (
            <Panel key={q}>
              <h3 className="mb-1.5 text-xs font-medium text-ink-1">{q}</h3>
              <p className="text-2xs leading-relaxed text-ink-2">{a}</p>
            </Panel>
          ))}
        </div>
      </Section>
    </div>
  );
}
