'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import { SaveToAccount } from '@/components/result/SaveToAccount';
import { LiveForecastPanel } from '@/components/result/LiveForecastPanel';

import { AssumptionEditor } from '@/components/result/AssumptionEditor';
import { PanelConfigurator } from '@/components/result/PanelConfigurator';
import { SystemSpecification } from '@/components/result/SystemSpecification';
import {
  BalanceBar,
  CashflowChart,
  DayProfileChart,
  MonthlyChart,
  type MonthlyUnit,
} from '@/components/result/charts';
import { Icon, type IconName } from '@/components/site/Icon';
import { EstimateError, estimateApi, type EstimateResult } from '@/lib/estimate';
import { formatCurrency, formatEnergy } from '@/lib/i18n';

/**
 * The answer (§20), and everything behind it (§37's Explore branch).
 *
 * The page is ordered by what a reader needs rather than by what the pipeline produced.
 * The headline figure, its range and its confidence come first and together — a number
 * without its range would be the exact overconfidence §19 forbids. Then plain language
 * explaining what it means. Only then the tabs, for the reader who wants to dig.
 *
 * Everything below the fold is optional depth, and none of it is required to walk away
 * with a true answer. That is the shape of a result that serves both a farmer and an EPC
 * contractor without patronising the first or short-changing the second.
 */

type TabKey =
  | 'generation'
  | 'savings'
  | 'system'
  | 'weather'
  | 'assumptions'
  | 'scenarios'
  | 'report';

const TABS: { key: TabKey; label: string; icon: IconName }[] = [
  { key: 'generation', label: 'Generation', icon: 'chart' },
  { key: 'savings', label: 'Savings', icon: 'wallet' },
  { key: 'system', label: 'System Size', icon: 'grid' },
  { key: 'weather', label: 'Weather', icon: 'cloud-sun' },
  { key: 'assumptions', label: 'Assumptions', icon: 'list' },
  { key: 'scenarios', label: 'Scenarios', icon: 'sliders' },
  { key: 'report', label: 'Report', icon: 'download' },
];

export function ResultView({ estimateId }: { estimateId: string }) {
  const [result, setResult] = useState<EstimateResult | null>(null);
  const [error, setError] = useState<EstimateError | null>(null);
  const [tab, setTab] = useState<TabKey>('generation');

  const load = useCallback(async () => {
    setError(null);
    try {
      setResult(await estimateApi.get(estimateId));
    } catch (err) {
      setError(
        err instanceof EstimateError
          ? err
          : new EstimateError('We could not load that estimate.', 500),
      );
    }
  }, [estimateId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <div className="mx-auto max-w-xl px-5 py-16 sm:px-8">
        <p className="eyebrow mb-5">Not found</p>
        <h1 className="text-xl font-medium text-ink-1">{error.message}</h1>
        {error.remedy ? <p className="mt-3 text-sm text-ink-2">{error.remedy}</p> : null}
        <div className="mt-6 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void load()}
            className="tap border border-line-strong px-5 py-2.5 text-sm text-ink-1
              transition-colors hover:border-solar hover:text-solar"
          >
            Try again
          </button>
          <Link
            href="/start"
            className="tap inline-flex items-center border border-line px-5 py-2.5 text-sm
              text-ink-2 transition-colors hover:border-line-bright hover:text-ink-1"
          >
            Start a new estimate
          </Link>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="mx-auto max-w-[1180px] px-5 py-16 sm:px-8" role="status" aria-live="polite">
        <span className="sr-only">Loading your estimate…</span>
        <div className="h-3 w-24 animate-pulse bg-surface-3" />
        <div className="mt-6 h-14 w-2/3 animate-pulse bg-surface-3" />
        <div className="mt-4 h-4 w-1/2 animate-pulse bg-surface-2" />
        <div className="mt-10 grid gap-3 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse bg-surface-2" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1180px] px-5 py-8 sm:px-8 lg:py-12">
      <Headline result={result} />
      <Explanation result={result} />

      {/*
        Offered after the answer, never before it. An estimate that already has an owner
        renders nothing here.
      */}
      <SaveToAccount
        estimateId={estimateId}
        owned={Boolean((result as { owned?: boolean }).owned)}
        onClaimed={() => void load()}
      />

      <LiveForecastPanel estimateId={estimateId} />

      {/* ------------------------------------------------------------------ tabs */}
      <div className="mt-12 border-b border-line">
        <div className="scroll-x">
          <div role="tablist" aria-label="Explore your results" className="flex min-w-max gap-1">
            {TABS.map((item) => {
              const active = tab === item.key;
              return (
                <button
                  key={item.key}
                  role="tab"
                  id={`tab-${item.key}`}
                  aria-selected={active}
                  aria-controls={`panel-${item.key}`}
                  tabIndex={active ? 0 : -1}
                  onClick={() => setTab(item.key)}
                  onKeyDown={(event) => {
                    // Arrow-key movement between tabs is expected of a tablist and is the
                    // only way a keyboard user reaches them efficiently.
                    const index = TABS.findIndex((t) => t.key === tab);
                    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                      event.preventDefault();
                      const delta = event.key === 'ArrowRight' ? 1 : -1;
                      const next = TABS[(index + delta + TABS.length) % TABS.length]!;
                      setTab(next.key);
                      document.getElementById(`tab-${next.key}`)?.focus();
                    }
                  }}
                  className={`tap flex items-center gap-2 border-b-2 px-4 py-3 text-sm
                    transition-colors ${
                      active
                        ? 'border-solar text-ink-1'
                        : 'border-transparent text-ink-2 hover:text-ink-1'
                    }`}
                >
                  <Icon name={item.icon} size={16} className={active ? 'text-solar' : ''} />
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        className="animate-fade-rise py-8"
      >
        {tab === 'generation' ? <GenerationPanel result={result} /> : null}
        {tab === 'savings' ? <SavingsPanel result={result} /> : null}
        {tab === 'system' ? (
          <SystemPanel result={result} onUpdated={setResult} />
        ) : null}
        {tab === 'weather' ? <WeatherPanel result={result} /> : null}
        {tab === 'assumptions' ? (
          <AssumptionsPanel result={result} onUpdated={setResult} />
        ) : null}
        {tab === 'scenarios' ? <ScenariosPanel result={result} /> : null}
        {tab === 'report' ? <ReportPanel result={result} /> : null}
      </div>

      <Actions result={result} />
    </div>
  );
}

// --------------------------------------------------------------------------------------
// Headline
// --------------------------------------------------------------------------------------

function Headline({ result }: { result: EstimateResult }) {
  const annual = formatEnergy(result.generation.annual_kwh);
  const lower = formatEnergy(result.uncertainty.lower, 'en', { forceUnit: annual.unit as 'kWh' | 'MWh' });
  const upper = formatEnergy(result.uncertainty.upper, 'en', { forceUnit: annual.unit as 'kWh' | 'MWh' });
  const currency = result.currency;

  return (
    <header>
      <p className="eyebrow mb-5">Your solar potential</p>

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <h1 className="figure-hero">
          {annual.value}
          <span className="ml-2 text-2xl text-ink-3">{annual.unit}</span>
        </h1>
        <span className="text-sm text-ink-3">expected each year</span>
      </div>

      <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-2">
        <span>
          Likely between{' '}
          <span className="num text-ink-1">
            {lower.value}–{upper.value} {annual.unit}
          </span>
        </span>
        <ConfidenceBadge level={result.uncertainty.confidence} />
      </p>
      <p className="mt-2 max-w-2xl text-xs leading-relaxed text-ink-3">
        {result.uncertainty.confidence_reason}
      </p>

      <div className="mt-8 grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={result.goal === 'existing' ? 'Your system' : 'Recommended system'}
          value={`${result.system.panels.count} × ${result.system.panels.watts} W`}
          note={`${result.system.capacity_kwp.toLocaleString()} kW in total. ${result.system.sizing.reason}`}
        />
        <Stat
          label="Average day"
          value={`${result.generation.daily_average_kwh.toLocaleString()} kWh`}
          note={`Best in ${result.generation.best_month_name}, weakest in ${result.generation.worst_month_name}.`}
        />
        {result.balance ? (
          <Stat
            label="Your electricity covered"
            value={`${Math.round(result.balance.solar_offset_pct)}%`}
            note={`${Math.round(result.balance.self_consumption_pct)}% of what you generate gets used on site.`}
          />
        ) : (
          <Stat
            label="Monthly average"
            value={`${result.generation.monthly_average_kwh.toLocaleString()} kWh`}
            note="Tell us your consumption to see what share of your bill this covers."
          />
        )}
        {result.economics ? (
          <Stat
            label="Estimated saving"
            value={`${formatCurrency(result.economics.annual_savings_year1, currency)}/yr`}
            note={
              result.economics.payback_years
                ? `Pays for itself in about ${result.economics.payback_years.toFixed(1)} years.`
                : 'Payback depends on your tariff — check the assumptions.'
            }
          />
        ) : (
          <Stat
            label="CO₂ avoided"
            value={
              result.emissions
                ? `${result.emissions.co2_avoided_tonnes_per_year} t/yr`
                : '—'
            }
            note="Compared with the same electricity drawn from the grid."
          />
        )}
      </div>

      <p className="mt-3 text-2xs text-ink-4">
        {result.location.label} · {result.system.panels.count} × {result.system.panels.watts} W
        ({result.system.capacity_kwp} kW) · {result.system.orientation.tilt_deg}° facing{' '}
        {result.system.orientation.azimuth_compass ?? 'the equator'}
      </p>
    </header>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="bg-base p-5">
      <p className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">{label}</p>
      <p className="num mt-2 text-2xl font-medium text-ink-1">{value}</p>
      {note ? <p className="mt-2 text-xs leading-relaxed text-ink-3">{note}</p> : null}
    </div>
  );
}

function ConfidenceBadge({ level }: { level: 'high' | 'medium' | 'low' }) {
  const tone =
    level === 'high'
      ? 'border-positive/50 text-positive'
      : level === 'medium'
        ? 'border-warning/50 text-warning'
        : 'border-critical/50 text-critical';
  const label = level === 'high' ? 'High' : level === 'medium' ? 'Medium' : 'Low';
  return (
    <span className={`tag ${tone}`}>
      {/* Filled circles rather than colour alone, so the level survives greyscale (§31). */}
      <span aria-hidden="true">{level === 'high' ? '●●●' : level === 'medium' ? '●●○' : '●○○'}</span>
      {label} confidence
    </span>
  );
}

// --------------------------------------------------------------------------------------
// Explanation (§22)
// --------------------------------------------------------------------------------------

function Explanation({ result }: { result: EstimateResult }) {
  const [open, setOpen] = useState(false);

  return (
    <section className="mt-12 border border-line bg-surface-1">
      <div className="p-6 sm:p-8">
        <h2 className="text-lg font-medium text-ink-1">What does this mean?</h2>
        <p className="mt-3 max-w-3xl text-base leading-relaxed text-ink-2">
          {result.explanation.summary}
        </p>

        {result.farm?.sufficient_inputs ? (
          <div className="mt-5 border-l-2 border-solar pl-4">
            <p className="mb-2 font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
              On your farm
            </p>
            <ul className="space-y-1.5">
              {result.farm.notes.map((note, index) => (
                <li key={index} className="text-sm leading-relaxed text-ink-2">
                  {note}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <div className="border-t border-line">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="tap flex w-full items-center justify-between gap-3 px-6 py-4 text-left
            transition-colors hover:bg-surface-2 sm:px-8"
        >
          <span className="text-sm font-medium text-ink-1">What could affect this result?</span>
          <Icon name={open ? 'close' : 'arrow-right'} size={16} className="text-ink-3" />
        </button>

        {open ? (
          <div className="grid gap-px border-t border-line bg-line sm:grid-cols-2">
            {result.explanation.what_affects_this.map((item) => (
              <div key={item.key} className="bg-surface-1 p-5">
                <h3 className="text-sm font-medium text-ink-1">{item.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-ink-2">{item.body}</p>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------------------
// Panels
// --------------------------------------------------------------------------------------

function GenerationPanel({ result }: { result: EstimateResult }) {
  const [unit, setUnit] = useState<MonthlyUnit>('kWh');
  const demandProfile = demandProfileOf(result);

  return (
    <div className="space-y-12">
      <section>
        <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h2 className="text-lg font-medium text-ink-1">Month by month</h2>
            <p className="mt-1 text-sm text-ink-2">
              Generation rises and falls with the season. Plan around the weak months, not
              the average.
            </p>
          </div>
          <div className="flex gap-1" role="group" aria-label="Units">
            {(
              [
                ['kWh', 'kWh'],
                ['MWh', 'MWh'],
                ['daily', 'Daily avg'],
              ] as [MonthlyUnit, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setUnit(key)}
                aria-pressed={unit === key}
                className={`min-h-touch border px-4 py-2.5 text-xs transition-colors sm:min-h-0
                  sm:py-1.5 ${
                  unit === key
                    ? 'border-solar text-solar'
                    : 'border-line text-ink-2 hover:border-line-bright hover:text-ink-1'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <MonthlyChart data={result.generation.monthly_ranges} unit={unit} />

        <div className="scroll-x mt-6">
          <table className="data-table">
            <caption className="sr-only">
              Expected generation and likely range for each month
            </caption>
            <thead>
              <tr>
                <th scope="col">Month</th>
                <th scope="col" className="numeric">
                  Expected
                </th>
                <th scope="col" className="numeric">
                  Likely range
                </th>
                <th scope="col" className="numeric">
                  Daily average
                </th>
              </tr>
            </thead>
            <tbody>
              {result.generation.monthly_ranges.map((row) => (
                <tr key={row.month}>
                  <td>{row.month_name}</td>
                  <td className="numeric text-ink-1">
                    {row.expected_kwh.toLocaleString()} kWh
                  </td>
                  <td className="numeric">
                    {row.lower_kwh.toLocaleString()}–{row.upper_kwh.toLocaleString()}
                  </td>
                  <td className="numeric">{row.daily_average_kwh} kWh</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium text-ink-1">A typical day</h2>
        <p className="mb-5 mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
          Solar arrives in the middle of the day. Where your own demand sits relative to
          this curve decides how much of it you use yourself rather than exporting.
        </p>
        <DayProfileChart
          generation={result.generation.daily_profile_kwh}
          consumption={demandProfile}
        />
      </section>

      <UncertaintySection result={result} />
    </div>
  );
}

function SavingsPanel({ result }: { result: EstimateResult }) {
  const { economics, balance, currency } = result;

  if (!economics || !balance) {
    return (
      <EmptyPanel
        title="We need your electricity use to work out savings"
        body="Savings depend on what you currently pay and how much of the solar you use yourself. Run the estimate again with your bill or your monthly units and this fills in."
      />
    );
  }

  return (
    <div className="space-y-12">
      <section>
        <h2 className="text-lg font-medium text-ink-1">Where the energy goes</h2>
        <p className="mb-6 mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
          Generating as much as you consume over a year is not the same as covering your
          bill. What matters is how much lines up with when you actually use electricity.
        </p>

        <div className="grid gap-8 lg:grid-cols-2">
          <BalanceBar
            label="What you generate"
            total={balance.generation_kwh}
            segments={[
              {
                key: 'self',
                label: 'Used on site',
                value: balance.self_consumed_kwh,
                className: 'bg-solar',
              },
              {
                key: 'export',
                label: 'Exported',
                value: balance.exported_kwh,
                className: 'bg-solar-dim',
              },
            ]}
          />
          <BalanceBar
            label="What you consume"
            total={balance.consumption_kwh}
            segments={[
              {
                key: 'solar',
                label: 'Covered by solar',
                value: balance.self_consumed_kwh,
                className: 'bg-solar',
              },
              {
                key: 'grid',
                label: 'Still bought from the grid',
                value: balance.imported_kwh,
                className: 'bg-steel-dim',
              },
            ]}
          />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium text-ink-1">The money</h2>
        <div className="mt-5 grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="System cost"
            value={formatCurrency(economics.total_capex, currency)}
            note={
              economics.battery_cost > 0
                ? `Including ${formatCurrency(economics.battery_cost, currency)} of storage.`
                : 'Before any subsidy.'
            }
          />
          <Stat
            label="Saving, year one"
            value={formatCurrency(economics.annual_savings_year1, currency)}
            note={`About ${formatCurrency(economics.monthly_savings_year1, currency)} a month.`}
          />
          <Stat
            label="Payback"
            value={
              economics.payback_years ? `${economics.payback_years.toFixed(1)} yr` : 'Not within life'
            }
            note={`Over an assumed ${economics.lifetime_years}-year life.`}
          />
          <Stat
            label="CO₂ avoided"
            value={`${(economics.co2_avoided_kg_per_year / 1000).toFixed(2)} t/yr`}
            note={
              result.emissions?.equivalences[0]
                ? `${result.emissions.equivalences[0].phrase.replace(/^roughly |^about /, 'Roughly ')} — ${result.emissions.equivalences[0].value.toLocaleString()} ${result.emissions.equivalences[0].unit}.`
                : undefined
            }
          />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium text-ink-1">Over the system's life</h2>
        <p className="mb-5 mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
          Output falls slightly each year as the panels age, while electricity prices
          generally rise. Both are modelled here.
        </p>
        <CashflowChart
          years={economics.yearly}
          symbol={currency.symbol}
          paybackYear={economics.payback_years}
        />
      </section>

      <section className="border border-warning/40 bg-warning/5 p-5">
        <h2 className="flex items-center gap-2 text-sm font-medium text-ink-1">
          <Icon name="info" size={16} className="text-warning" />
          Read these before trusting the figures
        </h2>
        <ul className="mt-3 space-y-2">
          {economics.caveats.map((caveat, index) => (
            <li key={index} className="text-sm leading-relaxed text-ink-2">
              {caveat}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function SystemPanel({
  result,
  onUpdated,
}: {
  result: EstimateResult;
  onUpdated: (updated: EstimateResult) => void;
}) {
  const { system } = result;
  const existing = result.goal === 'existing';
  return (
    <div className="space-y-10">
      <section>
        <h2 className="mb-5 text-lg font-medium text-ink-1">
          {existing ? 'Your array' : 'The panels'}
        </h2>
        <PanelConfigurator result={result} onUpdated={onUpdated} />
      </section>

      <section>
        <SystemSpecification result={result} />
      </section>

      <section>
        <h2 className="text-lg font-medium text-ink-1">
          {existing ? 'Your system' : 'What we recommend'}
        </h2>
        <dl className="mt-5 grid gap-px border border-line bg-line sm:grid-cols-2">
          <Detail label="System size" value={`${system.capacity_kwp} kW`} note={system.sizing.reason} />
          <Detail
            label="Space needed"
            value={`${Math.round(system.sizing.area_required_m2).toLocaleString()} m²`}
            note={`About ${Math.round(system.sizing.area_required_sqft).toLocaleString()} sq ft, including the spacing a real installation needs.`}
          />
          <Detail
            label="Angle and direction"
            value={`${system.orientation.tilt_deg}° facing ${system.orientation.azimuth_compass ?? '—'}`}
            note={system.orientation.note}
          />
          <Detail
            label="Inverter"
            value={`${system.ac_capacity_kw} kW AC`}
            note={`${(system.inverter_efficiency * 100).toFixed(1)}% efficient. A DC-to-AC ratio near 1.2 is normal.`}
          />
        </dl>
      </section>

      {system.battery ? (
        <section>
          <h2 className="text-lg font-medium text-ink-1">Battery storage</h2>
          <dl className="mt-5 grid gap-px border border-line bg-line sm:grid-cols-2">
            <Detail
              label="Capacity"
              value={`${system.battery.capacity_kwh} kWh`}
              note={system.battery.basis}
            />
            <Detail
              label="Usable"
              value={`${system.battery.usable_kwh} kWh`}
              note="Batteries are not run flat; this is what you can actually draw."
            />
            {system.battery.backup_hours ? (
              <Detail
                label="Backup"
                value={`${system.battery.backup_hours} hours`}
                note={
                  system.battery.critical_load_kw
                    ? `Running ${system.battery.critical_load_kw} kW of essential load.`
                    : undefined
                }
              />
            ) : null}
            <Detail label="Charging" value="From your own solar" note={system.battery.charging_note} />
          </dl>
        </section>
      ) : null}

      {result.demand ? (
        <section>
          <h2 className="text-lg font-medium text-ink-1">Your electricity use</h2>
          <p className="mt-1 text-sm text-ink-2">{result.demand.method_label}.</p>
          <dl className="mt-5 grid gap-px border border-line bg-line sm:grid-cols-3">
            <Detail
              label="Each year"
              value={`${result.demand.annual_kwh.toLocaleString()} kWh`}
            />
            <Detail
              label="Each month"
              value={`${result.demand.monthly_kwh.toLocaleString()} kWh`}
            />
            <Detail label="Each day" value={`${result.demand.daily_kwh} kWh`} />
          </dl>

          {result.demand.breakdown.length > 0 ? (
            <div className="scroll-x mt-6">
              <table className="data-table">
                <caption className="sr-only">Equipment behind the consumption estimate</caption>
                <thead>
                  <tr>
                    <th scope="col">Equipment</th>
                    <th scope="col" className="numeric">
                      How many
                    </th>
                    <th scope="col" className="numeric">
                      Hours/day
                    </th>
                    <th scope="col" className="numeric">
                      Units/month
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.demand.breakdown.map((row, index) => (
                    <tr key={`${row.key}-${index}`}>
                      <td>{row.label}</td>
                      <td className="numeric">{row.count}</td>
                      <td className="numeric">{row.hours_per_day}</td>
                      <td className="numeric text-ink-1">{row.monthly_kwh}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {result.demand.notes.map((note, index) => (
            <p key={index} className="mt-3 text-xs leading-relaxed text-ink-3">
              {note}
            </p>
          ))}
        </section>
      ) : null}
    </div>
  );
}

function WeatherPanel({ result }: { result: EstimateResult }) {
  const { generation } = result;
  return (
    <div className="space-y-10">
      <section>
        <h2 className="text-lg font-medium text-ink-1">The solar resource where you are</h2>
        <p className="mb-5 mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
          Everything here was measured at your location, not assumed from your region.
        </p>
        <dl className="grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
          <Detail
            label="Sunlight received"
            value={`${Math.round(generation.mean_ghi_kwh_per_m2_year).toLocaleString()} kWh/m²`}
            note="Horizontal surface, each year."
          />
          <Detail
            label="On your panels"
            value={`${Math.round(generation.mean_poa_kwh_per_m2_year).toLocaleString()} kWh/m²`}
            note="Higher than horizontal, because the panels are tilted toward the sun."
          />
          <Detail
            label="Yield per kW installed"
            value={`${Math.round(generation.specific_yield_kwh_per_kwp).toLocaleString()} kWh`}
            note="The standard way to compare locations."
          />
          <Detail
            label="Performance ratio"
            value={generation.performance_ratio.toFixed(2)}
            note="How much of the available energy the system actually delivers, after heat and losses."
          />
        </dl>
      </section>

      <section>
        <h2 className="text-lg font-medium text-ink-1">The record behind this</h2>
        <dl className="mt-5 grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
          <Detail
            label="Hours of weather"
            value={generation.rows_used.toLocaleString()}
            note={`From ${generation.period_start} to ${generation.period_end}.`}
          />
          <Detail
            label="Complete years"
            value={String(generation.complete_calendar_years)}
            note="Used to measure how much the years differ."
          />
          <Detail
            label="Data completeness"
            value={`${(result.data_completeness * 100).toFixed(1)}%`}
            note={
              generation.rows_dropped > 0
                ? `${generation.rows_dropped.toLocaleString()} incomplete hours were left out rather than filled in.`
                : 'No gaps in the record.'
            }
          />
          <Detail
            label="Inverter clipping"
            value={`${(generation.clipped_fraction * 100).toFixed(1)}%`}
            note="Share of daylight hours where the inverter limits output."
          />
        </dl>
        <p className="mt-4 text-xs leading-relaxed text-ink-3">
          {generation.variability_basis}
        </p>
      </section>

      {generation.warnings.length > 0 ? (
        <section className="border border-line bg-surface-1 p-5">
          <h2 className="text-sm font-medium text-ink-1">Notes on the data</h2>
          <ul className="mt-3 space-y-2">
            {generation.warnings.map((warning, index) => (
              <li key={index} className="text-sm leading-relaxed text-ink-2">
                {warning}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function UncertaintySection({ result }: { result: EstimateResult }) {
  return (
    <section>
      <h2 className="text-lg font-medium text-ink-1">How certain is this?</h2>
      <p className="mb-5 mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
        {result.uncertainty.confidence_reason}
      </p>
      <div className="scroll-x">
        <table className="data-table">
          <caption className="sr-only">Sources of uncertainty in this estimate</caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col" className="numeric">
                Size
              </th>
              <th scope="col">Can it be reduced?</th>
            </tr>
          </thead>
          <tbody>
            {result.uncertainty.factors.map((factor) => (
              <tr key={factor.key}>
                <td>
                  <span className="block text-ink-1">{factor.label}</span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-ink-3">
                    {factor.explanation}
                  </span>
                </td>
                <td className="numeric align-top text-ink-1">±{factor.relative_pct}%</td>
                <td className="align-top text-xs">
                  {factor.reducible_by ?? 'No — this is weather that has not happened yet.'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {result.uncertainty.improvements.length > 0 ? (
        <div className="mt-6 border border-line bg-surface-1 p-5">
          <h3 className="text-sm font-medium text-ink-1">To tighten this estimate</h3>
          <ul className="mt-3 space-y-2">
            {result.uncertainty.improvements.map((item, index) => (
              <li key={index} className="flex gap-2.5 text-sm leading-relaxed text-ink-2">
                <Icon name="arrow-right" size={15} className="mt-0.5 shrink-0 text-steel" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function AssumptionsPanel({
  result,
  onUpdated,
}: {
  result: EstimateResult;
  onUpdated: (updated: EstimateResult) => void;
}) {
  return (
    <div className="space-y-10">
      <section>
        <h2 className="text-lg font-medium text-ink-1">Everything we assumed</h2>
        <p className="mb-5 mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
          Every figure on this page rests on these. Anything marked{' '}
          <span className="text-ink-1">You told us</span> came from you; the rest are
          defaults we chose and stated.
        </p>
        <div className="scroll-x">
          <table className="data-table">
            <caption className="sr-only">Assumptions behind this estimate</caption>
            <thead>
              <tr>
                <th scope="col">Assumption</th>
                <th scope="col" className="numeric">
                  Value
                </th>
                <th scope="col">Where it came from</th>
              </tr>
            </thead>
            <tbody>
              {result.assumptions.map((assumption) => (
                <tr key={assumption.key}>
                  <td>
                    <span className="block text-ink-1">{assumption.label}</span>
                    {assumption.rationale ? (
                      <span className="mt-0.5 block text-xs leading-relaxed text-ink-3">
                        {assumption.rationale}
                      </span>
                    ) : null}
                  </td>
                  <td className="numeric align-top text-ink-1">
                    {String(assumption.value)}
                    {assumption.unit ? ` ${assumption.unit}` : ''}
                  </td>
                  <td className="align-top">
                    <span
                      className={`tag ${
                        assumption.provenance === 'user_supplied'
                          ? 'border-solar/50 text-solar'
                          : assumption.provenance === 'measured'
                            ? 'border-steel/50 text-steel'
                            : 'border-line-strong text-ink-3'
                      }`}
                    >
                      {assumption.provenance_label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <AssumptionEditor result={result} onUpdated={onUpdated} />
      </section>

      <section>
        <h2 className="text-lg font-medium text-ink-1">Where the data came from</h2>
        <ul className="mt-5 space-y-px bg-line">
          {result.data_sources.map((source) => (
            <li key={source.category} className="bg-base p-5">
              <p className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
                {source.category}
              </p>
              <p className="mt-1.5 text-sm font-medium text-ink-1">{source.name}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-ink-2">{source.detail}</p>
              <p className="mt-2 text-2xs text-ink-4">{source.licence}</p>
              {source.caveat ? (
                <p className="mt-2 border-l-2 border-line-strong pl-3 text-xs leading-relaxed text-ink-3">
                  {source.caveat}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      {result.warnings.length > 0 ? (
        <section>
          <h2 className="text-lg font-medium text-ink-1">Notes raised while calculating</h2>
          <ul className="mt-4 space-y-2">
            {result.warnings.map((warning, index) => (
              <li
                key={index}
                className="flex gap-2.5 border-l-2 border-line-strong pl-3 text-sm
                  leading-relaxed text-ink-2"
              >
                {warning}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function ScenariosPanel({ result }: { result: EstimateResult }) {
  return (
    <EmptyPanel
      title="Compare different system sizes"
      body={`Your estimate is built around a ${result.system.capacity_kwp} kW system. Comparing several sizes side by side — generation, cost, payback, space needed — runs the same weather and the same assumptions through each one.`}
      action={
        <Link
          href={`/compare?from=${result.estimate_id}`}
          className="tap inline-flex items-center gap-2 border border-solar bg-solar px-5 py-2.5
            text-sm font-medium text-base transition-opacity hover:opacity-90"
        >
          Compare system sizes
          <Icon name="arrow-right" size={16} />
        </Link>
      }
    />
  );
}

function ReportPanel({ result }: { result: EstimateResult }) {
  const [report, setReport] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function fetchReport() {
    setLoading(true);
    setFailed(false);
    try {
      setReport(await estimateApi.report(result.estimate_id!));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  function download() {
    if (!report) return;
    const blob = new Blob([report], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `solar-estimate-${result.estimate_id}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <h2 className="text-lg font-medium text-ink-1">A report you can share</h2>
      <p className="mb-5 mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
        The full analysis written out — system, generation month by month, consumption,
        savings, uncertainty, methodology, every assumption and every data source. Suitable
        to send to an installer, a manager or a lender.
      </p>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void fetchReport()}
          disabled={loading}
          className="tap inline-flex items-center gap-2 border border-line-strong px-5 py-2.5
            text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar
            disabled:opacity-60"
        >
          <Icon name="list" size={16} />
          {loading ? 'Preparing…' : report ? 'Refresh' : 'Generate report'}
        </button>
        {report ? (
          <button
            type="button"
            onClick={download}
            className="tap inline-flex items-center gap-2 border border-solar bg-solar px-5 py-2.5
              text-sm font-medium text-base transition-opacity hover:opacity-90"
          >
            <Icon name="download" size={16} />
            Download
          </button>
        ) : null}
      </div>

      {failed ? (
        <p role="alert" className="mt-4 text-sm text-critical">
          The report could not be generated just now. Try again in a moment.
        </p>
      ) : null}

      {report ? (
        <pre className="scroll-x mt-6 max-h-[32rem] overflow-y-auto border border-line
          bg-surface-1 p-5 text-xs leading-relaxed text-ink-2">
          {report}
        </pre>
      ) : null}
    </div>
  );
}

function EmptyPanel({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="border border-line bg-surface-1 p-8 text-center">
      <h2 className="text-lg font-medium text-ink-1">{title}</h2>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-ink-2">{body}</p>
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  );
}

function Detail({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="bg-base p-5">
      <dt className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">{label}</dt>
      <dd className="num mt-2 text-lg font-medium text-ink-1">{value}</dd>
      {note ? <dd className="mt-1.5 text-xs leading-relaxed text-ink-3">{note}</dd> : null}
    </div>
  );
}

// --------------------------------------------------------------------------------------
// Actions (§35)
// --------------------------------------------------------------------------------------

function Actions({ result }: { result: EstimateResult }) {
  const [copied, setCopied] = useState(false);

  async function share() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2400);
    } catch {
      // Clipboard access can be refused; the URL is in the address bar either way.
      setCopied(false);
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-8">
      <button
        type="button"
        onClick={() => void share()}
        className="tap inline-flex items-center gap-2 border border-line-strong px-5 py-2.5
          text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar"
      >
        <Icon name="share" size={16} />
        {copied ? 'Link copied' : 'Copy share link'}
      </button>
      <Link
        href="/projects"
        className="tap inline-flex items-center gap-2 border border-line px-5 py-2.5 text-sm
          text-ink-2 transition-colors hover:border-line-bright hover:text-ink-1"
      >
        My analyses
      </Link>
      <Link
        href="/start"
        className="tap inline-flex items-center gap-2 border border-line px-5 py-2.5 text-sm
          text-ink-2 transition-colors hover:border-line-bright hover:text-ink-1"
      >
        Start a new estimate
      </Link>
      <p className="ml-auto max-w-xs text-2xs leading-relaxed text-ink-4">
        This estimate is saved at its own link. Anyone with the link can view it, so share
        it only with people you mean to.
      </p>
    </div>
  );
}

/**
 * The hourly demand shape for the day-profile overlay.
 *
 * Taken from the response, never reconstructed here. These are the exact values the
 * self-consumption split was computed from, so the curve the reader sees is the curve the
 * calculation used. A client-side copy of the archetypes would drift the moment the
 * backend changed one, and the chart would then quietly misrepresent the number beside it.
 */
function demandProfileOf(result: EstimateResult): number[] | undefined {
  const hourly = result.demand?.hourly_kwh;
  return hourly && hourly.length === 24 ? hourly : undefined;
}
