import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'About',
  description: 'What Helios is, what it is built on, and what it will not do.',
};

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-3xl px-5 py-10 sm:px-8 lg:py-16">
      <p className="eyebrow mb-5">About</p>
      <h1 className="text-2xl font-medium leading-tight tracking-tight text-ink-1 sm:text-3xl">
        A solar estimate you can check
      </h1>

      <div className="mt-8 space-y-5 text-base leading-relaxed text-ink-2">
        <p>
          Most solar calculators ask for a roof size and return a confident number. The
          number is usually a regional average multiplied by an area, and there is no way to
          tell what went into it — which means there is no way to tell whether it applies to
          you.
        </p>
        <p>
          Helios takes the opposite approach. It runs years of real hourly weather for your
          exact coordinates through published photovoltaic models, states every assumption it
          made, and puts an honest range around the answer. If your inputs were thin, it says
          so and the range widens. If a figure rests on a default rather than something you
          told it, that is labelled.
        </p>
        <p>
          It began as a research platform for irradiance forecasting — time-aware
          validation, calibrated prediction intervals, traceable results. That work is still
          here, in full, at the{' '}
          <Link href="/advanced" className="link-underline text-ink-1">
            analysis console
          </Link>
          . What was added is the layer that turns it into an answer for somebody who does
          not want to read a model card: consumption, sizing, storage, cost and plain
          language.
        </p>
      </div>

      <h2 className="mt-12 text-lg font-medium text-ink-1">Built on</h2>
      <dl className="mt-5 space-y-4">
        {[
          [
            'ERA5 reanalysis, via Open-Meteo',
            'Hourly global irradiance, temperature, wind and cloud cover, worldwide, from 2000 onward. Licensed CC-BY 4.0; ERA5 is produced by ECMWF for the Copernicus Climate Change Service.',
          ],
          [
            'Published conversion models',
            'Erbs decomposition, HDKR transposition, Faiman cell temperature, and the PVWatts v5 DC model (Dobos 2014, NREL/TP-6A20-62641).',
          ],
          [
            'OpenStreetMap and GeoNames',
            'Map tiles, place search and reverse geocoding.',
          ],
          [
            'No API keys, anywhere',
            'Every upstream data service used is keyless and public. Nothing about your location is sent to an advertising network.',
          ],
          [
            'An account is optional',
            'The calculator never asks who you are, and an estimate produced without an account keeps working — it gets its own private link. An account only means your estimates follow you between devices instead of living in a link you have to keep.',
          ],
        ].map(([term, description]) => (
          <div key={term} className="border-t border-line pt-4">
            <dt className="text-sm font-medium text-ink-1">{term}</dt>
            <dd className="mt-1.5 text-sm leading-relaxed text-ink-2">{description}</dd>
          </div>
        ))}
      </dl>

      <h2 className="mt-12 text-lg font-medium text-ink-1">What it will not do</h2>
      <ul className="mt-5 space-y-3">
        {[
          'Present a modelled figure as a measurement.',
          'Report a number without the data behind it.',
          'Invent a tariff, a quotation, or a subsidy.',
          'Claim an accuracy it has not measured.',
          'Hide a weak estimate behind a confident-looking figure.',
        ].map((line) => (
          <li key={line} className="border-l-2 border-line-strong pl-4 text-sm text-ink-2">
            {line}
          </li>
        ))}
      </ul>

      <p className="mt-12 border-t border-line pt-6 text-xs leading-relaxed text-ink-3">
        Estimates produced here are for planning. They are not a structural, electrical or
        shading survey, and they are not financial advice. Before installing anything, get a
        site visit and a quotation.
      </p>
    </div>
  );
}
