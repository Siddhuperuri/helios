'use client';

import { useState } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import {
  Button,
  Callout,
  DataTable,
  ErrorState,
  LoadingPanel,
  Section,
  Tag,
} from '@/components/ui';
import { isoDate, isoDateTime, num, signed } from '@/lib/format';

/**
 * Experiment history.
 *
 * The comparison endpoint refuses to rank runs that are not comparable — different
 * locations, periods or targets — and that refusal is surfaced rather than hidden. Ranking
 * a Reykjavík run against a Hyderabad one by RMSE would be meaningless, since the two have
 * completely different irradiance regimes.
 */
export function ExperimentsView() {
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Record<string, any> | null>(null);
  const [comparing, setComparing] = useState(false);
  const experiments = useAsync(() => api.experiments(50), []);

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-6),
    );
    setComparison(null);
  }

  async function compare() {
    if (selected.length < 2) return;
    setComparing(true);
    try {
      setComparison(await api.compareExperiments(selected));
    } catch {
      setComparison(null);
    } finally {
      setComparing(false);
    }
  }

  if (experiments.error) {
    return <ErrorState message={experiments.error.message} onRetry={experiments.reload} />;
  }
  if (!experiments.data) return <LoadingPanel message="Loading experiment history…" />;

  const rows = experiments.data.experiments;

  return (
    <div className="space-y-14">
      <Section
        label="Experiment history"
        title={`${experiments.data.count} recorded runs`}
        description="Every analysis is persisted with its full manifest, so a result can be found again and reproduced later. Select two or more to compare."
        actions={
          <div className="flex items-center gap-3">
            {selected.length ? (
              <span className="font-mono text-2xs text-ink-3">{selected.length} selected</span>
            ) : null}
            <Button size="sm" onClick={compare} disabled={selected.length < 2 || comparing}>
              {comparing ? 'Comparing…' : 'Compare'}
            </Button>
          </div>
        }
      >
        {rows.length === 0 ? (
          <Callout tone="info" title="No runs yet">
            Experiments are recorded automatically each time an analysis completes.
          </Callout>
        ) : (
          <DataTable
            columns={[
              { key: 'select', label: '', width: '2.5rem' },
              { key: 'label', label: 'Run' },
              { key: 'model', label: 'Model' },
              { key: 'location', label: 'Location' },
              { key: 'period', label: 'Period' },
              { key: 'rmse', label: 'RMSE (W/m²)', numeric: true },
              { key: 'r2', label: 'R²', numeric: true },
              { key: 'skill', label: 'Skill', numeric: true },
              { key: 'created', label: 'Created' },
            ]}
            rows={rows.map((e) => ({
              select: (
                <input
                  type="checkbox"
                  checked={selected.includes(e.experiment_id)}
                  onChange={() => toggle(e.experiment_id)}
                  aria-label={`Select run ${e.label}`}
                  className="accent-solar"
                />
              ),
              label: (
                <span title={e.experiment_id}>
                  {e.label}
                  {e.n_warnings > 0 ? <Tag tone="warning">{e.n_warnings} warnings</Tag> : null}
                </span>
              ),
              model: e.model_display_name,
              location: e.location_label,
              period: `${isoDate(e.period_start)} → ${isoDate(e.period_end)}`,
              rmse: e.rmse_wm2 != null ? num(e.rmse_wm2, 2) : '—',
              r2: e.r2 != null ? num(e.r2, 4) : '—',
              skill:
                e.skill_scores?.smart_persistence != null
                  ? signed(e.skill_scores.smart_persistence, 3)
                  : '—',
              created: isoDateTime(e.created_at),
            }))}
            caption="Recorded experiment runs"
            dense
          />
        )}
      </Section>

      {comparison ? (
        <Section label="Comparison" title={`${comparison.experiments.length} runs`}>
          {!comparison.comparable ? (
            <div className="mb-5 space-y-2">
              <Callout tone="warning" title="Not directly comparable">
                <ul className="list-inside list-disc space-y-1">
                  {(comparison.comparability_warnings ?? []).map((w: string) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </Callout>
              <p className="text-2xs leading-relaxed text-ink-4">{comparison.ranking_note}</p>
            </div>
          ) : (
            <div className="mb-5">
              <Callout tone="positive" title="Comparable">
                {comparison.ranking_note}
              </Callout>
            </div>
          )}

          <DataTable
            columns={[
              { key: 'label', label: 'Run' },
              { key: 'model', label: 'Model' },
              { key: 'rmse', label: 'RMSE', numeric: true },
              { key: 'mae', label: 'MAE', numeric: true },
              { key: 'r2', label: 'R²', numeric: true },
              { key: 'cv', label: 'CV RMSE', numeric: true },
              { key: 'picp', label: 'Coverage', numeric: true },
              { key: 'ntest', label: 'Test n', numeric: true },
            ]}
            rows={(comparison.experiments ?? []).map((e: any) => ({
              label: (
                <span>
                  {e.label}
                  {comparison.best_by_rmse === e.experiment_id ? (
                    <Tag tone="positive">best</Tag>
                  ) : null}
                </span>
              ),
              model: e.model,
              rmse: e.rmse_wm2 != null ? num(e.rmse_wm2, 2) : '—',
              mae: e.mae_wm2 != null ? num(e.mae_wm2, 2) : '—',
              r2: e.r2 != null ? num(e.r2, 4) : '—',
              cv:
                e.cv_rmse_mean != null
                  ? `${num(e.cv_rmse_mean, 1)} ± ${num(e.cv_rmse_std, 1)}`
                  : '—',
              picp: e.picp != null ? `${num(e.picp * 100, 1)}%` : '—',
              ntest: num(e.n_test, 0),
            }))}
            caption="Experiment comparison"
          />
        </Section>
      ) : null}
    </div>
  );
}
