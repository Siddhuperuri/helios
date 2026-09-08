'use client';

import { useState } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import {
  Callout,
  DataTable,
  ErrorState,
  LoadingPanel,
  Panel,
  ScoreBar,
  Section,
  StatusDot,
  Tag,
  severityTone,
} from '@/components/ui';
import { isoDate, num } from '@/lib/format';

/**
 * Data quality.
 *
 * The arithmetic is exposed deliberately. A headline "94%" is an assertion; a table of
 * checks each carrying its own weight, score and row counts is evidence, and a reader who
 * disagrees with a weight can see exactly which one to argue with.
 */
export function DataQualityView({ analysisId }: { analysisId: string }) {
  const [showPassing, setShowPassing] = useState(false);
  const quality = useAsync(() => api.quality(analysisId), [analysisId]);
  const params = useAsync(() => api.parameters(), []);

  if (quality.error) {
    return <ErrorState message={quality.error.message} onRetry={quality.reload} />;
  }
  if (!quality.data) return <LoadingPanel message="Loading quality report…" />;

  const q = quality.data;
  const method = q.methodology as Record<string, any>;
  const visible = showPassing ? q.checks : q.checks.filter((c) => c.severity !== 'pass');
  const recomputed =
    Number(method.weighted_sum) / Number(method.total_weight || 1);

  return (
    <div className="space-y-14">
      <Section
        label="Data quality"
        title="How good is the input?"
        description="Every check declares its own weight and score, so the headline figure can be recomputed by hand from what is shown here."
      >
        <div className="grid gap-8 lg:grid-cols-[minmax(0,320px)_1fr]">
          <Panel>
            <ScoreBar score={q.overall_score} grade={q.grade} counts={q.counts} />
            <dl className="mt-5 space-y-2 border-t border-line pt-4 text-2xs">
              <div className="flex justify-between">
                <dt className="text-ink-3">Observations</dt>
                <dd className="num text-ink-1">{num(q.row_count, 0)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-3">Period</dt>
                <dd className="num text-ink-1">
                  {isoDate(q.period_start)} → {isoDate(q.period_end)}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-3">Worst severity</dt>
                <dd>
                  <Tag tone={severityTone(q.worst_severity)}>{q.worst_severity}</Tag>
                </dd>
              </div>
            </dl>
          </Panel>

          <div>
            <Callout tone="info" title="How the score is computed">
              <code className="num text-ink-1">{String(method.formula)}</code>
              <p className="mt-2">
                Weighted sum <span className="num text-ink-1">{num(Number(method.weighted_sum), 4)}</span>{' '}
                ÷ total weight <span className="num text-ink-1">{num(Number(method.total_weight), 1)}</span>{' '}
                = <span className="num text-ink-1">{num(recomputed * 100, 1)}%</span>.
              </p>
            </Callout>
            <div className="mt-3">
              <Callout tone="warning" title="Grade capping">
                {String(method.grade_capping)}
              </Callout>
            </div>
            {q.blocking_issues.length ? (
              <div className="mt-3">
                <Callout tone="critical" title="Blocking issues">
                  <ul className="list-inside list-disc space-y-1">
                    {q.blocking_issues.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                </Callout>
              </div>
            ) : null}
          </div>
        </div>
      </Section>

      <Section
        label="Checks"
        title={`${visible.length} of ${q.checks.length} checks shown`}
        actions={
          <button
            onClick={() => setShowPassing((v) => !v)}
            className="border border-line px-2.5 py-1 text-2xs text-ink-3 transition-colors
              hover:border-solar hover:text-solar"
          >
            {showPassing ? 'Hide passing' : 'Show all'}
          </button>
        }
      >
        {visible.length === 0 ? (
          <Callout tone="positive" title="All checks passed">
            No warnings or failures were raised. Toggle “Show all” to inspect the passing
            checks and their weights.
          </Callout>
        ) : (
          <div className="space-y-2.5">
            {visible.map((c) => (
              <Panel key={c.key}>
                <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-3">
                  <h3 className="flex items-center gap-2 text-xs font-medium text-ink-1">
                    <StatusDot tone={severityTone(c.severity)} />
                    {c.title}
                  </h3>
                  <div className="flex items-center gap-3 font-mono text-2xs text-ink-4">
                    <span>weight {num(c.weight, 1)}</span>
                    <span>score {num(c.score, 3)}</span>
                    <span className="text-ink-3">
                      contributes {num(c.weighted_contribution, 3)}
                    </span>
                  </div>
                </div>
                <p className="text-xs leading-relaxed text-ink-2">{c.message}</p>
                {c.remedy ? (
                  <p className="mt-2 border-t border-line pt-2 text-2xs leading-relaxed text-ink-3">
                    {c.remedy}
                  </p>
                ) : null}
              </Panel>
            ))}
          </div>
        )}
      </Section>

      {params.data ? (
        <>
          <Section
            label="Parameter dictionary"
            title="Every variable, defined"
            description="Ranges below are physical plausibility bounds, not statistical ones. A value is flagged because it is physically improbable at Earth's surface, never because it is statistically unusual."
          >
            <DataTable
              columns={[
                { key: 'name', label: 'Parameter' },
                { key: 'symbol', label: 'Symbol' },
                { key: 'unit', label: 'Unit' },
                { key: 'range', label: 'Valid range', numeric: true },
                { key: 'role', label: 'Role' },
                { key: 'origin', label: 'Origin' },
              ]}
              rows={params.data.parameters.map((p) => ({
                name: <span title={p.definition}>{p.display_name}</span>,
                symbol: p.symbol ?? '—',
                unit: p.unit ?? '—',
                range:
                  p.valid_min != null || p.valid_max != null
                    ? `${p.valid_min ?? '−∞'} … ${p.valid_max ?? '∞'}`
                    : '—',
                role: <Tag tone={p.role === 'target' ? 'accent' : 'neutral'}>{p.role}</Tag>,
                origin: p.origin,
              }))}
              caption="Scientific parameter dictionary"
              dense
            />
          </Section>

          <Section
            label="Not available"
            title="Variables named in the research that this source cannot supply"
            description="Surfaced rather than silently omitted, so the gap between what the literature used and what this platform has is visible."
          >
            <div className="space-y-3">
              {params.data.unavailable.map((u) => (
                <Panel key={u.display_name}>
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <h3 className="text-xs font-medium text-ink-1">{u.display_name}</h3>
                    {u.unit ? <Tag tone="neutral">{u.unit}</Tag> : null}
                    <Tag tone="accent">{u.sources}</Tag>
                  </div>
                  <p className="text-2xs leading-relaxed text-ink-2">{u.reason}</p>
                </Panel>
              ))}
            </div>
          </Section>
        </>
      ) : null}
    </div>
  );
}
