# Product Transformation Audit — Helios → Consumer Solar Intelligence Platform

Audit date: 2026-08-19. Scope: full repository inspection prior to any code change.
Target: transform the existing research-grade forecasting console into a product that
answers *"How much useful solar energy can I realistically generate at my location?"*
for farmers, homeowners, businesses, institutions and technical users alike.

---

## 1. Existing architecture (as built)

```
backend/   FastAPI + numpy/pandas/scikit-learn, 8,574 LOC, 133 tests, keyless upstreams
frontend/  Next.js 15 (App Router, but single route) + React 19 + TS + Tailwind, 7,007 LOC
docs/      research synthesis + reference audit
```

**Data flow.** Browser → `POST /api/analysis` → geocode (Open-Meteo) → fetch hourly ERA5
archive (disk-cached, 30-day TTL) → quality assessment → feature build (solar geometry +
meteorology + cyclical time) → chronological split with 24 h embargo → fit estimator on
clear-sky index → evaluate against persistence/climatology baselines → conformalize
prediction intervals → persist experiment → return `analysis_id`. Every other panel is a
follow-up `GET /api/analysis/{id}/…` served from an **in-process LRU cache of 12
analyses**.

**API surface (24 routes).** `analysis` (create, quality, performance, predictions,
explain, leakage, anomalies, forecast, scenario, compare-models, model-card, report),
`experiments` (list, get, compare), `meta` (health, parameters, models, metrics,
scenarios, limits, literature, locations/search).

**Frontend.** One route (`app/page.tsx` → `Console.tsx`), view switching by React state,
14 analyst views, a hand-written SVG chart library (no charting dependency), typed API
client (`lib/api.ts`, 686 LOC), dark "instrument" design tokens in `tailwind.config.ts`.
Total runtime dependencies: `next`, `react`, `react-dom` — nothing else.

## 2. Existing prediction methodology

| Aspect | What is actually implemented |
|---|---|
| Inputs | GHI/DNI/DHI, temperature, humidity, dew point, pressure, wind speed/direction, cloud cover, precipitation (Open-Meteo ERA5), plus closed-form solar geometry: zenith, azimuth, AOI, air mass, extraterrestrial and Haurwitz clear-sky GHI, cyclical time encodings |
| Target | Clear-sky index (`ghi / clear_sky_ghi`), reported back in W/m² |
| Models | Random Forest (default), Histogram Gradient Boosting, Extra Trees, Ridge, and a four-model stacking ensemble of exactly those |
| Split | Chronological hold-out + rolling-origin CV, 24 h embargo; no target lags, by design |
| Uncertainty | Conformalized quantile regression; measured 80.2 % coverage at 80 % nominal |
| Metrics | MAE, RMSE, MBE, R², rRMSE, rMAE, MAPE, sMAPE, skill score; pinball, PICP, PINAW, CRPS |
| PV chain | GHI → Erbs (DHI/DNI) → HDKR transposition → Faiman cell temperature → PVWatts v5 DC → inverter efficiency and clipping → AC kW |
| Forecast | Real forward NWP from the Open-Meteo forecast endpoint, up to 16 days, 7 days validated |
| Reproducibility | Dataset SHA-256 fingerprint + seed + library versions per experiment |

**Verdict: the physics and the ML are sound and stay.** `features/solar_geometry.py`,
`features/pipeline.py`, `models/*`, `evaluation/*`, `quality/engine.py` and
`data/sources.py` are the asset this product is built on, not something to rewrite.

## 3. Findings

### 3.1 Keep as-is
- Entire `features/`, `evaluation/`, `models/`, `quality/`, `anomaly/`, `explain/`,
  `scenario/`, `experiments/`, `reports/` packages.
- `data/sources.py` fetch + cache layer, the error taxonomy (`DataSourceError` hierarchy),
  and the structured error envelope in `main.py` (message / detail / remedy) — that
  contract is exactly what a consumer UI needs in order to render human guidance.
- The custom SVG chart primitives (`components/charts/*`): good quality, zero dependencies.
- The 14 analyst views — they become the **Technical / Advanced** surface, not the default.

### 3.2 Missing — the entire consumer domain (nothing exists today)
Confirmed by search: no occurrence of tariff, consumption, bill, battery, payback, roof,
shading, soiling or degradation anywhere in `backend/app`. The platform can state
irradiance and AC kW for a declared array; it cannot answer any question a non-engineer
actually asks. Required new layer:

1. **Demand estimation** — bill → kWh (tariff-aware), direct kWh entry, and appliance or
   equipment inference per persona (farm pumps by HP × hours × days; shop lighting,
   refrigeration and AC; office by floor area and headcount; industrial by connected load).
2. **Sizing** — kWh demand + roof/land area + budget → recommended kWp, with an area→kWp
   conversion (≈ 6.5 m²/kWp monocrystalline, configurable) and the binding constraint named.
3. **Orientation recommendation** — optimal tilt and azimuth from latitude, so a beginner
   never types a tilt. Deterministic, computable from the existing geometry code.
4. **Self-consumption and battery** — hourly generation against an hourly load profile,
   export versus self-use split, battery dispatch with round-trip and depth-of-discharge losses.
5. **Economics** — capex, savings, payback, lifetime yield with degradation, currency and
   regional tariff defaults. Labelled as modelled assumptions, and editable.
6. **Lifetime** — annual degradation (default 0.5 %/yr) and a 25-year projection.

### 3.3 Broken or weak for the product
- **Latency.** A full analysis takes 10–40 s; measured in `backend_server.log`, `explain`
  took 24.8 s and `report` 17.6 s. A homeowner will not wait 40 s for a number. **Quick
  Estimate must not train a model.** Fast path: cached multi-year archive plus the existing
  physical chain, aggregated to a climatology (TMY-style) — sub-3 s, and scientifically
  defensible for an annual-yield question. ML forecasting stays for the forward-looking and
  technical paths.
- **Statefulness.** Results live in a 12-entry in-process LRU; a restart loses them and a
  13th user evicts the first. No shareable result URL, no saved projects, no auth.
- **Location.** Forward geocoding only. No browser geolocation, no reverse geocoding, no
  map picker, no elevation for coordinate entry, and no failure path when permission is
  denied. Coordinates are the primary UI today, which the directive explicitly forbids.
- **Frontend routing.** A single route with view state means no deep links, no back button,
  no shareable estimate, and no per-step URL for a wizard.
- **Mobile.** Dense tables, a 13.5rem rail and small type. The primary personas (farmers,
  shopkeepers) are phone-first.
- **Language.** kWp, azimuth, clear-sky index, PICP, conformal coverage and rRMSE are
  surfaced with no plain-language layer.
- **No "I don't know" affordance anywhere.** Every input is a required number.

### 3.4 Scientifically questionable, to correct in presentation
- `PVSystem.ac_capacity_kw` silently assumes a 1.2 DC/AC ratio when undeclared. Acceptable,
  but it must be surfaced as an assumption in consumer output rather than hidden.
- Forecast intervals are scaled from test residuals rather than refit — already stated in
  code comments, and must stay stated in the consumer UI rather than quietly dropped.
- Reanalysis is not ground measurement, and PV output is **not** validated against metered
  generation. The consumer surface carries this honestly, as a confidence band plus a
  plain-language caveat — never laundered into a false-precision "you will earn ₹X".

### 3.5 Redundant
- `backend_server.log` sits at the repo root; `.pytest_cache` and `.ruff_cache` are present.
- `frontend/.env.local` duplicates `.env.example` verbatim.
- Nothing in the source tree is dead. No rewrite is warranted.

## 4. Implementation strategy

**Principle: additive. Zero deletion of working science.** The consumer product is a new
layer consuming existing primitives; the existing console is demoted to a route.

### Backend
| Action | Detail |
|---|---|
| ADD | `app/estimate/` — `climatology.py` (fast TMY-style yield from cached archive + `pv_power_chain`), `demand.py` (bill/kWh/appliance inference and load profiles), `sizing.py` (area, budget and demand → kWp; optimal tilt and azimuth), `battery.py` (dispatch and losses), `economics.py` (capex, savings, payback, 25-year degraded yield), `personas.py` (question graph per user type), `tariffs.py` (regional defaults and currency) |
| ADD | `POST /api/estimate` — one call, complete consumer result, sub-3 s target; `POST /api/estimate/{id}/refine` to deepen with the ML path; `GET /api/estimate/{id}` shareable |
| ADD | `GET /api/locations/reverse` — reverse geocode plus elevation, cached and attributed |
| ADD | Durable estimate store on disk, reusing `experiments/store.py` patterns, so results survive a restart and are linkable |
| EXTEND | `PVSystemInput` with soiling, shading, degradation and DC/AC ratio — all optional, with declared defaults |
| KEEP | Every existing route, unchanged, for the technical surface |

### Frontend
| Action | Detail |
|---|---|
| RESTRUCTURE | Real App Router routes: `/` landing, `/start` persona, `/estimate/*` wizard (URL-carried, resumable state), `/result/[id]`, `/advanced` (today's Console, intact) |
| ADD | Location component: geolocation → reverse geocode, search, and map picker (Leaflet + OSM tiles, keyless, attributed), with a non-trapping failure path |
| ADD | A question engine driving progressive disclosure from a persona-specific schema, with `I don't know` / `Help me estimate` on every technical question |
| ADD | Plain-language result surface, with an "inspect the assumptions" disclosure that reveals the existing scientific detail rather than hiding it |
| REWORK | Design tokens: keep the amber = modelled / steel = measured semantic rule and the monospaced-numeral discipline (both are genuinely good); add a light theme and mobile-first density, since the current dark instrument aesthetic reads as a lab tool rather than a product for a farmer |
| KEEP | SVG chart primitives, `lib/api.ts` typing conventions, error rendering |

### Engineering decisions taken (no approval sought)
- **No API keys.** Every added upstream stays keyless: OSM tiles, Open-Meteo.
- **Quick Estimate never trains.** Physical chain plus cached climatology only.
- **Every consumer number is traceable** to the assumption that produced it, and every
  assumption is editable. No fabricated precision, no fake AI features.
- **Deterministic where deterministic is right.** Optimal tilt, area→kWp and tariff maths
  are closed-form, not learned.

## 5. Sequencing
1. Backend consumer domain (`app/estimate/*`), `/api/estimate`, durable store, tests.
2. Location services (reverse geocode, elevation) and the frontend location component.
3. Route restructure, persona selection, mode selection, question engine.
4. Result experience: plain language first, progressive technical depth behind it.
5. Advanced surface re-mounted at `/advanced`, cross-linked in both directions.
6. Accessibility, mobile and performance pass; repo hygiene (stray log, duplicated env).
