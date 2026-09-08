import type { Metadata } from 'next';
import Link from 'next/link';

import { Icon } from '@/components/site/Icon';

export const metadata: Metadata = {
  title: 'Resources',
  description: 'Plain explanations of the terms and ideas behind a solar estimate.',
};

/**
 * A glossary, and the honest answers to the questions people ask before buying.
 *
 * This exists because §31 asks the product to serve people with limited technical
 * literacy, and the alternative to a glossary is either jargon or condescension. Terms are
 * defined where somebody would look for them rather than only in a tooltip they have to
 * find twice.
 */

const TERMS = [
  {
    term: 'Unit (kWh)',
    plain:
      'What your electricity bill counts. One unit runs a 1,000-watt appliance for an hour — an iron for an hour, or ten LED bulbs for ten hours.',
  },
  {
    term: 'kW and kWp',
    plain:
      'The size of a system, not how much it makes. A 5 kW system produces 5 kW at its very best moment. Over a year in India it typically generates 1,300–1,600 units per kW installed.',
  },
  {
    term: 'Tilt',
    plain:
      'How steeply the panels lean. Flat collects less over a year than a tilt near your latitude. We work out the best angle for your location rather than guessing.',
  },
  {
    term: 'Azimuth',
    plain:
      'Which way the panels face. In India that is south. Facing east or west costs some output but is not disqualifying.',
  },
  {
    term: 'Inverter',
    plain:
      'The box that turns the panels’ DC electricity into the AC your building uses. It is usually the first thing to fail, and the cheapest one is rarely the cheapest over twenty years.',
  },
  {
    term: 'Self-consumption',
    plain:
      'The share of your solar you use yourself instead of exporting. It matters because exported units usually earn far less than the units you buy.',
  },
  {
    term: 'Solar offset',
    plain:
      'The share of your electricity covered by solar. Generating as much as you use over a year does not mean 100 per cent offset — solar arrives midday, and much use is after dark.',
  },
  {
    term: 'Payback',
    plain:
      'How long the savings take to cover the cost. It depends entirely on what you pay per unit, which is why we ask, and why a subsidised farm connection changes the answer completely.',
  },
  {
    term: 'Degradation',
    plain:
      'Panels lose about half a per cent of their output each year. After 25 years a panel typically still produces around 85 per cent of what it did when new.',
  },
  {
    term: 'Performance ratio',
    plain:
      'How much of the available sunlight energy actually reaches your meter, after heat, dust, wiring and conversion. A good system sits around 0.75 to 0.80.',
  },
];

const QUESTIONS = [
  {
    q: 'Will solar work if my area gets a heavy monsoon?',
    a: 'Yes, but plan around the weak months rather than the average. Our month-by-month figures show exactly how much the monsoon costs you, because they come from years of weather actually recorded at your location.',
  },
  {
    q: 'Do I need batteries?',
    a: 'Only if you need power when the grid is down, or you want to use your own solar after dark. They add a substantial amount to the cost and do not increase how much you generate. If your grid supply is reliable and you export at a fair rate, you may not need them.',
  },
  {
    q: 'Does heat help or hurt?',
    a: 'Sunlight helps, heat hurts. Panels lose efficiency as they warm up, so the hottest days are not the most productive. Our model accounts for this hour by hour using recorded temperature and wind.',
  },
  {
    q: 'How much space do I need?',
    a: 'Roughly 6 to 7 square metres per kW on a roof, including walkways. Ground mounting needs two to three times that, because rows must be spaced so they do not shade each other.',
  },
  {
    q: 'What if my roof faces the wrong way?',
    a: 'East or west facing typically costs 10 to 15 per cent against due south — worth knowing, rarely a reason not to proceed. Tell us the direction and the estimate accounts for it.',
  },
  {
    q: 'Why does your estimate differ from an installer’s?',
    a: 'Usually one of three things: a different assumed system size, a different tariff, or an installer using a regional average rather than your location’s own weather. Compare the assumptions panel against their quote line by line — that is what it is for.',
  },
];

export default function ResourcesPage() {
  return (
    <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 lg:py-16">
      <header className="max-w-3xl">
        <p className="eyebrow mb-5">Resources</p>
        <h1 className="text-2xl font-medium leading-tight tracking-tight text-ink-1 sm:text-3xl">
          The words, explained properly
        </h1>
        <p className="mt-4 text-base leading-relaxed text-ink-2">
          Solar has a vocabulary problem. None of these ideas are difficult, but they are
          usually explained either in jargon or not at all.
        </p>
      </header>

      <section className="mt-12">
        <p className="eyebrow mb-6">Glossary</p>
        <dl className="grid gap-px bg-line sm:grid-cols-2">
          {TERMS.map((entry) => (
            <div key={entry.term} className="bg-base p-5">
              <dt className="text-sm font-medium text-ink-1">{entry.term}</dt>
              <dd className="mt-1.5 text-sm leading-relaxed text-ink-2">{entry.plain}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mt-16">
        <p className="eyebrow mb-6">Questions people actually ask</p>
        <dl className="space-y-px bg-line">
          {QUESTIONS.map((entry) => (
            <div key={entry.q} className="bg-base p-6">
              <dt className="text-base font-medium text-ink-1">{entry.q}</dt>
              <dd className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-2">{entry.a}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mt-16">
        <p className="eyebrow mb-6">Going deeper</p>
        <ul className="grid gap-3 sm:grid-cols-2">
          <li>
            <Link
              href="/how-it-works"
              className="choice-card h-full items-center transition-colors"
            >
              <Icon name="chart" size={20} className="text-steel" />
              <span className="flex-1">
                <span className="block text-sm font-medium text-ink-1">
                  The calculation chain
                </span>
                <span className="mt-1 block text-xs leading-relaxed text-ink-2">
                  Every stage between your location and your number, with the model used at
                  each one.
                </span>
              </span>
              <Icon name="arrow-right" size={16} className="text-ink-4" />
            </Link>
          </li>
          <li>
            <Link href="/advanced" className="choice-card h-full items-center transition-colors">
              <Icon name="sliders" size={20} className="text-steel" />
              <span className="flex-1">
                <span className="block text-sm font-medium text-ink-1">
                  The analysis console
                </span>
                <span className="mt-1 block text-xs leading-relaxed text-ink-2">
                  Forecast accuracy, interval calibration, model comparison and experiment
                  history, for technical users.
                </span>
              </span>
              <Icon name="arrow-right" size={16} className="text-ink-4" />
            </Link>
          </li>
        </ul>
      </section>
    </div>
  );
}
