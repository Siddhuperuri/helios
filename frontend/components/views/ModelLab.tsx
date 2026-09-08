'use client';

import { useState } from 'react';

import { ModelCatalogue, ModelComparison, api } from '@/lib/api';
import {
  Button,
  Callout,
  DataTable,
  ErrorState,
  LoadingPanel,
  Panel,
  Section,
  Tag,
} from '@/components/ui';
import { BarChart } from '@/components/charts';
import { duration, num, signed } from '@/lib/format';

/**
 * Model laboratory.
 *
 * The protocol note is prominent because a comparison is only meaningful if everything
 * except the estimator is held constant. Every model here sees the identical feature
 * matrix, the identical chronological split, the identical embargo and the identical seed.
 */
export function ModelLabView({
  analysisId,
  models,
}: {
  analysisId: string;
  models: ModelCatalogue | null;
}) {
  // The whole registry. Five models is small enough that selecting a subset by default
  // would only hide part of the comparison the page exists to make.
  const [selected, setSelected] = useState<string[]>([
    'ridge',
    'random_forest',
    'extra_trees',
    'hist_gradient_boosting',
    'ensemble_four',
  ]);
  const [result, setResult] = useState<ModelComparison | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(key: string) {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }

  async function run() {
    if (selected.length < 2) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await api.compareModels(analysisId, selected));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  const slowSelected = (models?.models ?? []).filter(
    (m) => selected.includes(m.key) && m.cost === 'high',
  );

  return (
    <div className="space-y-14">
      <Section
        label="Model laboratory"
        title="Compare estimators under identical conditions"
        description="Select two or more models. Each is fitted on the same feature matrix with the same split, embargo and seed, so any difference in the results is attributable to the estimator alone."
      >
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(models?.models ?? []).map((m) => {
            const on = selected.includes(m.key);
            return (
              <button
                key={m.key}
                onClick={() => toggle(m.key)}
                aria-pressed={on}
                className={`border p-3 text-left transition-colors ${
                  on
                    ? 'border-solar bg-surface-1'
                    : 'border-line hover:border-line-bright hover:bg-surface-1'
                }`}
              >
                <div className="mb-1 flex items-start justify-between gap-2">
                  <span className={`text-xs font-medium ${on ? 'text-solar' : 'text-ink-1'}`}>
                    {m.display_name}
                  </span>
                  {m.cost === 'high' ? <Tag tone="warning">slow</Tag> : null}
                </div>
                <p className="text-2xs text-ink-4">{m.family}</p>
                <p className="mt-1.5 line-clamp-2 text-2xs leading-relaxed text-ink-3">
                  {m.description}
                </p>
              </button>
            );
          })}
        </div>

        {slowSelected.length ? (
          <div className="mt-4">
            <Callout tone="warning" title="Expect a longer run" compact>
              {slowSelected.map((m) => m.display_name).join(', ')} scale super-linearly with
              sample size and may take several minutes on a multi-year window.
            </Callout>
          </div>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center gap-4">
          <Button variant="primary" onClick={run} disabled={running || selected.length < 2}>
            {running ? 'Training…' : `Compare ${selected.length} models`}
          </Button>
          {selected.length < 2 ? (
            <p className="text-2xs text-ink-4">Select at least two models to compare.</p>
          ) : null}
        </div>

        {error ? (
          <div className="mt-5">
            <ErrorState message={error} />
          </div>
        ) : null}
      </Section>

      {running ? (
        <LoadingPanel message="Fitting each model and cross-validating — this trains every selected estimator from scratch…" />
      ) : null}

      {result ? (
        <>
          <Section label="Results" title="Ranked by hold-out RMSE">
            <DataTable
              columns={[
                { key: 'rank', label: '#', numeric: true },
                { key: 'model', label: 'Model' },
                { key: 'family', label: 'Family' },
                { key: 'rmse', label: `RMSE (${result.unit})`, numeric: true },
                { key: 'mae', label: `MAE (${result.unit})`, numeric: true },
                { key: 'r2', label: 'R²', numeric: true },
                { key: 'cv', label: 'CV RMSE', numeric: true },
                { key: 'skill', label: 'Skill', numeric: true },
                { key: 'time', label: 'Fit', numeric: true },
              ]}
              rows={result.results.map((r) => ({
                rank: String(r.rank),
                model: (
                  <span className={r.rank === 1 ? 'text-solar' : ''}>{r.display_name}</span>
                ),
                family: r.family,
                rmse: num(r.rmse_wm2, 2),
                mae: num(r.mae_wm2, 2),
                r2: num(r.r2, 4),
                cv:
                  r.cv_rmse_mean != null
                    ? `${num(r.cv_rmse_mean, 1)} ± ${num(r.cv_rmse_std, 1)}`
                    : '—',
                skill:
                  r.skill_vs_smart_persistence != null ? (
                    <span
                      className={
                        r.skill_vs_smart_persistence > 0 ? 'text-positive' : 'text-critical'
                      }
                    >
                      {signed(r.skill_vs_smart_persistence, 3)}
                    </span>
                  ) : (
                    '—'
                  ),
                time: duration(r.fit_seconds),
              }))}
              caption="Model comparison ranked by hold-out RMSE"
            />

            {result.errors.length ? (
              <div className="mt-4 space-y-2">
                {result.errors.map((e) => (
                  <Callout key={e.model} tone="critical" title={`${e.model} failed`} compact>
                    {e.error}
                  </Callout>
                ))}
              </div>
            ) : null}
          </Section>

          <Section label="Visual comparison">
            <div className="grid gap-8 lg:grid-cols-2">
              <BarChart
                items={result.results.map((r) => ({
                  label: r.display_name,
                  value: r.rmse_wm2,
                  sublabel: `R² ${num(r.r2, 3)}`,
                }))}
                title="Hold-out RMSE"
                subtitle="Lower is better"
                unit={result.unit}
                valueFormat={(v) => num(v, 1)}
              />
              <BarChart
                items={result.results
                  .filter((r) => r.cv_rmse_mean != null)
                  .map((r) => ({
                    label: r.display_name,
                    value: r.cv_rmse_mean!,
                    error: r.cv_rmse_std ?? 0,
                    sublabel: `± ${num(r.cv_rmse_std, 1)}`,
                  }))}
                title="Cross-validated RMSE"
                subtitle="Mean across rolling-origin folds, with spread"
                unit="W/m²"
                valueFormat={(v) => num(v, 1)}
                showError
                footnote="A model with a low hold-out score but wide fold spread is period-dependent rather than reliably better."
              />
            </div>
          </Section>

          <Section label="Protocol">
            <Callout tone="info" title="How this comparison was run">
              {String(result.evaluation_protocol.note)}
            </Callout>
            <p className="mt-3 text-2xs leading-relaxed text-ink-4">
              Selecting a model by hold-out RMSE alone risks choosing the one that happened to
              suit the final period. The cross-validated column is the more reliable signal, and
              a model is only worth its complexity if it also beats the baselines in the
              Performance view.
            </p>
          </Section>
        </>
      ) : null}

      {models?.future_work?.length ? (
        <Section
          label="Not implemented"
          title="Methods present in the research, deliberately excluded"
          description="Listed so the scope is legible: a reviewer can see what was considered and why it was left out, rather than wondering whether it was overlooked."
        >
          <div className="space-y-3">
            {models.future_work.map((f) => (
              <Panel key={f.name}>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <h3 className="text-xs font-medium text-ink-1">{f.name}</h3>
                  <Tag tone={f.status === 'Future Work' ? 'neutral' : 'info'}>{f.status}</Tag>
                  {f.sources.map((s) => (
                    <Tag key={s} tone="accent">
                      {s}
                    </Tag>
                  ))}
                </div>
                <p className="text-2xs leading-relaxed text-ink-2">{f.reason}</p>
              </Panel>
            ))}
          </div>
        </Section>
      ) : null}
    </div>
  );
}
