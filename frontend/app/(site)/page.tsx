import Link from 'next/link';

import { Icon } from '@/components/site/Icon';
import { ResourceCurve } from '@/components/site/ResourceCurve';
import { translate } from '@/lib/i18n';

/**
 * The entry experience (§5).
 *
 * Short, on purpose. The instruction is that a user should be able to start immediately,
 * so there is one screen of proposition and then the door. What length this page does have
 * goes on answering the two questions that decide whether somebody trusts a number from a
 * website they have never used: where does this come from, and what does it not know.
 *
 * The visual identity (§38) is carried by a real plot rather than an illustration — the
 * curve below is a genuine modelled day of generation, drawn from the same physical chain
 * the product runs. Data as decoration is the one kind of decoration this design allows.
 */
export default function LandingPage() {
  const t = (key: string) => translate('en', key);

  return (
    <>
      {/* ------------------------------------------------------------------ hero */}
      <section className="border-b border-line">
        <div className="mx-auto grid max-w-[1180px] gap-10 px-5 py-14 sm:px-8 lg:grid-cols-[1.15fr_1fr] lg:items-center lg:gap-16 lg:py-24">
          <div>
            <p className="eyebrow mb-6">{t('landing.eyebrow')}</p>

            <h1 className="max-w-[16ch] text-3xl font-medium leading-[1.1] tracking-tight text-ink-1 sm:text-4xl lg:text-5xl">
              {t('landing.headline')}
            </h1>

            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
              {t('landing.subhead')}
            </p>

            <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
              <Link
                href="/start"
                className="tap inline-flex items-center justify-center gap-2 border border-solar
                  bg-solar px-6 py-3.5 text-base font-medium text-base transition-opacity
                  hover:opacity-90"
              >
                {t('landing.primaryCta')}
                <Icon name="arrow-right" size={18} />
              </Link>
              <Link
                href="/how-it-works"
                className="tap inline-flex items-center justify-center gap-2 border border-line-strong
                  px-6 py-3.5 text-base text-ink-1 transition-colors hover:border-solar
                  hover:text-solar"
              >
                {t('landing.secondaryCta')}
              </Link>
            </div>

            <p className="mt-4 text-xs text-ink-3">{t('landing.noSignup')}</p>
          </div>

          <div className="lg:pl-4">
            <ResourceCurve />
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- promise */}
      <section className="border-b border-line bg-surface-1">
        <div className="mx-auto max-w-[1180px] px-5 py-12 sm:px-8">
          <p className="max-w-3xl text-xl leading-relaxed text-ink-1 sm:text-2xl">
            {t('landing.promise')}
          </p>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-ink-2">
            You do not need to know what a kilowatt-peak is, which way your roof faces, or
            what your panels will cost. Answer what you can, skip what you cannot, and every
            gap is filled with a stated assumption you can see and change.
          </p>
        </div>
      </section>

      {/* ------------------------------------------------------------------ steps */}
      <section>
        <div className="mx-auto max-w-[1180px] px-5 py-14 sm:px-8">
          <p className="eyebrow mb-8">What happens</p>
          <ol className="grid gap-px bg-line sm:grid-cols-3">
            {[
              {
                n: '01',
                title: 'Tell us where and what',
                body:
                  'Your location, roughly what you use, and how much space you have. Two minutes, and every question can be skipped.',
              },
              {
                n: '02',
                title: 'We run the physics',
                body:
                  'Years of hourly weather for your exact coordinates, through a published photovoltaic model — sunlight, heat, angle, losses, inverter.',
              },
              {
                n: '03',
                title: 'You get a straight answer',
                body:
                  'Expected generation with an honest range around it, what it offsets, what it saves, and every assumption behind it.',
              },
            ].map((step) => (
              <li key={step.n} className="bg-base p-6">
                <span className="num block text-2xs tracking-[0.14em] text-solar">{step.n}</span>
                <h2 className="mt-3 text-lg font-medium text-ink-1">{step.title}</h2>
                <p className="mt-2 text-sm leading-relaxed text-ink-2">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ------------------------------------------------------------ credibility */}
      <section className="border-t border-line bg-surface-1">
        <div className="mx-auto grid max-w-[1180px] gap-10 px-5 py-14 sm:px-8 lg:grid-cols-2 lg:gap-16">
          <div>
            <p className="eyebrow mb-6">What sits underneath</p>
            <dl className="space-y-4">
              {[
                [
                  'Real weather, not a rule of thumb',
                  'Hourly irradiance, temperature and wind from ERA5 reanalysis, for your coordinates — typically 26,000 hours of record behind a single estimate.',
                ],
                [
                  'Published engineering models',
                  'Erbs decomposition, HDKR transposition, Faiman cell temperature and the PVWatts v5 DC model. Named, so they can be checked.',
                ],
                [
                  'A measured range, not a guess',
                  'The spread around your figure comes from how much the years actually differed at your location, plus a term for every question you could not answer.',
                ],
              ].map(([term, description]) => (
                <div key={term} className="border-t border-line pt-4">
                  <dt className="text-sm font-medium text-ink-1">{term}</dt>
                  <dd className="mt-1.5 text-sm leading-relaxed text-ink-2">{description}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div>
            <p className="eyebrow mb-6">What it will not do</p>
            <ul className="space-y-4">
              {[
                'Present a modelled figure as a measurement. No metered generation was available to validate against, and the interface says so.',
                'Invent a tariff or a quotation. Cost and rate defaults are labelled as planning figures, and every number moves when you correct them.',
                'Hide a weak estimate behind a confident number. If your inputs were thin, the range widens and the confidence rating says low.',
              ].map((line) => (
                <li key={line} className="flex gap-3 border-t border-line pt-4">
                  <Icon name="check" size={16} className="mt-0.5 text-steel" />
                  <span className="text-sm leading-relaxed text-ink-2">{line}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------- final cta */}
      <section>
        <div className="mx-auto max-w-[1180px] px-5 py-16 sm:px-8">
          <div className="border border-line bg-surface-1 p-8 sm:p-12">
            <h2 className="max-w-2xl text-2xl font-medium leading-snug tracking-tight text-ink-1">
              Find out what your roof, your land or your farm could generate.
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink-2">
              No account, no email, no obligation. Your estimate gets a private link you can
              come back to or send to an installer.
            </p>
            <Link
              href="/start"
              className="tap mt-7 inline-flex items-center justify-center gap-2 border border-solar
                bg-solar px-6 py-3.5 text-base font-medium text-base transition-opacity
                hover:opacity-90"
            >
              {t('landing.primaryCta')}
              <Icon name="arrow-right" size={18} />
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
