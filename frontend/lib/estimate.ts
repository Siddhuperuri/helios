/**
 * Typed client for the consumer estimate API.
 *
 * Kept separate from `lib/api.ts`, which serves the analysis console. They talk to the
 * same server but they are different products with different contracts, and merging them
 * would produce one module that neither surface fully uses.
 *
 * The error handling is the interesting part. The backend returns a structured envelope —
 * `message` written for a person, `detail` for diagnostics, `remedy` stating what to
 * change — and this client preserves all three rather than flattening them into a string.
 * §30 requires the interface never to show a raw failure, and it can only honour that if
 * the guidance survives the trip.
 */

import { getAccessToken, refreshSession } from '@/lib/auth';

export interface ApiFieldError {
  field: string;
  message: string;
  type?: string;
}

export class EstimateError extends Error {
  readonly status: number;
  readonly detail?: string;
  readonly remedy?: string;
  readonly fieldErrors?: ApiFieldError[];
  /** True when the request never reached the server — offline, DNS, CORS, timeout. */
  readonly isNetwork: boolean;

  constructor(
    message: string,
    status: number,
    opts: {
      detail?: string;
      remedy?: string;
      fieldErrors?: ApiFieldError[];
      isNetwork?: boolean;
    } = {},
  ) {
    super(message);
    this.name = 'EstimateError';
    this.status = status;
    this.detail = opts.detail;
    this.remedy = opts.remedy;
    this.fieldErrors = opts.fieldErrors;
    this.isNetwork = opts.isNetwork ?? false;
  }
}

// Empty means same-origin: a Next.js rewrite in development, Nginx in production. That
// is what lets the httpOnly refresh cookie travel at all — see next.config.mjs.
const BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').replace(/\/$/, '');

// A first estimate for an unseen location downloads several years of hourly weather, which
// can take the better part of a minute on a slow connection. Timing that out at the usual
// ten seconds would abandon work that was about to succeed.
const DEFAULT_TIMEOUT_MS = 90_000;

/**
 * One attempt. Attaches the access token when there is one.
 *
 * The token is optional throughout this client, and that is the whole ownership model:
 * every estimate endpoint works signed out, and signing in only changes who the resulting
 * estimate belongs to. A missing token is the anonymous path, never an error.
 */
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
    return await fetch(`${BASE}${path}`, {
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
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = init;

  let response: Response;
  try {
    response = await attempt(path, rest, timeoutMs);

    // A 401 on this surface means the access token expired mid-session. Refresh once and
    // retry; `refreshSession` is single-flight, so several calls failing together produce
    // one refresh rather than several racing rotations.
    if (response.status === 401 && (await refreshSession())) {
      response = await attempt(path, rest, timeoutMs);
    }
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === 'AbortError';
    throw new EstimateError(
      aborted
        ? 'That took longer than expected and we stopped waiting.'
        : 'We could not reach the server.',
      0,
      {
        isNetwork: true,
        remedy: aborted
          ? 'Try again — the weather data for your location may now be downloaded and ready.'
          : 'Check your internet connection and try again. Nothing you entered has been lost.',
      },
    );
  }

  if (response.status === 204) return undefined as T;

  const isJson = (response.headers.get('content-type') ?? '').includes('application/json');

  if (!response.ok) {
    if (isJson) {
      const body = await response.json().catch(() => null);
      throw new EstimateError(
        body?.message ?? 'The request could not be completed.',
        response.status,
        {
          detail: body?.detail,
          remedy: body?.remedy,
          fieldErrors: body?.field_errors,
        },
      );
    }
    throw new EstimateError(
      `The server returned an unexpected response (${response.status}).`,
      response.status,
      { remedy: 'Try again in a moment.' },
    );
  }

  return (isJson ? await response.json() : ((await response.text()) as unknown)) as T;
}

// --------------------------------------------------------------------------------------
// Types mirroring the backend payloads
// --------------------------------------------------------------------------------------

export interface LocationDto {
  latitude: number;
  longitude: number;
  name: string;
  country?: string | null;
  admin1?: string | null;
  elevation_m?: number | null;
  timezone?: string | null;
  source: string;
  label: string;
}

export interface InterviewOption {
  value: string;
  label: string;
  description: string;
  icon: string | null;
  synonyms: string[];
}

export interface InterviewQuestion {
  id: string;
  field: string;
  kind:
    | 'single_choice'
    | 'multi_choice'
    | 'number'
    | 'currency'
    | 'area'
    | 'location'
    | 'equipment_list'
    | 'pump_list'
    | 'boolean'
    | 'text'
    | 'multi_choice'
    | 'info';
  prompt: string;
  spoken_prompt: string;
  help_text: string;
  options: InterviewOption[];
  unit: string | null;
  min_value: number | null;
  max_value: number | null;
  required: boolean;
  unknown_label: string | null;
  unknown_effect: string | null;
  depends_on: Record<string, unknown> | null;
  group: string;
}

export interface InterviewStep {
  id: string;
  title: string;
  subtitle: string;
  questions: InterviewQuestion[];
}

export interface UserTypeDto {
  key: string;
  title: string;
  description: string;
  icon: string;
  synonyms: string[];
}

export interface GoalDto {
  key: string;
  title: string;
  description: string;
  icon: string;
  synonyms: string[];
}

export interface ModeDto {
  key: string;
  title: string;
  description: string;
  duration: string;
  suited_to: string;
  icon: string;
}

export interface ApplianceDto {
  key: string;
  label: string;
  category: string;
  typical_watts: number;
  default_hours_per_day: number;
  default_days_per_month: number;
  user_types: string[];
  hint: string;
}

export interface InterviewCatalogue {
  user_types: UserTypeDto[];
  goals: GoalDto[];
  modes: ModeDto[];
  /** user type -> mode -> goal -> steps. */
  flows: Record<string, Record<string, Record<string, InterviewStep[]>>>;
  panel_wattages: { watts: number; label: string; note: string }[];
  default_panel_watts: number;
  appliances: ApplianceDto[];
  panel_technologies: {
    key: string;
    display_name: string;
    plain_name: string;
    efficiency_pct: number;
    degradation_pct_per_year: number;
    note: string;
  }[];
  installation_types: { key: string; label: string; note: string }[];
  shading_levels: { key: string; label: string; description: string; fraction: number }[];
  loss_stack: { key: string; label: string; default_pct: number; explanation: string }[];
}

export interface UncertaintyFactorDto {
  key: string;
  label: string;
  explanation: string;
  relative_pct: number;
  kind: 'irreducible' | 'data' | 'model' | 'assumption';
  reducible_by: string | null;
}

export interface AssumptionDto {
  key: string;
  label: string;
  value: string | number | boolean | null;
  unit: string | null;
  provenance: string;
  provenance_label: string;
  source: string | null;
  rationale: string | null;
  editable: boolean;
}

export interface MonthlyRange {
  month: number;
  month_name: string;
  expected_kwh: number;
  lower_kwh: number;
  upper_kwh: number;
  daily_average_kwh: number;
  /** How much this particular month varied between years, as a percentage. */
  variability_pct: number;
}

export interface EstimateResult {
  estimate_id: string | null;
  saved?: boolean;
  created_at?: string;
  updated_at?: string;
  label?: string;
  user_type: string;
  mode: string;
  goal: string;
  location: LocationDto;
  currency: { code: string; symbol: string; name: string; symbol_position: string };
  system: {
    capacity_kwp: number;
    ac_capacity_kw: number;
    surface_tilt_deg: number;
    surface_azimuth_deg: number;
    inverter_efficiency: number;
    system_losses_fraction: number;
    panel_technology: string;
    installation_type: string;
    /** The array as a whole number of real panels, and what they add up to. */
    panels: {
      count: number;
      watts: number;
      capacity_kwp: number;
      watts_known: boolean;
      source: 'existing_system' | 'recommended' | 'user_specified';
      model: string | null;
      note: string;
      summary: string;
      /** Each property with the provenance of its value (§9). */
      specification: {
        label: string;
        value: string | number;
        unit: string | null;
        provenance: 'user_provided' | 'datasheet' | 'estimated';
        provenance_label: string;
      }[];
      /** Electrical characteristics: recorded when supplied, never invented (§14). */
      datasheet: {
        key: string;
        label: string;
        unit: string;
        note: string;
        value: number | null;
        provenance: 'user_provided' | 'not_supplied';
      }[];
      datasheet_note: string;
    };
    /** The four areas §6 keeps distinct, and whether the array fits. */
    space: {
      panel_area_m2: number;
      module_area_m2: number;
      module_area_sqft: number;
      footprint_m2: number;
      footprint_sqft: number;
      available_area_m2: number | null;
      usable_area_m2: number | null;
      usable_fraction: number;
      usable_pct: number;
      spacing_multiplier: number;
      installation_type: string;
      fits: boolean | null;
      utilisation: number | null;
      utilisation_pct: number | null;
      max_panels_in_space: number | null;
      panel_dimensions_known: boolean;
      usable_note: string;
      notes: string[];
    };
    inverter: {
      ac_capacity_kw: number;
      dc_ac_ratio: number;
      severity: 'ok' | 'note' | 'caution' | 'error';
      verdict: string;
      /** The same finding without the vocabulary, for the beginner surface (§13). */
      plain: string;
      typical_range: [number, number];
    };
    dc_model: string;
    cell_temperature_model: string;
    transposition_model: string;
    sizing: {
      capacity_kwp: number;
      binding_constraint: string;
      reason: string;
      area_required_m2: number;
      area_required_sqft: number;
      area_available_m2: number | null;
      capacity_from_demand_kwp: number | null;
      capacity_from_area_kwp: number | null;
      capacity_from_budget_kwp: number | null;
      notes: string[];
    };
    orientation: {
      tilt_deg: number;
      azimuth_deg: number;
      azimuth_compass?: string;
      annual_kwh_per_kwp?: number;
      gain_over_flat_pct?: number;
      method: string;
      note?: string;
      candidates?: { tilt_deg: number; azimuth_deg: number; annual_kwh_per_kwp: number }[];
    };
    battery: {
      capacity_kwh: number;
      usable_kwh: number;
      basis: string;
      backup_hours: number | null;
      critical_load_kw: number | null;
      charging_note: string;
      notes: string[];
    } | null;
  };
  generation: {
    annual_kwh: number;
    annual_std_kwh: number;
    monthly_kwh: number[];
    monthly_std_kwh: number[];
    month_names: string[];
    daily_profile_kwh: number[];
    best_month: number;
    best_month_name: string;
    worst_month: number;
    worst_month_name: string;
    specific_yield_kwh_per_kwp: number;
    capacity_factor: number;
    performance_ratio: number;
    mean_poa_kwh_per_m2_year: number;
    mean_ghi_kwh_per_m2_year: number;
    clipped_fraction: number;
    years_used: number;
    complete_calendar_years: number;
    period_start: string;
    period_end: string;
    rows_used: number;
    rows_dropped: number;
    variability_basis: string;
    warnings: string[];
    daily_average_kwh: number;
    monthly_average_kwh: number;
    monthly_ranges: MonthlyRange[];
  };
  demand: {
    annual_kwh: number;
    monthly_kwh: number;
    daily_kwh: number;
    method: string;
    method_label: string;
    confidence: string;
    notes: string[];
    breakdown: {
      key: string;
      label: string;
      category: string;
      count: number;
      watts_each: number;
      hours_per_day: number;
      days_per_month: number;
      monthly_kwh: number;
    }[];
    profile_key: string;
    profile_description: string;
    /** The 24 hourly values the self-consumption split was actually computed from. */
    hourly_kwh: number[];
  } | null;
  balance: {
    generation_kwh: number;
    consumption_kwh: number;
    self_consumed_kwh: number;
    exported_kwh: number;
    imported_kwh: number;
    solar_offset_pct: number;
    self_consumption_pct: number;
    grid_dependence_pct: number;
    battery: Record<string, unknown> | null;
    notes: string[];
  } | null;
  economics: {
    currency_code: string;
    currency_symbol: string;
    system_cost: number;
    battery_cost: number;
    total_capex: number;
    annual_savings_year1: number;
    annual_import_savings: number;
    annual_export_income: number;
    monthly_savings_year1: number;
    lifetime_savings: number;
    lifetime_years: number;
    payback_years: number | null;
    roi_pct: number | null;
    lcoe_per_kwh: number | null;
    annual_om_cost: number;
    co2_avoided_kg_per_year: number;
    co2_avoided_tonnes_lifetime: number;
    yearly: {
      year: number;
      generation_kwh: number;
      savings: number;
      net_cash_flow: number;
      cumulative_cash_flow: number;
    }[];
    caveats: string[];
  } | null;
  emissions: {
    co2_avoided_kg_per_year: number;
    co2_avoided_tonnes_per_year: number;
    equivalences: { key: string; value: number; unit: string; phrase: string }[];
  } | null;
  uncertainty: {
    expected: number;
    lower: number;
    upper: number;
    relative_pct: number;
    confidence: 'high' | 'medium' | 'low';
    confidence_reason: string;
    coverage: number;
    coverage_label: string;
    factors: UncertaintyFactorDto[];
    improvements: string[];
  };
  farm: {
    sufficient_inputs: boolean;
    missing: string[];
    pump_input_kw: number | null;
    typical_daily_hours: number | null;
    best_month_hours: number | null;
    worst_month_hours: number | null;
    daily_water_m3: number | null;
    daily_water_litres: number | null;
    irrigable_area_hectares: number | null;
    irrigable_area_acres: number | null;
    meets_requirement: boolean | null;
    notes: string[];
    assumptions: { key: string; label: string; value: number; note: string }[];
  } | null;
  operations: {
    operating_hours: number | null;
    peak_demand_kw: number | null;
    connected_load_kw: number | null;
    offset_target_pct: number | null;
    grid_connection: string | null;
    facility_type: string | null;
    business_type: string | null;
    farm_loads: string[];
    peak_demand_note: string | null;
  } | null;
  assumptions: AssumptionDto[];
  data_sources: {
    category: string;
    name: string;
    detail: string;
    licence: string;
    caveat?: string;
  }[];
  attribution: string;
  warnings: string[];
  timings: Record<string, number>;
  data_completeness: number;
  explanation: {
    summary: string;
    confidence: string;
    confidence_reason: string;
    what_affects_this: { key: string; title: string; body: string }[];
    how_to_improve: string[];
  };
  input?: Record<string, unknown>;
}

export interface EstimateSummary {
  estimate_id: string;
  created_at: string;
  updated_at: string;
  label: string;
  location_label: string | null;
  user_type: string | null;
  capacity_kwp: number | null;
  annual_kwh: number | null;
  payback_years: number | null;
  confidence: string | null;
}

export interface ScenarioRow {
  name: string;
  capacity_kwp: number;
  battery_kwh: number | null;
  annual_kwh: number;
  annual_kwh_lower: number;
  annual_kwh_upper: number;
  solar_offset_pct: number | null;
  self_consumption_pct: number | null;
  total_capex: number | null;
  annual_savings: number | null;
  payback_years: number | null;
  roi_pct: number | null;
  co2_tonnes_per_year: number | null;
  area_required_m2: number;
  confidence: string;
}

/** The request body. Mirrors `app/schemas/estimate.py`; every field is optional but one. */
export interface EstimateRequestBody {
  user_type?: string;
  mode?: string;
  goal?: string;
  location: { query?: string; latitude?: number; longitude?: number };
  consumption_method?: string | null;
  monthly_bill?: number | null;
  monthly_kwh?: number | null;
  equipment?: {
    key: string;
    count?: number;
    hours_per_day?: number | null;
    days_per_month?: number | null;
    watts?: number | null;
  }[];
  pumps?: {
    horsepower: number;
    count?: number;
    hours_per_day?: number;
    days_per_month?: number;
    motor_efficiency?: number | null;
  }[];
  floor_area_m2?: number | null;
  occupants?: number | null;
  installation_type?: string;
  area?: {
    value?: number | null;
    unit?: string;
    length?: number | null;
    width?: number | null;
    dimension_unit?: string;
    polygon?: [number, number][] | null;
  } | null;
  system?: {
    capacity_kwp?: number | null;
    panel_count?: number | null;
    panel_watts?: number | null;
    panel_model?: string | null;
    panel_length_m?: number | null;
    panel_width_m?: number | null;
    panel_voc?: number | null;
    panel_isc?: number | null;
    panel_vmp?: number | null;
    panel_imp?: number | null;
    panel_key?: string;
    tilt_deg?: number | null;
    azimuth_deg?: number | null;
    shading_level?: string;
    inverter_efficiency?: number | null;
    inverter_ac_capacity_kw?: number | null;
    dc_ac_ratio?: number | null;
    degradation_rate?: number | null;
    lifetime_years?: number | null;
    loss_overrides?: Record<string, number>;
  };
  battery?: {
    wanted?: boolean;
    capacity_kwh?: number | null;
    desired_backup_hours?: number | null;
    critical_load_kw?: number | null;
    grid_connected?: boolean;
  };
  money?: {
    tariff_per_kwh?: number | null;
    fixed_monthly_charge?: number | null;
    export_rate_per_kwh?: number | null;
    budget?: number | null;
    system_cost?: number | null;
  };
  farm?: {
    pump_horsepower?: number | null;
    pump_head_metres?: number | null;
    required_daily_water_m3?: number | null;
    crop_water_mm_per_day?: number | null;
  };
  operations?: {
    operating_hours?: number | null;
    peak_demand_kw?: number | null;
    connected_load_kw?: number | null;
    offset_target_pct?: number | null;
    grid_connection?: string | null;
    farm_loads?: string[];
    business_type?: string | null;
    facility_type?: string | null;
  };
  export_allowed?: boolean;
  history_years?: number;
  label?: string | null;
  save?: boolean;
}

// --------------------------------------------------------------------------------------
// Client
// --------------------------------------------------------------------------------------

export const estimateApi = {
  interview: () => request<InterviewCatalogue>('/api/meta/interview'),

  searchLocations: (q: string, limit = 6) =>
    request<{ results: LocationDto[] }>(
      `/api/locations/search?q=${encodeURIComponent(q)}&limit=${limit}`,
      { timeoutMs: 12_000 },
    ),

  reverseGeocode: (latitude: number, longitude: number) =>
    request<{ location: LocationDto }>(
      `/api/locations/reverse?latitude=${latitude}&longitude=${longitude}`,
      { timeoutMs: 15_000 },
    ),

  create: (body: EstimateRequestBody) =>
    request<EstimateResult>('/api/estimate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  get: (id: string) => request<EstimateResult>(`/api/estimate/${encodeURIComponent(id)}`),

  /**
   * The signed-in user's own estimates.
   *
   * Requires a session and returns only estimates owned by it. This used to list every
   * estimate the server held, which was defensible when there were no accounts and is not
   * now. Anonymous estimates are reachable only by their link.
   */
  list: (limit = 25) =>
    request<{ estimates: EstimateSummary[]; owner: string }>(
      `/api/estimates?limit=${limit}`,
      { timeoutMs: 15_000 },
    ),

  rename: (id: string, label: string) =>
    request<{ estimate_id: string; label: string }>(
      `/api/estimate/${encodeURIComponent(id)}/rename`,
      { method: 'POST', body: JSON.stringify({ label }) },
    ),

  remove: (id: string) =>
    request<{ deleted: boolean }>(`/api/estimate/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      timeoutMs: 15_000,
    }),

  update: (
    id: string,
    body: {
      system?: EstimateRequestBody['system'];
      money?: EstimateRequestBody['money'];
      battery?: EstimateRequestBody['battery'];
      operations?: EstimateRequestBody['operations'];
      label?: string;
    },
  ) =>
    request<EstimateResult>(`/api/estimate/${encodeURIComponent(id)}/update`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  compare: (base: EstimateRequestBody, scenarios: { name: string; capacity_kwp?: number; battery_kwh?: number }[]) =>
    request<{ scenarios: ScenarioRow[]; currency: EstimateResult['currency']; note: string }>(
      '/api/estimate/compare',
      { method: 'POST', body: JSON.stringify({ base, scenarios }) },
    ),

  report: (id: string) =>
    request<string>(`/api/estimate/${encodeURIComponent(id)}/report`, { timeoutMs: 20_000 }),

  health: () => request<Record<string, unknown>>('/api/health', { timeoutMs: 6_000 }),
};
