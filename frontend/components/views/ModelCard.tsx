'use client';

import { useState } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import {
  Callout,
  ErrorState,
  KeyValue,
  LoadingPanel,
  Panel,
  Section,
  Tag,
} from '@/components/ui';
import { isoDate, num, signed } from '@/lib/format';

/**
 * Model documentation.
 *
 * Written at two levels. The plain-language explanation is not a simplification of the
 * technical one — it is a different, equally accurate account for a reader who needs to
 * judge whether to trust the output without being able to audit the method.
 */
export function ModelCardView({ analysisId }: { analysisId: string }) {
  const [mode, setMode] = useState<'plain' | 'technical'>('plain');
  const card = useAsync(() => api.modelCard(analysisId), [analysisId]);

  if (card.error) return <ErrorState message={card.error.message} onRetry={card.reload} />;
  if (!card.data) return <LoadingPanel message="Loading model documentation…" />;

  const c = card.data;
  const perf = c.performance.hold_out ?? {};
  const cv = c.performance.cross_validation ?? {};
  const repro = c.reproducibility ?? {};
  const training = c.training_data ?? {};

  return (
    <div className="space-y-14">
      <Section
        label="Model card"
        title={c.model_name}
        description={c.objective}
        actions={
          <div className="flex" role="group" aria-label="Explanation level">
            {(['plain', 'technical'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                className={`border px-3 py-1 text-2xs capitalize transition-colors ${
                  mode === m
                    ? 'border-solar text-solar'
                    : 'border-line text-ink-3 hover:border-line-bright hover:text-ink-1'
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        }
      >
        {mode === 'plain' ? (
          <div className="max-w-3xl space-y-4">
            {Object.entries(c.plain_language).map(([k, v]) => (
              <Panel key={k}>
                <h3 className="mb-2 font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
                  {k.replace(/_/g, ' ')}
                </h3>
                <p className="text-sm leading-relaxed text-ink-1">{v}</p>
              </Panel>
            ))}
          </div>
        ) : (
          <div className="max-w-3xl space-y-4">
            {Object.entries(c.technical_summary).map(([k, v]) => (
              <Panel key={k}>
                <h3 className="mb-2 font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
                  {k.replace(/_/g, ' ')}
                </h3>
                <p className="text-sm leading-relaxed text-ink-1">{v}</p>
              </Panel>
            ))}
            <Panel>
              <h3 className="mb-2 font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
                Hyperparameters
              </h3>
              <pre className="num overflow-x-auto text-2xs leading-relaxed text-ink-2">
                {JSON.stringify(c.hyperparameters, null, 2)}
              </pre>
              {c.hyperparameter_provenance ? (
                <p className="mt-3 border-t border-line pt-3 text-2xs leading-relaxed text-ink-3">
                  {c.hyperparameter_provenance}
                </p>
              ) : null}
            </Panel>
            {c.ensemble_weights?.length ? (
              <Panel>
                <h3 className="mb-2 font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
                  Learned base-model weights
                </h3>
                <KeyValue
                  items={c.ensemble_weights.map((w) => ({
                    label: w.display_name,
                    value: `${w.weight >= 0 ? '+' : ''}${w.weight.toFixed(3)}${
                      w.weight_share != null
                        ? ` · ${Math.round(w.weight_share * 100)}% of the blend`
                        : ''
                    }`,
                  }))}
                  columns={1}
                />
                <p className="mt-3 border-t border-line pt-3 text-2xs leading-relaxed text-ink-3">
                  Fitted by the meta-learner on out-of-fold predictions, not assumed. A
                  negative weight means that model is used to correct another rather than to
                  predict directly.
                </p>
              </Panel>
            ) : null}
          </div>
        )}
      </Section>

      <Section label="Specification">
        <div className="grid gap-8 lg:grid-cols-2">
          <div>
            <p className="eyebrow mb-3">Target</p>
            <KeyValue
              items={Object.entries(c.target_variable).map(([k, v]) => ({
                label: k.replace(/_/g, ' '),
                value: v,
                mono: false,
              }))}
              columns={1}
            />
          </div>
          <div>
            <p className="eyebrow mb-3">Training data</p>
            <KeyValue
              items={[
                { label: 'Source', value: String(training.source ?? '—'), mono: false },
                { label: 'Type', value: String(training.kind ?? '—') },
                {
                  label: 'Period',
                  value: `${isoDate(String(training.period_start))} → ${isoDate(String(training.period_end))}`,
                },
                { label: 'Rows used', value: num(Number(training.rows_used ?? 0), 0) },
                { label: 'Resolution', value: String(training.temporal_resolution ?? '—') },
                { label: 'Fingerprint', value: String(training.fingerprint ?? '—') },
              ]}
              columns={1}
            />
          </div>
        </div>

        <div className="mt-8">
          <p className="eyebrow mb-3">Input variables ({c.input_variables.length})</p>
          <div className="flex flex-wrap gap-1.5">
            {c.input_variables.map((v) => (
              <span key={v} className="num border border-line px-1.5 py-0.5 text-2xs text-ink-3">
                {v}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-8">
          <p className="eyebrow mb-3">Preprocessing</p>
          <KeyValue
            items={Object.entries(c.preprocessing).map(([k, v]) => ({
              label: k.replace(/_/g, ' '),
              value: String(v),
              mono: false,
            }))}
            columns={2}
          />
        </div>
      </Section>

      <Section label="Measured performance">
        <KeyValue
          items={[
            { label: 'RMSE', value: `${num(perf.rmse, 2)} W/m²` },
            { label: 'MAE', value: `${num(perf.mae, 2)} W/m²` },
            { label: 'R² / NSE', value: num(perf.r2, 4) },
            { label: 'Bias', value: `${signed(perf.mbe, 2)} W/m²` },
            { label: 'rRMSE', value: `${num(perf.rrmse, 2)}%` },
            { label: 'Test observations', value: num(perf.n, 0) },
            {
              label: 'CV RMSE',
              value: cv.rmse_mean != null ? `${num(cv.rmse_mean, 2)} ± ${num(cv.rmse_std, 2)}` : '—',
            },
            {
              label: 'Interval coverage',
              value:
                c.uncertainty?.metrics?.picp != null
                  ? `${num(c.uncertainty.metrics.picp * 100, 1)}%`
                  : '—',
            },
          ]}
          columns={3}
        />
        <div className="mt-4">
          <KeyValue
            items={Object.entries(c.performance.skill_scores ?? {}).map(([k, v]) => ({
              label: `Skill vs ${k.replace(/_/g, ' ')}`,
              value: signed(Number(v), 3),
            }))}
            columns={2}
          />
        </div>
      </Section>

      <Section
        label="Known failure modes"
        title="When this model should not be trusted"
        description="Stated explicitly rather than left for a user to discover."
      >
        <div className="space-y-3">
          {c.known_failure_modes.map((f) => (
            <Panel key={f.condition}>
              <h3 className="mb-1.5 flex items-center gap-2 text-xs font-medium text-ink-1">
                <Tag tone="warning">condition</Tag>
                {f.condition}
              </h3>
              <p className="text-2xs leading-relaxed text-ink-2">{f.evidence}</p>
            </Panel>
          ))}
        </div>
      </Section>

      <Section label="Limitations">
        <ul className="max-w-3xl space-y-2.5">
          {c.limitations.map((l, i) => (
            <li key={i} className="flex gap-3 border-b border-line pb-2.5">
              <span className="num shrink-0 text-2xs text-ink-4">{String(i + 1).padStart(2, '0')}</span>
              <span className="text-xs leading-relaxed text-ink-2">{l}</span>
            </li>
          ))}
        </ul>
        {c.warnings.length ? (
          <div className="mt-5 space-y-2">
            {c.warnings.map((w, i) => (
              <Callout key={i} tone="warning" compact>
                {w}
              </Callout>
            ))}
          </div>
        ) : null}
      </Section>

      <Section
        label="Reproducibility"
        title="Exactly what produced these numbers"
        description="An identical dataset fingerprint with an identical seed and library versions reproduces this run exactly."
      >
        <KeyValue
          items={[
            { label: 'Model version', value: c.version },
            { label: 'Random seed', value: String(repro.random_seed ?? '—') },
            { label: 'Python', value: String(repro.python_version ?? '—') },
            { label: 'NumPy', value: String(repro.numpy_version ?? '—') },
            { label: 'pandas', value: String(repro.pandas_version ?? '—') },
            { label: 'scikit-learn', value: String(repro.scikit_learn_version ?? '—') },
            { label: 'Platform', value: String(repro.platform ?? '—') },
            { label: 'Dataset fingerprint', value: String(training.fingerprint ?? '—') },
          ]}
          columns={2}
        />
      </Section>
    </div>
  );
}
