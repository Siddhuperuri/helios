# Helios — Delivery Report

What was built, what was kept, how it calculates, what it cannot do, and how to run it.

Companion documents: [`PRODUCT_TRANSFORMATION_AUDIT.md`](PRODUCT_TRANSFORMATION_AUDIT.md)
(the pre-implementation audit), [`RESEARCH_SYNTHESIS.md`](RESEARCH_SYNTHESIS.md) (technique
provenance), [`REFERENCE_AUDIT.md`](REFERENCE_AUDIT.md) (audit of the superseded reference
application).

---

## 1. What changed

The project was a research-grade irradiance forecasting platform: scientifically sound,
and unusable by anyone who did not already understand solar engineering. Its front door
asked for DC capacity in kWp, surface tilt, surface azimuth and a model key before it would
produce anything.

It is now two surfaces over one engine.

**Frontend.** Rebuilt around a real route structure. The single-route console
(`app/page.tsx` → view state) became an App Router tree: a landing page, a two-question
entry, a server-driven interview, a results dashboard with seven explore tabs, a saved-work
dashboard, and three supporting content pages. The console moved intact to `/advanced`. The
design system gained a light theme and mobile-first density; the consumer surface defaults
to light because it is read on a phone outdoors, while the console keeps the dark
instrument palette it was designed for.

**Backend.** A new `app/estimate/` package — 12 modules — implements the consumer domain
that did not exist: demand, sizing, storage, economics, uncertainty, farm translation,
reporting, persistence. Nothing in `features/`, `models/`, `evaluation/`, `quality/`,
`explain/`, `scenario/` or `experiments/` was rewritten; the new layer composes them.

**Prediction engine.** The physical chain is unchanged and now drives a second, faster
path: a climatology over years of observed weather rather than a trained forecast. The
orientation search is new — it finds the best tilt and azimuth by evaluating candidates
against the location's own weather rather than applying a latitude rule.

**APIs.** Nine consumer endpoints added alongside the twenty-four research endpoints, which
are untouched. Reverse geocoding and elevation lookup added to the data layer.

**UX.** The governing change: the interview is *data served by the API*, not a hardcoded
wizard. A farmer and a factory manager get different questions because the server describes
different flows.

---

## 2. Existing functionality retained

Everything scientifically load-bearing was kept and is still exercised.

| Retained | Where | Now used by |
|---|---|---|
| Solar geometry (position, AOI, air mass, clear-sky, extraterrestrial) | `features/solar_geometry.py` | Both surfaces |
| PV conversion chain (Erbs → HDKR → Faiman → PVWatts v5 → inverter) | `features/solar_geometry.py` | Both surfaces |
| Feature pipeline with leakage guards | `features/pipeline.py` | Console |
| 10 estimators, chronological splits, embargo, rolling-origin CV | `models/`, `evaluation/` | Console |
| Conformalized quantile regression | `models/uncertainty.py` | Console |
| Data quality engine | `quality/engine.py` | Console |
| Permutation importance, partial dependence | `explain/attribution.py` | Console |
| Anomaly detection, scenario engine, experiment store | `anomaly/`, `scenario/`, `experiments/` | Console |
| Open-Meteo fetch layer with disk caching and retry | `data/sources.py` | Both surfaces |
| Structured error envelope (message / detail / remedy) | `main.py` | Both surfaces |
| Custom SVG chart primitives | `components/charts/` | Console |
| All 14 analysis views | `components/views/` | `/advanced` |
| 133 original tests | `backend/tests/` | Still passing |

**Nothing was deleted except code that nothing called.** Five unused functions and one
superseded dataclass were removed during the self-review; each is named in §8.

---

## 3. New functionality

### Backend — `app/estimate/`

| Module | What it does |
|---|---|
| `assumptions.py` | Every default with provenance, panel technologies, itemised loss stack, shading levels, area factors, cost tiers, emission factors, data-source declarations |
| `climatology.py` | The fast path: physical chain over years of hourly weather, aggregated to a typical year with measured inter-annual variability |
| `demand.py` | Consumption from bill / metered units / equipment / floor area; 23-item appliance library with duty cycles; hourly load archetypes |
| `sizing.py` | Area conversion (7 units, dimensions, map polygon), empirical orientation search, capacity recommendation with binding constraint |
| `balance.py` | Hourly self-consumption, export and import; battery dispatch and sizing |
| `economics.py` | Capex, savings, payback, ROI, LCOE, 25-year projection with degradation and tariff escalation, emissions with equivalences |
| `uncertainty.py` | Range and confidence from named, separable components |
| `farm.py` | Pump hours, water volume, irrigable area — gated on sufficient inputs |
| `tariffs.py` | Currency, regional tariffs, bill-to-kWh conversion, subsidy detection |
| `personas.py` | The interview as data: 6 user types, 2 modes, per-persona question flows |
| `report.py` | 12-section shareable Markdown report |
| `store.py` | Durable estimates with unguessable ids and a retention sweep |
| `engine.py` | Pipeline orchestration and plain-language narrative |

### New API endpoints

```
GET    /api/meta/interview            the whole question flow, as data
GET    /api/locations/reverse         coordinates → place name + elevation
POST   /api/estimate                  one call, complete result
GET    /api/estimate/{id}             shareable, durable
POST   /api/estimate/{id}/update      edit assumptions and re-run
POST   /api/estimate/{id}/rename
DELETE /api/estimate/{id}
GET    /api/estimates                 saved work
GET    /api/estimate/{id}/report      professional report
POST   /api/estimate/compare          controlled side-by-side comparison
```

### Frontend

- **Routes**: `/`, `/start`, `/predict`, `/estimate`, `/result/[id]`, `/compare`,
  `/projects`, `/how-it-works`, `/resources`, `/about`, `/advanced`
- **Location**: geolocation with a non-trapping failure path, debounced search, and a
  **hand-rolled slippy map** (~250 lines: tile grid, pointer pan, pinch zoom, pin drop,
  polygon tracing, keyboard control) with a **Leaflet adapter** behind the same interface
- **Interview**: renders whatever the server describes; conditional questions; an
  "I don't know" escape on every technical question that states what it costs
- **Results**: headline with range and confidence, plain-language explanation, seven tabs,
  four purpose-built charts, editable assumptions
- **Staged loading**, draft persistence across reloads, light/dark themes, i18n scaffold

---

## 4. Prediction methodology

A consumer estimate runs this pipeline. No step is a rule of thumb.

```
location → tariff & currency → demand → weather (fetched once)
    → best orientation → yield per kWp → system size
    → yield for that system → energy balance → economics
    → uncertainty → narrative
```

**1. Location.** A place name, a GPS fix or a map pin resolves to coordinates, and to a
place name and ISO country code by reverse geocoding — the country selects currency,
tariff defaults and grid emission factor.

**2. Weather.** Three years of hourly ERA5 reanalysis for those coordinates: GHI, air
temperature, wind speed and the rest. Typically ~26,000 hours. Fetched once and cached;
incomplete hours are dropped, never imputed.

**3. Orientation.** Rather than applying a latitude rule, ~20 candidate orientations are
evaluated against this location's own weather. Solar position is invariant to orientation,
so it is computed once and reused, which makes the search affordable. A win over
equator-facing below 0.5 % snaps back to due south — "face south" is an instruction a
builder can follow, and 170° would be false precision.

**4. Reference yield.** The chain runs for a 1 kWp array to get specific yield, which is
capacity-invariant and therefore what sizing needs.

**5. Sizing.** Three constraints — demand to offset, space available, budget — and the
smallest binds. Which one bound the answer is reported.

**6. Final yield.** The chain runs again for the sized system, because inverter clipping is
*not* capacity-invariant. Per hour:

```
GHI → Erbs decomposition → DHI + DNI
    → HDKR transposition (+ ground reflection) → plane-of-array irradiance
    → Faiman cell temperature (irradiance, air temp, wind)
    → PVWatts v5 DC model (temperature coefficient against nameplate)
    → system losses, combined multiplicatively
    → inverter efficiency and AC clipping
    → hourly AC kWh
```

Summed to months and years, averaged across the years in the record.

**7. Energy balance.** Generation is matched against demand *hour by hour*, not as annual
totals. This is why a system generating 100 % of annual consumption can still only offset
58 % of the bill — solar arrives midday, and much household use is after dark. Batteries,
when wanted, are dispatched greedily against the surplus with round-trip and
depth-of-discharge losses applied.

**8. Economics.** Self-consumed units valued at the import rate, exported units at the
export rate, projected across the system's life with annual degradation and tariff
escalation, net of maintenance.

**9. Uncertainty.** Components combined in quadrature:

| Component | Source |
|---|---|
| Year-to-year weather | **Measured** — the spread between years at these coordinates |
| Solar resource data | Reanalysis grid cell vs. a point measurement (~5 %) |
| Conversion model | The published chain applied to correct inputs (~5 %) |
| Shading, orientation, equipment | One term per question the user could not answer |
| Record length, data gaps | Added when the record is short or incomplete |

Monthly bands use **each month's own measured variability**, so a monsoon July shows
±11.5 % where a dry February shows ±1.1 %.

### Where machine learning sits

The consumer path is **physics only, no training**. An annual-yield question is a
climatology question; the honest answer is the physics run over observed weather. Training
a model to forecast hour-ahead irradiance would cost 30 seconds to say the same thing about
an annual average.

ML earns its place on the forward-looking path — `/advanced`, `/api/analysis`,
`/api/point-forecast` (default model: XGBoost trained on measured plant output, README §7b) — where predicting a specific day and hour is the actual task. That path is the hybrid the brief
describes and predates this work:

```
weather + solar resource → physical model (clear-sky index)
    → ML correction (Random Forest et al., trained per location)
    → loss model → energy → conformal prediction intervals
```

**The ML is not advertised as making the consumer estimate more accurate**, because it does
not: the annual figure is dominated by weather that has not happened yet, and no model
narrows that.

---

## 5. Data sources

Only services actually integrated. No invented citations.

| Category | Source | Used for | Licence |
|---|---|---|---|
| Solar resource & weather | **Open-Meteo Historical Weather API** (ERA5 / ERA5-Land reanalysis) | Hourly GHI, DNI, DHI, temperature, humidity, wind, cloud cover, precipitation | Open-Meteo CC-BY 4.0; ERA5 © ECMWF / Copernicus |
| Weather forecast | **Open-Meteo Forecast API** | Forward NWP, to 16 days (console) | CC-BY 4.0 |
| Place search & elevation | **Open-Meteo Geocoding API** | Name → coordinates, elevation, timezone | GeoNames, CC-BY 4.0 |
| Reverse geocoding | **OpenStreetMap Nominatim** | Coordinates → place name, country code | ODbL |
| Map tiles | **OpenStreetMap** | The map | ODbL |
| PV conversion | Published models: Erbs, HDKR, Faiman, PVWatts v5 (Dobos 2014, NREL/TP-6A20-62641), Haurwitz | The physical chain | Literature |
| Tariffs, costs, emission factors | **Editable planning defaults** | Financial figures | Not a schedule, not a quotation |

**No API keys.** Every upstream service is keyless and public. Nominatim requests carry an
identifying User-Agent and round coordinates before sending, which improves cache hit rate
and sends a third party less precision about where the user is standing.

---

## 6. Assumptions

Every one is surfaced in the result's Assumptions tab with its provenance, and the
important ones are editable there.

**System losses** — PVWatts v5 default stack, combined multiplicatively (≈13.6 % total):
soiling 2 %, shading 3 %, mismatch 2 %, wiring 2 %, connections 0.5 %, light-induced
degradation 1.5 %, nameplate tolerance 1 %, availability 3 %. Temperature and inverter
losses are **deliberately absent** — both are modelled explicitly, and including them here
would apply each penalty twice.

**Equipment** — monocrystalline PERC by default (20.5 % efficient, −0.35 %/°C, 0.5 %/yr
degradation); inverter 96 % efficient; DC/AC ratio 1.2 when undeclared; albedo 0.2.

**Space** — 4.9 m²/kWp of module area, multiplied for real installations: rooftop ×1.35
(walkways, setbacks), ground and farm ×2.6 (row spacing against self-shading), carport
×1.15, unknown ×1.6.

**Motors** — pump horsepower is shaft output, so electrical input is HP × 745.7 ÷ 0.75
motor efficiency; pump-end efficiency 0.55 for water volume.

**Financial** — installed cost tiered by size (₹62,000/kWp under 3 kW down to ₹38,000/kWp
above 250 kW, with equivalents per currency); 25-year life; 0.5 %/yr degradation; 3 %/yr
tariff escalation; 1 % of capex annual maintenance. **These are planning figures, not
quotations**, and every result says so.

**Tariffs** — regional defaults per country and user type. Indian agricultural supply is
flagged **subsidised**, because billing a farmer's displaced units at a commercial rate
would overstate their savings several-fold; in that case the result says the benefit is
reliable daytime power rather than a lower bill.

**Load shapes** — five hourly archetypes (home, farm, shop, commercial, institution). These
are archetypes, labelled as such, and a real interval meter would beat them.

**Emissions** — grid emission factors as national averages (India 0.71 kg CO₂/kWh).

---

## 7. Limitations

Stated plainly, and stated in the product as well as here.

1. **Modelled, not measured.** No metered generation from an installed system was available.
   Every PV figure is physics applied to weather data and has **not** been validated against
   real production.
2. **Reanalysis, not a pyranometer.** ERA5 is a modelled gridded product covering an area,
   not a sensor at the user's address. Local haze, dust and coastal cloud can differ.
3. **Load shapes are archetypes.** Self-consumption, and therefore savings, depend on a
   daily shape inferred from user type. A household that runs its washing at noon behaves
   nothing like one that runs it at 21:00.
4. **No seasonal demand modelling.** Demand is flat across the year by design; the module
   models the daily shape only. Air conditioning in summer is not represented.
5. **Financial defaults are not quotations.** Costs, tariffs and emission factors are
   planning figures. Financing, subsidies, tax treatment and commercial demand charges are
   not modelled.
6. **Currency conversion is approximate and static.** Used only to place a default in the
   right order of magnitude. Where no rate is known, the currency falls back to USD rather
   than showing a familiar symbol beside a wrong number.
7. **No shading survey.** Shading is a four-option estimate, not a horizon analysis.
8. **Battery model is simple.** Greedy dispatch with round-trip and DoD losses. No tariff
   arbitrage, no cell ageing, no export limits.
9. **No accounts.** `/projects` lists everything on the server, not per-user. An estimate
   link is a bearer token. A multi-user deployment must put authentication in front of it.
10. **The console's limitations are unchanged** and documented in the README §10: intervals
    cover model error given supplied weather, not error in the weather forecast; models are
    trained per location with no cross-location generalisation claimed.

---

## 8. Testing

**278 automated tests. All passing.**

### Backend — 227 tests (`cd backend && python -m pytest`)

The original 133 (solar geometry against known astronomical values, PV chain, metrics,
split leakage properties, quality detection of eight corruptions, feature-pipeline leakage
guards, API validation) plus 94 new ones weighted toward failures that would be *silently*
wrong rather than loudly broken:

- Losses compound rather than add; the stack excludes temperature and inverter
- Polygon area against a known square, orientation-independent, matching the frontend
- Bill conversion removes the fixed charge; a bill under the standing charge is reported
- Refrigerator duty cycle; pump draws more than its horsepower rating
- Both energy ledgers balance, with and without storage; a battery cannot return more than
  it stored; offset never exceeds 100 %
- Yield is capacity-invariant; partial months excluded; missing weather dropped not imputed
- Optimal tilt near latitude, equator-facing in both hemispheres; sampling keeps hour-of-day
  coverage
- Sizing binds on the smallest constraint and names it
- Payback interpolated within the year; no-payback reported honestly; degradation reduces
  output year on year
- Unknown inputs widen the range; incomplete data forces low confidence
- Farm output refuses without a pump rating; no water figure without a head
- Store round-trip; path traversal refused; identifiers unguessable
- Every technical question in every persona flow has an escape route
- Currency and tariff always on the same scale; ISO code preferred over translated name

### Frontend — 51 tests (`cd frontend && npm test`)

- Web Mercator round-trip at four latitudes and four zooms; pole clamping; date-line wrap
- Polygon area against a known square, agreeing with the backend within 0.5 %
- Draft-to-request mapping: coordinates preferred over names, nothing sent as zero, empty
  branches dropped, percent-to-fraction conversion
- Indian digit grouping (1,53,500 not 153,500); MWh switching; missing values
- Validation produces corrections naming the bound and unit, never "invalid"
- "I don't know" reveals its consequence and is reversible
- Denied, timed-out and unavailable geolocation each get their own path
- Loading never says "Loading" and never marks a stage done before it is

### Manual and browser testing

- Full farm journey driven through the real UI: persona → mode → live geocoding → six
  steps → staged loading → result
- Detailed mode with panel technology, explicit tilt/azimuth, inverter efficiency, DC/AC
  ratio, loss override, 30-year lifetime, battery from backup hours
- Assumption edit round-trip: tariff 9.2 → 12.5 moved payback 3.3 → 2.0 years, same link
- Failure paths with the backend stopped: dashboard and interview both degrade with a
  remedy and a reassurance
- Physical sanity across latitudes: Nairobi (1°S) → 0° tilt, Reykjavik (64°N) → 45° tilt
  and PR 0.84, Seville (37°N) → 30° tilt, 1,564 kWh/kWp
- Mobile at 375 px: zero horizontal overflow, no unlabelled controls, all tap targets ≥40 px

### Fixed during the self-review (§59)

| Found | Fix |
|---|---|
| Savings shown in USD for an Indian location | Coordinates now reverse-geocode to a country; ISO code drives currency |
| Summary read "16.5074, 80.6466 has a strong solar resource" | Same fix — coordinates resolve to a place name |
| Extending the currency table would have served `KSh 0.15/kWh` (130× wrong) | Currency, tariff and cost derive from one rates table; unknown currency falls back to USD |
| `'geolocation' in navigator` passed when the value was `undefined` | Check the function, not the key |
| Search results reopened after selecting one | Suppress the search the selection itself triggers |
| Step title rendered twice in the wizard header | Header now shows what is next |
| All 12 months shared one annual uncertainty | Each month uses its own measured variability |
| Frontend duplicated the backend's load profiles | Backend returns the 24 values it used |
| `/estimate/{id}/update` existed but nothing called it | Assumption editor built and wired |
| Six unused functions and one dataclass | Removed; `prune` wired into startup retention instead |
| Unit toggle 31 px, footer links 15 px | Raised to the 44 px minimum on mobile |
| Landing chart was a hand-shaped curve | Now computed from declination, hour angle, Haurwitz and PVWatts |

---

## 9. Run instructions

### Requirements

- **Python 3.11+**
- **Node 20+**
- No API keys. No database. Internet access for weather data.

### First run

**Terminal 1 — backend**

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — frontend**

```bash
cd frontend
npm install
npm run dev
```

`frontend/.env.local` is already present and points at `http://127.0.0.1:8000`. If it is
ever missing, copy it from the example — `copy .env.example .env.local` on Windows `cmd`,
or `cp .env.example .env.local` on macOS, Linux and Git Bash.

Then open **<http://localhost:3000>**.

- Consumer calculator: <http://localhost:3000>
- Analysis console: <http://localhost:3000/advanced>
- API documentation: <http://localhost:8000/api/docs>

### Verify the installation

```bash
cd backend && python -m pytest
```

```bash
cd frontend && npm run typecheck && npm test && npm run build
```

Expect 227 backend tests and 51 frontend tests passing, a clean typecheck, and a successful
build.

### A first estimate

1. **Calculate My Solar Potential**
2. Choose **Farm / Agriculture** (or any type), then **Quick Estimate**
3. Search a location — try `Vijayawada` — and pick a result
4. Answer what you can; skip anything you do not know
5. **Calculate my solar potential**

The first estimate for a new location takes ~15 s while several years of weather download.
Anything in the same area afterwards takes about a second.

### Optional configuration

| Variable | Default | Effect |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `http://127.0.0.1:8000` | Where the frontend finds the API |
| `NEXT_PUBLIC_MAP_ENGINE` | *(unset)* | `leaflet` swaps in the Leaflet map adapter |
| `SOLAR_CORS_ORIGINS` | `http://localhost:3000,…` | Allowed frontend origins |
| `SOLAR_ESTIMATE_RETENTION_DAYS` | `365` | Retention sweep at startup |
| `SOLAR_CACHE_DIR`, `SOLAR_STORE_DIR` | `backend/var/…` | Cache and store location |
| `SOLAR_RATE_LIMIT`, `SOLAR_RATE_WINDOW` | `60` / `60` | In-process rate limit |

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "We could not reach the server" | Backend not running, or `NEXT_PUBLIC_API_BASE` wrong |
| Port 8000 already in use | An old server is still running — stop it, or use `--port 8001` and set `NEXT_PUBLIC_API_BASE` to match |
| First estimate is slow | Downloading years of weather for a new location. Subsequent runs are cached |
| "Use my location" does nothing | Browsers only allow geolocation on `localhost` or HTTPS. Search or the map still work |
| Map tiles blank | No internet, or OpenStreetMap unreachable. Search entry still works |

---

## 10. Deployment

### Backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Set `SOLAR_CORS_ORIGINS` to the deployed frontend origin.

### Frontend

```bash
cd frontend
npm ci
npm run build
npm start          # or deploy the build to any Node host
```

Set `NEXT_PUBLIC_API_BASE` to the public API URL **at build time** — `NEXT_PUBLIC_*`
variables are inlined during the build, not read at runtime.

### Before going live

**These matter and are not defaults:**

1. **Put HTTPS in front of both.** Browser geolocation requires a secure context, so
   "Use my location" will not work over plain HTTP on a real domain.
2. **Add authentication in front of `/projects` and `/api/estimates`.** With no accounts,
   that route lists every estimate on the server. Estimate links themselves are unguessable
   bearer tokens and are fine to share deliberately.
3. **Add a gateway rate limiter.** The in-process limiter bounds one client per worker and
   is not a substitute. A single analysis on the console costs tens of seconds of CPU.
4. **Use shared storage for multi-node deployments.** The cache and both stores are on local
   disk; two nodes will not see each other's results.
5. **Review the Nominatim usage policy** if you expect meaningful traffic. Reverse geocoding
   is cached and coordinate-rounded, but a busy deployment should run its own instance or
   use a commercial provider.
6. **Persist `backend/var/`.** It holds the weather cache (making restarts fast) and every
   saved estimate. In a container, mount it as a volume.
7. **Update `npm` dependencies.** Three high-severity advisories exist in Next's transitive
   `postcss` and `sharp`. Fixing them requires a Next 16 major upgrade, which was out of
   scope here.

### Container sketch

```dockerfile
# Backend
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
VOLUME /app/var
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

```dockerfile
# Frontend
FROM node:20-slim
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build
CMD ["npm", "start"]
```

### Health and monitoring

`GET /api/health` reports service state. Every response carries `X-Request-ID` and
`X-Response-Time-ms`; requests over 5 s are logged as slow. Watch for upstream failures from
Open-Meteo — the platform degrades to cached data and says so rather than failing silently.

---

## 11. Panel quantity and adaptive questioning

Added after the initial delivery, integrated into the existing pipeline rather than as a
separate calculator.

### Panel count as a real system parameter

The governing distinction: **panel count is an input for an existing array and an output
for a planned one.** A `goal` of `existing` / `install` / `compare` is asked immediately
after the user type and reshapes the interview — the existing path asks how many panels
before anything optional, the install path never asks in Quick mode because the count is
what the user came for.

Capacity is quantised to whole panels and **recomputed from the rounded count**: a sizing
target of 15.37 kW becomes 28 × 550 W = 15.40 kW, and 15.40 is what is modelled. Reporting
the target while quoting the count would put a capacity on the page that no whole number of
panels produces.

Changing the count on the result page re-runs the entire pipeline against cached weather.
It does not rescale the figures, because output is not proportional to size: with a fixed
20 kW inverter, going from 40 to 60 panels raised clipping from 0 % to 18.2 % and delivered
49,730 kWh where proportional scaling would have claimed 51,331.

### The four areas (§6)

A roof is not a rectangle of glass, and four quantities are tracked separately:

| | On a 300 m² roof with 40 × 550 W |
|---|---|
| Available | 300 m² — as described by the user |
| Usable | 210 m² — 70 %, after tanks, parapets, setbacks and access |
| Footprint | 145 m² — what the array occupies with row spacing |
| Panel area | 107 m² — the glass alone |

Feasibility is footprint ≤ usable. Panel area is **derived, not tabulated**: at STC the
reference is 1000 W/m², so area = watts ÷ (efficiency × 1000), which reproduces four real
datasheets (Waaree, Trina, Jinko, Adani) to within 1.1 %. Datasheet dimensions override it.

This corrected a genuine error: capacity was previously sized from stated area with only a
spacing allowance, treating a roof as 100 % buildable. On a 100 m² roof that claimed ~27
panels fit where 19 do.

### Per-persona interviews (§7)

There is no universal questionnaire. Each persona is asked what it is powering — a farm
about pumps and cold storage, a shop about its trade, a facility about its type — and only
commercial and institutional flows are asked about peak demand, connected load, offset
target and grid connection. Home stays at five steps.

Offset target and grid connection are load-bearing, not decorative: the first feeds
capacity sizing, the second decides whether surplus is credited or wasted. Peak demand is
recorded and **deliberately excluded from savings**, because solar rarely reduces it.

### Beginner and expert surfaces (§13, §14)

The technical vocabulary is gated on the mode the user chose. A Quick Estimate reader sees
"You have slightly more panels than the inverter can pass at full sun" and no DC/AC ratio,
no "kW DC", no temperature coefficient. A Detailed Analysis reader sees the ratio, the
verdict, the full specification and the datasheet fields — and the same disclosure is
available on the quick path for anyone curious. Nothing is hidden; it is only unasked-for.

Datasheet electricals (Voc, Isc, Vmp, Imp) are **accepted, never invented**: they depend on
cell count and chemistry this platform does not hold for any product. They are displayed
with their source, marked *Not supplied* when absent, and the note states plainly that the
energy model is driven by rated power, efficiency and the temperature coefficient.

### Inverter validation (§11)

The array is checked against the inverter and the finding is reported with a severity, but
an unusual configuration is **never rejected**. A DC/AC ratio of 1.6 is flagged as a
caution and modelled as given, because it is a real design somebody may have chosen — for a
hard export limit, or an array facing away from the sun.

### Additional tests

45 further backend tests covering: panel arithmetic against the specified examples,
capacity recomputed from rounded counts, the four areas ordered and distinct, a roof not
treated as fully coverable, feasibility reported both ways, panel area against datasheets,
inverter severity bands, warn-never-reject, plain-language twins free of jargon, per-persona
flow differences, and unit capitalisation in the summary.

**Backend 257 tests, frontend 60 tests, all passing.**
