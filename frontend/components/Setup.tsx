'use client';

import { useEffect, useRef, useState } from 'react';

import {
  ApiError,
  AnalysisRequestBody,
  LocationDto,
  ModelCatalogue,
  api,
} from '@/lib/api';
import { Button, ErrorState, Field, Select, TextInput } from '@/components/ui';

/**
 * The entry experience.
 *
 * Deliberately not a marketing hero. The first screen states the actual capability in
 * precise terms, exposes the configuration immediately rather than behind a call to
 * action, and shows the honest constraints — where the data comes from, how far back it
 * goes, what horizon has been validated. A researcher can tell within seconds whether
 * this instrument does what they need.
 */

const PRESETS: { label: string; query: string; note: string }[] = [
  { label: 'Hyderabad', query: 'Hyderabad, India', note: '17.4°N · monsoon-driven variability' },
  { label: 'Seville', query: 'Seville, Spain', note: '37.4°N · high-insolation Mediterranean' },
  { label: 'Reykjavík', query: 'Reykjavik, Iceland', note: '64.1°N · extreme seasonal day length' },
  { label: 'Lima', query: 'Lima, Peru', note: '12.0°S · persistent coastal cloud' },
];

export function Setup({
  onCreated,
  models,
  limits,
}: {
  onCreated: (id: string) => void;
  models: ModelCatalogue | null;
  limits: Record<string, any> | null;
}) {
  const [query, setQuery] = useState('Hyderabad, India');
  const [suggestions, setSuggestions] = useState<LocationDto[]>([]);
  const [resolved, setResolved] = useState<LocationDto | null>(null);
  const [years, setYears] = useState(2);
  const [modelKey, setModelKey] = useState('random_forest');
  const [capacity, setCapacity] = useState(5);
  const [tilt, setTilt] = useState(20);
  const [azimuth, setAzimuth] = useState(180);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [stage, setStage] = useState('');
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listboxId = 'location-suggestions';

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (query.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    searchTimer.current = setTimeout(async () => {
      try {
        const { results } = await api.searchLocations(query, 5);
        setSuggestions(results);
      } catch {
        setSuggestions([]); // a failed lookup should not block manual entry
      }
    }, 320);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, [query]);

  const latest: string | undefined = limits?.latest_archive_date;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const end = latest ? new Date(latest) : new Date();
    const start = new Date(end);
    start.setFullYear(start.getFullYear() - years);

    const body: AnalysisRequestBody = {
      location: resolved
        ? { latitude: resolved.latitude, longitude: resolved.longitude }
        : { query: query.trim() },
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
      model_key: modelKey,
      target: 'clear_sky_index',
      system: {
        dc_capacity_kwp: capacity,
        surface_tilt_deg: tilt,
        surface_azimuth_deg: azimuth,
      },
      label: `${resolved?.label ?? query} · ${modelKey}`,
    };

    const stages = [
      'Retrieving hourly reanalysis…',
      'Assessing data quality…',
      'Computing solar geometry…',
      'Fitting model…',
      'Running rolling-origin cross-validation…',
      'Calibrating prediction intervals…',
    ];
    let i = 0;
    setStage(stages[0]!);
    const ticker = setInterval(() => {
      i = Math.min(i + 1, stages.length - 1);
      setStage(stages[i]!);
    }, 4200);

    try {
      const analysis = await api.createAnalysis(body);
      onCreated(analysis.analysis_id);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err
          : new ApiError('An unexpected error occurred.', 500, String(err)),
      );
    } finally {
      clearInterval(ticker);
      setBusy(false);
      setStage('');
    }
  }

  return (
    <main id="main" className="mx-auto min-h-screen w-full max-w-[1180px] px-5 py-12 sm:px-8 lg:py-20">
      {/* ---------------------------------------------------------- masthead */}
      <header className="mb-14 lg:mb-20">
        <div className="mb-8 flex items-center gap-3">
          <Mark />
          <span className="font-mono text-2xs uppercase tracking-[0.24em] text-ink-3">
            Helios
          </span>
          <span className="h-px flex-1 bg-line" />
          <span className="font-mono text-2xs text-ink-4">v1.0</span>
        </div>

        <div className="grid gap-10 lg:grid-cols-[1.35fr_1fr] lg:gap-16">
          <div>
            <h1 className="max-w-2xl text-3xl font-medium leading-[1.12] tracking-tight text-ink-1 sm:text-4xl">
              Hourly solar irradiance forecasting,
              <span className="text-ink-3"> validated the way it will be deployed.</span>
            </h1>
            <p className="mt-6 max-w-xl text-sm leading-relaxed text-ink-2">
              Helios predicts global horizontal irradiance at any location on Earth from
              numerical weather prediction, then converts it to photovoltaic yield through
              a declared, inspectable physical chain. Models are trained on the past and
              tested on the future — never on shuffled hours — and every figure carries the
              uncertainty that produced it.
            </p>

            <ul className="mt-8 grid max-w-xl gap-x-8 gap-y-3 sm:grid-cols-2">
              {[
                ['Predicts', 'Global horizontal irradiance, W/m², hourly'],
                ['Derives', 'AC energy for a system you declare, kWh'],
                ['Validates', 'Chronological split + rolling-origin CV'],
                ['Quantifies', 'Conformal prediction intervals'],
              ].map(([k, v]) => (
                <li key={k} className="border-t border-line pt-2.5">
                  <span className="block font-mono text-2xs uppercase tracking-[0.12em] text-ink-4">
                    {k}
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-2">{v}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Provenance stated up front rather than buried in a footer. */}
          <aside className="lg:pt-2">
            <p className="eyebrow mb-4">Data foundation</p>
            <dl className="space-y-3 text-xs">
              {[
                ['Source', 'ERA5 reanalysis via Open-Meteo'],
                ['Coverage', 'Global, hourly, from 2000'],
                ['Latest available', latest ?? '—'],
                ['Validated horizon', `${(limits?.validated_horizon_hours ?? 168) / 24} days`],
                ['API key required', 'None'],
              ].map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-4 border-b border-line pb-2">
                  <dt className="text-ink-3">{k}</dt>
                  <dd className="num text-right text-ink-1">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-4 text-2xs leading-relaxed text-ink-4">
              Reanalysis is a modelled gridded product, not a ground pyranometer
              measurement. Results are reported on that basis and are not presented as
              comparable to station-measured studies.
            </p>
          </aside>
        </div>
      </header>

      {/* ------------------------------------------------------------- form */}
      <form onSubmit={submit} className="border-t border-line-strong pt-10">
        <p className="eyebrow mb-6">Configure analysis</p>

        <div className="grid gap-x-8 gap-y-6 lg:grid-cols-[1.4fr_1fr_1fr]">
          <div>
            <Field
              label="Location"
              htmlFor="location"
              hint="Search by place name, or pick a preset below."
            >
              <TextInput
                id="location"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setResolved(null);
                }}
                placeholder="City, country"
                autoComplete="off"
                role="combobox"
                aria-expanded={suggestions.length > 0}
                aria-controls={listboxId}
                aria-autocomplete="list"
                required
              />
            </Field>

            {suggestions.length > 0 && !resolved ? (
              <ul
                id={listboxId}
                role="listbox"
                aria-label="Location suggestions"
                className="mt-1 divide-y divide-line border border-line-strong bg-surface-2"
              >
                {suggestions.slice(0, 4).map((s) => (
                  <li key={`${s.latitude},${s.longitude}`} role="option" aria-selected={false}>
                    <button
                      type="button"
                      onClick={() => {
                        setResolved(s);
                        setQuery(s.label);
                        setSuggestions([]);
                      }}
                      className="flex w-full items-baseline justify-between gap-3 px-2.5 py-2
                        text-left text-xs text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink-1"
                    >
                      <span className="truncate">{s.label}</span>
                      <span className="num shrink-0 text-2xs text-ink-4">
                        {s.latitude.toFixed(2)}, {s.longitude.toFixed(2)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="mt-3 flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button
                  key={p.query}
                  type="button"
                  title={p.note}
                  onClick={() => {
                    setQuery(p.query);
                    setResolved(null);
                  }}
                  className="border border-line px-2 py-1 text-2xs text-ink-3 transition-colors
                    hover:border-solar hover:text-solar"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <Field label="Training window" htmlFor="years" hint="Longer windows cover more seasons.">
            <Select id="years" value={years} onChange={(e) => setYears(Number(e.target.value))}>
              <option value={1}>1 year</option>
              <option value={2}>2 years</option>
              <option value={3}>3 years</option>
              <option value={5}>5 years</option>
            </Select>
          </Field>

          <Field
            label="Model"
            htmlFor="model"
            hint={models?.models.find((m) => m.key === modelKey)?.family}
          >
            <Select id="model" value={modelKey} onChange={(e) => setModelKey(e.target.value)}>
              {(models?.models ?? []).map((m) => (
                <option key={m.key} value={m.key}>
                  {m.display_name}
                  {m.cost === 'high' ? ' — slow' : ''}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="mt-8 border-t border-line pt-6">
          <p className="mb-4 flex items-baseline gap-2 text-xs text-ink-2">
            <span className="font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
              PV system
            </span>
            <span className="text-2xs text-ink-4">
              — energy in kWh is undefined without a declared array, so these are required.
            </span>
          </p>
          <div className="grid gap-x-8 gap-y-5 sm:grid-cols-3">
            <Field label="DC capacity (kWp)" htmlFor="cap">
              <TextInput
                id="cap"
                type="number"
                min={0.1}
                max={100000}
                step={0.1}
                value={capacity}
                onChange={(e) => setCapacity(Number(e.target.value))}
              />
            </Field>
            <Field label="Tilt (°)" htmlFor="tilt" hint="0 = horizontal, 90 = vertical">
              <TextInput
                id="tilt"
                type="number"
                min={0}
                max={90}
                value={tilt}
                onChange={(e) => setTilt(Number(e.target.value))}
              />
            </Field>
            <Field label="Azimuth (°)" htmlFor="azi" hint="180 = due south, 0 = due north">
              <TextInput
                id="azi"
                type="number"
                min={0}
                max={359}
                value={azimuth}
                onChange={(e) => setAzimuth(Number(e.target.value))}
              />
            </Field>
          </div>
        </div>

        {error ? (
          <div className="mt-6">
            <ErrorState
              message={error.message}
              remedy={error.remedy}
              detail={error.detail ?? error.fieldErrors?.map((f) => `${f.field}: ${f.message}`).join('\n')}
            />
          </div>
        ) : null}

        <div className="mt-8 flex flex-wrap items-center gap-4 border-t border-line pt-6">
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Running analysis…' : 'Run analysis'}
          </Button>
          {busy ? (
            <p className="flex items-center gap-2 text-xs text-ink-2" role="status" aria-live="polite">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-solar opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-solar" />
              </span>
              {stage}
            </p>
          ) : (
            <p className="text-2xs leading-relaxed text-ink-4">
              Fetches hourly data, scores its quality, fits the model on the earlier
              portion and tests on the most recent. Typically 10–40 seconds.
            </p>
          )}
        </div>
      </form>
    </main>
  );
}

/** The mark: a sun elevation trace over a horizon rule. Drawn, not decorative. */
function Mark() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true" className="shrink-0">
      <path
        d="M1 15 Q 10 2, 19 15"
        fill="none"
        stroke="#F2A93B"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <line x1="1" y1="15.5" x2="19" y2="15.5" stroke="rgba(255,255,255,0.22)" strokeWidth="1" />
      <circle cx="10" cy="5.6" r="2" fill="#F2A93B" />
    </svg>
  );
}
