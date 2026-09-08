'use client';

import { useState } from 'react';

import { ScenarioResponse, api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import {
  Button,
  Callout,
  ErrorState,
  LoadingPanel,
  Metric,
  MetricGrid,
  Panel,
  Section,
  Tag,
} from '@/components/ui';
import { num, signed } from '@/lib/format';

/**
 * Scenario workspace.
 *
 * The SIMULATION marking is not decoration: no figure on this screen is an observation,
 * and the layout is built so that fact is unavoidable — the label sits above the numbers,
 * the assumptions are listed beside them, and the validity assessment is given equal
 * weight to the result itself.
 */
export function ScenariosView({ analysisId }: { analysisId: string }) {
  const presets = useAsync(() => api.scenarioPresets(), []);
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(presetKey: string) {
    setRunning(presetKey);
    setError(null);
    try {
      const r = await api.scenario(analysisId, { kind: 'meteorological', preset_key: presetKey });
      setResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(null);
    }
  }

  const pathway = result?.validity.pathway_decomposition;

  return (
    <div className="space-y-14">
      <Section
        label="Scenario simulator"
        title="What if conditions were different?"
        description="Each scenario perturbs the weather inputs, re-runs the fitted model and the physical chain, and reports the difference against the same period's baseline. Nothing here is an observation."
      >
        <Callout tone="simulation" title="Simulation — modelled scenario">
          Every figure produced in this view is a modelled counterfactual conditional on the
          assumptions listed with it. Scenario outputs are never presented as measurements and
          are not comparable with the observed results shown elsewhere in this platform.
        </Callout>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(presets.data?.presets ?? []).map((p) => (
            <Panel key={p.key} className="flex flex-col justify-between">
              <div>
                <h3 className="mb-1.5 text-xs font-medium text-ink-1">{p.name}</h3>
                <p className="text-2xs leading-relaxed text-ink-3">{p.description}</p>
              </div>
              <Button
                size="sm"
                className="mt-4 self-start"
                onClick={() => run(p.key)}
                disabled={running !== null}
              >
                {running === p.key ? 'Running…' : 'Run scenario'}
              </Button>
            </Panel>
          ))}
        </div>

        {error ? (
          <div className="mt-6">
            <ErrorState message={error} />
          </div>
        ) : null}
      </Section>

      {running && !result ? <LoadingPanel message="Re-running the model under perturbed conditions…" /> : null}

      {result ? (
        <>
          <Section
            label={result.label}
            title={result.name}
            description={
              <>
                Applied over the held-out test period, so the comparison uses hours the model
                was never fitted on. Perturbations:{' '}
                {result.perturbations.map((p, i) => (
                  <span key={p} className="num text-ink-1">
                    {p}
                    {i < result.perturbations.length - 1 ? ', ' : ''}
                  </span>
                ))}
                .
              </>
            }
          >
            <MetricGrid cols={3}>
              <Metric
                label="Baseline energy"
                value={num(result.baseline.energy_kwh, 0)}
                unit="kWh"
                size="lg"
                hint="Model output over the test period, unperturbed."
              />
              <Metric
                label="Scenario energy"
                value={num(result.scenario.energy_kwh, 0)}
                unit="kWh"
                size="lg"
                tone="accent"
                hint="Same period under the perturbed conditions."
              />
              <Metric
                label="Difference"
                value={signed(result.difference.energy_kwh?.relative_pct ?? 0, 2)}
                unit="%"
                size="lg"
                tone={
                  (result.difference.energy_kwh?.relative_pct ?? 0) > 0 ? 'positive' : 'critical'
                }
                hint={`${signed(result.difference.energy_kwh?.absolute ?? 0, 1)} kWh absolute.`}
              />
            </MetricGrid>
          </Section>

          {pathway ? (
            <Section
              label="Pathway decomposition"
              title="Two mechanisms, and they can cancel"
              description="A weather perturbation moves the result through two quite different routes. Reporting only the net change would hide a sign flip that a reviewer would rightly challenge."
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Panel>
                  <div className="mb-2">
                    <Tag tone="warning">correlational</Tag>
                  </div>
                  <h3 className="mb-1 text-xs font-medium text-ink-1">
                    Statistical pathway
                  </h3>
                  <p className="num mb-2 text-2xl text-ink-1">
                    {signed(pathway.statistical_pathway_kwh, 1)}
                    <span className="ml-1 text-xs text-ink-4">kWh</span>
                  </p>
                  <p className="text-2xs leading-relaxed text-ink-3">
                    Change in predicted irradiance, arising from correlations the model learned
                    between weather variables. Not a causal effect.
                  </p>
                </Panel>
                <Panel>
                  <div className="mb-2">
                    <Tag tone="positive">causal</Tag>
                  </div>
                  <h3 className="mb-1 text-xs font-medium text-ink-1">Physical pathway</h3>
                  <p className="num mb-2 text-2xl text-ink-1">
                    {signed(pathway.physical_pathway_kwh, 1)}
                    <span className="ml-1 text-xs text-ink-4">kWh</span>
                  </p>
                  <p className="text-2xs leading-relaxed text-ink-3">
                    Change in conversion efficiency from module temperature, computed from the
                    Faiman and PVWatts models. Genuinely causal.
                  </p>
                </Panel>
              </div>
              <div className="mt-4">
                <Callout tone="info" title="Why this matters">
                  {pathway.explanation}
                </Callout>
              </div>
            </Section>
          ) : null}

          <Section label="Validity" title="How far can this be trusted?">
            <Callout
              tone={
                result.validity.level === 'high'
                  ? 'positive'
                  : result.validity.level === 'moderate'
                    ? 'warning'
                    : 'critical'
              }
              title={`Confidence: ${result.validity.level}`}
            >
              {result.validity.message}
            </Callout>

            {result.validity.variables_outside_range.length ? (
              <div className="mt-4">
                <p className="mb-2 font-mono text-2xs uppercase tracking-[0.1em] text-ink-3">
                  Inputs pushed outside the training range
                </p>
                <ul className="space-y-2">
                  {result.validity.variables_outside_range.map((v) => (
                    <li key={v.variable} className="border-b border-line pb-2 text-2xs">
                      <span className="text-ink-1">{v.display_name}</span>
                      <span className="num ml-2 text-ink-3">
                        training range {num(v.training_range[0], 1)} –{' '}
                        {num(v.training_range[1], 1)}; {num(v.fraction_outside * 100, 1)}% of
                        perturbed values fall outside
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="mt-6">
              <p className="mb-2 font-mono text-2xs uppercase tracking-[0.1em] text-ink-3">
                Assumptions
              </p>
              <ul className="space-y-1.5">
                {result.assumptions.map((a) => (
                  <li key={a} className="flex gap-2 text-2xs leading-relaxed text-ink-2">
                    <span className="mt-1.5 h-px w-2 shrink-0 bg-line-bright" aria-hidden="true" />
                    {a}
                  </li>
                ))}
              </ul>
            </div>

            <div className="mt-5">
              <Callout tone="simulation" title="Disclaimer">
                {result.disclaimer}
              </Callout>
            </div>
          </Section>
        </>
      ) : null}
    </div>
  );
}
