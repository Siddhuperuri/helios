/**
 * The date-and-time prediction page.
 *
 * Three promises are pinned here, and each of them is one the reference application broke.
 *
 * The **date and hour reach the server**. The original had inert controls: the same figure
 * came back whatever you picked. A page that renders a time selector and then sends
 * something else is the same failure wearing a different shirt, so the request body is
 * asserted, not just the rendering.
 *
 * The **four base models are visible**. The ensemble's number is the headline; if the
 * individual predictions and their weights vanish from the page, the blend becomes a claim
 * the reader has to take on trust.
 *
 * The **caveats survive**. "Modelled, not metered" and the no-future-data rule are the two
 * statements that keep the kilowatt-hour figure honest, and a redesign must not quietly
 * drop them.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PredictView, PredictionResult } from '@/components/predict/PredictView';
import { OperatingConditionCards } from '@/components/insights/OperatingConditions';
import type { PointForecastResponse } from '@/lib/api';

const pointForecast = vi.fn();
const limits = vi.fn();
const searchLocations = vi.fn();

vi.mock('@/lib/estimate', async () => {
  const actual = await vi.importActual<typeof import('@/lib/estimate')>('@/lib/estimate');
  return {
    ...actual,
    estimateApi: {
      ...actual.estimateApi,
      searchLocations: (q: string, limit?: number) => searchLocations(q, limit),
    },
  };
});

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      limits: () => limits(),
      pointForecast: (body: unknown) => pointForecast(body),
    },
  };
});

const RESULT: PointForecastResponse = {
  kwh_hour: 3.214,
  kwh_day: 24.6,
  ghi_wm2: 812,
  air_temperature_c: 33.4,
  wind_speed_ms: 2.7,
  latitude: 17.385,
  longitude: 78.4867,
  resolved_place_name: 'Hyderabad, Telangana, India',
  location: {
    latitude: 17.385,
    longitude: 78.4867,
    name: 'Hyderabad',
    label: 'Hyderabad, Telangana, India',
  },
  model_key: 'ensemble_four',
  model_display_name: 'Four-Model Stacking Ensemble',
  per_model: [
    { model: 'random_forest', display_name: 'Random Forest', weight: 0.31, weight_share: 0.3, kwh_hour: 3.1 },
    {
      model: 'hist_gradient_boosting',
      display_name: 'Histogram Gradient Boosting',
      weight: 0.52,
      weight_share: 0.5,
      kwh_hour: 3.35,
    },
    {
      model: 'extra_trees',
      display_name: 'Extremely Randomised Trees',
      weight: 0.22,
      weight_share: 0.15,
      kwh_hour: 3.05,
    },
    { model: 'ridge', display_name: 'Ridge Regression', weight: -0.05, weight_share: 0.05, kwh_hour: 2.6 },
  ],
  per_model_note: 'Each base model’s own prediction for this hour, with its learned weight.',
  interval: {
    lower_kwh: 2.81,
    upper_kwh: 3.62,
    nominal_coverage: 0.8,
    method: 'Empirical 80% quantiles of 1,204 hold-out residuals in kWh.',
  },
  operating_conditions: [
    {
      key: 'wind_cooling',
      title: 'Wind cooling',
      severity: 'info',
      value: 2.7,
      unit: 'm/s',
      threshold: 'Faiman model: T_cell = T_air + POA / (25.0 + 6.84·v)',
      message: 'Mean daytime wind of 2.70 m/s holds modules 12.1 °C above ambient.',
    },
  ],
  target: {
    requested: '2024-06-20T13:00:00',
    resolved_local: '2024-06-20T12:30:00+05:30',
    resolved_utc: '2024-06-20T07:00:00+00:00',
    timezone: 'Asia/Kolkata',
    timezone_source: "IANA zone 'Asia/Kolkata' from the location service",
    is_daytime: true,
    solar_zenith_deg: 18.4,
    weather_regime: 'sunny',
  },
  system: {
    dc_capacity_kwp: 5,
    ac_capacity_kw: 4.167,
    surface_tilt_deg: 20,
    surface_azimuth_deg: 180,
    temperature_coefficient_per_c: -0.0035,
    system_losses_fraction: 0.14,
    inverter_efficiency: 0.96,
    albedo: 0.2,
    dc_model: 'PVWatts v5 (Dobos 2014)',
    cell_temperature_model: 'Faiman (2008)',
    transposition_model: 'HDKR',
  },
  hours_in_day: 24,
  n_clipped_to_physical_bounds: 0,
  reference: {
    physics_chain_kwh: 3.3,
    physics_chain_day_kwh: 25.1,
    description: 'The PV chain run over the observed weather for this hour.',
  },
  training: {
    analysis_id: 'abc123',
    period_start: '2022-06-19T00:00:00+00:00',
    period_end: '2024-06-19T13:00:00+00:00',
    n_train: 6800,
    n_test: 1700,
    hold_out_rmse_kwh: 0.184,
    hold_out_mae_kwh: 0.121,
    hold_out_r2: 0.93,
    skill_scores: { persistence: 0.61 },
    leakage_rule:
      'Trained only on data through 2024-06-19, which ends strictly before the target hour. Chronological split with a 24-hour embargo; no lagged target values.',
  },
  label_provenance:
    'The model was trained on hourly energy produced by the deterministic PV chain applied to reanalysis weather. These labels are modelled, not metered.',
  warnings: [],
};

beforeEach(() => {
  limits.mockResolvedValue({ latest_archive_date: '2024-06-30' });
  pointForecast.mockResolvedValue(RESULT);
  searchLocations.mockResolvedValue({
    results: [
      {
        latitude: 17.385,
        longitude: 78.4867,
        name: 'Hyderabad',
        admin1: 'Telangana',
        country: 'India',
        label: 'Hyderabad, Telangana, India',
        elevation_m: 505,
      },
    ],
  });
  // jsdom has no ResizeObserver and the map measures itself with one.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('the prediction request', () => {
  it('cannot be sent before a location is chosen', async () => {
    render(<PredictView />);
    await waitFor(() => expect(limits).toHaveBeenCalled());

    const button = screen.getByRole('button', { name: /predict this hour/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it('offers no date beyond what the archive covers', async () => {
    render(<PredictView />);
    const date = (await screen.findByLabelText('Date')) as HTMLInputElement;
    await waitFor(() => expect(date.value).toBe('2024-06-30'));
    expect(date.max).toBe('2024-06-30');
  });

  it('sends the chosen hour, not just the chosen date', async () => {
    render(<PredictView />);
    const date = (await screen.findByLabelText('Date')) as HTMLInputElement;

    fireEvent.click(screen.getByText('Search for a place'));
    fireEvent.change(screen.getByLabelText('Search for a place'), {
      target: { value: 'Hyderabad' },
    });
    // The search input is debounced, so the match appears a moment after typing. The
    // listbox is addressed by name because the hour and model selects on this page are
    // full of <option> elements of their own.
    const matches = await screen.findByRole('listbox', { name: 'Matching places' }, { timeout: 3000 });
    fireEvent.click(within(matches).getByRole('button'));

    fireEvent.change(date, { target: { value: '2024-06-20' } });
    fireEvent.change(screen.getByLabelText('Time'), { target: { value: '15:00' } });
    fireEvent.click(screen.getByRole('button', { name: /predict this hour/i }));

    await waitFor(() => expect(pointForecast).toHaveBeenCalledTimes(1));
    expect(pointForecast).toHaveBeenCalledWith({
      location: { latitude: 17.385, longitude: 78.4867 },
      target_datetime: '2024-06-20T15:00:00',
      model_key: 'ensemble_four',
    });
  });

  it('asks for a different hour when a different hour is picked', async () => {
    render(<PredictView />);
    await screen.findByLabelText('Date');

    fireEvent.click(screen.getByText('Search for a place'));
    fireEvent.change(screen.getByLabelText('Search for a place'), {
      target: { value: 'Hyderabad' },
    });
    const matches = await screen.findByRole('listbox', { name: 'Matching places' }, { timeout: 3000 });
    fireEvent.click(within(matches).getByRole('button'));

    fireEvent.change(screen.getByLabelText('Time'), { target: { value: '09:00' } });
    fireEvent.click(screen.getByRole('button', { name: /predict this hour/i }));
    await waitFor(() => expect(pointForecast).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText('Time'), { target: { value: '17:00' } });
    fireEvent.click(screen.getByRole('button', { name: /predict this hour/i }));
    await waitFor(() => expect(pointForecast).toHaveBeenCalledTimes(2));

    const [first, second] = pointForecast.mock.calls.map((call) => call[0].target_datetime);
    expect(first).toMatch(/T09:00:00$/);
    expect(second).toMatch(/T17:00:00$/);
  });
});

describe('the result', () => {
  it('leads with the energy for the requested hour, with its interval', () => {
    render(<PredictionResult result={RESULT} />);
    expect(screen.getByText('Energy this hour')).toBeTruthy();
    expect(screen.getByText('3.21')).toBeTruthy();
    expect(screen.getByText(/2.81–3.62 kWh at 80% confidence/)).toBeTruthy();
  });

  it('shows the three parameters that drive the number', () => {
    render(<PredictionResult result={RESULT} />);
    for (const label of ['Sun intensity', 'Wind speed', 'Air temperature']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.getByText('812')).toBeTruthy();
    expect(screen.getByText('2.7')).toBeTruthy();
    expect(screen.getByText('33.4')).toBeTruthy();
  });

  it('names the place and the resolved local hour', () => {
    render(<PredictionResult result={RESULT} />);
    expect(screen.getByText(/12:30 on 2024-06-20 · Hyderabad/)).toBeTruthy();
  });

  it('shows all four base models beside the ensemble', () => {
    render(<PredictionResult result={RESULT} />);
    for (const name of [
      'Random Forest',
      'Histogram Gradient Boosting',
      'Extremely Randomised Trees',
      'Ridge Regression',
      'Four-Model Stacking Ensemble',
    ]) {
      expect(screen.getByText(name)).toBeTruthy();
    }
  });

  it('shows the learned weights, including a negative one, rather than implying an average', () => {
    render(<PredictionResult result={RESULT} />);
    expect(screen.getByText(/weight \+0.310/)).toBeTruthy();
    expect(screen.getByText(/weight -0.050/)).toBeTruthy();
    expect(screen.getByText(/disagree by 0.750 kWh/)).toBeTruthy();
  });

  it('keeps the caveats that make the figure honest', () => {
    render(<PredictionResult result={RESULT} />);
    expect(screen.getByText(/labels are modelled, not metered/i)).toBeTruthy();
    expect(screen.getByText(/strictly before the target hour/)).toBeTruthy();
  });

  it('explains itself when a single estimator was used instead of the ensemble', () => {
    render(
      <PredictionResult
        result={{
          ...RESULT,
          model_key: 'ridge',
          model_display_name: 'Ridge Regression',
          per_model: [],
          per_model_note:
            "'ridge' is a single estimator, so there are no base-model contributions to report.",
        }}
      />,
    );
    expect(screen.getByText(/single estimator/)).toBeTruthy();
  });
});

describe('operating condition cards', () => {
  it('never shows a verdict without the threshold it was judged against', () => {
    render(<OperatingConditionCards notes={RESULT.operating_conditions} />);
    expect(screen.getByText('Wind cooling')).toBeTruthy();
    expect(screen.getByText(/Threshold: Faiman model/)).toBeTruthy();
  });

  it('renders nothing at all when there are no notes', () => {
    const { container } = render(<OperatingConditionCards notes={[]} />);
    expect(container.textContent).toBe('');
  });
});
