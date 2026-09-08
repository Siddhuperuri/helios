/**
 * The in-progress interview, kept safe across reloads.
 *
 * Somebody standing in a field on a weak connection will lose the page. When they come
 * back, an interface that has forgotten their pump's horsepower and their monthly bill has
 * wasted their time twice. §30 promises "nothing you entered has been lost", and this is
 * what makes that promise true rather than reassuring.
 *
 * `sessionStorage` rather than `localStorage`, deliberately: a draft holds a location and
 * an electricity bill, and it should not outlive the browsing session on a shared or
 * borrowed device. Completed estimates persist server-side under an unguessable id
 * instead, which is a decision the user makes rather than one made for them.
 */

import type { EstimateRequestBody } from '@/lib/estimate';

const KEY = 'helios.draft.v1';

export interface EquipmentDraft {
  key: string;
  count: number;
  hours_per_day?: number | null;
  days_per_month?: number | null;
}

export interface PumpDraft {
  horsepower: number;
  count: number;
  hours_per_day: number;
  days_per_month: number;
}

export interface AreaDraft {
  mode: 'value' | 'dimensions' | 'polygon' | 'unknown';
  value?: number | null;
  unit?: string;
  length?: number | null;
  width?: number | null;
  dimension_unit?: string;
  polygon?: [number, number][] | null;
  /** Area in m² computed from a drawn polygon, kept for display. */
  polygon_area_m2?: number | null;
}

export interface Draft {
  user_type?: string;
  mode?: 'quick' | 'detailed';
  /** What they came to do. Decides whether panel count is asked for or handed back. */
  goal?: 'existing' | 'install' | 'compare';

  location?: {
    query?: string;
    latitude?: number;
    longitude?: number;
    label?: string;
    elevation_m?: number | null;
    /** How the location was chosen, for the assumptions panel and for analytics-free debugging. */
    method?: 'geolocation' | 'search' | 'map';
  };

  consumption_method?: string;
  monthly_bill?: number | null;
  monthly_kwh?: number | null;
  equipment?: EquipmentDraft[];
  pumps?: PumpDraft[];
  floor_area_m2?: number | null;

  installation_type?: string;
  area?: AreaDraft;
  shading_level?: string;

  wants_battery?: boolean;
  desired_backup_hours?: number | null;
  critical_load_kw?: number | null;
  grid_connected?: boolean;

  tariff_per_kwh?: number | null;
  budget?: number | null;
  system_cost?: number | null;

  panel_key?: string;
  panel_count?: number | null;
  panel_watts?: number | null;
  panel_model?: string | null;
  panel_length_m?: number | null;
  panel_width_m?: number | null;
  panel_voc?: number | null;
  panel_isc?: number | null;
  panel_vmp?: number | null;
  panel_imp?: number | null;
  /** Which branch of the panel-knowledge question they took (§12). */
  panel_knowledge?: 'specs' | 'model' | 'unknown';

  /** How the site runs — only the personas that are asked will carry these. */
  operating_hours?: number | null;
  peak_demand_kw?: number | null;
  connected_load_kw?: number | null;
  offset_target_pct?: number | null;
  grid_connection?: string | null;
  farm_loads?: string[];
  business_type?: string | null;
  facility_type?: string | null;
  tilt_deg?: number | null;
  azimuth_deg?: number | null;
  inverter_efficiency_pct?: number | null;
  dc_ac_ratio?: number | null;
  capacity_kwp?: number | null;

  pump_horsepower?: number | null;
  pump_head_metres?: number | null;
  crop_water_mm_per_day?: number | null;
  required_daily_water_m3?: number | null;

  /** Questions the user explicitly skipped, so the interface stops re-asking. */
  skipped?: string[];
  updated_at?: number;
}

export function loadDraft(): Draft {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Draft) : {};
  } catch {
    // A corrupt or unreadable draft must not block the user from starting again.
    return {};
  }
}

export function saveDraft(draft: Draft): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify({ ...draft, updated_at: Date.now() }),
    );
  } catch {
    // Private browsing modes can refuse storage entirely. Losing persistence is a
    // degradation, not a failure — the interview still works in memory.
  }
}

export function clearDraft(): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}

/**
 * Translate the draft into the API request.
 *
 * The rule applied throughout: a value the user did not give is *omitted*, never sent as
 * zero or an empty string. The backend distinguishes "not supplied" from "supplied as
 * nothing" — the first widens the uncertainty band and records a default in the
 * assumptions ledger, the second would be taken as a real answer.
 */
export function draftToRequest(draft: Draft): EstimateRequestBody {
  const location = draft.location ?? {};
  const hasCoords =
    typeof location.latitude === 'number' && typeof location.longitude === 'number';

  const body: EstimateRequestBody = {
    user_type: draft.user_type ?? 'exploring',
    mode: draft.mode ?? 'quick',
    goal: draft.goal ?? 'install',
    location: hasCoords
      ? { latitude: location.latitude, longitude: location.longitude }
      : { query: location.query ?? '' },
    installation_type: draft.installation_type ?? 'not_sure',
    save: true,
  };

  // ------------------------------------------------------------------ consumption
  if (draft.consumption_method === 'bill' && draft.monthly_bill) {
    body.consumption_method = 'bill';
    body.monthly_bill = draft.monthly_bill;
  } else if (draft.consumption_method === 'units' && draft.monthly_kwh) {
    body.consumption_method = 'units';
    body.monthly_kwh = draft.monthly_kwh;
  } else if (draft.consumption_method === 'equipment') {
    const equipment = (draft.equipment ?? []).filter((e) => e.key && e.count > 0);
    const pumps = (draft.pumps ?? []).filter((p) => p.horsepower > 0 && p.hours_per_day > 0);
    if (equipment.length || pumps.length) {
      body.consumption_method = 'equipment';
      body.equipment = equipment;
      body.pumps = pumps;
    }
  } else if (draft.consumption_method === 'floor_area' && draft.floor_area_m2) {
    body.consumption_method = 'floor_area';
    body.floor_area_m2 = draft.floor_area_m2;
  }

  // ------------------------------------------------------------------------ area
  const area = draft.area;
  if (area && area.mode !== 'unknown') {
    if (area.mode === 'polygon' && area.polygon && area.polygon.length >= 3) {
      body.area = { polygon: area.polygon };
    } else if (area.mode === 'dimensions' && area.length && area.width) {
      body.area = {
        length: area.length,
        width: area.width,
        dimension_unit: area.dimension_unit ?? 'm',
      };
    } else if (area.mode === 'value' && area.value) {
      body.area = { value: area.value, unit: area.unit ?? 'sqm' };
    }
  }

  // ---------------------------------------------------------------------- system
  const system: NonNullable<EstimateRequestBody['system']> = {};
  if (draft.shading_level) system.shading_level = draft.shading_level;
  if (draft.panel_count) system.panel_count = draft.panel_count;
  if (draft.panel_watts) system.panel_watts = draft.panel_watts;
  if (draft.panel_model?.trim()) system.panel_model = draft.panel_model.trim();
  if (draft.panel_length_m) system.panel_length_m = draft.panel_length_m;
  if (draft.panel_width_m) system.panel_width_m = draft.panel_width_m;
  if (draft.panel_voc) system.panel_voc = draft.panel_voc;
  if (draft.panel_isc) system.panel_isc = draft.panel_isc;
  if (draft.panel_vmp) system.panel_vmp = draft.panel_vmp;
  if (draft.panel_imp) system.panel_imp = draft.panel_imp;
  if (draft.panel_key) system.panel_key = draft.panel_key;
  if (typeof draft.tilt_deg === 'number') system.tilt_deg = draft.tilt_deg;
  if (typeof draft.azimuth_deg === 'number') system.azimuth_deg = draft.azimuth_deg;
  if (typeof draft.capacity_kwp === 'number') system.capacity_kwp = draft.capacity_kwp;
  if (typeof draft.dc_ac_ratio === 'number') system.dc_ac_ratio = draft.dc_ac_ratio;
  if (typeof draft.inverter_efficiency_pct === 'number') {
    // The interview asks for a percentage because that is what a datasheet prints; the
    // API takes a fraction. Converting here keeps the unit mismatch in one place.
    system.inverter_efficiency = draft.inverter_efficiency_pct / 100;
  }
  if (Object.keys(system).length) body.system = system;

  // --------------------------------------------------------------------- battery
  if (draft.wants_battery) {
    body.battery = {
      wanted: true,
      desired_backup_hours: draft.desired_backup_hours ?? null,
      critical_load_kw: draft.critical_load_kw ?? null,
      grid_connected: draft.grid_connected ?? true,
    };
  } else if (draft.grid_connected === false) {
    body.battery = { wanted: false, grid_connected: false };
  }

  // ----------------------------------------------------------------------- money
  const money: NonNullable<EstimateRequestBody['money']> = {};
  if (draft.tariff_per_kwh) money.tariff_per_kwh = draft.tariff_per_kwh;
  if (draft.budget) money.budget = draft.budget;
  if (draft.system_cost) money.system_cost = draft.system_cost;
  if (Object.keys(money).length) body.money = money;

  // ------------------------------------------------------------------ operations
  const operations: NonNullable<EstimateRequestBody['operations']> = {};
  if (draft.operating_hours) operations.operating_hours = draft.operating_hours;
  if (draft.peak_demand_kw) operations.peak_demand_kw = draft.peak_demand_kw;
  if (draft.connected_load_kw) operations.connected_load_kw = draft.connected_load_kw;
  if (draft.offset_target_pct) operations.offset_target_pct = draft.offset_target_pct;
  if (draft.grid_connection) operations.grid_connection = draft.grid_connection;
  if (draft.business_type) operations.business_type = draft.business_type;
  if (draft.facility_type) operations.facility_type = draft.facility_type;
  if (draft.farm_loads?.length) operations.farm_loads = draft.farm_loads;
  if (Object.keys(operations).length) body.operations = operations;

  // ------------------------------------------------------------------------ farm
  if (draft.user_type === 'farm') {
    const farm: NonNullable<EstimateRequestBody['farm']> = {};
    if (draft.pump_horsepower) farm.pump_horsepower = draft.pump_horsepower;
    if (draft.pump_head_metres) farm.pump_head_metres = draft.pump_head_metres;
    if (draft.crop_water_mm_per_day) farm.crop_water_mm_per_day = draft.crop_water_mm_per_day;
    if (draft.required_daily_water_m3) {
      farm.required_daily_water_m3 = draft.required_daily_water_m3;
    }
    if (Object.keys(farm).length) body.farm = farm;
  }

  return body;
}

/** Whether the draft holds enough to run at all. Location is the only hard requirement. */
/**
 * Whether a usable location has been chosen.
 *
 * Deliberately separate from `canSubmit`. The location step asks only this; folding the
 * other completeness rules in here once made that step refuse with "choose a location"
 * while a location was plainly selected — an error message pointing at the wrong field is
 * worse than no validation at all.
 */
export function hasLocation(draft: Draft): boolean {
  const location = draft.location;
  if (!location) return false;
  const hasCoords =
    typeof location.latitude === 'number' && typeof location.longitude === 'number';
  return hasCoords || Boolean(location.query && location.query.trim().length >= 2);
}

/** Whether the whole draft is complete enough to send. Checked only at submit. */
export function canSubmit(draft: Draft): boolean {
  if (!hasLocation(draft)) return false;

  // An existing array is described by its panel count. Without it there is nothing to
  // model, and the server would refuse — so the interface does not offer to try.
  if (draft.goal === 'existing' && !draft.panel_count) return false;

  return true;
}
