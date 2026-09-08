'use client';

import { useState } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import { ErrorState, LoadingPanel, Panel, Section, Tag } from '@/components/ui';

/**
 * Literature traceability.
 *
 * Maps each implemented technique back to the paper it came from, and states honestly
 * where the platform departs from the source research. The statuses that matter most are
 * the negative ones: SUBSTITUTED, NOT ADOPTED and FUTURE WORK are what make the positive
 * claims credible.
 */
const STATUS_TONE: Record<string, 'positive' | 'warning' | 'critical' | 'neutral' | 'accent' | 'info'> = {
  IMPLEMENTED: 'positive',
  'PARTIALLY IMPLEMENTED': 'warning',
  SUBSTITUTED: 'warning',
  ENHANCEMENT: 'info',
  'FUTURE WORK': 'neutral',
  'NOT ADOPTED': 'neutral',
};

export function LiteratureView() {
  const [filter, setFilter] = useState<string | null>(null);
  const lit = useAsync(() => api.literature(), []);

  if (lit.error) return <ErrorState message={lit.error.message} onRetry={lit.reload} />;
  if (!lit.data) return <LoadingPanel message="Loading literature map…" />;

  const l = lit.data;
  const statuses = Array.from(new Set(l.techniques.map((t) => t.status)));
  const visible = filter ? l.techniques.filter((t) => t.status === filter) : l.techniques;
  const paperByKey = Object.fromEntries(l.papers.map((p) => [p.key, p]));

  return (
    <div className="space-y-14">
      <Section
        label="Source research"
        title="The papers this platform is built on"
        description="Six studies of solar irradiance and photovoltaic forecasting. Techniques below are traced back to these."
      >
        <ol className="space-y-3">
          {l.papers.map((p, i) => (
            <li key={p.key} className="flex gap-4 border-b border-line pb-3">
              <span className="num shrink-0 text-2xs text-ink-4">
                P{i + 1}
              </span>
              <div className="min-w-0">
                <h3 className="text-xs font-medium leading-relaxed text-ink-1">{p.title}</h3>
                <p className="mt-1 text-2xs text-ink-3">
                  {p.authors} · <span className="italic">{p.venue}</span> · {p.year}
                </p>
                <p className="num mt-1 text-2xs text-ink-4">{p.key}</p>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section
        label="Technique traceability"
        title={`${visible.length} of ${l.techniques.length} techniques`}
        description="Each entry states what was taken from the research, what it is for, and whether it was implemented as described, substituted, or deliberately left out."
        actions={
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => setFilter(null)}
              aria-pressed={filter === null}
              className={`border px-2 py-1 text-2xs transition-colors ${
                filter === null
                  ? 'border-solar text-solar'
                  : 'border-line text-ink-3 hover:border-line-bright hover:text-ink-1'
              }`}
            >
              All
            </button>
            {statuses.map((s) => (
              <button
                key={s}
                onClick={() => setFilter(s)}
                aria-pressed={filter === s}
                className={`border px-2 py-1 text-2xs transition-colors ${
                  filter === s
                    ? 'border-solar text-solar'
                    : 'border-line text-ink-3 hover:border-line-bright hover:text-ink-1'
                }`}
              >
                {s.toLowerCase()}
              </button>
            ))}
          </div>
        }
      >
        <div className="space-y-2.5">
          {visible.map((t) => (
            <Panel key={t.technique}>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h3 className="text-xs font-medium text-ink-1">{t.technique}</h3>
                <Tag tone={STATUS_TONE[t.status] ?? 'neutral'}>{t.status}</Tag>
                {t.sources.map((s) => (
                  <Tag key={s} tone="accent" title={paperByKey[s]?.title}>
                    {s}
                  </Tag>
                ))}
                {t.sources.length === 0 ? <Tag tone="info">no source paper</Tag> : null}
              </div>
              <p className="text-2xs leading-relaxed text-ink-2">{t.purpose}</p>
              {t.note ? (
                <p className="mt-2 border-t border-line pt-2 text-2xs leading-relaxed text-ink-3">
                  {t.note}
                </p>
              ) : null}
            </Panel>
          ))}
        </div>
      </Section>

      <Section label="Status legend">
        <dl className="grid gap-3 sm:grid-cols-2">
          {Object.entries(l.status_legend).map(([status, meaning]) => (
            <div key={status} className="border-b border-line pb-2.5">
              <dt className="mb-1">
                <Tag tone={STATUS_TONE[status] ?? 'neutral'}>{status}</Tag>
              </dt>
              <dd className="text-2xs leading-relaxed text-ink-2">{meaning}</dd>
            </div>
          ))}
        </dl>
      </Section>
    </div>
  );
}
