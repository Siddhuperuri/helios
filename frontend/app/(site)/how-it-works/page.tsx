import type { Metadata } from 'next';
import Link from 'next/link';

import { Icon } from '@/components/site/Icon';

export const metadata: Metadata = {
  title: 'How It Works',
  description:
    'The calculation chain behind every estimate: solar resource, plane-of-array ' +
    'irradiance, temperature, conversion, losses and uncertainty.',
};

/**
 * The methodology, written for somebody who is deciding whether to believe the number.
 *
 * Not a marketing page and not a paper. It walks the actual pipeline in order, names the
 * published model at each stage, and states plainly what the platform does not know. The
 * §38 brief — energy, science, trust, simplicity — is served by being specific rather than
 * by looking technical.
 */

const STAGES = [
  {
    n: '01',
    title: 'Your location becomes a weather record',
    body:
      'The coordinates you give are used to pull hourly weather from the ERA5 reanalysis archive — global horizontal irradiance, direct and diffuse components, air temperature, wind speed, humidity, cloud cover. A typical estimate rests on around 26,000 hours of record.',
    caveat:
      'This is a modelled gridded product covering an area around you, not a sensor on your roof.',
  },
  {
    n: '02',
    title: 'Sunlight on a flat surface becomes sunlight on your panels',
    body:
      'Irradiance is measured horizontally, but panels are tilted. The horizontal figure is split into its beam and diffuse parts (Erbs decomposition), then recombined onto the tilted plane along with light reflected from the ground (HDKR transposition).',
    caveat: 'The gain from tilting is real and material — often 10 to 20 per cent.',
  },
  {
    n: '03',
    title: 'The panels get hot, and hot panels produce less',
    body:
      'Cell temperature is computed hour by hour from the irradiance landing on the panel, the air temperature and the wind speed (Faiman model). This is why the hottest days are not the best days, and why a still hot afternoon is worse than a breezy one.',
    caveat: 'Modelled from recorded weather, not assumed from an annual average.',
  },
  {
    n: '04',
    title: 'Sunlight becomes direct current',
    body:
      'The PVWatts v5 model converts plane-of-array irradiance and cell temperature into DC output, using the panel technology’s own temperature coefficient against its nameplate rating.',
    caveat: 'A published NREL model, not a coefficient invented for this platform.',
  },
  {
    n: '05',
    title: 'Losses are subtracted, itemised',
    body:
      'Dust, shading, panel mismatch, wiring, connections, first-year settling, nameplate tolerance and downtime. They are combined multiplicatively rather than added, because two ten per cent losses leave 81 per cent, not 80.',
    caveat:
      'Heat and inverter losses are not in this stack — they are modelled separately, so nothing is counted twice.',
  },
  {
    n: '06',
    title: 'Direct current becomes usable electricity',
    body:
      'The inverter’s efficiency is applied, and its AC limit is enforced. If the array is large relative to the inverter, the midday peak is clipped — and the result tells you what share of hours that happens in.',
    caveat: 'A common and often deliberate design choice, but it should be visible.',
  },
  {
    n: '07',
    title: 'Hours become a typical year',
    body:
      'Hourly output is summed to months and years, then averaged across the years in the record. The spread between those years is measured and becomes the range around your figure.',
    caveat:
      'Which is why the range is not a round ±10 per cent — it is what the weather actually did where you are.',
  },
];

export default function HowItWorksPage() {
  return (
    <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 lg:py-16">
      <header className="max-w-3xl">
        <p className="eyebrow mb-5">Methodology</p>
        <h1 className="text-2xl font-medium leading-tight tracking-tight text-ink-1 sm:text-3xl">
          What happens between your answers and your number
        </h1>
        <p className="mt-4 text-base leading-relaxed text-ink-2">
          This is not a rule of thumb multiplied by your roof size. Every estimate runs
          years of real hourly weather for your exact coordinates through a chain of
          published engineering models, one hour at a time. Here is that chain, in order.
        </p>
      </header>

      <ol className="mt-12 space-y-px bg-line">
        {STAGES.map((stage) => (
          <li key={stage.n} className="bg-base">
            <div className="grid gap-4 p-6 sm:grid-cols-[auto_1fr] sm:gap-8 sm:p-8">
              <span className="num text-sm tracking-[0.14em] text-solar">{stage.n}</span>
              <div>
                <h2 className="text-lg font-medium text-ink-1">{stage.title}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">
                  {stage.body}
                </p>
                <p className="mt-3 border-l-2 border-line-strong pl-3 text-xs leading-relaxed text-ink-3">
                  {stage.caveat}
                </p>
              </div>
            </div>
          </li>
        ))}
      </ol>

      <section className="mt-16 grid gap-10 lg:grid-cols-2 lg:gap-16">
        <div>
          <p className="eyebrow mb-6">Why there is a range</p>
          <p className="text-sm leading-relaxed text-ink-2">
            No estimate of next year&apos;s generation can be exact, because next year&apos;s
            weather has not happened. That single fact is usually the largest source of
            uncertainty, and no amount of better modelling removes it.
          </p>
          <p className="mt-4 text-sm leading-relaxed text-ink-2">
            So instead of hiding it, we measure it: the spread between what each year in the
            record actually delivered at your coordinates. On top of that sit smaller,
            named terms — the gap between a reanalysis grid cell and your roof, the accuracy
            of the conversion models, and one term for every question you could not answer.
          </p>
          <p className="mt-4 text-sm leading-relaxed text-ink-2">
            That last part is what makes skipping a question honest rather than free. Skip
            the shading question and the estimate still runs, but the band around it widens
            to say so.
          </p>
        </div>

        <div>
          <p className="eyebrow mb-6">What we do not claim</p>
          <ul className="space-y-4">
            {[
              [
                'This is modelled, not measured.',
                'No metered output from an installed system was available to check these figures against. They are physics applied to weather data, and that is stated wherever a number appears.',
              ],
              [
                'A tariff is a planning default until you replace it.',
                'Costs and electricity rates are representative figures, not quotations. Every financial number moves the moment you enter your own.',
              ],
              [
                'This is not a site survey.',
                'Nothing here inspects your roof structure, your wiring, or what the tree next door will look like in five years.',
              ],
            ].map(([title, body]) => (
              <li key={title} className="flex gap-3 border-t border-line pt-4">
                <Icon name="info" size={16} className="mt-0.5 shrink-0 text-steel" />
                <span>
                  <span className="block text-sm font-medium text-ink-1">{title}</span>
                  <span className="mt-1 block text-sm leading-relaxed text-ink-2">{body}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <div className="mt-16 border border-line bg-surface-1 p-8">
        <h2 className="text-xl font-medium tracking-tight text-ink-1">
          See it run on your own location
        </h2>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-2">
          Two minutes, no account. Every figure comes back with the assumption that
          produced it.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/start"
            className="tap inline-flex items-center gap-2 border border-solar bg-solar px-6 py-3
              text-sm font-medium text-base transition-opacity hover:opacity-90"
          >
            Calculate my solar potential
            <Icon name="arrow-right" size={16} />
          </Link>
          <Link
            href="/advanced"
            className="tap inline-flex items-center gap-2 border border-line-strong px-6 py-3
              text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar"
          >
            Open the analysis console
          </Link>
        </div>
      </div>
    </div>
  );
}
