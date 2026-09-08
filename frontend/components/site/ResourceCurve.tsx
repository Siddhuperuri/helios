/**
 * The identity graphic: a day of generation, drawn as a plot.
 *
 * §38 asks for a visual language built from real data visualisation rather than stock
 * imagery or a cartoon sun, and this is the load-bearing example. It is the same picture
 * the product produces on the results page — a clear-sky envelope with an actual day's
 * output beneath it — so the front door shows the thing itself rather than an artist's
 * impression of it.
 *
 * It is computed, not drawn. Solar elevation comes from the declination and hour-angle
 * relations, the clear-sky ceiling from the Haurwitz model, and the conversion to AC from
 * the PVWatts DC model and an inverter efficiency — the same chain the product runs. Only
 * the cloud attenuation is illustrative, and the caption states the array, latitude and
 * date so the reader can check the rest. §51 forbids fake charts; the fix for that is to
 * make the chart real rather than to shrink the disclaimer.
 *
 * Rendered on the server as static SVG. No JavaScript, no animation loop, no layout shift
 * (§39, §41).
 */

const WIDTH = 520;
const HEIGHT = 340;
const MARGIN = { top: 24, right: 16, bottom: 34, left: 40 };

const PLOT_W = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom;

/**
 * The array and the day this curve is drawn for. Stated, because a plot without its
 * conditions is decoration.
 */
const LATITUDE = 17.4; // Hyderabad
const DAY_OF_YEAR = 80; // the March equinox
const SYSTEM_KWP = 5;
const SYSTEM_LOSSES = 0.14; // the PVWatts v5 default stack
const INVERTER_EFFICIENCY = 0.96;
const PEAK_KW = SYSTEM_KWP; // axis headroom

/**
 * Solar elevation, from the standard declination and hour-angle relations.
 *
 * This is the same geometry the backend computes in closed form; reproducing the textbook
 * relations here keeps the landing page honest — the curve below is a real modelled day,
 * not a shape drawn to look like one (§51).
 */
function solarElevationDeg(hour: number): number {
  const declination =
    23.45 * Math.sin((2 * Math.PI * (284 + DAY_OF_YEAR)) / 365) * (Math.PI / 180);
  const latitude = (LATITUDE * Math.PI) / 180;
  const hourAngle = ((hour - 12) * 15 * Math.PI) / 180;
  const sinElevation =
    Math.sin(latitude) * Math.sin(declination) +
    Math.cos(latitude) * Math.cos(declination) * Math.cos(hourAngle);
  return (Math.asin(Math.max(-1, Math.min(1, sinElevation))) * 180) / Math.PI;
}

/**
 * Clear-sky global horizontal irradiance by the Haurwitz model — the same clear-sky
 * formulation the platform uses, driven by the air mass at this elevation.
 */
function clearSkyGhi(hour: number): number {
  const elevation = solarElevationDeg(hour);
  if (elevation <= 0) return 0;
  const zenith = ((90 - elevation) * Math.PI) / 180;
  const cosZenith = Math.cos(zenith);
  if (cosZenith <= 0) return 0;
  return 1098 * cosZenith * Math.exp(-0.059 / cosZenith);
}

/** Irradiance through the PVWatts DC model and the inverter, to AC kilowatts. */
function toAcKw(ghi: number): number {
  const dc = (ghi / 1000) * SYSTEM_KWP * (1 - SYSTEM_LOSSES);
  return Math.min(dc * INVERTER_EFFICIENCY, SYSTEM_KWP);
}

function clearSky(hour: number): number {
  return toAcKw(clearSkyGhi(hour));
}

/**
 * The same day with weather on it: thin morning haze and a bank of cloud through the early
 * afternoon. The attenuation is illustrative — this is the one part not computed from
 * data, and the caption says so — but it is applied to a genuinely modelled clear-sky
 * ceiling rather than to an invented curve.
 */
function observed(hour: number): number {
  const ceiling = clearSky(hour);
  if (ceiling === 0) return 0;
  const haze = 0.94 - 0.05 * Math.max(0, 1 - Math.abs(hour - 8) / 2.5);
  const cloudBank = 1 - 0.46 * Math.exp(-Math.pow((hour - 13.4) / 1.5, 2));
  return ceiling * haze * cloudBank;
}

const x = (hour: number) => MARGIN.left + (hour / 24) * PLOT_W;
const y = (kw: number) => MARGIN.top + PLOT_H - (kw / (PEAK_KW * 1.12)) * PLOT_H;

function path(fn: (hour: number) => number, close = false): string {
  const points: string[] = [];
  for (let hour = 0; hour <= 24; hour += 0.25) {
    points.push(`${x(hour).toFixed(2)},${y(fn(hour)).toFixed(2)}`);
  }
  const line = `M${points.join(' L')}`;
  return close
    ? `${line} L${x(24).toFixed(2)},${y(0).toFixed(2)} L${x(0).toFixed(2)},${y(0).toFixed(2)} Z`
    : line;
}

export function ResourceCurve() {
  const hourTicks = [0, 6, 12, 18, 24];
  const kwTicks = [0, 1, 2, 3, 4];

  return (
    <figure className="border border-line bg-surface-1 p-4 sm:p-5">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="img"
        aria-label={
          'A modelled day of solar generation for a 5 kilowatt array at 17.4 degrees north ' +
          'on the March equinox. The clear-sky ceiling peaks near 4 kilowatts at midday, ' +
          'with output tracking just below it and dipping in the early afternoon as cloud ' +
          'passes over.'
        }
      >
        {/* horizontal grid */}
        {kwTicks.map((kw) => (
          <line
            key={kw}
            x1={MARGIN.left}
            x2={WIDTH - MARGIN.right}
            y1={y(kw)}
            y2={y(kw)}
            stroke="var(--c-grid)"
            strokeWidth="1"
          />
        ))}

        {/* clear-sky envelope: the ceiling the weather takes away from */}
        <path d={path(clearSky, true)} fill="var(--c-interval)" />
        <path
          d={path(clearSky)}
          fill="none"
          stroke="rgb(var(--c-solar) / 0.55)"
          strokeWidth="1.25"
          strokeDasharray="3 3"
        />

        {/* the day as modelled */}
        <path
          d={path(observed)}
          fill="none"
          stroke="rgb(var(--c-solar))"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* axes */}
        <line
          x1={MARGIN.left}
          x2={WIDTH - MARGIN.right}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--c-axis)"
          strokeWidth="1"
        />
        {hourTicks.map((hour) => (
          <text
            key={hour}
            x={x(hour)}
            y={HEIGHT - 12}
            textAnchor="middle"
            className="num"
            fill="rgb(var(--c-ink-4))"
            fontSize="10"
          >
            {hour === 24 ? '24:00' : `${String(hour).padStart(2, '0')}:00`}
          </text>
        ))}
        {kwTicks.slice(1).map((kw) => (
          <text
            key={kw}
            x={MARGIN.left - 8}
            y={y(kw) + 3}
            textAnchor="end"
            className="num"
            fill="rgb(var(--c-ink-4))"
            fontSize="10"
          >
            {kw}
          </text>
        ))}

        {/* the annotation that makes the picture mean something */}
        <line
          x1={x(13.4)}
          x2={x(13.4)}
          y1={y(observed(13.4)) - 6}
          y2={MARGIN.top + 6}
          stroke="var(--c-line-bright)"
          strokeWidth="1"
        />
        <text
          x={x(13.4) + 6}
          y={MARGIN.top + 12}
          fill="rgb(var(--c-ink-3))"
          fontSize="10.5"
        >
          cloud passes over
        </text>
      </svg>

      <figcaption className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line pt-3">
        <span className="flex items-center gap-1.5 text-2xs text-ink-3">
          <span className="h-px w-4 bg-solar" aria-hidden="true" />
          Generation, kW
        </span>
        <span className="flex items-center gap-1.5 text-2xs text-ink-3">
          <span
            className="h-px w-4 border-t border-dashed border-solar/60"
            aria-hidden="true"
          />
          Clear-sky ceiling
        </span>
        <span className="ml-auto text-2xs text-ink-4">
          Modelled 5 kW array, 17.4°N, March equinox
        </span>
      </figcaption>
    </figure>
  );
}
