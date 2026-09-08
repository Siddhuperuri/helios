/**
 * Client for the live forecast endpoint.
 *
 * Deliberately self-contained rather than an addition to `lib/estimate.ts`. That file is
 * the consumer API's contract and this is an additive feature sitting beside it; keeping
 * them separate means the forecast can be removed by deleting two files, and it means the
 * existing client's behaviour cannot be affected by a change made here.
 *
 * No auth handling, and that is correct rather than an omission: the endpoint reads a
 * saved estimate, where the opaque identifier in the URL is the capability — the same rule
 * as `GET /api/estimate/{id}`. Credentials are still sent so that a signed-in user's
 * request looks like every other request from the app.
 */

/** Empty means same-origin — a Next.js rewrite in development, Nginx in production. */
const BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').replace(/\/$/, '');

/**
 * A forecast is a live upstream fetch, so it is slower than a cached read and faster than
 * an estimate. Thirty seconds is generous enough for a cold call to the weather service
 * and short enough that a hung request does not leave a skeleton on screen indefinitely.
 */
const TIMEOUT_MS = 30_000;

export interface LiveForecastDay {
  /** Local calendar date, ISO `YYYY-MM-DD`. */
  date: string;
  energy_kwh: number;
  /**
   * Hours contributing to this day. An operational forecast starts at the current day's
   * first hour, so the first entry usually covers a day already partly over — this is what
   * lets the interface say so instead of showing an unexplained short bar.
   */
  hours: number;
}

export interface LiveForecastResponse {
  /** Always `physics_pass_through`. Named so it cannot be read as a model prediction. */
  method: string;
  issued_at: string;
  horizon_hours: number;
  daily: LiveForecastDay[];
  total_kwh: number;
  daily_average_kwh: number | null;
  /** Written by the backend and rendered verbatim; never replaced with generic text. */
  note: string;
  provenance: {
    source: string;
    kind: string;
    model_chain: string;
    retrieved_at: string;
    system_dc_capacity_kwp: number;
  };
}

/**
 * Fetch the forecast for a saved estimate.
 *
 * Throws on any failure. The caller renders nothing in that case — this is progressive
 * enhancement, and a weather service being unreachable must never make the estimate the
 * user actually came for look broken.
 */
export async function fetchLiveForecast(
  estimateId: string,
  horizonHours = 168,
  signal?: AbortSignal,
): Promise<LiveForecastResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  // Honour a caller's abort (React unmount) as well as our own timeout.
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    const response = await fetch(
      `${BASE}/api/estimate/${encodeURIComponent(estimateId)}/live-forecast` +
        `?horizon_hours=${horizonHours}`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
      },
    );

    if (!response.ok) {
      throw new Error(`live-forecast responded ${response.status}`);
    }
    return (await response.json()) as LiveForecastResponse;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
