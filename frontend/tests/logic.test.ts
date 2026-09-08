import { describe, expect, it } from 'vitest';

import {
  clampLatitude,
  metresPerPixel,
  polygonAreaM2,
  project,
  scaleBar,
  unproject,
  wrapLongitude,
} from '@/components/estimate/map/projection';
import { canSubmit, draftToRequest, hasLocation, type Draft } from '@/lib/draft';
import { formatCurrency, formatEnergy, translate } from '@/lib/i18n';

/**
 * Logic that would fail silently.
 *
 * The projection maths is the clearest case: an error there does not throw, it places the
 * pin in the wrong field, and every number that follows is confidently about the wrong
 * place. The draft mapping is the second: sending a zero where the user gave nothing turns
 * "we assumed this" into "you told us this", which quietly removes the uncertainty the
 * platform is supposed to carry.
 */

describe('web mercator projection', () => {
  it('round-trips a coordinate through world pixels', () => {
    for (const [lat, lon] of [
      [16.5074, 80.6466],
      [-33.87, 151.21],
      [64.13, -21.9],
      [0, 0],
    ] as [number, number][]) {
      for (const zoom of [3, 10, 15, 19]) {
        const { x, y } = project(lat, lon, zoom);
        const back = unproject(x, y, zoom);
        expect(back.lat).toBeCloseTo(lat, 6);
        expect(back.lon).toBeCloseTo(lon, 6);
      }
    }
  });

  it('places the origin at the centre of the world at zoom 0', () => {
    const { x, y } = project(0, 0, 0);
    expect(x).toBeCloseTo(128, 6);
    expect(y).toBeCloseTo(128, 6);
  });

  it('clamps latitude to the mercator limit rather than producing infinity', () => {
    expect(clampLatitude(90)).toBeLessThan(85.06);
    expect(Number.isFinite(project(90, 0, 10).y)).toBe(true);
    expect(Number.isFinite(project(-90, 0, 10).y)).toBe(true);
  });

  it('wraps longitude across the date line', () => {
    expect(wrapLongitude(181)).toBeCloseTo(-179);
    expect(wrapLongitude(-181)).toBeCloseTo(179);
    expect(wrapLongitude(45)).toBeCloseTo(45);
  });

  it('shrinks metres per pixel as zoom increases', () => {
    expect(metresPerPixel(16.5, 15)).toBeLessThan(metresPerPixel(16.5, 10));
    // Each zoom level halves the ground distance a pixel covers.
    expect(metresPerPixel(0, 10) / metresPerPixel(0, 11)).toBeCloseTo(2, 6);
  });

  it('produces a scale bar with a round number', () => {
    const bar = scaleBar(16.5, 17);
    expect(bar.label).toMatch(/^\d+(\.\d+)? (m|km)$/);
    expect(bar.widthPx).toBeGreaterThan(0);
  });
});

describe('polygon area', () => {
  it('matches a known square', () => {
    const side = 0.01;
    const area = polygonAreaM2([
      { lat: 0, lon: 0 },
      { lat: 0, lon: side },
      { lat: side, lon: side },
      { lat: side, lon: 0 },
    ]);
    expect(area).toBeCloseTo((side * 111_320) ** 2, -3);
  });

  it('does not depend on winding order', () => {
    const points = [
      { lat: 16.5, lon: 80.6 },
      { lat: 16.5, lon: 80.61 },
      { lat: 16.51, lon: 80.61 },
    ];
    expect(polygonAreaM2(points)).toBeCloseTo(polygonAreaM2([...points].reverse()), 6);
  });

  it('returns zero for a degenerate shape', () => {
    expect(polygonAreaM2([])).toBe(0);
    expect(polygonAreaM2([{ lat: 1, lon: 1 }, { lat: 2, lon: 2 }])).toBe(0);
  });

  it('agrees with the backend within a fraction of a percent', () => {
    // The same rooftop-scale polygon the Python test uses. The two implementations must
    // not drift, or the area shown while drawing stops being the area that is calculated.
    const area = polygonAreaM2([
      { lat: 16.5, lon: 80.6 },
      { lat: 16.5, lon: 80.61 },
      { lat: 16.51, lon: 80.61 },
      { lat: 16.51, lon: 80.6 },
    ]);
    const expected = 0.01 * 111_320 * (0.01 * 111_320 * Math.cos((16.505 * Math.PI) / 180));
    expect(Math.abs(area / expected - 1)).toBeLessThan(0.005);
  });
});

describe('draft to request mapping', () => {
  const base: Draft = {
    user_type: 'farm',
    mode: 'quick',
    location: { latitude: 16.5, longitude: 80.6, label: 'Vijayawada' },
  };

  it('requires a location before it can be submitted', () => {
    expect(canSubmit({})).toBe(false);
    expect(canSubmit({ location: { query: 'x' } })).toBe(false); // too short
    expect(canSubmit({ location: { query: 'Vijayawada' } })).toBe(true);
    expect(canSubmit(base)).toBe(true);
  });

  it('prefers coordinates over a place name when both are present', () => {
    const body = draftToRequest({
      ...base,
      location: { ...base.location!, query: 'somewhere else' },
    });
    expect(body.location.latitude).toBe(16.5);
    expect(body.location.query).toBeUndefined();
  });

  it('omits consumption entirely when nothing was answered', () => {
    const body = draftToRequest(base);
    expect(body.consumption_method).toBeUndefined();
    expect(body.monthly_bill).toBeUndefined();
    expect(body.monthly_kwh).toBeUndefined();
  });

  it('does not send a bill of zero as an answer', () => {
    const body = draftToRequest({ ...base, consumption_method: 'bill', monthly_bill: 0 });
    expect(body.consumption_method).toBeUndefined();
  });

  it('drops an equipment branch with no equipment in it', () => {
    const body = draftToRequest({
      ...base,
      consumption_method: 'equipment',
      equipment: [],
      pumps: [],
    });
    expect(body.consumption_method).toBeUndefined();
  });

  it('keeps pumps even when no appliances were added', () => {
    const body = draftToRequest({
      ...base,
      consumption_method: 'equipment',
      pumps: [{ horsepower: 5, count: 1, hours_per_day: 6, days_per_month: 25 }],
    });
    expect(body.consumption_method).toBe('equipment');
    expect(body.pumps).toHaveLength(1);
  });

  it('converts inverter efficiency from percent to a fraction', () => {
    const body = draftToRequest({ ...base, inverter_efficiency_pct: 96 });
    expect(body.system?.inverter_efficiency).toBeCloseTo(0.96);
  });

  it('sends a traced polygon rather than a computed area', () => {
    const polygon: [number, number][] = [
      [16.5, 80.6],
      [16.5, 80.61],
      [16.51, 80.61],
    ];
    const body = draftToRequest({ ...base, area: { mode: 'polygon', polygon } });
    expect(body.area?.polygon).toEqual(polygon);
    expect(body.area?.value).toBeUndefined();
  });

  it('ignores a polygon with too few corners', () => {
    const body = draftToRequest({
      ...base,
      area: { mode: 'polygon', polygon: [[16.5, 80.6]] },
    });
    expect(body.area).toBeUndefined();
  });

  it('omits area entirely when the user asked for help estimating it', () => {
    const body = draftToRequest({ ...base, area: { mode: 'unknown' } });
    expect(body.area).toBeUndefined();
  });

  it('only sends farm details for a farm', () => {
    const withPump = { ...base, pump_horsepower: 5 };
    expect(draftToRequest(withPump).farm?.pump_horsepower).toBe(5);
    expect(draftToRequest({ ...withPump, user_type: 'home' }).farm).toBeUndefined();
  });

  it('carries an off-grid answer through even without a battery', () => {
    const body = draftToRequest({ ...base, wants_battery: false, grid_connected: false });
    expect(body.battery?.grid_connected).toBe(false);
  });
});

describe('panel quantity and goal', () => {
  const base: Draft = {
    user_type: 'home',
    location: { latitude: 17.4, longitude: 78.5, label: 'Hyderabad' },
  };

  it('sends the goal so the server knows which flow this was', () => {
    expect(draftToRequest({ ...base, goal: 'existing', panel_count: 20 }).goal).toBe('existing');
    expect(draftToRequest({ ...base, goal: 'install' }).goal).toBe('install');
  });

  it('defaults to installing when no goal was chosen', () => {
    expect(draftToRequest(base).goal).toBe('install');
  });

  it('passes panel count and wattage through for an existing array', () => {
    const body = draftToRequest({
      ...base, goal: 'existing', panel_count: 20, panel_watts: 550,
    });
    expect(body.system?.panel_count).toBe(20);
    expect(body.system?.panel_watts).toBe(550);
  });

  it('omits panel fields entirely when they are unknown', () => {
    // Not zero, not null — absent, so the server records a default rather than taking a
    // fabricated value as an answer.
    const body = draftToRequest({ ...base, goal: 'existing', panel_count: 20 });
    expect(body.system?.panel_count).toBe(20);
    expect('panel_watts' in (body.system ?? {})).toBe(false);
  });

  it('trims a panel model and drops it when blank', () => {
    expect(
      draftToRequest({ ...base, panel_count: 8, panel_model: '  Waaree 550  ' }).system?.panel_model,
    ).toBe('Waaree 550');
    expect(
      'panel_model' in (draftToRequest({ ...base, panel_count: 8, panel_model: '   ' }).system ?? {}),
    ).toBe(false);
  });

  it('separates having a location from being ready to submit', () => {
    // Regression: folding the panel-count rule into the location check made the location
    // step refuse with "choose a location" while a location was plainly selected.
    const existingWithoutPanels: Draft = { ...base, goal: 'existing' };
    expect(hasLocation(existingWithoutPanels)).toBe(true);
    expect(canSubmit(existingWithoutPanels)).toBe(false);
  });

  it('accepts an existing array once its panel count is known', () => {
    expect(canSubmit({ ...base, goal: 'existing', panel_count: 20 })).toBe(true);
  });

  it('does not require a panel count when planning a new system', () => {
    expect(canSubmit({ ...base, goal: 'install' })).toBe(true);
  });

  it('still requires a location whatever the goal', () => {
    expect(hasLocation({ goal: 'install' })).toBe(false);
    expect(canSubmit({ goal: 'existing', panel_count: 20 })).toBe(false);
  });
});

describe('formatting', () => {
  it('switches to MWh only when the figure is large enough to warrant it', () => {
    expect(formatEnergy(9_119).unit).toBe('kWh');
    expect(formatEnergy(18_420).unit).toBe('MWh');
    expect(formatEnergy(18_420).value).toBe('18.4');
  });

  it('can be forced to a unit so a range matches its headline', () => {
    expect(formatEnergy(9_119, 'en', { forceUnit: 'MWh' }).unit).toBe('MWh');
  });

  it('handles missing values without printing NaN', () => {
    expect(formatEnergy(null).value).toBe('—');
    expect(formatEnergy(undefined).value).toBe('—');
    expect(formatCurrency(null, { code: 'INR', symbol: '₹' })).toBe('—');
  });

  it('places the currency symbol where the currency puts it', () => {
    expect(formatCurrency(1234, { code: 'INR', symbol: '₹' })).toContain('₹');
    expect(
      formatCurrency(1234, { code: 'SEK', symbol: 'kr', symbol_position: 'suffix' }),
    ).toMatch(/kr$/);
  });

  it('groups Indian numbers the Indian way', () => {
    // 1,53,500 rather than 153,500 — a rupee figure grouped the American way reads wrong
    // to the person holding the bill.
    expect(formatCurrency(153500, { code: 'INR', symbol: '₹' })).toBe('₹1,53,500');
  });
});

describe('translation', () => {
  it('resolves a dotted path', () => {
    expect(translate('en', 'result.tabs.savings')).toBe('Savings');
  });

  it('returns the key for a missing path, so the gap is visible', () => {
    expect(translate('en', 'nope.missing')).toBe('nope.missing');
  });

  it('falls back to English for a language that is not translated yet', () => {
    // Better a complete English interface than one that switches language mid-sentence.
    expect(translate('te', 'landing.primaryCta')).toBe(
      translate('en', 'landing.primaryCta'),
    );
  });
});
