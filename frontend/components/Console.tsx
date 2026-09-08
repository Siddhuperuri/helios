'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { AnalysisSummary, ModelCatalogue, api } from '@/lib/api';
import { Setup } from '@/components/Setup';
import { num } from '@/lib/format';

import { OverviewView } from '@/components/views/Overview';
import { ForecastView } from '@/components/views/Forecast';
import { PerformanceView } from '@/components/views/Performance';
import { UncertaintyView } from '@/components/views/Uncertainty';
import { ExplainView } from '@/components/views/Explain';
import { ValidationView } from '@/components/views/Validation';
import { AnomaliesView } from '@/components/views/Anomalies';
import { ScenariosView } from '@/components/views/Scenarios';
import { ModelLabView } from '@/components/views/ModelLab';
import { DataQualityView } from '@/components/views/DataQuality';
import { ModelCardView } from '@/components/views/ModelCard';
import { LiteratureView } from '@/components/views/Literature';
import { ExperimentsView } from '@/components/views/Experiments';
import { ReportView } from '@/components/views/Report';

type ViewKey =
  | 'overview'
  | 'forecast'
  | 'scenarios'
  | 'performance'
  | 'uncertainty'
  | 'validation'
  | 'anomalies'
  | 'explain'
  | 'lab'
  | 'card'
  | 'quality'
  | 'literature'
  | 'experiments'
  | 'report';

interface NavItem {
  key: ViewKey;
  label: string;
  hint: string;
}

/**
 * Navigation grouped by the question each view answers, not by data type.
 *
 * The grouping is the information architecture: a reviewer asking "how do I know this is
 * reliable?" goes to Evidence; one asking "why did it say that?" goes to Model. A single
 * flat list of fourteen items would make both of them read all fourteen.
 */
const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: 'Operate',
    items: [
      { key: 'overview', label: 'Overview', hint: 'System state at a glance' },
      { key: 'forecast', label: 'Forecast', hint: 'Forward-looking irradiance and yield' },
      { key: 'scenarios', label: 'Scenarios', hint: 'Modelled counterfactuals' },
    ],
  },
  {
    group: 'Evidence',
    items: [
      { key: 'performance', label: 'Performance', hint: 'Accuracy against held-out data' },
      { key: 'uncertainty', label: 'Uncertainty', hint: 'Interval calibration and sharpness' },
      { key: 'validation', label: 'Validation', hint: 'Leakage controls and split strategy' },
      { key: 'anomalies', label: 'Anomalies', hint: 'Irregularities in data and residuals' },
    ],
  },
  {
    group: 'Model',
    items: [
      { key: 'explain', label: 'Explainability', hint: 'What drives the prediction' },
      { key: 'lab', label: 'Model Laboratory', hint: 'Compare estimators fairly' },
      { key: 'card', label: 'Model Card', hint: 'Documentation and limitations' },
    ],
  },
  {
    group: 'Provenance',
    items: [
      { key: 'quality', label: 'Data Quality', hint: 'Transparent scoring' },
      { key: 'literature', label: 'Literature', hint: 'Technique traceability' },
      { key: 'experiments', label: 'Experiments', hint: 'Run history and comparison' },
      { key: 'report', label: 'Report', hint: 'Exportable scientific summary' },
    ],
  },
];

const ALL_ITEMS = NAV.flatMap((g) => g.items);

export function Console() {
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisSummary | null>(null);
  const [view, setView] = useState<ViewKey>('overview');
  const [models, setModels] = useState<ModelCatalogue | null>(null);
  const [limits, setLimits] = useState<Record<string, any> | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  const [reachable, setReachable] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [m, l] = await Promise.all([api.models(), api.limits()]);
        if (cancelled) return;
        setModels(m);
        setLimits(l);
        setReachable(true);
      } catch {
        if (!cancelled) setReachable(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onCreated = useCallback((id: string) => {
    setAnalysisId(id);
    setView('overview');
  }, []);

  // Restore the analysis summary whenever the id changes.
  useEffect(() => {
    if (!analysisId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.analysis(analysisId);
        if (!cancelled) setAnalysis(data);
      } catch {
        /* the Overview view surfaces the failure with full context */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [analysisId]);

  // Close the mobile rail whenever the view changes.
  useEffect(() => {
    setRailOpen(false);
  }, [view]);

  const activeItem = useMemo(() => ALL_ITEMS.find((i) => i.key === view), [view]);

  if (reachable === false) {
    return (
      <main id="main" className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6">
        <p className="eyebrow mb-4">Connection</p>
        <h1 className="text-xl font-medium text-ink-1">The analysis server is not reachable.</h1>
        <p className="mt-3 text-sm leading-relaxed text-ink-2">
          The interface is running, but it cannot reach the Helios API at{' '}
          <code className="num text-solar">
            {process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000'}
          </code>
          .
        </p>
        <div className="mt-5 border border-line bg-surface-1 p-4">
          <p className="mb-2 font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
            Start the backend
          </p>
          <pre className="num overflow-x-auto text-xs text-ink-1">
{`cd backend
python -m uvicorn app.main:app --reload --port 8000`}
          </pre>
        </div>
        <button
          onClick={() => window.location.reload()}
          className="mt-5 self-start border border-line-strong px-3.5 py-2 text-xs text-ink-1
            transition-colors hover:border-solar hover:text-solar"
        >
          Retry connection
        </button>
      </main>
    );
  }

  if (!analysisId) {
    return <Setup onCreated={onCreated} models={models} limits={limits} />;
  }

  return (
    <div className="flex min-h-screen">
      {/* ------------------------------------------------------------ rail */}
      {/*
        The mobile rail is toggled with `display`, not an off-canvas transform.
        A translated-off-screen nav stays in the tab order and in the accessibility
        tree while invisible, so keyboard and screen-reader users traverse fourteen
        hidden links before reaching the content. `hidden` removes it from both.
      */}
      <nav
        aria-label="Analysis sections"
        className={`fixed inset-y-0 left-0 z-40 w-rail shrink-0 overflow-y-auto border-r
          border-line bg-base/95 backdrop-blur-sm lg:static lg:block
          lg:bg-transparent lg:backdrop-blur-none
          ${railOpen ? 'block' : 'hidden'}`}
      >
        <div className="flex h-full flex-col p-4">
          <button
            onClick={() => {
              setAnalysisId(null);
              setAnalysis(null);
            }}
            className="mb-6 flex items-center gap-2.5 text-left transition-opacity hover:opacity-80"
            title="Start a new analysis"
          >
            <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
              <path d="M1 15 Q 10 2, 19 15" fill="none" stroke="#F2A93B" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="1" y1="15.5" x2="19" y2="15.5" stroke="rgba(255,255,255,0.22)" />
              <circle cx="10" cy="5.6" r="2" fill="#F2A93B" />
            </svg>
            <span className="font-mono text-2xs uppercase tracking-[0.2em] text-ink-2">
              Helios
            </span>
          </button>

          {analysis ? (
            <div className="mb-6 border-b border-line pb-4">
              <p className="truncate text-xs text-ink-1" title={analysis.location.label}>
                {analysis.location.label}
              </p>
              <p className="num mt-1 text-2xs text-ink-4">
                {analysis.location.latitude.toFixed(3)}, {analysis.location.longitude.toFixed(3)}
              </p>
              <p className="mt-2 text-2xs text-ink-3">{analysis.model.display_name}</p>
            </div>
          ) : null}

          <div className="flex-1 space-y-6">
            {NAV.map((group) => (
              <div key={group.group}>
                <p className="mb-2 font-mono text-2xs uppercase tracking-[0.14em] text-ink-4">
                  {group.group}
                </p>
                <ul className="space-y-px">
                  {group.items.map((item) => {
                    const active = item.key === view;
                    return (
                      <li key={item.key}>
                        <button
                          onClick={() => setView(item.key)}
                          aria-current={active ? 'page' : undefined}
                          className={`flex w-full items-center gap-2 border-l-2 py-1.5 pl-2.5 pr-2
                            text-left text-xs transition-colors
                            ${
                              active
                                ? 'border-l-solar bg-surface-1 text-ink-1'
                                : 'border-l-transparent text-ink-3 hover:border-l-line-bright hover:text-ink-1'
                            }`}
                        >
                          {item.label}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>

          <button
            onClick={() => {
              setAnalysisId(null);
              setAnalysis(null);
            }}
            className="mt-6 border border-line px-2.5 py-1.5 text-2xs text-ink-3 transition-colors
              hover:border-solar hover:text-solar"
          >
            New analysis
          </button>
        </div>
      </nav>

      {railOpen ? (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setRailOpen(false)}
          aria-hidden="true"
        />
      ) : null}

      {/* ------------------------------------------------------------ main */}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 border-b border-line bg-base/90 backdrop-blur-sm">
          <div className="flex items-center gap-3 px-4 py-2.5 sm:px-6">
            <button
              onClick={() => setRailOpen((v) => !v)}
              className="lg:hidden"
              aria-label={railOpen ? 'Close navigation' : 'Open navigation'}
              aria-expanded={railOpen}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" strokeWidth="1.4" className="text-ink-2" />
              </svg>
            </button>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-medium text-ink-1">{activeItem?.label}</h1>
              <p className="truncate text-2xs text-ink-4">{activeItem?.hint}</p>
            </div>

            {analysis ? (
              <dl className="ml-auto hidden items-center gap-5 sm:flex">
                <HeaderStat
                  label="RMSE"
                  value={`${num(analysis.headline.rmse_wm2, 1)} W/m²`}
                />
                <HeaderStat label="R²" value={num(analysis.headline.r2, 3)} />
                <HeaderStat
                  label="Quality"
                  value={`${num(analysis.data_quality.overall_score, 0)}%`}
                  tone={
                    analysis.data_quality.worst_severity === 'fail'
                      ? 'critical'
                      : analysis.data_quality.worst_severity === 'warn'
                        ? 'warning'
                        : 'positive'
                  }
                />
              </dl>
            ) : null}
          </div>
        </header>

        <main id="main" className="px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
          <div className="mx-auto max-w-[1100px] animate-fade-rise">
            {view === 'overview' && <OverviewView analysisId={analysisId} onNavigate={setView} />}
            {view === 'forecast' && <ForecastView analysisId={analysisId} />}
            {view === 'scenarios' && <ScenariosView analysisId={analysisId} />}
            {view === 'performance' && <PerformanceView analysisId={analysisId} />}
            {view === 'uncertainty' && <UncertaintyView analysisId={analysisId} />}
            {view === 'validation' && <ValidationView analysisId={analysisId} />}
            {view === 'anomalies' && <AnomaliesView analysisId={analysisId} />}
            {view === 'explain' && <ExplainView analysisId={analysisId} />}
            {view === 'lab' && <ModelLabView analysisId={analysisId} models={models} />}
            {view === 'card' && <ModelCardView analysisId={analysisId} />}
            {view === 'quality' && <DataQualityView analysisId={analysisId} />}
            {view === 'literature' && <LiteratureView />}
            {view === 'experiments' && <ExperimentsView />}
            {view === 'report' && <ReportView analysisId={analysisId} />}
          </div>

          <footer className="mx-auto mt-16 max-w-[1100px] border-t border-line pt-5">
            <p className="text-2xs leading-relaxed text-ink-4">
              Weather and irradiance data from Open-Meteo (CC-BY 4.0), derived from ECMWF
              ERA5 / ERA5-Land reanalysis (Copernicus Climate Change Service). Reanalysis is
              a modelled product, not a ground measurement.
            </p>
          </footer>
        </main>
      </div>
    </div>
  );
}

function HeaderStat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'positive' | 'warning' | 'critical';
}) {
  const toneClass = {
    neutral: 'text-ink-1',
    positive: 'text-positive',
    warning: 'text-warning',
    critical: 'text-critical',
  }[tone];
  return (
    <div className="text-right">
      <dt className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-4">{label}</dt>
      <dd className={`num text-xs ${toneClass}`}>{value}</dd>
    </div>
  );
}
