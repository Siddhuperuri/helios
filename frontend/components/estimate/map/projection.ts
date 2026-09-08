/**
 * Web Mercator projection and the geodesy the map needs.
 *
 * Separated from the component so it can be unit-tested without a DOM, which matters: an
 * error here does not throw, it silently puts the pin in the wrong field, and the estimate
 * that follows is confidently about the wrong place.
 */

export const TILE_SIZE = 256;

/** Mercator cannot represent the poles; this is the standard cut-off used by tile schemes. */
export const MAX_LATITUDE = 85.05112878;

export interface Point {
  x: number;
  y: number;
}

export function clampLatitude(lat: number): number {
  return Math.max(-MAX_LATITUDE, Math.min(MAX_LATITUDE, lat));
}

/** Wrap a longitude into [-180, 180) so panning past the date line still works. */
export function wrapLongitude(lon: number): number {
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

/** Longitude and latitude to world pixel coordinates at a given zoom. */
export function project(lat: number, lon: number, zoom: number): Point {
  const scale = TILE_SIZE * Math.pow(2, zoom);
  const clamped = clampLatitude(lat);
  const sinLat = Math.sin((clamped * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
  };
}

/** World pixel coordinates back to latitude and longitude. */
export function unproject(x: number, y: number, zoom: number): { lat: number; lon: number } {
  const scale = TILE_SIZE * Math.pow(2, zoom);
  const lon = (x / scale) * 360 - 180;
  const n = Math.PI - 2 * Math.PI * (y / scale);
  const lat = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  return { lat, lon: wrapLongitude(lon) };
}

/** Metres per screen pixel at a latitude and zoom — used for the scale bar. */
export function metresPerPixel(lat: number, zoom: number): number {
  const earthCircumference = 40_075_016.686;
  return (
    (earthCircumference * Math.cos((clampLatitude(lat) * Math.PI) / 180)) /
    (TILE_SIZE * Math.pow(2, zoom))
  );
}

/**
 * Area of a polygon of coordinates, in square metres.
 *
 * Equirectangular projection about the polygon's own centroid, with longitude scaled by
 * cos(latitude), then the shoelace formula. For a rooftop or a field this sits far inside
 * the error of the user's own tracing, and it needs no projection library.
 *
 * This mirrors `polygon_area_m2` in the backend deliberately: the figure shown while
 * drawing must be the figure the server computes, or the area silently changes when the
 * estimate runs.
 */
export function polygonAreaM2(points: { lat: number; lon: number }[]): number {
  if (points.length < 3) return 0;

  const meanLat = points.reduce((sum, p) => sum + p.lat, 0) / points.length;
  const meanLon = points.reduce((sum, p) => sum + p.lon, 0) / points.length;
  const metresPerDegLat = 111_320;
  const metresPerDegLon = 111_320 * Math.cos((meanLat * Math.PI) / 180);

  const xs = points.map((p) => (p.lon - meanLon) * metresPerDegLon);
  const ys = points.map((p) => (p.lat - meanLat) * metresPerDegLat);

  let area = 0;
  for (let i = 0; i < points.length; i += 1) {
    const j = (i + 1) % points.length;
    area += xs[i]! * ys[j]! - xs[j]! * ys[i]!;
  }
  return Math.abs(area / 2);
}

/** A rounded distance and unit for the scale bar. */
export function scaleBar(lat: number, zoom: number, maxWidthPx = 90): {
  widthPx: number;
  label: string;
} {
  const mpp = metresPerPixel(lat, zoom);
  const maxMetres = mpp * maxWidthPx;
  const steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10_000];
  const chosen = steps.reverse().find((s) => s <= maxMetres) ?? 1;
  return {
    widthPx: chosen / mpp,
    label: chosen >= 1000 ? `${chosen / 1000} km` : `${chosen} m`,
  };
}
