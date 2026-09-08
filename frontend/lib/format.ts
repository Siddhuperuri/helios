/**
 * Number formatting.
 *
 * The governing rule: never display more precision than the underlying measurement can
 * support. The reference system reported "16.79 kWh" from a model with no stated error at
 * all — four significant figures implying an accuracy that had never been measured.
 *
 * `withPrecision` takes the quantity *and its error* and rounds the value to the same
 * decimal place as that error. An energy figure carrying a ±3 kWh uncertainty is shown as
 * "54 kWh", not "54.16 kWh".
 */

export function num(
  value: number | null | undefined,
  decimals = 2,
  fallback = '—',
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function int(value: number | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return Math.round(value).toLocaleString('en-US');
}

export function pct(
  value: number | null | undefined,
  decimals = 1,
  fallback = '—',
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return `${value.toFixed(decimals)}%`;
}

export function fraction(
  value: number | null | undefined,
  decimals = 1,
  fallback = '—',
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return `${(value * 100).toFixed(decimals)}%`;
}

export function signed(
  value: number | null | undefined,
  decimals = 2,
  fallback = '—',
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  const s = value.toFixed(decimals);
  return value > 0 ? `+${s}` : s;
}

/**
 * Round a value to a precision its own error can justify.
 *
 * Uses the standard scientific convention — round the value to the same decimal place as
 * its uncertainty — and mirrors `significant_figures` in the backend so a figure rendered
 * here and the same figure in an exported report never disagree.
 *
 * @param value the quantity to display
 * @param error a comparable uncertainty (RMSE, interval half-width, standard deviation)
 */
export function withPrecision(
  value: number | null | undefined,
  error: number | null | undefined,
  fallback = '—',
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  if (error === null || error === undefined || !Number.isFinite(error) || error <= 0) {
    return num(value, 2);
  }
  const magnitude = Math.floor(Math.log10(Math.abs(error)));
  const decimals = Math.min(3, Math.max(0, -magnitude));
  return num(value, decimals);
}

/** Significant-figure formatting, for quantities without an explicit error term. */
export function sig(value: number | null | undefined, figures = 3, fallback = '—'): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  if (value === 0) return '0';
  const magnitude = Math.floor(Math.log10(Math.abs(value)));
  const decimals = Math.max(0, figures - 1 - magnitude);
  return num(value, Math.min(decimals, 6));
}

const DATE_OPTS: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  timeZone: 'UTC',
};

export function isoDate(value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 10);
  return d.toLocaleDateString('en-GB', DATE_OPTS);
}

export function isoDateTime(value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 16);
  return `${d.toLocaleDateString('en-GB', DATE_OPTS)} ${d
    .toISOString()
    .slice(11, 16)} UTC`;
}

export function hourLabel(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value).slice(11, 16);
  return d.toISOString().slice(11, 16);
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

/** Sentence-case a snake_case or kebab-case identifier for display. */
export function humanise(key: string): string {
  const s = key.replace(/[_-]+/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const REGIME_LABEL: Record<string, string> = {
  sunny: 'Clear',
  cloudy: 'Cloudy',
  other: 'Precipitation',
};

export const REGIME_DESCRIPTION: Record<string, string> = {
  sunny: 'Cloud cover below 25%',
  cloudy: 'Cloud cover at or above 25%, no precipitation',
  other: 'Precipitation present',
};
