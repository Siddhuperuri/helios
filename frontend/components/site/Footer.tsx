import Link from 'next/link';

import { Mark } from '@/components/site/Icon';

/**
 * Footer.
 *
 * Carries the data attribution, which is a licence condition rather than a courtesy —
 * Open-Meteo is CC-BY 4.0 and ERA5 is Copernicus — and the honest statement of what this
 * platform does not claim. Both belong somewhere permanent rather than only inside a
 * result, because they are true of the whole product.
 *
 * This is also where the analysis console is reachable from, deliberately kept out of the
 * main navigation (§42): it is the same data seen by a different reader, and putting it in
 * the primary nav would make a homeowner wonder what they were missing.
 */
export function Footer() {
  return (
    <footer className="mt-20 border-t border-line">
      <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <Mark size={18} />
              <span className="font-mono text-xs tracking-[0.06em] text-ink-1">Helios</span>
            </div>
            <p className="text-xs leading-relaxed text-ink-3">
              Solar energy estimates built from real weather data and published engineering
              models.
            </p>
          </div>

          <nav aria-label="Product">
            <p className="mb-3 font-mono text-2xs uppercase tracking-[0.12em] text-ink-4">
              Product
            </p>
            <ul className="space-y-2 text-xs">
              <li>
                <Link href="/start" className="inline-flex min-h-touch items-center text-ink-2 transition-colors hover:text-solar sm:min-h-0">
                  Solar calculator
                </Link>
              </li>
              <li>
                <Link href="/predict" className="inline-flex min-h-touch items-center text-ink-2 transition-colors hover:text-solar sm:min-h-0">
                  Predict an hour
                </Link>
              </li>
              <li>
                <Link
                  href="/how-it-works"
                  className="inline-flex min-h-touch items-center text-ink-2 transition-colors hover:text-solar sm:min-h-0"
                >
                  How it works
                </Link>
              </li>
              <li>
                <Link href="/projects" className="inline-flex min-h-touch items-center text-ink-2 transition-colors hover:text-solar sm:min-h-0">
                  My analyses
                </Link>
              </li>
            </ul>
          </nav>

          <nav aria-label="Technical">
            <p className="mb-3 font-mono text-2xs uppercase tracking-[0.12em] text-ink-4">
              Technical
            </p>
            <ul className="space-y-2 text-xs">
              <li>
                <Link
                  href="/advanced"
                  className="inline-flex min-h-touch items-center text-ink-2 transition-colors hover:text-solar sm:min-h-0"
                >
                  Analysis console
                </Link>
              </li>
              <li>
                <Link href="/resources" className="inline-flex min-h-touch items-center text-ink-2 transition-colors hover:text-solar sm:min-h-0">
                  Methodology
                </Link>
              </li>
              <li>
                <Link href="/about" className="inline-flex min-h-touch items-center text-ink-2 transition-colors hover:text-solar sm:min-h-0">
                  About
                </Link>
              </li>
            </ul>
          </nav>

          <div>
            <p className="mb-3 font-mono text-2xs uppercase tracking-[0.12em] text-ink-4">
              Data
            </p>
            <p className="text-2xs leading-relaxed text-ink-3">
              Weather and irradiance data from Open-Meteo (CC-BY 4.0), derived from ECMWF
              ERA5 / ERA5-Land reanalysis (Copernicus Climate Change Service). Geographic
              data from GeoNames and OpenStreetMap.
            </p>
          </div>
        </div>

        <div className="mt-8 border-t border-line pt-5">
          <p className="text-2xs leading-relaxed text-ink-4">
            Estimates are modelled, not measured. Figures are produced from reanalysis
            weather and published photovoltaic models, and have not been validated against
            metered generation from an installed system. They are for planning, and are not
            a substitute for a site survey or a quotation.
          </p>
        </div>
      </div>
    </footer>
  );
}
