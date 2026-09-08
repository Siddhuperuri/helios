'use client';

import { Icon } from '@/components/site/Icon';
import type { EstimateResult } from '@/lib/estimate';

/**
 * The array, described twice — once for each reader.
 *
 * §13 says a beginner should never need to understand DC capacity, STC, Voc, Isc, MPPT,
 * DC/AC ratio or temperature coefficients *unless they chose Detailed Analysis*. §14 says
 * an expert must be able to see all of it. Both are satisfied by the same rule: the
 * vocabulary is gated on the mode the user picked, and everything technical sits inside a
 * disclosure rather than on the page by default.
 *
 * So a farmer on Quick Estimate reads "40 panels of 550 W, and the inverter is well
 * matched to them". An engineer on Detailed Analysis reads the same thing plus the ratio,
 * the coefficients and the datasheet — and can open the technical panel on the quick path
 * too, if curious. Nothing is hidden; it is only unasked-for.
 *
 * The other rule this component holds to: four areas, never collapsed. A reader comparing
 * panel area against roof area and concluding it fits is the §6 failure this display
 * exists to prevent.
 */

export function SystemSpecification({ result }: { result: EstimateResult }) {
  const { panels, space, inverter } = result.system;
  const expert = result.mode === 'detailed';

  return (
    <div className="space-y-10">
      {/* --------------------------------------------------- the array, in plain terms */}
      <section>
        <h3 className="mb-1 text-base font-medium text-ink-1">Your panels</h3>
        <p className="mb-4 max-w-2xl text-sm leading-relaxed text-ink-2">
          {panels.count} panels of {panels.watts} W each.{' '}
          {panels.watts_known
            ? 'That is the rating you told us.'
            : 'We assumed a typical modern panel, because the rating was not known — the real number is printed on the panel label.'}
        </p>

        {/* The inverter finding, in whichever register the reader chose. */}
        <div
          className={`border p-4 ${
            inverter.severity === 'caution'
              ? 'border-warning/40 bg-warning/5'
              : 'border-line bg-surface-1'
          }`}
        >
          <p className="flex items-start gap-2.5 text-sm text-ink-1">
            <Icon
              name={inverter.severity === 'caution' ? 'alert' : 'check'}
              size={18}
              className={
                inverter.severity === 'caution' ? 'mt-0.5 text-warning' : 'mt-0.5 text-positive'
              }
            />
            <span>{expert ? inverter.verdict : inverter.plain}</span>
          </p>
          {expert ? (
            <dl className="mt-4 grid gap-px border border-line bg-line sm:grid-cols-3">
              <Cell label="Inverter" value={`${inverter.ac_capacity_kw} kW AC`} />
              <Cell
                label="DC to AC ratio"
                value={inverter.dc_ac_ratio.toFixed(2)}
                note={`Typical range ${inverter.typical_range[0]}–${inverter.typical_range[1]}.`}
              />
              <Cell
                label="Clipped hours"
                value={`${(result.generation.clipped_fraction * 100).toFixed(1)}%`}
                note="Daylight hours where the inverter limits output."
              />
            </dl>
          ) : null}
        </div>
      </section>

      {/* --------------------------------------------------------------- space (§6) */}
      <section>
        <h3 className="mb-1 text-base font-medium text-ink-1">Space</h3>
        <p className="mb-4 max-w-2xl text-sm leading-relaxed text-ink-2">
          A roof is not a rectangle of glass. These are four different things, and the one
          that has to fit is the footprint.
        </p>

        <ol className="space-y-px bg-line">
          {space.available_area_m2 ? (
            <AreaRow
              step="1"
              label="Space you have"
              value={space.available_area_m2}
              note="The whole roof or plot, as you described it."
              width={100}
            />
          ) : null}
          {space.usable_area_m2 ? (
            <AreaRow
              step="2"
              label="Space you can build on"
              value={space.usable_area_m2}
              note={`${space.usable_pct}% of it. ${space.usable_note}`}
              width={space.usable_pct}
              emphasis
            />
          ) : null}
          <AreaRow
            step={space.available_area_m2 ? '3' : '1'}
            label="Space the array takes"
            value={space.footprint_m2}
            note={`What ${panels.count} panels occupy once rows are spaced and access is left.`}
            width={
              space.available_area_m2
                ? Math.min(100, (space.footprint_m2 / space.available_area_m2) * 100)
                : 100
            }
            emphasis
          />
          <AreaRow
            step={space.available_area_m2 ? '4' : '2'}
            label="The panels themselves"
            value={space.module_area_m2}
            note={`The glass alone — ${space.panel_area_m2} m² per panel × ${panels.count}.`}
            width={
              space.available_area_m2
                ? Math.min(100, (space.module_area_m2 / space.available_area_m2) * 100)
                : Math.min(100, (space.module_area_m2 / space.footprint_m2) * 100)
            }
          />
        </ol>

        {space.fits !== null ? (
          <div
            className={`mt-5 border p-4 ${
              space.fits ? 'border-positive/40 bg-positive/5' : 'border-warning/40 bg-warning/5'
            }`}
          >
            <p className="flex items-start gap-2.5 text-sm text-ink-1">
              <Icon
                name={space.fits ? 'check' : 'alert'}
                size={18}
                className={space.fits ? 'mt-0.5 text-positive' : 'mt-0.5 text-warning'}
              />
              <span>
                {space.fits
                  ? `This array fits the space you described, using ${space.utilisation_pct}% of the part you can build on.`
                  : `This array does not fit the space you described. About ${space.max_panels_in_space} panels would.`}
              </span>
            </p>
          </div>
        ) : null}
      </section>

      {/* ------------------------------------------------- technical detail (§9, §14) */}
      <section>
        <details open={expert} className="border border-line bg-surface-1">
          <summary
            className="tap flex cursor-pointer list-none items-center justify-between gap-3
              px-5 py-4 text-sm font-medium text-ink-1 transition-colors hover:bg-surface-2"
          >
            <span>
              Full specification
              <span className="ml-2 font-normal text-ink-3">
                {expert ? '' : '— technical detail, if you want it'}
              </span>
            </span>
            <Icon name="sliders" size={16} className="shrink-0 text-ink-3" />
          </summary>

          <div className="border-t border-line p-5">
            <p className="mb-4 max-w-2xl text-xs leading-relaxed text-ink-2">
              Where each figure came from is marked. Anything estimated can be replaced by
              the real value from your panel label, quote or datasheet.
            </p>

            <div className="scroll-x">
              <table className="data-table">
                <caption className="sr-only">
                  Panel specification with the source of each value
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Property</th>
                    <th scope="col" className="numeric">Value</th>
                    <th scope="col">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {panels.specification.map((row) => (
                    <tr key={row.label}>
                      <td className="text-ink-1">{row.label}</td>
                      <td className="numeric text-ink-1">
                        {row.value}
                        {row.unit ? <span className="ml-1 text-ink-3">{row.unit}</span> : null}
                      </td>
                      <td>
                        <ProvenanceTag provenance={row.provenance} label={row.provenance_label} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Electrical characteristics: shown as supplied, blank when not (§14). */}
            <h4 className="mb-2 mt-8 text-sm font-medium text-ink-1">
              Electrical characteristics
            </h4>
            <p className="mb-3 max-w-2xl text-xs leading-relaxed text-ink-3">
              {panels.datasheet_note}
            </p>
            <div className="scroll-x">
              <table className="data-table">
                <caption className="sr-only">Datasheet electrical characteristics</caption>
                <thead>
                  <tr>
                    <th scope="col">Characteristic</th>
                    <th scope="col" className="numeric">Value</th>
                    <th scope="col">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {panels.datasheet.map((row) => (
                    <tr key={row.key}>
                      <td>
                        <span className="block text-ink-1">{row.label}</span>
                        <span className="mt-0.5 block text-xs leading-relaxed text-ink-3">
                          {row.note}
                        </span>
                      </td>
                      <td className="numeric align-top text-ink-1">
                        {row.value !== null ? (
                          <>
                            {row.value}
                            <span className="ml-1 text-ink-3">{row.unit}</span>
                          </>
                        ) : (
                          <span className="text-ink-4">—</span>
                        )}
                      </td>
                      <td className="align-top">
                        {row.value !== null ? (
                          <ProvenanceTag provenance="user_provided" label="User provided" />
                        ) : (
                          <span className="text-xs text-ink-4">Not supplied</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <ul className="mt-6 space-y-2">
              {space.notes.map((note, index) => (
                <li key={index} className="text-xs leading-relaxed text-ink-3">
                  {note}
                </li>
              ))}
            </ul>
          </div>
        </details>
      </section>
    </div>
  );
}

function ProvenanceTag({ provenance, label }: { provenance: string; label: string }) {
  return (
    <span
      className={`tag ${
        provenance === 'user_provided'
          ? 'border-solar/50 text-solar'
          : provenance === 'datasheet'
            ? 'border-steel/50 text-steel'
            : 'border-line-strong text-ink-3'
      }`}
    >
      {label}
    </span>
  );
}

function AreaRow({
  step,
  label,
  value,
  note,
  width,
  emphasis = false,
}: {
  step: string;
  label: string;
  value: number;
  note: string;
  width: number;
  emphasis?: boolean;
}) {
  return (
    <li className="bg-base p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="flex items-baseline gap-2.5">
          <span className="num text-2xs text-ink-4">{step}</span>
          <span className="text-sm font-medium text-ink-1">{label}</span>
        </span>
        <span className="num text-base text-ink-1">
          {value.toLocaleString(undefined, { maximumFractionDigits: 0 })} m²
          <span className="ml-2 text-2xs text-ink-4">
            {Math.round(value * 10.7639).toLocaleString()} sq ft
          </span>
        </span>
      </div>
      {/* A bar rather than a number alone: the point of this section is the relative size
          of four quantities people assume are one. */}
      <div className="mt-2 h-1.5 w-full bg-surface-3" aria-hidden="true">
        <div
          className={emphasis ? 'h-full bg-solar' : 'h-full bg-steel'}
          style={{ width: `${Math.max(1, Math.min(100, width))}%` }}
        />
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-ink-3">{note}</p>
    </li>
  );
}

function Cell({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="bg-base p-4">
      <dt className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">{label}</dt>
      <dd className="num mt-1.5 text-lg font-medium text-ink-1">{value}</dd>
      {note ? <dd className="mt-1 text-xs leading-relaxed text-ink-3">{note}</dd> : null}
    </div>
  );
}
