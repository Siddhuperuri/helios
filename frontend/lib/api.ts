/**
 * Typed client for the Helios API.
 *
 * Errors from the backend arrive as structured payloads with a human-readable message
 * and, where applicable, a remedy. Those are surfaced verbatim to the user, because the
 * backend is where the domain knowledge lives — it knows that 18 % of the required hourly
 * values are missing, and the UI does not. The client's job is to preserve that message,
 * never to replace it with something generic.
 */

// Empty means same-origin: a Next.js rewrite in development, Nginx in production. See
// next.config.mjs for why the two must share an origin.
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').replace(/\/$/, '');

import { getAccessToken, refreshSession } from '@/lib/auth';

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;
  readonly remedy?: string;
  readonly fieldErrors?: { field: string; message: string }[];

  constructor(
    message: string,
    status: number,
    detail?: string,
    remedy?: string,
    fieldErrors?: { field: string; message: string }[],
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.remedy = remedy;
    this.fieldErrors = fieldErrors;
  }
}

async function attempt(
  path: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const headers = new Headers({ 'Content-Type': 'application/json', ...(init.headers ?? {}) });
  const token = getAccessToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  try {
    return await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const { timeoutMs = 180_000, ...rest } = init ?? {};

  let response: Response;
  try {
    response = await attempt(path, rest, timeoutMs);

    // The console fires many calls at once against one analysis. `refreshSession` is
    // single-flight, so an expired token produces one refresh rather than a dozen racing
    // rotations — which the backend would read as refresh-token theft.
    if (response.status === 401 && (await refreshSession())) {
      response = await attempt(path, rest, timeoutMs);
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(
        'The request timed out.',
        408,
        undefined,
        'Training a model over a long period can take a minute or more. Try a shorter date range, or a faster model such as Ridge or Histogram Gradient Boosting.',
      );
    }
    throw new ApiError(
      'Could not reach the analysis server.',
      0,
      err instanceof Error ? err.message : String(err),
      `Confirm the backend is running and reachable at ${API_BASE || 'this origin'}.`,
    );
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (!response.ok) {
    if (contentType.includes('application/json')) {
      const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      throw new ApiError(
        (body.message as string) ?? (body.detail as string) ?? 'The request failed.',
        response.status,
        body.detail as string | undefined,
        body.remedy as string | undefined,
        body.field_errors as { field: string; message: string }[] | undefined,
      );
    }
    throw new ApiError(await response.text(), response.status);
  }

  if (contentType.includes('text/plain')) {
    return (await response.text()) as unknown as T;
  }
  return (await response.json()) as T;
}

/* ------------------------------------------------------------------ types */

export interface LocationDto {
  latitude: number;
  longitude: number;
  name: string;
  country?: string | null;
  admin1?: string | null;
  elevation_m?: number | null;
  timezone?: string | null;
  label: string;
}

export interface PVSystemDto {
  dc_capacity_kwp: number;
  ac_capacity_kw: number;
  surface_tilt_deg: number;
  surface_azimuth_deg: number;
  temperature_coefficient_per_c: number;
  system_losses_fraction: number;
  inverter_efficiency: number;
  albedo: number;
  dc_model: string;
  cell_temperature_model: string;
  transposition_model: string;
}

export interface Metrics {
  n: number;
  mae: number;
  rmse: number;
  mbe: number;
  r2: number;
  nse: number;
  mape: number;
  smape: number;
  rrmse: number;
  rmae: number;
  observed_mean: number;
  observed_std: number;
  observed_min: number;
  observed_max: number;
  notes?: string[];
  n_clipped_to_physical_bounds?: number;
  target_unit?: string;
}

export interface AnalysisSummary {
  analysis_id: string;
  experiment_id: string | null;
  location: LocationDto;
  system: PVSystemDto;
  model: { key: string; display_name: string; target: string };
  data_quality: {
    overall_score: number;
    grade: string;
    worst_severity: string;
    counts: { pass: number; warn: number; fail: number };
    blocking_issues: string[];
  };
  dataset: Record<string, unknown>;
  validation: Record<string, unknown>;
  /**
   * Headline error figures, keyed by the unit they are in.
   *
   * The `_wm2` fields are present for the irradiance targets, which is everything the
   * console creates. An analysis run against `pv_kwh` publishes the `_kwh` fields instead —
   * the same numbers cannot be labelled both ways, so they are not.
   */
  headline: {
    rmse_wm2: number;
    mae_wm2: number;
    mbe_wm2: number;
    observed_mean_wm2: number;
    rmse_kwh?: number;
    mae_kwh?: number;
    mbe_kwh?: number;
    observed_mean_kwh?: number;
    r2: number;
    rrmse_pct: number;
    n_test: number;
    unit: string;
  };
  cv_summary: Record<string, number | string>;
  skill_scores: Record<string, number>;
  interval_metrics: Record<string, unknown>;
  warnings: string[];
  timings: Record<string, number>;
  notes?: string[];
}

export interface QualityCheck {
  key: string;
  title: string;
  severity: 'pass' | 'warn' | 'fail' | 'info';
  score: number;
  weight: number;
  weighted_contribution: number;
  message: string;
  affected_rows: number;
  total_rows: number;
  affected_fraction: number;
  remedy: string | null;
  detail: Record<string, unknown>;
}

export interface QualityReport {
  overall_score: number;
  grade: string;
  worst_severity: string;
  counts: { pass: number; warn: number; fail: number };
  row_count: number;
  period_start: string;
  period_end: string;
  blocking_issues: string[];
  checks: QualityCheck[];
  methodology: Record<string, unknown>;
}

export interface BaselineResult {
  name: string;
  display_name: string;
  description: string;
  horizon_hours: number;
  coverage: number;
  source: string | null;
  is_probabilistic: boolean;
  metrics: Metrics | null;
  skill_score?: number;
  note?: string;
}

export interface Performance {
  test_metrics_physical: Metrics;
  test_metrics_target_space: Metrics;
  train_metrics: Metrics;
  cv_summary: Record<string, number | string>;
  cv_folds: {
    fold: number;
    metrics: Metrics;
    n_train: number;
    n_test: number;
    test_start: string;
    test_end: string;
  }[];
  baselines: BaselineResult[];
  skill_scores: Record<string, number>;
  by_regime: Record<string, Metrics>;
  by_hour: Record<string, Metrics>;
  by_month: Record<string, Metrics>;
  interval_metrics: Record<string, any>;
  uncertainty_decomposition: Record<string, any>;
  interval: Record<string, any> | null;
  warnings: string[];
}

/**
 * One hold-out hour.
 *
 * The `*_wm2` fields are present for the irradiance targets. An analysis run against the
 * `pv_kwh` target publishes `*_kwh` fields instead and no predicted irradiance at all —
 * an energy model has none to report, and inventing one would be a fabricated figure. The
 * response's `unit` says which set is in play.
 */
export interface PredictionPoint {
  timestamp: string;
  observed_ghi_wm2: number;
  clear_sky_ghi_wm2: number;
  weather_regime: string;
  predicted_ghi_wm2?: number;
  residual_wm2?: number;
  lower_wm2?: number;
  upper_wm2?: number;
  observed_kwh?: number;
  predicted_kwh?: number;
  residual_kwh?: number;
  lower_kwh?: number;
  upper_kwh?: number;
}

export interface PredictionsResponse {
  total: number;
  offset: number;
  limit: number;
  series: PredictionPoint[];
  residual_summary: Record<string, number | null>;
  residual_histogram: { counts: number[]; edges: number[] };
  unit: string;
}

export interface ForecastPoint {
  timestamp: string;
  ghi_wm2: number;
  ghi_lower_wm2: number;
  ghi_upper_wm2: number;
  clear_sky_ghi_wm2: number;
  clear_sky_index: number;
  poa_wm2: number;
  ac_power_kw: number;
  ac_power_lower_kw: number;
  ac_power_upper_kw: number;
  cell_temperature_c: number;
  temperature_c: number;
  wind_speed_ms: number;
  cloud_cover_pct: number;
  solar_zenith_deg: number;
  is_daytime: boolean;
  weather_regime: string;
}

export interface ForecastResponse {
  issued_at: string;
  horizon_hours: number;
  validated_horizon_hours: number;
  beyond_validated_horizon: boolean;
  location: LocationDto;
  system: PVSystemDto;
  model: string;
  series: ForecastPoint[];
  daily: {
    date: string;
    energy_kwh: number;
    energy_lower_kwh: number;
    energy_upper_kwh: number;
    peak_power_kw: number;
    mean_ghi_wm2: number;
    peak_ghi_wm2: number;
    daylight_hours: number;
  }[];
  totals: Record<string, any>;
  warnings: string[];
  provenance: Record<string, any>;
  interval_scope: string;
  operating_conditions: {
    key: string;
    title: string;
    severity: string;
    value: number;
    unit: string;
    threshold: string;
    message: string;
  }[];
}

export interface Explanation {
  importance: {
    per_feature: {
      feature: string;
      importance_mean: number;
      importance_std: number;
      importance_share: number;
      rank: number;
    }[];
    grouped: {
      group: string;
      features: string[];
      rmse_increase_mean: number;
      rmse_increase_std: number;
      relative_increase: number;
      share: number;
    }[];
    method: string;
    n_repeats: number;
    evaluated_on: string;
    scoring: string;
    caveat: string;
  };
  partial_dependence: {
    feature: string;
    grid?: number[];
    values?: number[];
    range?: [number, number];
    effect_size?: number;
    error?: string;
  }[];
  partial_dependence_caveat: string;
  narrative: string[];
  target: string;
}

export interface LeakageResponse {
  audit: {
    key: string;
    title: string;
    question: string;
    status: string;
    finding: string;
    mechanism: string;
  }[];
  experiment?: {
    strategies: Record<
      string,
      {
        rmse: number;
        mae: number;
        r2: number;
        n_train: number;
        n_test: number;
        name: string;
        description: string;
        leakage_risk: string;
        recommended: string;
      }
    >;
    comparison: {
      chronological_rmse: number;
      random_rmse: number;
      rmse_understatement_pct: number;
      chronological_r2: number;
      random_r2: number;
      r2_overstatement: number;
    };
    conclusion: string;
    method_note: string;
    why_it_matters: string;
    provenance: string;
    model_display_name: string;
  } | null;
  experiment_error?: string;
}

export interface AnomalyResponse {
  summary: {
    total: number;
    by_detector: Record<string, number>;
    by_severity: Record<string, number>;
    scope_note: string;
  };
  anomalies: {
    timestamp: string;
    detector: string;
    variable: string;
    severity: string;
    observed: number | null;
    expected: number | null;
    expected_low: number | null;
    expected_high: number | null;
    deviation_sigma: number | null;
    description: string;
    possible_causes: string[];
    confidence: string;
  }[];
  distribution_shift: {
    variable: string;
    display_name: string;
    unit: string | null;
    severity: string;
    train_mean: number;
    test_mean: number;
    standardised_mean_difference: number;
    ks_statistic: number;
    ks_p_value: number;
    description: string;
  }[];
  distribution_shift_note: string;
  threshold_sigma: number;
}

export interface ScenarioResponse {
  name: string;
  kind: string;
  is_simulation: true;
  label: string;
  baseline: Record<string, number>;
  scenario: Record<string, number>;
  difference: Record<string, { absolute: number; relative_pct: number | null }>;
  perturbations: string[];
  assumptions: string[];
  validity: {
    level: string;
    message: string;
    max_excess_fraction_of_range: number;
    variables_outside_range: {
      variable: string;
      display_name: string;
      training_range: [number, number];
      fraction_outside: number;
    }[];
    pathway_decomposition?: {
      statistical_pathway_kwh: number;
      physical_pathway_kwh: number;
      net_kwh: number;
      explanation: string;
    };
  };
  disclaimer: string;
}

/**
 * A model comparison, in whatever unit the analysis was scored in.
 *
 * As with `AnalysisSummary.headline`, the `_wm2` fields belong to the irradiance targets —
 * the only ones the console creates — and an energy analysis returns `_kwh` fields instead.
 * `unit` says which, and the table reads its column labels from it rather than assuming.
 */
export interface ModelComparison {
  results: {
    rank: number;
    model: string;
    display_name: string;
    family: string;
    rmse_wm2: number;
    mae_wm2: number;
    mbe_wm2: number;
    rmse_kwh?: number;
    mae_kwh?: number;
    mbe_kwh?: number;
    r2: number;
    rrmse_pct: number;
    cv_rmse_mean: number | null;
    cv_rmse_std: number | null;
    skill_vs_smart_persistence: number | null;
    skill_vs_persistence: number | null;
    fit_seconds: number;
    sources: string[];
    warnings: string[];
  }[];
  errors: { model: string; error: string }[];
  evaluation_protocol: Record<string, any>;
  unit: string;
}

export interface ModelCatalogue {
  models: {
    key: string;
    display_name: string;
    family: string;
    description: string;
    sources: string[];
    supports_feature_importance: boolean;
    requires_scaling: boolean;
    cost: string;
    hyperparameters: Record<string, unknown>;
    hyperparameter_source: string | null;
    notes: string | null;
  }[];
  default_comparison: string[];
  future_work: { name: string; sources: string[]; status: string; reason: string }[];
}

export interface ParameterCatalogue {
  parameters: {
    key: string;
    display_name: string;
    symbol: string | null;
    unit: string | null;
    definition: string;
    role: string;
    origin: string;
    valid_min: number | null;
    valid_max: number | null;
    typical_min: number | null;
    typical_max: number | null;
    resolution: string;
    required: boolean;
    used_in_training: boolean;
    used_in_inference: boolean;
    effect: string | null;
    sources: string[];
    notes: string | null;
  }[];
  unavailable: { display_name: string; unit: string; sources: string; reason: string }[];
  day_mask_threshold_deg: number;
  day_mask_source: string;
}

export interface Literature {
  papers: {
    key: string;
    title: string;
    authors: string;
    venue: string;
    year: number;
  }[];
  techniques: {
    technique: string;
    sources: string[];
    purpose: string;
    status: string;
    note?: string;
  }[];
  status_legend: Record<string, string>;
}

export interface ModelCard {
  model_name: string;
  version: string;
  objective: string;
  target_variable: Record<string, string>;
  input_variables: string[];
  training_data: Record<string, any>;
  preprocessing: Record<string, any>;
  validation_strategy: Record<string, any>;
  performance: Record<string, any>;
  uncertainty: Record<string, any>;
  hyperparameters: Record<string, any>;
  hyperparameter_provenance: string | null;
  /** The stacking ensemble's learned base-model weights; null for a single estimator. */
  ensemble_weights:
    | { model: string; display_name: string; weight: number; weight_share: number | null }[]
    | null;
  reproducibility: Record<string, any>;
  plain_language: Record<string, string>;
  technical_summary: Record<string, string>;
  limitations: string[];
  known_failure_modes: { condition: string; evidence: string }[];
  warnings: string[];
}

export interface ExperimentListItem {
  experiment_id: string;
  created_at: string;
  label: string;
  model_key: string;
  model_display_name: string;
  target: string;
  location_label: string;
  period_start: string;
  period_end: string;
  n_train: number;
  n_test: number;
  rmse_wm2: number | null;
  mae_wm2: number | null;
  r2: number | null;
  skill_scores: Record<string, number>;
  n_warnings: number;
}

export interface OperatingCondition {
  key: string;
  title: string;
  severity: string;
  value: number;
  unit: string;
  threshold: string;
  message: string;
}

/**
 * One base model's own answer for the target hour, beside the weight the ensemble's
 * meta-learner gave it. A negative weight is meaningful, not a bug: it means the
 * meta-learner uses that model to correct another rather than to predict directly.
 */
export interface ModelContribution {
  model: string;
  display_name: string;
  weight: number;
  weight_share: number | null;
  kwh_hour: number;
}

export interface PointForecastResponse {
  kwh_hour: number;
  kwh_day: number;
  ghi_wm2: number;
  air_temperature_c: number;
  wind_speed_ms: number;
  /** Present for the XGBoost model: panel temperature from the NOCT model. */
  module_temperature_c?: number;
  latitude: number;
  longitude: number;
  resolved_place_name: string;
  location: LocationDto;
  model_key: string;
  model_display_name: string;
  per_model: ModelContribution[];
  per_model_note: string;
  /** XGBoost and the baselines, scored on the same held-out week. */
  baselines?: { model: string; display_name: string; r2: number; mae_kwh: number; is_project_model: boolean }[];
  cross_plant?: { train_plant: number; test_plant: number; r2: number; mae_kwh: number }[];
  interval: {
    lower_kwh: number | null;
    upper_kwh: number | null;
    nominal_coverage: number;
    method: string;
  };
  operating_conditions: OperatingCondition[];
  target: {
    requested: string;
    resolved_local: string;
    resolved_utc: string;
    timezone: string;
    timezone_source: string;
    is_daytime: boolean;
    solar_zenith_deg: number;
    weather_regime: string;
  };
  system: PVSystemDto;
  hours_in_day: number;
  n_clipped_to_physical_bounds: number;
  reference: {
    physics_chain_kwh: number;
    physics_chain_day_kwh: number;
    description: string;
  } | null;
  training: {
    analysis_id: string;
    period_start: string;
    period_end: string;
    n_train: number;
    n_test: number;
    hold_out_rmse_kwh: number;
    hold_out_mae_kwh: number;
    hold_out_r2: number;
    skill_scores: Record<string, number>;
    leakage_rule: string;
  };
  label_provenance: string;
  warnings: string[];
}

export interface PointForecastRequestBody {
  location: { query?: string; latitude?: number; longitude?: number };
  /** Local ISO datetime for the hour to predict, e.g. '2025-06-14T14:00'. */
  target_datetime: string;
  system?: Partial<{
    dc_capacity_kwp: number;
    surface_tilt_deg: number;
    surface_azimuth_deg: number;
    system_losses_fraction: number;
    inverter_efficiency: number;
    inverter_ac_capacity_kw: number;
  }>;
  model_key?: string;
  nominal_coverage?: number;
}

export interface AnalysisRequestBody {
  location: { query?: string; latitude?: number; longitude?: number };
  start_date?: string;
  end_date?: string;
  model_key?: string;
  target?: 'clear_sky_index' | 'ghi_wm2' | 'pv_kwh';
  system?: Partial<{
    dc_capacity_kwp: number;
    surface_tilt_deg: number;
    surface_azimuth_deg: number;
    system_losses_fraction: number;
    inverter_efficiency: number;
  }>;
  horizon_hours?: number;
  test_fraction?: number;
  cv_splits?: number;
  nominal_coverage?: number;
  compute_intervals?: boolean;
  run_cv?: boolean;
  label?: string;
}

/* ---------------------------------------------------------------- methods */

export const api = {
  health: () => request<Record<string, unknown>>('/api/health', { timeoutMs: 8000 }),

  searchLocations: (q: string, limit = 6) =>
    request<{ results: LocationDto[] }>(
      `/api/locations/search?q=${encodeURIComponent(q)}&limit=${limit}`,
      { timeoutMs: 15_000 },
    ),

  parameters: () => request<ParameterCatalogue>('/api/meta/parameters'),
  models: () => request<ModelCatalogue>('/api/meta/models'),
  metrics: () => request<{ metrics: any[] }>('/api/meta/metrics'),
  literature: () => request<Literature>('/api/meta/literature'),
  limits: () => request<Record<string, any>>('/api/meta/limits'),
  scenarioPresets: () =>
    request<{ presets: { key: string; name: string; kind: string; description: string }[] }>(
      '/api/meta/scenarios',
    ),

  createAnalysis: (body: AnalysisRequestBody) =>
    request<AnalysisSummary>('/api/analysis', {
      method: 'POST',
      body: JSON.stringify(body),
      timeoutMs: 300_000,
    }),

  analysis: (id: string) => request<AnalysisSummary>(`/api/analysis/${id}`),

  quality: (id: string) => request<QualityReport>(`/api/analysis/${id}/quality`),
  performance: (id: string) => request<Performance>(`/api/analysis/${id}/performance`),
  predictions: (id: string, limit = 1500) =>
    request<PredictionsResponse>(`/api/analysis/${id}/predictions?limit=${limit}`),
  explain: (id: string) =>
    request<Explanation>(`/api/analysis/${id}/explain`, { timeoutMs: 240_000 }),
  leakage: (id: string) =>
    request<LeakageResponse>(`/api/analysis/${id}/leakage`, { timeoutMs: 240_000 }),
  anomalies: (id: string, sigma = 4) =>
    request<AnomalyResponse>(`/api/analysis/${id}/anomalies?sigma=${sigma}`),
  modelCard: (id: string) => request<ModelCard>(`/api/analysis/${id}/model-card`),
  report: (id: string) => request<string>(`/api/analysis/${id}/report`),

  /**
   * Energy for one hour at one place on one date.
   *
   * The long timeout is not defensive padding: the endpoint trains a model on the archive
   * up to the day before the target, which takes tens of seconds the first time. Repeat
   * requests for the same location, model and day reuse that trained model server-side and
   * come back quickly.
   */
  pointForecast: (body: PointForecastRequestBody) =>
    request<PointForecastResponse>('/api/point-forecast', {
      method: 'POST',
      body: JSON.stringify(body),
      timeoutMs: 300_000,
    }),

  forecast: (id: string, horizonHours: number) =>
    request<ForecastResponse>(`/api/analysis/${id}/forecast`, {
      method: 'POST',
      body: JSON.stringify({ horizon_hours: horizonHours }),
      timeoutMs: 120_000,
    }),

  scenario: (
    id: string,
    body: {
      kind: 'meteorological' | 'system';
      preset_key?: string;
      name?: string;
      perturbations?: { variable: string; mode: string; value: number }[];
      scenario_system?: Record<string, number>;
    },
  ) =>
    request<ScenarioResponse>(`/api/analysis/${id}/scenario`, {
      method: 'POST',
      body: JSON.stringify(body),
      timeoutMs: 120_000,
    }),

  compareModels: (id: string, modelKeys: string[]) =>
    request<ModelComparison>(`/api/analysis/${id}/compare-models`, {
      method: 'POST',
      body: JSON.stringify({ model_keys: modelKeys }),
      timeoutMs: 600_000,
    }),

  experiments: (limit = 50) =>
    request<{ experiments: ExperimentListItem[]; count: number }>(
      `/api/experiments?limit=${limit}`,
    ),

  compareExperiments: (ids: string[]) =>
    request<Record<string, any>>('/api/experiments/compare', {
      method: 'POST',
      body: JSON.stringify({ experiment_ids: ids }),
    }),
};

export { API_BASE };
