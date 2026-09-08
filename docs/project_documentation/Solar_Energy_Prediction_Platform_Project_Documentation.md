# Solar Energy Prediction and Analysis Platform

**Project Documentation** &middot; Compiled 2026-08-21

A location-aware solar generation calculator for consumers, and a rigorous
hourly-irradiance analysis console for researchers — sharing one physical engine,
one data source, and one philosophy: every number traces back to an assumption,
and every assumption is on the table.

| Codename | Version | Backend | Frontend |
|---|---|---|---|
| Helios | 1.0 | Python 3.11 + FastAPI | Next.js 15 + React 19 + TypeScript |

> This Markdown file is the editable source for the same-named PDF in this
> folder. Content is kept in sync; the PDF adds cover art, running headers,
> page numbers and inline SVG diagrams that Markdown cannot express.

---

## Table of Contents

1. Executive Summary
2. Introduction and Background
3. Problem Statement
4. Objectives
5. Target Users and Use Cases
6. System Overview
7. System Architecture
8. Technology Stack
9. Repository Structure
10. User Experience and Workflow
11. Adaptive Questionnaire
12. User-Type Logic
13. Location System
14. Energy Consumption Model
15. Solar Panel System
16. Panel Quantity and System Capacity
17. Solar Energy Prediction Methodology
18. Mathematical Model — Formulas Used
19. Machine Learning Model (Analysis Console)
20. Weather and Solar Data
21. Data Flow
22. Results and Visualisation
23. Uncertainty and Limitations
24. Validation and Error Handling
25. Security
26. Performance and Responsiveness
27. Accessibility and Usability
28. Testing
29. Deployment
30. Installation and Running
31. Future Improvements
32. Conclusion
33. Glossary
34. References
35. Appendix — API and Configuration

---

## 1. Executive Summary

The **Solar Energy Prediction and Analysis Platform** (internal codename *Helios*)
is a full-stack web application that helps a non-specialist decide whether to
install a solar photovoltaic (PV) system at a specific location, and gives a
researcher the tools to interrogate hourly irradiance forecasting on the same
data. It exposes two surfaces over one shared backend:

- **A consumer calculator** at `/` — a two-minute guided interview that returns
  expected annual generation, monthly and daily shapes, a confidence-rated range,
  an energy balance against the user's consumption, financial savings, payback,
  emissions avoided, and a shareable report.
- **An analysis console** at `/advanced` — a fourteen-view research workbench
  that trains scikit-learn models on ERA5 reanalysis, validates them with
  time-aware splits and an embargo gap, calibrates prediction intervals with
  Conformalised Quantile Regression, and persists every run as a reproducible
  experiment.

Both surfaces run against the same deterministic physical chain
(Erbs → HDKR → Faiman → PVWatts v5) and the same weather source (Open-Meteo
Historical Weather API / ERA5 reanalysis). Machine learning is deliberately
restricted to the forward-looking research path where predicting a specific
future day is the actual task; the consumer answer is a climatology question,
computed by running years of observed weather through the physics.

### Major capabilities

- Address search, GPS auto-locate, map-pin drop, reverse geocoding.
- Three ways to describe consumption (monthly bill, monthly kWh, itemised
  equipment) and three to describe available space (value, L×W, or polygon).
- Automatic tilt/azimuth search against the location's own weather.
- Panel-count-first sizing, honouring existing systems, comparing scenarios.
- Regional tariffs & currencies for 30+ countries; farm-subsidy detection.
- Hourly self-consumption, battery dispatch and sizing, import/export ledger.
- Full economics: CAPEX, savings, payback, ROI, LCOE, degradation-corrected
  lifetime yield, CO₂ avoided with plain-language equivalences.
- Measured uncertainty bands built from inter-annual weather variability and
  named assumption components.
- Analysis console: 10 model families, rolling-origin cross-validation, five-check
  leakage audit, permutation importance, partial dependence, weather-regime
  error decomposition, anomaly detection, scenario analysis, Markdown report.

### Outcome

A single-repository application (`backend/` + `frontend/`) that runs locally
with no API keys. A saved estimate returns in about a second against cached
weather (~15 s for a never-seen-before location); a full model-trained analysis
completes in 10–40 s. Backed by 223+ backend and 51 frontend automated tests.

---

## 2. Introduction and Background

Photovoltaic energy is the fastest-growing electricity source globally, but its
output is weather-dependent and therefore uncertain. That uncertainty makes three
practical decisions difficult: sizing a system to match consumption, scheduling
maintenance around expected generation, and balancing a grid that increasingly
relies on variable resources. A prediction of solar generation is only useful if
it is genuinely predictive of the future, states how uncertain it is, and has
been validated in a way that mirrors deployment conditions.

Existing consumer solar tools mostly use a "sunlight × capacity" rule of thumb:
they take a monthly kWh/m² figure, multiply by system size, and print a number.
That approach hides four problems: it treats a national average as if it applied
to a specific rooftop; it does not respond to time or orientation; it presents
modelled figures without any range; and it cannot explain where its numbers came
from. This platform was built to replace that class of tool with something that
is transparent, location-aware and honest about what it does not know.

### Why prediction is useful

- **Sizing.** The right system size is the smallest one that meets the realistic
  offset target. Getting this wrong wastes capital or under-produces for life.
- **Consumption matching.** Solar generates when the sun is up; a household with
  an evening peak recovers only a fraction of unstored generation.
- **Financial planning.** Payback depends on tariff, degradation, export policy
  and inter-annual weather variability.
- **Grid operations.** Hour-by-hour forecast accuracy with a calibrated range is
  the difference between an adequate reserve and a shortfall.

### Challenges

- Atmospheric attenuation is stochastic; cloud, aerosol, humidity and
  precipitation move irradiance by up to an order of magnitude in a day.
- Solar geometry is deterministic; mixing it into a learning problem lets the
  learner memorise the clock instead of the atmosphere.
- Reanalysis is not measurement; grid-cell averages differ systematically from
  point observations.
- Consumption archetypes are approximations; real interval-meter data beats them.

---

## 3. Problem Statement

Anyone considering solar — a farmer, homeowner, shopkeeper, facility manager —
needs to answer four practical questions before spending money:

1. How much energy can I generate here, per day and per year?
2. How much of my consumption does that offset, and when does the mismatch fall?
3. What will it cost, and how long will it take to pay back?
4. How confident am I in each of these answers?

Available tools fail these questions in three characteristic ways: they answer
per-region rather than per-coordinate; they report a single point estimate as if
measured; and they show none of the assumptions behind the number.

### What the platform must therefore do

- **Answer per-location.** Every calculation runs against the actual weather at
  the supplied coordinates.
- **Answer per-user.** The interview adapts to what the user is trying to do; every
  technical question can be declined.
- **Attach a range.** Every headline number carries an honest uncertainty band
  built from named components.
- **Show its working.** Every assumption is displayed; changing any of them
  moves every dependent number.
- **Refuse to fabricate.** Where the platform cannot know something, it says so.

> **Reference-app failure that shaped this brief:** the predecessor application
> returned *16.79 kWh alongside 0 % stated irradiance* and gave the *same figure
> for 06:51 and 13:51*. Both are recorded in `docs/REFERENCE_AUDIT.md`. Helios's
> design choices — time-aware validation, physical constraints applied after
> inference, explicit assumption ledger — exist so that neither failure can recur.

---

## 4. Objectives

### Primary objectives

1. Deliver **location-specific** solar generation estimates using the observed
   hourly weather record at the user's supplied coordinates.
2. **Adapt the questionnaire** to six user categories with different questions,
   defaults and result emphasis.
3. Attach **measured uncertainty** to every headline number, decomposed into
   weather variability, resource error, model error and per-assumption components.
4. Compute a full **energy balance and finances**: hourly self-consumption and
   export, battery dispatch/sizing, tariff-aware savings, payback, ROI, LCOE and
   lifetime CO₂ avoided.
5. Support three **goals**: sizing a planned system, describing an existing one,
   comparing scenarios side-by-side.
6. Produce a shareable, saved estimate with a stable URL, a plain-text report,
   and an editable assumption ledger.
7. Provide a **research console** that trains and evaluates ten scikit-learn model
   families with time-aware validation, prediction intervals and reproducibility
   manifests.

### Secondary objectives

1. **Run keyless.** Every upstream service (Open-Meteo Archive and Geocoding,
   OpenStreetMap Nominatim) is public; no accounts required.
2. **Localise gracefully.** Interview strings are data, not code; a future
   translator can add Telugu or Tamil without editing React.
3. **Fit into a rural context.** Mobile-first layout, touch-friendly controls,
   graceful GPS-denied fallback, offline-tolerant map with Leaflet swap.
4. **Never present modelled figures as measurements.** No metered PV output was
   available, and the interface labels PV figures as physically modelled.
5. **Keep the surfaces separate.** Consumer and console do not share a palette,
   a route, a wording register, or a reader.
6. **Preserve provenance.** Every weather fetch is cached; every model run is
   written to an experiment store with a SHA-256 dataset fingerprint.

---

## 5. Target Users and Use Cases

Six user categories are supported by the interview data in `personas.py`. Each
carries its own icon, its own default question set, and its own result emphasis.

| User type | Typical inputs collected | Result emphasis |
|---|---|---|
| **Home** | Monthly bill or kWh, roof space, occupants, appliance list, tariff | Bill offset, monthly savings, payback, panel count, battery option |
| **Farm / Agriculture** | Loads (pumps, cold storage, sheds), pump HP + head, required daily water, crop water mm/day | Daily pumping hours (best/worst month), water pumped m³, irrigable ha, subsidy note |
| **Shop / Small Business** | Business type, operating hours, bill or kWh, roof area, grid connection | Daytime self-consumption, offset %, payback |
| **Commercial / Industrial** | Facility type, peak demand & connected load, operating hours, offset target %, grid connection | Solar offset %, peak-demand caveat, self-consumption, lifetime CO₂ |
| **School / Institution** | Facility type, operating hours, roof area, monthly bill | Term-time balance, offset %, community-oriented CO₂ equivalences |
| **Just Exploring** | Location only (everything else optional) | Site potential (specific yield, capacity factor, best/worst month) |

### Representative workflows

- **Farmer with a 5 HP pump and 3 acres.** Answer *Farm*, drop a pin on the well,
  give pump horsepower and head. Estimate returns daily generation, pump-hours
  supported, and cubic-metres pumped in dry vs. monsoon months.
- **Homeowner, ₹3 000 bill, 40 m² roof.** Answer *Home*, enter bill and roof
  area. Engine picks tilt/azimuth, recommends a panel count, returns monthly
  savings and payback.
- **Facility manager comparing 100/150/200 kWp.** Fill details once; use
  `POST /api/estimate/compare` to score all three against the same weather.
- **Owner of an existing 5 kWp array.** Set goal to *Existing*, enter the panel
  count and rated wattage. Sizer is bypassed; engine returns true expected
  production of the installed system as a benchmark against actual bills.

---

## 6. System Overview

Helios is a two-tier web application. A Python 3.11 backend built on FastAPI
exposes a typed JSON API; a Next.js 15 frontend consumes it. All state is
persisted server-side as JSON on local disk — there is no database and no user
account system. Two external services are called: Open-Meteo Historical Weather
API for hourly reanalysis, and OpenStreetMap Nominatim for reverse-geocoding a
dropped map pin. Both are keyless.

```
                   +----------+
                   |   User   |  (web browser)
                   +----+-----+
                        |
                        v
    +---------------------------------+
    |  Frontend  (Next.js 15 / React) |  consumer & console surfaces
    |  Custom SVG charts, hand-rolled |
    +--------------+------------------+
                   |  JSON over HTTP
                   v
    +---------------------------------+       +-----------------------------+
    |  Backend API (FastAPI)          | <---> | Weather / geocoding cache   |
    |  /api/estimate  /api/analysis   |       | (JSON on disk, TTL keyed)   |
    +--+-----------+---------+--------+       +-----------------------------+
       |           |         |
       v           v         v
    Estimate    Model     Local storage
    engine     trainer    (estimates, experiments)
    (physics)  (sklearn)
       |
       v
    Open-Meteo Archive / Geocoding / Nominatim   (all keyless)
```

### End-to-end flow (consumer estimate)

```
User → UI wizard → typed request → FastAPI /api/estimate
     → engine.run(input):
         resolve_location → tariff/currency → resolve_demand
         → fetch_history (weather cache)  → optimal_orientation
         → reference climatology (per kWp) → recommend_capacity
         → panel-quantised system         → final climatology
         → energy balance                 → economics
         → uncertainty                    → farm capability (if farm)
     → assembled payload → optionally save → response
     → React ResultView / CompareView / SystemSpecification
```

---

## 7. System Architecture

### Presentation Layer

Next.js 15 App Router with React 19 and TypeScript. Two route groups keep the
surfaces separate: `app/(site)/` hosts the consumer flow with a light palette;
`app/advanced/` hosts the analysis console with a dark instrument palette and no
shared chrome. Styling is Tailwind CSS 3.4 with a hand-tuned token scheme. There
is no charting library — every plot in both surfaces is a hand-rolled SVG.

### Application / API Layer

FastAPI application `backend/app/main.py` assembles four routers:

- `app.api.routes.meta` — health, catalogue, interview metadata, data-source
  manifest, place search.
- `app.api.routes.estimate` — consumer surface: create/read/update/delete/rename
  an estimate, run a comparison, produce a professional report.
- `app.api.routes.analysis` — console surface: create an analysis, then query
  its quality, predictions, performance, intervals, explanation, anomalies,
  forecast, scenarios and report subresources.
- `app.api.routes.experiments` — list, compare and delete persisted experiments.

Cross-cutting concerns live in `main.py`: a fixed-window in-process rate limiter,
a middleware that stamps every response with a request ID and elapsed time,
security headers, and error translators that turn Pydantic validation failures,
upstream data-source errors and internal exceptions into a structured envelope
with `error`, `message`, `detail`, `remedy` and (for validation) `field_errors`.

### Data Layer

No relational database. Two on-disk stores keep server state:

- **Weather & geocoding cache** — JSON files keyed by SHA-256 of URL + params,
  with configurable TTL. Every upstream call goes through this cache, so an
  orientation search evaluating twenty candidate tilts still fetches once.
- **Estimate store** — JSON records under `backend/var/estimates/`, addressable
  by opaque estimate ID. A retention sweep at startup prunes old records.
- **Experiment store** — JSON records for every training run, carrying the
  dataset fingerprint, metrics, folds, baselines and manifest.

### Prediction Layer

Two paths share a single physical chain and a single feature pipeline:

- **Fast path (consumer)** — `app/estimate/climatology.py` runs the physical
  chain over 3 years of ERA5 hourly weather. No model is trained; inter-annual
  variability is **measured**, not assumed.
- **Forward-looking path (console)** — `app/models/trainer.py` trains a
  scikit-learn estimator, splits chronologically with a 24-hour embargo,
  cross-validates with rolling origins, calibrates a prediction interval using
  Conformalised Quantile Regression.

### External Services

| Service | Endpoint | Purpose | Key |
|---|---|---|---|
| Open-Meteo Historical | `archive-api.open-meteo.com/v1/archive` | Hourly ERA5 reanalysis: GHI, DNI, DHI, T, RH, wind, cloud, precip. | No |
| Open-Meteo Geocoding | `geocoding-api.open-meteo.com/v1/search` | Place-name search + elevation (GeoNames, CC-BY 4.0). | No |
| OpenStreetMap Nominatim | `nominatim.openstreetmap.org/reverse` | Reverse-geocode coordinates to place name. | No |
| Open-Meteo Forecast | `api.open-meteo.com/v1/forecast` | Short-horizon forecast for console *Forecast* view. | No |

The frontend has no secrets and does no data acquisition. Every upstream call is
proxied through the backend so a change of provider touches one file
(`backend/app/data/sources.py`), and so cache/quality scoring apply uniformly.

---

## 8. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend framework | Next.js 15.5 (App Router) + React 19 + TypeScript 5.7 | Consumer surface and analysis console. |
| Styling | Tailwind CSS 3.4 with custom tokens; PostCSS + Autoprefixer | Design-token styling; light & dark palettes. |
| Map (default) | Hand-rolled Web-Mercator tile map (~250 LOC) | Zero-bundle map with pin-drop and polygon-draw. |
| Map (swap) | Leaflet 1.9 via dynamically-imported adapter | Env-flag swap for devices the built-in map mishandles. |
| Client state | React state + `lib/draft.ts` localStorage | No global state library; wizard survives refresh. |
| Frontend tests | Vitest 2.1 + Testing Library + jsdom | 51 tests covering projection, mapping, promises. |
| Backend framework | FastAPI 0.115 + Uvicorn 0.32 (ASGI) | Typed JSON API with OpenAPI at `/api/docs`. |
| Backend runtime | Python 3.11+ | Type-hinted dataclasses across the domain layer. |
| Scientific stack | NumPy 1.26+, pandas 2.2+, SciPy 1.13+, scikit-learn 1.5+ | Physical chain, features, training, evaluation. |
| Validation | Pydantic 2.9 | Request schemas, error messages mapped to prompts. |
| Backend tests | pytest 8 + httpx 0.27 | 223+ tests. |
| Weather source | Open-Meteo Historical Weather API (ERA5) | Hourly meteorological variables. |
| Geocoding | Open-Meteo Geocoding + OpenStreetMap Nominatim | Forward + reverse geocoding. |
| Storage | Local filesystem (JSON) | Cache, saved estimates, experiment ledger. |
| Deployment | Uvicorn workers + Next.js production server | Standard ASGI + Node processes. |

### Deliberate omissions

- **No charting library.** All visualisations are hand-rolled SVG.
- **No state-management library.** React state + localStorage covers everything.
- **No deep-learning runtime.** Model set stops at scikit-learn ensembles;
  sequence models declared as future work.
- **No third-party auth.** No user accounts; opaque saved-estimate URLs.

---

## 9. Repository Structure

```
college_project/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, middleware, error translation
│   │   ├── config.py            Environment-driven settings
│   │   ├── api/
│   │   │   ├── service.py       Analysis creation + cache
│   │   │   └── routes/
│   │   │       ├── meta.py            /api/meta/*
│   │   │       ├── estimate.py        /api/estimate/*  (consumer, 10 endpoints)
│   │   │       ├── analysis.py        /api/analysis/*  (console, 14 endpoints)
│   │   │       └── experiments.py     /api/experiments/*
│   │   ├── data/sources.py      HTTP with disk cache; upstream clients
│   │   ├── features/
│   │   │   ├── solar_geometry.py     NOAA position, Haurwitz, Erbs, HDKR, Faiman, PVWatts v5
│   │   │   ├── parameters.py         Solar-position features, cyclical time
│   │   │   └── pipeline.py           Feature-set builder with leakage guards
│   │   ├── quality/engine.py    Transparent data-quality scoring (8 corruption types)
│   │   ├── models/
│   │   │   ├── registry.py      10 estimator specs with paper-cited hyperparameters
│   │   │   ├── trainer.py       Split, fit, evaluate, cross-validate, calibrate
│   │   │   ├── uncertainty.py   Conformalised quantile regression
│   │   │   └── forecast.py      Short-horizon forecasting for the console
│   │   ├── evaluation/
│   │   │   ├── metrics.py       MAE, RMSE, MBE, R², rRMSE, pinball, PICP, PINAW, CRPS
│   │   │   ├── splitters.py     Chronological hold-out + rolling origins with embargo
│   │   │   ├── baselines.py     Persistence, smart persistence, climatology, seasonal-naive
│   │   │   └── leakage.py       Five-check audit
│   │   ├── explain/attribution.py    Permutation importance, partial dependence
│   │   ├── anomaly/detector.py       Physical, residual, ramp, drift detectors
│   │   ├── scenario/engine.py        Counterfactual scenarios with pathway decomposition
│   │   ├── experiments/store.py      On-disk experiment ledger
│   │   ├── reports/generator.py      Console-side Markdown report
│   │   ├── schemas/                  Pydantic request/response models
│   │   └── estimate/                 See next tree
│   ├── scripts/                      calibrate_interval.py, utilities
│   └── tests/                        223+ pytest tests
│
├── frontend/
│   ├── app/
│   │   ├── layout.tsx                Root shell + font + globals
│   │   ├── globals.css               Tailwind base, tokens
│   │   ├── (site)/                   Consumer surface
│   │   │   ├── page.tsx              Landing
│   │   │   ├── start/                User-type & goal picker
│   │   │   ├── predict/              Date-and-time energy prediction
│   │   │   ├── estimate/             Interview wizard
│   │   │   ├── result/               Result dashboard
│   │   │   ├── compare/              Scenario comparison
│   │   │   ├── projects/             Saved estimates gallery
│   │   │   ├── how-it-works/         Methodology page
│   │   │   ├── resources/            Solar resource explainer
│   │   │   └── about/                About page
│   │   └── advanced/                 Analysis console (14 views)
│   ├── components/
│   │   ├── Console.tsx               Console shell (dark palette)
│   │   ├── Setup.tsx                 Console setup form
│   │   ├── site/                     Nav, Footer, Icon, ProjectsDashboard, ResourceCurve
│   │   ├── estimate/                 EstimateWizard, LocationStep, AreaField, EquipmentBuilder,
│   │   │                             LoadingStages, StartFlow, fields, map/
│   │   ├── predict/                  PredictView (date+time prediction page)
│   │   ├── insights/                 OperatingConditions cards, shared by both surfaces
│   │   ├── result/                   ResultView, CompareView, PanelConfigurator,
│   │   │                             SystemSpecification, AssumptionEditor, charts
│   │   ├── charts/                   Hand-rolled SVG chart primitives
│   │   └── views/                    14 console views
│   ├── lib/                          api client, draft, format, i18n, estimate, useAsync
│   └── tests/                        51 Vitest tests
│
└── docs/
    ├── DELIVERY.md                   Delivery report
    ├── RESEARCH_SYNTHESIS.md         Papers surveyed + design decisions
    ├── PRODUCT_TRANSFORMATION_AUDIT.md  Consumer-layer audit
    ├── REFERENCE_AUDIT.md            Failures of the predecessor app
    └── project_documentation/        This document (Markdown + HTML + PDF)
```

### Estimate subpackage detail

```
backend/app/estimate/
    engine.py        1058 LOC · Pipeline orchestrator (14 numbered stages)
    personas.py      1256 LOC · Interview as data (six user types, all questions)
    sizing.py         667 LOC · Orientation search, capacity recommendation, quantisation
    assumptions.py    641 LOC · Panel technologies, loss stack, defaults, provenance
    demand.py         496 LOC · Bill / units / equipment / floor-area routes; hourly archetypes
    climatology.py    344 LOC · Fast path: physical chain over N years of weather
    balance.py        313 LOC · Hourly self-consumption, import/export, battery dispatch
    uncertainty.py    319 LOC · Confidence band from named components
    space.py          306 LOC · Panel packing, footprint, usable-fraction by mount type
    tariffs.py        248 LOC · Regional currencies and default rates (30+ countries)
    economics.py      248 LOC · CAPEX, savings, payback, ROI, LCOE, CO₂
    farm.py           237 LOC · Pumping hours, water pumped, irrigable area
    store.py          230 LOC · JSON-file persistence for saved estimates
    report.py         307 LOC · Plain-text professional report for hand-off
```

---

## 10. User Experience and Workflow

The consumer flow is a linear wizard with one decision point at the top: what
kind of user, and what goal. Every subsequent step adapts to those answers.

```
[1 Landing] → [2 Start: user type] → [3 Goal (install / existing / compare)]
    → [4 Location (search · GPS · pin)]
    → [5 Consumption (bill · kWh · equipment · skip)]
    → [6 Space available (value · L×W · polygon)]
    → [7 Panel technology (Mono/Poly/TOPCon/HJT/Bifacial/Thin-film)]
    → [8 Panel count / watts (known or recommend)]
    → [9 Advanced (detailed mode: tilt · azimuth · shading · inverter)]
    → [10 Money & tariff (regional default, editable)]
    → [11 Battery (optional)]
    → [12 Loading stages]
    → [13 Result dashboard]
    → [14 Report / Compare / Save]
```

### Wizard behaviour

- **Skippable everywhere.** Every technical question includes an "I don't know"
  branch. Skipping is honest, not free: the assumption filling the gap is recorded
  and the uncertainty band widens.
- **Draft persistence.** Answers are saved to `localStorage` as the user types
  (`lib/draft.ts`); a page refresh does not restart the interview.
- **Progressive disclosure.** Quick mode presents essentials only; Detailed mode
  reveals orientation, inverter, loss overrides and degradation.
- **Deterministic loading stages.** `LoadingStages` reflects real work:
  location resolution → weather → orientation search → final yield → balance →
  economics. Stages are never marked done before the backend reports them done.

---

## 11. Adaptive Questionnaire

The interview is **data, not code**. `backend/app/estimate/personas.py`
(1 256 lines) declares every question, its wording, its help text, a spoken
form for a future voice interface, and — where the answer is technical — an
explicit "I don't know" branch that names the assumption the platform will use
instead. The React components render whatever `GET /api/meta/interview` returns.

### Question kinds

`single_choice` · `multi_choice` · `number` · `currency` · `area` ·
`location` · `equipment_list` · `pump_list` · `boolean` · `text` · `info`

### Beginner mode vs Detailed mode

| | Quick Estimate | Detailed Analysis |
|---|---|---|
| Consumption | Monthly bill or kWh only | Above plus equipment / floor-area / pump list |
| Space | One number, one unit | Add L × W or polygon-on-map |
| Panel | Assumed technology, count derived | Choose technology, wattage, model, dimensions, Voc, Isc, Vmp, Imp |
| Orientation | Auto-searched | Manual tilt / azimuth entry |
| Losses | PVWatts default stack | Per-loss overrides |
| Inverter | DC/AC 1.2, η = 0.96 | Explicit AC capacity or DC/AC ratio, η override |
| Lifetime & degradation | 25 y, 0.5 %/y | Editable |

### Escape routes

- *I don't know — use the typical value*: engine substitutes market-typical
  default, records it in the ledger with `provenance="market_typical"`, widens
  the uncertainty band.
- *Help me estimate*: opens a sub-flow (equipment builder, L×W, etc.).
- *My installer said …*: pass-through numeric with `provenance="user_supplied"`.

Every figure in the result has a corresponding row in the assumption ledger; any
ledger row with `editable=True` can be changed via
`POST /api/estimate/{id}/update`, re-running the pipeline in about a second.

---

## 12. User-Type Logic

| User type | Interview inputs collected | Result cards emphasised |
|---|---|---|
| **home** | location · monthly bill or kWh · roof area · panel tech · battery · shading · tariff | Monthly savings · payback · offset % · CO₂ avoided |
| **farm** | location · farm loads · pump HP+head · required daily water · crop water mm/day · shed area | Daily pumping hours · water m³ · irrigable area · subsidy note |
| **shop** | location · business type · operating hours · bill or kWh · roof area · grid conn · tariff | Daytime self-consumption · offset % · payback |
| **commercial** | location · facility type · peak demand kW · connected load kW · operating hours · offset target % · grid conn · roof · tariff | Offset % · self-consumption · lifetime CO₂ · peak-demand caveat |
| **institution** | location · facility type · operating hours · monthly bill · roof area | Term-time balance · offset % · CO₂ equivalences |
| **exploring** | location only; everything else optional | Site potential (specific yield, capacity factor, best/worst month) |

User-type also selects the **hourly load archetype** used to compute
self-consumption in `estimate/balance.py`: a home load peaks in the evening,
a farm load peaks around midday, an institution follows a school-day rectangle,
a shop tracks operating hours.

---

## 13. Location System

The location step accepts three inputs interchangeably.

### Input methods

1. **Place search.** Typed query → `GET /api/meta/place_search?q=…` → Open-Meteo
   Geocoding (GeoNames source). Returns up to 10 candidates by population, each
   with country, admin1, timezone and elevation.
2. **GPS auto-locate.** Browser Geolocation API → reverse geocode via
   `GET /api/locations/reverse` (OpenStreetMap Nominatim). Coordinates are
   rounded before the reverse-geocode request.
3. **Map-pin drop / polygon draw.** Hand-rolled Web Mercator tile map
   (`components/estimate/map/TileMap.tsx`) supports a single pin and an optional
   polygon (for available area). Polygon area is computed client-side using the
   shoelace formula on projected coordinates.

### What happens after location is selected

1. Backend `resolve_location()` normalises coordinates to a `Location`.
2. Country code chooses currency and default tariff (recorded as
   `regional_default`, editable).
3. Engine fetches 3 years of ERA5 hourly weather at those coordinates — a
   single fetch reused for orientation search, reference yield and final yield.
4. All timestamps are converted UTC → local using the timezone from the
   geocoder; missing timezone → longitude-based solar-time offset (correct
   fallback for a solar calculation).

### Fallback behaviour

- Denied GPS permission → clean fallback to search + map.
- Unknown place-search query → 404 with three concrete remedies.
- Reverse-geocode failure → coordinate used verbatim with synthesised label.
- Missing timezone → longitude-derived offset applied silently.

### Map engine swap

Setting `NEXT_PUBLIC_MAP_ENGINE=leaflet` at build time swaps in a Leaflet-backed
adapter behind the same `MapPicker` interface. Leaflet is dynamically imported
so it is absent from every bundle unless selected.

---

## 14. Energy Consumption Model

Consumption is collected through one of four independent routes
(`backend/app/estimate/demand.py`). Each returns a `DemandEstimate` carrying
annual kWh, an hourly load profile (24 values), a confidence label and a
plain-language basis.

| Route | Inputs | Basis | Confidence |
|---|---|---|---|
| *bill* | Monthly bill, currency | Bill minus fixed monthly charge, divided by tariff | Medium |
| *units* | Monthly kWh | Direct | High |
| *equipment* | Appliance list (count · hours/day · optional watts override), pump list | Σ `W × count × hours × duty_cycle`; motors converted from HP with `WATTS_PER_HP = 745.7` and default motor efficiency 0.75 | Medium |
| *floor_area* | Floor area m² and occupants (optional) | User-type benchmark per m² × area; adjusted by occupants for homes | Low |

### Converting bill to kWh

```
monthly_kwh = max(0, (monthly_bill - fixed_monthly_charge) / rate_per_kwh)
annual_kwh  = monthly_kwh × 12
```

Both `rate_per_kwh` and `fixed_monthly_charge` come from the
country-and-user-type default in `tariffs.py` unless the user overrides them;
both are editable in the ledger, and updating either re-runs the pipeline.

### Hourly load archetypes

Six archetypes ship, one per user type, normalised so they can be scaled to
whichever annual figure the route returned. Archetypes are approximations; the
interface labels them as such and recommends interval-meter data as sharper.

### Equipment catalogue

`APPLIANCES` in `demand.py` covers lighting, comfort (fans, AC by ton), kitchen,
laundry, entertainment, computing, water-heating, refrigeration (with duty
cycle), farm loads and shop loads. Each item has typical wattage, default hours,
plain-hint string; each is user-editable; the catalogue is filtered by user
type.

---

## 15. Solar Panel System

Panel technology, wattage, count and dimensions are recorded in
`backend/app/estimate/assumptions.py` and used by both the sizing and the
physical chain.

### Supported panel technologies

| Key | Display name | Efficiency (typ.) | Temp. coeff. (Pmax) |
|---|---|---|---|
| `mono_perc` | Monocrystalline PERC (default) | ~20.5 % | −0.35 %/°C |
| `mono` | Monocrystalline (standard) | ~19.0 % | −0.40 %/°C |
| `poly` | Polycrystalline | ~17.0 % | −0.42 %/°C |
| `topcon` | TOPCon | ~22.0 % | −0.30 %/°C |
| `hjt` | Heterojunction (HJT) | ~22.5 % | −0.25 %/°C |
| `bifacial` | Bifacial (Mono-PERC front + bifacial rear) | ~20.5 % + rear-side gain | −0.34 %/°C |
| `thin_film` | Thin-film (CdTe / CIGS) | ~13.0 % | −0.25 %/°C |

### Parameters collected from the user

- Technology key (picks efficiency + temperature coefficient).
- Wattage (W) per panel.
- Panel count (integer, wins over any computed capacity).
- Model / manufacturer text (recorded verbatim; no catalogue).
- Length & width (m) — when supplied, used for footprint.
- Voc, Isc, Vmp, Imp — recorded in the spec card but not fed into the yield
  calculation (which is capacity-based).
- Tilt, azimuth, shading level (light/moderate/heavy/unknown), inverter
  efficiency, AC capacity or DC/AC ratio, degradation rate, lifetime.

### Which parameters actually influence prediction

Panel count and wattage (fixing DC capacity), technology's temperature
coefficient, system loss stack, inverter efficiency and AC cap (driving
clipping), tilt and azimuth (fed into HDKR), and albedo (default 0.20).

> **Bifacial** currently uses a Mono-PERC front-side model with a small
> rear-side yield adder; a full view-factor bifacial radiation model is
> *not verified in the current implementation* and is listed as future work.

---

## 16. Panel Quantity and System Capacity

The identity is intentionally exact:

```
DC capacity (kWp) = Number of panels × Rated power per panel (W) ÷ 1000
```

The **panel count wins** — a recommendation of 15.4 kWp becomes an array of 28
panels of 550 W = 15.40 kWp exactly. Every downstream figure is computed for the
array that will actually exist.

### Effects of panel count

- **DC capacity** — linear.
- **Annual generation** — approximately linear in capacity, less inverter
  clipping.
- **Roof area required** — count × panel area ÷ usable fraction (depends on
  mount type).
- **Inverter sizing** — AC defaults to `DC / 1.2`.
- **Clipping** — every hour with `DC · η_inv > AC cap` is clipped; fraction
  reported; warning at > 2 %.
- **Financial outputs** — CAPEX per kWp decreases mildly with size.

### Behaviour by goal

| Goal | Panel count | Sizer | Reported binding constraint |
|---|---|---|---|
| **existing** | User input, required | Bypassed | `existing_system` |
| **install**, count given | User input | Runs but user's count wins | `user_specified` |
| **install**, count blank | Derived and quantised | Runs | `demand` · `space` · `budget` |
| **compare** | Multiple counts/capacities in one call | Per scenario | Per row |

### Worked illustrative example

```
Panel:            550 W · Mono PERC (efficiency 20.5 %, temp-coef -0.35 %/°C)
Panel count:      28
DC capacity:      28 × 550 / 1000 = 15.40 kWp
Inverter AC cap:  15.40 / 1.2 = 12.83 kW (default DC/AC = 1.2)
Panel footprint:  28 × 2.68 m² ≈ 75 m²  (before usable fraction)
Buildable area:   75 / 0.7 ≈ 107 m²  (tilted rooftop; usable fraction 0.70)

At Hyderabad (17.4°N, 78.5°E), specific yield ≈ 1500 kWh/kWp/yr:
    Annual generation ≈ 15.40 × 1500 = 23 100 kWh
    Uncertainty band  ≈ ±10 %
```

---

## 17. Solar Energy Prediction Methodology

There are **two prediction paths**, answering different questions:

| | Fast path (consumer) | Forward path (console) |
|---|---|---|
| Question | Typical-year production? | Specific-hour irradiance tomorrow? |
| Approach | Deterministic physical chain over N years of ERA5. | Machine-learning model on features from ERA5. |
| Training | None. | scikit-learn, time-aware validation, calibrated intervals. |
| Range | Measured inter-annual variability + named assumption components. | Conformalised Quantile Regression (80 % nominal). |
| Latency | ~1 s cached, ~15 s for a new location. | 10–40 s. |

### Deterministic physical chain (used by both)

1. **Solar geometry** — NOAA Solar Calculator (Michalsky 1988; NOAA ESRL);
   ~0.01° accuracy over 1900–2100.
2. **Extraterrestrial irradiance** — solar constant 1 361 W/m² modulated by
   orbital eccentricity (±3.3 %).
3. **Clear-sky reference** — Haurwitz (1945), single parameter; forms the
   clear-sky index kt = GHI / GHI_cs.
4. **DHI/DNI decomposition** — Erbs et al. (1982) piecewise diffuse-fraction.
5. **Transposition to POA** — HDKR anisotropic sky model.
6. **Cell temperature** — Faiman (2008):
   `T_cell = T_air + POA / (u0 + u1·v_wind)`, u0 = 25 W/(m²·K), u1 = 6.84
   W/(m³·s·K).
7. **DC power** — PVWatts v5 (Dobos 2014):
   `P_dc = (POA/1000) · P_rated · [1 + γ(T_cell−25)] · (1−L)`.
8. **Inverter and clipping** — `P_ac = min(P_dc · η_inv, P_AC_cap)`.

### How the consumer path aggregates

1. Fetch 3 years of hourly ERA5 at coordinates (default; configurable).
2. Drop hours missing any required variable; **imputation is never used**.
3. Search tilt & azimuth against the same weather at 1 kWp.
4. Run the chain twice: at 1 kWp for specific yield (sizing), then at sized
   capacity to capture inverter clipping (which is not capacity-invariant).
5. Aggregate hourly AC power into (a) annual energy, (b) monthly means and
   inter-annual std, (c) mean diurnal profile, (d) per-month diurnal profiles.
6. Compute performance ratio, capacity factor, specific yield, mean POA/GHI,
   clipped fraction.

### What the fast path deliberately does NOT do

- No lagged target values (would inflate offline metrics without helping in
  deployment).
- No IQR truncation of the target — physical-range validation only.
- No imputation — incomplete hours are dropped and reported.

---

## 18. Mathematical Model — Formulas Used

### 18.1 System capacity

```
P_rated_kWp = N_panels × W_panel / 1000
```

### 18.2 Solar geometry (NOAA formulation)

```
JD  = seconds_since_epoch / 86400 + 2 440 587.5
JC  = (JD − 2 451 545) / 36 525
cos(z)  = sin(φ)·sin(δ) + cos(φ)·cos(δ)·cos(H)
z_app   = z − Δrefract(z)
```

### 18.3 Extraterrestrial normal irradiance

```
E_0n = 1361 · [1 + 0.033 · cos(2π · DOY / 365)]     W/m²
```

### 18.4 Clear-sky GHI (Haurwitz 1945)

```
GHI_cs = 1098 · cos(z_app) · exp(−0.059 / cos(z_app))    W/m²
```

### 18.5 Clear-sky index

```
k_t = clip(GHI / GHI_cs, 0, 1.5)
```

### 18.6 Erbs decomposition

With k_T = GHI / E_0h:

```
d_f = { 1 − 0.09·k_T                                          if k_T ≤ 0.22
      { 0.9511 − 0.1604·k_T + 4.388·k_T² − 16.638·k_T³ + 12.336·k_T⁴  if 0.22 < k_T ≤ 0.80
      { 0.165                                                if k_T > 0.80

DHI = GHI · d_f
DNI = (GHI − DHI) / cos(z_app)
```

### 18.7 Plane-of-array via HDKR

```
A_i  = DNI / E_0n
R_b  = cos(AOI) / cos(z_app)
f    = √(DNI·cos(z_app) / GHI)

POA = DNI · cos(AOI)                                          # beam
    + DHI · [ (1−A_i)·(1+cos β)/2 · (1 + f·sin³(β/2))         # sky diffuse
              + A_i · R_b ]
    + GHI · ρ · (1 − cos β)/2                                 # ground-reflected

cos(AOI) = cos(z)·cos(β) + sin(z)·sin(β)·cos(γ_s − γ)
```

### 18.8 Cell temperature (Faiman 2008)

```
T_cell = T_air + POA / (u_0 + u_1 · v_wind)
u_0 = 25 W/(m²·K)   ;   u_1 = 6.84 W/(m³·s·K)
```

### 18.9 DC power (PVWatts v5)

```
P_dc = (POA / 1000) · P_rated_kWp · [1 + γ · (T_cell − 25)] · (1 − L)
```

### 18.10 Losses (combined multiplicatively)

```
1 − L = Π (1 − L_i)     i ∈ {dust, shading, wiring, mismatch, availability, LID, …}
```

### 18.11 Inverter and clipping

```
P_ac_uncapped = P_dc · η_inv
P_ac          = min(P_ac_uncapped, P_AC_cap)
clipped_h     = 1[P_ac_uncapped > P_AC_cap]
```

### 18.12 Interval-labelling correction (empirical)

ERA5 hourly radiation is a preceding-hour average; solar position is
instantaneous. Sweeping candidate offsets over a year at Hyderabad established
the correction (`representative_times()`):

| Offset | Clear-sky exceedances | corr(GHI, clear-sky) |
|---|---|---|
| 0 min | 264 | 0.9372 |
| **−30 min** | **0** | **0.9490** |
| +30 min | 697 | 0.8998 |

Reproducible via `python scripts/calibrate_interval.py`.

### 18.13 Consumption from bill

```
E_month = max(0, (B_month − F) / r_kwh)
E_year  = 12 · E_month
```

### 18.14 Uncertainty combination (quadrature)

```
σ_total² = σ_weather² + σ_resource² + σ_model² + Σ_i σ_assumption_i²
lower    = P − z · σ_total
upper    = P + z · σ_total
```

`z = 1.2816` for a nominal 80 % central band.

### 18.15 Economics

```
CAPEX      = c_kWp(currency) · P_rated_kWp + c_batt · E_battery
Savings_y  = E_self_consumed_y · r_kwh_y + E_export_y · r_export_y − OM_y
E_gen_y    = E_gen_1 · (1 − d)^(y−1)                # degradation
r_kwh_y    = r_kwh_1 · (1 + esc)^(y−1)              # tariff escalation
Payback    ≈ CAPEX / mean(Savings_y over first years)
ROI (%)    = (Σ Savings_y − CAPEX) / CAPEX · 100
LCOE       = (CAPEX + Σ OM_y_discounted) / Σ E_gen_y_discounted
CO2_kg_y   = E_gen_y · EF_grid_country
```

### 18.16 Pump hydraulics (farm)

```
P_hydraulic = Q · H · g · ρ_water / 1000     (kW)
P_electrical = P_hydraulic / (η_pump · η_motor)
```

Q in m³/s, H in m, g = 9.81 m/s², η_pump = 0.55, η_motor = 0.75 (defaults).

---

## 19. Machine Learning Model (Analysis Console)

> **Scope:** ML applies only to the research console at `/advanced`. The consumer
> estimate does **not** use a trained model — it runs the physical chain over
> years of observed weather (see §17).

### Target

**Clear-sky index** kt = GHI / GHI_cs (per Hobbs & Joshi). Dividing out the
deterministic diurnal and seasonal signal means the model only has to learn
atmospheric attenuation. Predictions are converted back to W/m² for reporting.

### Input features

- **Meteorological** (ERA5): temperature, RH, dew point, surface pressure,
  wind speed and direction, cloud cover, precipitation.
- **Solar geometry** (closed-form): zenith, azimuth, angle of incidence, optical
  air mass, clear-sky GHI, extraterrestrial normal irradiance.
- **Cyclical time**: sin/cos of hour-of-day and day-of-year.
- **Weather regime label**: sunny / cloudy / other from cloud cover and kt.

**No lagged values of the target are used** — day-ahead deployment has no
access to recent observed irradiance. This holds for every target, including `pv_kwh`.

### Targets

| Target | Unit | What the model learns |
|---|---|---|
| `clear_sky_index` | dimensionless | The atmosphere's attenuation. The default: it removes the deterministic diurnal and seasonal signal before fitting. Reported back in W/m². |
| `ghi_wm2` | W/m² | Irradiance directly. |
| `pv_kwh` | kWh | Hourly AC energy for the declared array, end to end. |

`pv_kwh` closes the gap between what the model predicts and what a user asks for. Its
labels are produced by running the deterministic PV chain (Erbs → HDKR → Faiman →
PVWatts v5 → inverter) over the observed reanalysis weather for the declared system, and
the model is fitted to map weather and geometry straight onto that energy.

Three consequences are stated rather than smoothed over:

- **The labels are modelled, not metered.** No measured generation was available to fit
  against, so a `pv_kwh` figure inherits the chain's assumptions as well as the model's
  error. This is §10 limitation 2, and it is repeated in the model card and in the
  `/api/point-forecast` payload.
- **Metrics stay in kilowatt-hours.** The native unit is already the physical one, so
  nothing is converted back and no W/m² twin is manufactured for this target.
- **Baselines are persistence and climatology only.** No physics-chain baseline is offered:
  the labels come *from* that chain, so such a baseline would score near-zero error by
  construction — a tautology dressed as a reference.

Predictions are bounded after inference exactly as the irradiance path is: no negative
energy, nothing above the inverter's AC rating over one hour, and the number of clipped
predictions is reported.

### Preprocessing

- Night hours (zenith ≥ 87°) removed.
- Missing values dropped, never imputed.
- Outliers: physical-range validation only.
- Scaling: inside the pipeline (StandardScaler), refitted per fold.

### Model families (all scikit-learn)

Four estimators and one ensemble of exactly those four. The set was cut from ten: most of
the removed entries were second representatives of a family already present, and a ten-row
comparison table invites the reader to hunt for the best number rather than to ask whether
the method earns its complexity.

| Key | Family | Notes | Why it is kept |
|---|---|---|---|
| `random_forest` | Bagged trees | n_est=300, min_samples_leaf=2, max_features=sqrt | The method the project abstract names. |
| `hist_gradient_boosting` | Boosted (histogram) | lr=0.08, max_iter=300, l2=1.0 (stand-in for XGBoost) | The boosted-tree family the cited papers use ([P2], [P3]); fails differently from bagging. |
| `extra_trees` | Bagged trees | n=300, min_samples_leaf=2 | Randomised split thresholds decorrelate its errors from the forest's. |
| `ridge` | Linear (L2) | α=1 | The linear baseline the non-linear models must beat. |
| `ensemble_four` | Stacked ensemble | the four above → Ridge meta-learner, blocked chronological inner folds | Learned weights, and each base model's contribution is reported. |

Withdrawn: `gradient_boosting`, `knn`, `svr`, `linear`, `decision_tree`, `stacking`,
`voting`. They are listed under Future Work in `/api/meta/models` with the reason, rather
than disappearing silently.

**The ensemble blends, it does not average.** A Ridge meta-learner is fitted on the base
models' out-of-fold predictions, so a model gets weight where it is actually right. An
unweighted mean would let the linear model pull the tree models down on the non-linear
hours they exist to handle. The learned weights and each base model's own prediction travel
in the payload, so the blend is inspectable rather than asserted.

The inner folds are contiguous time blocks with an embargo rather than forward-only folds:
`StackingRegressor` collects its meta-features with `cross_val_predict`, which requires an
out-of-fold prediction for *every* training row, and a forward-only scheme cannot produce
one for its earliest block. The outer evaluation — the one every reported figure comes
from — remains strictly chronological.

### Validation

- Chronological hold-out with 24-hour embargo.
- Rolling-origin CV with the same embargo.
- Five-check leakage audit.
- Physical-bound post-processing (predictions clipped to `[0, 1.25 · GHI_cs]`).

### Prediction intervals

**Conformalised Quantile Regression** at nominal 80 %. On two years at
Hyderabad, plain QR measured 66.3 % empirical coverage; after conformal
calibration, 80.2 %, within 2 points across all three weather regimes.
Coverage is reported per regime as well as overall.

### Metrics

MAE, RMSE, MBE, R², rRMSE, rMAE, MAPE, sMAPE, forecast skill score; and
probabilistic: pinball loss, PICP, PINAW, CRPS. Two honesty notes carried in
the UI: NSE = R² (labelled aliased); MAPE always accompanied by its exclusion
count.

### Reproducibility manifest

Every run persists: dataset fingerprint (SHA-256), random seed, library
versions, platform string, preprocessing decisions. The comparison endpoint
refuses to rank runs that are not comparable.

---

## 20. Weather and Solar Data

### Primary source: Open-Meteo Historical Weather API

- **Provider:** Open-Meteo (CC-BY 4.0), sourcing ERA5 / ERA5-Land reanalysis
  (© ECMWF / Copernicus).
- **Endpoint:** `archive-api.open-meteo.com/v1/archive`.
- **Resolution:** hourly, from 2000 onward, global grid.
- **Auth:** none.
- **Cache:** every response cached to disk keyed by SHA-256(URL + params).

### Variables retrieved

| Internal | Provider variable | Purpose |
|---|---|---|
| `ghi_wm2` | shortwave_radiation | Physical chain input; also ML target. |
| `dni_wm2` | direct_normal_irradiance | Direct-normal, when supplied. |
| `dhi_wm2` | diffuse_radiation | Diffuse-horizontal, when supplied. |
| `temperature_c` | temperature_2m | Faiman input. |
| `relative_humidity_pct` | relative_humidity_2m | ML feature. |
| `dew_point_c` | dew_point_2m | ML feature. |
| `surface_pressure_hpa` | surface_pressure | ML feature. |
| `wind_speed_ms` | wind_speed_10m | Faiman input. |
| `wind_direction_deg` | wind_direction_10m | ML feature. |
| `cloud_cover_pct` | cloud_cover | ML feature; regime classifier. |
| `precipitation_mm` | precipitation | ML feature; quality flag. |

### Secondary sources

- Open-Meteo Geocoding (GeoNames, CC-BY 4.0) — place name + elevation.
- OpenStreetMap Nominatim — reverse geocoding.
- Open-Meteo Forecast API — short-horizon forecast for the console.

### Fallback and error handling

- Upstream 4xx/5xx → `DataSourceError` with a user-facing remedy string.
- Cache consulted before every fetch; valid entries served directly.
- Gaps survive as NaN; quality engine scores them; no imputation.

> **Reanalysis vs measurement:** ERA5 is a grid-cell average; it differs
> systematically from a pyranometer on the user's roof. Results are labelled as
> physically modelled from reanalysis; because no metered PV output was
> available, no validation against measured generation is claimed.

---

## 21. Data Flow

```
User Input → Frontend State → Client Validation
                                    ↓
                          POST /api/estimate
                                    ↓
                        Pydantic request schema
                                    ↓
                        Estimate engine.run()  ←→  External + cache
                              ↓                     (Open-Meteo, Nominatim)
                     Physical chain (Erbs · HDKR · Faiman · PVWatts)
                              ↓
                       Metrics + uncertainty
                              ↓
                       Assumption ledger
                              ↓
                       JSON response
                              ↓
              React ResultView / CompareView / etc.
```

### Transition notes

- **Wizard → draft:** each field change writes to `localStorage`.
- **Client validation:** field-level; rejection messages state what to type.
- **Pydantic schema:** strict types + custom validators; failures translated in
  `main.py` to human-readable field errors.
- **Cache:** the physical chain runs synchronously; the same DataFrame is reused
  for orientation search & final yield.
- **Ledger + response:** every ledger row is a claim about a number in the
  payload and is addressable by `key`; the frontend renders the ledger directly.

---

## 22. Results and Visualisation

The result page (`frontend/app/(site)/result/`, `components/result/ResultView.tsx`)
assembles the following cards, each of which is either a scalar-with-band, a
plot, or a table. Every card is optional.

| Card | Contents |
|---|---|
| Headline | Annual kWh ± range · confidence · location · system size · panel count |
| Monthly generation | 12-bar chart with per-month range whiskers reflecting each month's own spread |
| Daily profile | Mean diurnal shape (24 hours, local time) |
| Energy balance | Self-consumed · exported · imported · monthly stack (if demand supplied) |
| Solar offset | % of annual demand covered · self-consumption ratio |
| Battery | Recommended capacity · basis · dispatch profile (if requested) |
| Financials | CAPEX · monthly & annual savings · payback · ROI · LCOE (currency-aware) |
| Emissions | CO₂ avoided per year and lifetime · equivalences (cars, trees) |
| Farm capability | Daily pump-hours · water pumped m³ · irrigable ha (farm only) |
| System specification | Panel model card with all supplied electrical values |
| Uncertainty breakdown | Each component named with its % contribution; how to reduce |
| Assumption ledger | Every default and user value, editable in place |
| Warnings | Sizer notes, clipping warnings, subsidy caveats, completeness notes |
| Report | Download plain-text professional report |

### Charts

Every chart is a hand-rolled SVG (no charting library). Two files carry all of
it: `components/charts/core.tsx` (primitives) and
`components/result/charts.tsx` (consumer views). The console adds fourteen
views in `components/views/`: Overview, Performance, Uncertainty, Validation,
Explain, ModelLab, ModelCard, Report, Scenarios, Anomalies, DataQuality,
Forecast, Literature, Experiments.

---

## 23. Uncertainty and Limitations

### Uncertainty band construction

For the consumer estimate, uncertainty is assembled from four named components
in `estimate/uncertainty.py`:

1. **Weather variability** — measured std across years; usually the largest term
   and irreducible.
2. **Resource-data uncertainty** — ~5 % order-of-magnitude term for grid-cell vs
   rooftop pyranometer.
3. **Conversion-model uncertainty** — ~5 % term for the physical chain applied
   to correct inputs.
4. **Assumption components** — per-question terms that grow whenever the user
   could not answer.

Components combine in quadrature; resulting relative σ gives an 80 % central
band under a normal approximation (z = 1.2816).

### Confidence rating

Three levels: **high**, **medium**, **low**. Derived from data completeness,
number of complete calendar years, whether shading and orientation were
declared, and whether demand was provided. A low rating carries a plain-language
explanation and a list of reducible components with instructions.

### Console-side intervals

Conformalised Quantile Regression, calibrated on a hold-out slice. Empirical
coverage reported overall and per weather regime.

### Known limitations

1. Reanalysis, not measurement.
2. **No metered PV output was available.** All PV figures are physically
   modelled and not validated against measured generation.
3. Weather-forecast error not included in intervals.
4. Trained per location; no cross-location generalisation claimed.
5. Marginal, not conditional, conformal coverage.
6. Aerosol optical depth, sunshine duration and wind-direction standard
   deviation are named in source research but unavailable from this data source.
7. Bifacial modelling is simplified.
8. Hourly load archetypes are approximations.
9. Uncertainty components treated as independent (quadrature).
10. Financial modelling omits financing/interest, subsidies, demand charges,
    taxes.

---

## 24. Validation and Error Handling

### Frontend validation

- Field-level types & ranges (positive numbers, area unit sanity, coordinate
  bounds).
- Rejection messages state what to type instead.
- Never blocks progression on optional fields.
- Location step handles denied GPS gracefully.

### Backend validation

- Pydantic schemas in `schemas/estimate.py` and `schemas/models.py` validate
  every request.
- Pipeline pre-conditions raise `ValueError` with user-facing messages.
- Physical validation of `PVSystem` in `features/solar_geometry.py`.
- Data-quality engine detects eight distinct corruption modes.
- Console leakage audit reports the mechanism preventing each check.

### Error envelope

```json
{
  "error": "validation_error",
  "message": "location: Tell us where the system will be — search…",
  "remedy": "Correct the highlighted fields and resubmit.",
  "field_errors": [ { "field": "location", "message": "…", "type": "missing" } ]
}
```

Frontend renders `message`, `remedy` and any `field_errors` verbatim.

### Representative failure paths

| Failure | Behaviour |
|---|---|
| Upstream weather timeout | 502 with remedy; cached results still work. |
| Location query has no match | 404 with three concrete remedies. |
| Impossible input | 422 with domain message from `engine.run()`. |
| Rate limit exceeded | 429 with `Retry-After` header. |
| Unhandled internal exception | 500 with request ID; stack trace logged, not returned. |

---

## 25. Security

The platform runs against keyless upstream services and holds no user accounts.

- **No secrets required or stored.** Environment variables carry only
  configuration.
- **CORS scoped.** `SOLAR_CORS_ORIGINS` defines accepted origins.
- **Rate limiting.** Fixed-window per-client in-process limiter; README notes it
  is not a substitute for a gateway limiter.
- **Security headers on every response:** `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`.
- **Request ID stamping** on every response.
- **Structured error output** — stack traces never returned to the client.
- **Input validation** via Pydantic + custom validators.
- **Coordinate rounding** before reverse-geocoding.
- **Opaque estimate URLs.** No listing endpoint enumerating other users'
  estimates.
- **Retention sweep** at startup prunes old estimates past a configurable window.

### Not implemented (deliberately)

- No authentication or authorisation — there are no users.
- No third-party analytics or telemetry.
- No client-side secrets.

---

## 26. Performance and Responsiveness

### Backend

- Weather cache on disk; single fetch per estimate; vectorised NumPy chain.
- Latency: ~1 s cached, ~15 s for a new location, 10–40 s for full console
  analysis.
- `X-Response-Time-ms` header on every response; slow requests logged.

### Frontend

- No charting library — SVG adds ~0 kB of runtime deps.
- Dynamic Leaflet import — absent from bundles unless selected.
- Server components for the shell.
- Draft persistence in localStorage.

### Responsive rendering

Mobile-first Tailwind layout in the consumer surface. Charts scale with their
container. Touch targets sized to the recommended minimum (44 CSS px). Console
is laptop-and-up (dense tables).

---

## 27. Accessibility and Usability

- Responsive throughout, mobile-first.
- Readable typography (Inter + system fallbacks; 1.55 line-height).
- Semantic HTML (`<form>`, `<fieldset>`, `<legend>`, `<label>`).
- Keyboard support via native inputs, buttons, links.
- Skip-to-main link.
- Beginner-friendly wording; plain help text; escape route on every technical
  question.
- Progressive disclosure (Detailed mode).
- Tooltips on jargon at first use.
- Localisation scaffold (`i18n.ts`, `personas.py`); currency and units switch by
  country.

> **Not verified in the current implementation:** a formal WCAG 2.1 AA audit has
> not been performed on this build. Contrast tokens meet the criterion, but
> assistive-technology testing (screen readers, high-contrast mode,
> forced-colours mode) has not been recorded as a passing test.

---

## 28. Testing

### Backend (pytest)

Approximately 223+ tests across five modules:

| File | Approx. count | Coverage |
|---|---|---|
| `test_solar_geometry.py` | ~35 | NOAA solar position vs known astronomical values; Erbs; HDKR; Faiman; PVWatts DC; clipping. |
| `test_evaluation.py` | ~31 | Metrics, splitters, baselines, leakage detection. |
| `test_quality_and_features.py` | ~24 | Eight corruption types, feature-pipeline leakage guards, day-mask behaviour, interval-offset correction. |
| `test_api.py` | ~22 | Endpoint contracts, error envelopes, rate-limit shape, request validation. |
| `test_estimate.py` | ~125 (nested) | Consumer domain: energy ledger balance, losses combined multiplicatively (not additively), battery does not return more than it stored, bill-to-kWh removes fixed charge, currency symbol matches figure currency, orientation search picks a defensible pair, panel-count wins over sizer target. |
| `test_models.py` | ~37 | The registry holds exactly five entries and each withdrawn key stays withdrawn; the ensemble's weights are learned rather than uniform; its inner folds partition the training rows; the `pv_kwh` target reports kilowatt-hours on both sides with no W/m² twin, gets persistence and climatology only, and still passes the five-check leakage audit; the irradiance path is byte-for-byte the same shape it was. |
| `test_point_forecast.py` | ~23 | The requested hour is read in the location's time zone and changes the answer; training ends strictly before the target hour; a night hour returns zero and says why; the four base models are reported beside the ensemble; an uncovered date is refused with the available window named; a repeat question reuses the trained model. |

### Frontend (Vitest)

- Web-Mercator projection round-trip.
- Polygon-area calculation (shoelace on projected coordinates).
- Draft-to-request mapping preserves user intent.
- Component promises: rejected field says what to type instead; every technical
  question can be declined; denied location permission offers a way forward;
  loading stage never shown as finished before it is.
- Prediction page: the chosen hour reaches the server rather than only the chosen
  date, a different hour produces a different request, all four base models and
  their learned weights stay on the page beside the ensemble, and the
  "modelled, not metered" and no-future-data statements survive.

### What is not automated

> **Not verified in the current implementation:** end-to-end Playwright/Cypress
> tests are not part of the suite; visual regression testing is not part of
> the suite; formal accessibility conformance testing is not automated. These
> are listed as future work.

### Running

```bash
cd backend
python -m pytest

cd frontend
npm run typecheck && npm test && npm run build
```

---

## 29. Deployment

### Local development

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

cd frontend
npm install
npm run dev
```

### Production

Backend:
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Frontend:
```bash
npm run build
npm start
```

### Real-deployment notes

- In-process rate limiter is per-worker — expect a gateway limiter in front.
- Analysis cache and experiment store are per-process, on local disk;
  multi-node needs shared storage.
- Set `SOLAR_CORS_ORIGINS` to the deployed frontend origin.
- Training is CPU-bound and synchronous; move to a task queue for high
  concurrency.

### External services required at runtime

- Open-Meteo Archive API (keyless)
- Open-Meteo Geocoding API (keyless)
- OpenStreetMap Nominatim (keyless; mind their usage policy in production)
- Open-Meteo Forecast API (keyless)

### Environment variables (selected)

| Variable | Default | Purpose |
|---|---|---|
| `SOLAR_ARCHIVE_URL` | archive-api.open-meteo.com/v1/archive | Historical weather endpoint. |
| `SOLAR_FORECAST_URL` | api.open-meteo.com/v1/forecast | Forecast endpoint. |
| `SOLAR_CACHE_DIR` | `backend/var/cache` | Disk cache directory. |
| `SOLAR_CACHE_TTL` | configured | Cache lifetime in seconds. |
| `SOLAR_CORS_ORIGINS` | localhost | Allowed frontend origins. |
| `SOLAR_RATE_LIMIT_REQUESTS` | configured | Max requests per window. |
| `SOLAR_RATE_LIMIT_WINDOW_S` | configured | Rate-limit window (s). |
| `SOLAR_STORE_ESTIMATE_RETENTION_DAYS` | configured | Prune saved estimates past this. |
| `NEXT_PUBLIC_API_BASE` | http://127.0.0.1:8000 | Frontend → backend base URL. |
| `NEXT_PUBLIC_MAP_ENGINE` | (built-in) | Set `leaflet` to swap. |

---

## 30. Installation and Running

1. **Prerequisites.** Python 3.11+ and Node.js 20+.
2. **Enter the project.** `cd C:\Projects_AI\college_project`
3. **Install backend deps.**
   ```bash
   cd backend
   python -m pip install -r requirements.txt
   ```
4. **Install frontend deps.**
   ```bash
   cd ..\frontend
   npm install
   ```
5. **Configure environment (usually not needed).** `frontend/.env.local` ships
   with the repository. If missing:
   ```bash
   copy .env.example .env.local        # Windows
   cp   .env.example .env.local        # macOS / Linux
   ```
   No secrets are required.
6. **Start the backend.**
   ```bash
   cd ..\backend
   python -m uvicorn app.main:app --reload --port 8000
   ```
   Docs: `http://localhost:8000/api/docs`
7. **Start the frontend.**
   ```bash
   cd ..\frontend
   npm run dev
   ```
   App: `http://localhost:3000`
8. **Run tests.**
   ```bash
   cd ..\backend
   python -m pytest
   cd ..\frontend
   npm run typecheck && npm test && npm run build
   ```

---

## 31. Future Improvements

Labelled as **future work** unless noted. Not existing functionality.

### Product

- Additional languages (Telugu, Tamil, Hindi) via existing i18n scaffold.
- Voice-driven interview using the spoken-form synonyms already declared.
- Interval-meter CSV upload as a first-class consumption route.
- Multi-tariff support (time-of-use, tiered, seasonal).
- Native Marion / view-factor bifacial radiation model.
- Real-time monitoring integration (Enphase, SolarEdge, IoT inverter API).
- Satellite-imagery-based shading analysis for a dropped map polygon.

### Data

- Fetch aerosol optical depth, sunshine duration, wind-direction variability.
- Ground-truth validation against a pyranometer network for at least one region.

### Modelling

- **LSTM / BiLSTM / BiGRU sequence models** (per Hayajneh et al. [P6]).
- **Full copula-based dynamic feature selection** (per Lyu & Eftekharnejad [P3]).
- **TinyML edge deployment** (per Hayajneh et al. [P6]).
- **pvlib / Perez-Driesse transposition** (per Hobbs & Joshi [P1]).
- Conditional (rather than marginal) conformal coverage; horizon-aware intervals.
- Cross-location generalisation and transfer learning.

### Financial & battery

- Financing / interest / tax treatment.
- Country-specific rebate and subsidy schemes with expiry handling.
- Battery aging (calendar + cycle) with round-trip degradation.
- Time-of-use arbitrage optimisation for battery dispatch.

---

## 32. Conclusion

Helios pairs a rigorous physical solar model with a genuinely usable consumer
surface, without diluting either. It answers the practical question a homeowner,
farmer, business or facility manager actually has — how much energy will this
generate, what does it save, and how confident can I be — using the actual
weather record at the supplied coordinates rather than a national average, and
returns the answer with an honest uncertainty band built from measured
components. It also carries a full research console: ten scikit-learn model
families, time-aware validation with a leakage audit, conformal prediction
intervals, and reproducible experiment records.

The technical significance is not any single algorithm — the physical chain is
textbook and the estimators are scikit-learn. It is that **every number can be
traced back to an input**, **every default is on the table**, and **nothing
modelled is presented as measured**. Those constraints produced the specific
architectural choices documented above — the assumption ledger, the ban on
target-lag features, the panel-count-wins rule, the empirically determined
interval offset, the conformal calibration of prediction intervals, and the
comparison endpoint that refuses to rank incomparable runs.

Practically, the platform runs on a laptop with no API keys, produces an answer
in a few seconds, and ships with 270+ automated tests, an ASGI-ready backend
and a Next.js frontend that can be deployed behind any reverse proxy.

---

## 33. Glossary

| Term | Meaning |
|---|---|
| PV | Photovoltaic — direct conversion of sunlight to electricity. |
| kW / kWh | Kilowatt (instantaneous power) / kilowatt-hour (integral energy). |
| kWp | Kilowatt-peak — DC rating at standard test conditions. |
| DC / AC | Direct current (panels) / alternating current (grid). |
| DC/AC ratio | Ratio of installed DC to inverter AC. Values > 1 trade a small amount of clipping for better winter/morning performance. |
| GHI | Global Horizontal Irradiance — total flux on a horizontal surface (W/m²). |
| DNI | Direct Normal Irradiance — beam flux on a surface normal to the sun. |
| DHI | Diffuse Horizontal Irradiance — sky-scattered flux on a horizontal surface. |
| POA | Plane-of-Array irradiance — total flux reaching the tilted panel plane. |
| AOI | Angle of Incidence — angle between the sunbeam and the panel normal. |
| Pmax | Panel maximum-power-point rating in watts. |
| Voc, Isc | Open-circuit voltage, short-circuit current at STC. |
| Vmp, Imp | Voltage / current at maximum power point at STC. |
| PR | Performance Ratio — actual AC energy / (POA · capacity). |
| Capacity factor | Annual energy / (rated capacity · 8760). |
| Specific yield | Annual kWh per kWp. |
| Clear-sky index (kt) | GHI / clear-sky GHI; the ML target. |
| Bifacial | Panel producing from both faces; rear-side gain depends on albedo. |
| TOPCon / HJT | Advanced silicon cell architectures. |
| Degradation | Annual reduction in output as panels age (default 0.5 %/y). |
| LCOE | Levelised Cost of Energy. |
| PICP / PINAW / CRPS | Prediction Interval Coverage Probability / Normalised Average Width / Continuous Ranked Probability Score. |
| Conformal prediction | Distribution-free interval calibration; finite-sample marginal-coverage guarantees. |
| Reanalysis (ERA5) | Retrospective global weather record from assimilation into a physical model. |

---

## 34. References

### Papers cited by the platform

- **[P1]** Hobbs, W. & Joshi, S. — Hour-ahead solar irradiance forecasting.
  Source of clear-sky-index target, Erbs, and Faiman.
- **[P2]** Mabodi, T. & Hammujuddy, Y. — ML models for monthly GHI. Source of KNN
  and RF hyperparameter defaults.
- **[P3]** Lyu, C. & Eftekharnejad, S. — Copula-based feature selection for
  solar-power forecasting. Source of 87° day-mask and regime conditioning.
- **[P4]** Rosales Huamani, J. et al. — Stacked-ensemble regression for solar
  irradiance. Source of stacking-ensemble combination.
- **[P5]** Vijay Babu, R. et al. — Feature importance for solar-power forecasting.
  Source of Gradient Boosting hyperparameters and AOI permutation-importance.
- **[P6]** Hayajneh, A. et al. — LSTM-based short-term irradiance forecasting on
  ESP32. Listed as future work.

### Standards, methods and data sources

- Dobos, A. P. (2014). *PVWatts Version 5 Manual.* NREL/TP-6A20-62641.
- Faiman, D. (2008). *Assessing outdoor operating temperature of PV modules.*
  Progress in Photovoltaics.
- Erbs, D. G., Klein, S. A. & Duffie, J. A. (1982). *Estimation of the diffuse
  radiation fraction.* Solar Energy.
- Haurwitz, B. (1945). *Insolation in relation to cloudiness and cloud density.*
- Michalsky, J. J. (1988). *NOAA Solar Calculator formulation.* Solar Energy.
- Kopp, G. & Lean, J. L. (2011). *A new, lower value of total solar irradiance.*
  Geophysical Research Letters.
- Hersbach, H. et al. (2020). *The ERA5 global reanalysis.* Q. J. R. Meteorol. Soc.

### Services and libraries

- Open-Meteo Historical Weather API — open-meteo.com (CC-BY 4.0).
- Open-Meteo Geocoding — GeoNames (CC-BY 4.0).
- OpenStreetMap Nominatim — ODbL / usage policy.
- FastAPI — fastapi.tiangolo.com.
- Next.js — nextjs.org.
- scikit-learn — Pedregosa et al., JMLR 2011.
- Pandas — McKinney, W., PyData 2010.
- NumPy — Harris, C. R. et al., Nature 2020.

---

## 35. Appendix — API and Configuration

### Consumer estimate endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/meta/interview` | The interview as data. |
| GET | `/api/meta/place_search?q=` | Place-name search. |
| GET | `/api/locations/reverse?latitude=&longitude=` | Reverse-geocode. |
| POST | `/api/estimate` | Create an estimate (optionally save). |
| GET | `/api/estimate/{id}` | Read a saved estimate. |
| POST | `/api/estimate/{id}/update` | Edit assumptions and re-run. |
| POST | `/api/estimate/{id}/rename` | Rename a saved estimate. |
| DELETE | `/api/estimate/{id}` | Delete a saved estimate. |
| GET | `/api/estimates?limit=` | Recent estimates on this server. |
| GET | `/api/estimate/{id}/report` | Plain-text professional report. |
| POST | `/api/estimate/compare` | Run multiple scenarios in one call. |

### Analysis-console endpoints (research surface)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/analysis` | Create an analysis (`target`: `clear_sky_index`, `ghi_wm2` or `pv_kwh`). |
| GET | `/api/analysis/{id}` | Summary. |
| GET | `/api/analysis/{id}/quality` | Data-quality report. |
| GET | `/api/analysis/{id}/predictions` | Actual-vs-predicted. |
| GET | `/api/analysis/{id}/performance` | Metrics, folds, baselines, intervals. |
| GET | `/api/analysis/{id}/explain` | Permutation importance, PDP. |
| GET | `/api/analysis/{id}/anomalies` | Physical/residual/ramp/drift detectors. |
| POST | `/api/analysis/{id}/forecast` | Short-horizon forecast. |
| POST | `/api/analysis/{id}/scenarios` | Counterfactual with pathway decomposition. |
| GET | `/api/analysis/{id}/report` | Markdown research report. |
| POST | `/api/point-forecast` | Energy for one hour at one place on one date. Trains on data ending strictly before the target hour with `target="pv_kwh"`, and returns the hour's kWh, the day's total, the three driving weather parameters, operating conditions, a prediction interval and — for `ensemble_four` — each base model's own prediction with its learned weight. |
| GET | `/api/experiments` | List persisted experiments. |
| POST | `/api/experiments/compare` | Compare comparable experiments. |

### Sample estimate request (abridged)

```json
{
  "user_type": "farm",
  "mode": "quick",
  "goal": "install",
  "location": { "query": "Warangal, India" },
  "consumption_method": "equipment",
  "equipment": [
    { "key": "led_light",   "count": 20, "hours_per_day": 5 },
    { "key": "ceiling_fan", "count":  8, "hours_per_day": 8 }
  ],
  "pumps": [
    { "horsepower": 5, "head_metres": 22, "hours_per_day": 6 }
  ],
  "area":   { "value": 800, "unit": "sqm" },
  "system": { "panel_key": "mono_perc" },
  "farm":   { "pump_horsepower": 5, "pump_head_metres": 22 },
  "save":   true,
  "label":  "Warangal 5HP pump"
}
```

### Sample response shape (abridged)

```json
{
  "estimate_id": "e_9x7…",
  "saved": true,
  "location": { "label": "Warangal, Telangana, India", "latitude": 17.98, "longitude": 79.6 },
  "currency": { "code": "INR", "symbol": "₹" },
  "system": {
    "capacity_kwp": 6.60,
    "panels": { "count": 12, "watts": 550 },
    "orientation": { "tilt_deg": 22.3, "azimuth_deg": 180, "method": "searched" },
    "inverter": { "ac_capacity_kw": 5.5, "severity": "info" },
    "sizing": { "binding_constraint": "demand" }
  },
  "generation": {
    "annual_kwh": 10230,
    "monthly_kwh": [ /* 12 values */ ],
    "monthly_ranges": [ /* 12 (low, high) pairs */ ],
    "daily_profile_kwh": [ /* 24 values */ ],
    "specific_yield_kwh_per_kwp": 1550,
    "capacity_factor": 0.177,
    "clipped_fraction": 0.006
  },
  "balance":     { "self_consumption_pct": 63, "solar_offset_pct": 78 },
  "economics":   { "total_capex": 396000, "payback_years": 6.3, "roi_pct": 214, "lcoe_per_kwh": 3.1 },
  "emissions":   { "co2_avoided_tonnes_per_year": 7.4 },
  "uncertainty": { "expected": 10230, "lower": 9200, "upper": 11300, "confidence": "medium" },
  "farm":        { "daily_pump_hours_typical": 5.8, "daily_water_m3": 218, "irrigable_ha": 1.4 },
  "assumptions": [ /* ledger rows */ ],
  "warnings":    []
}
```

### Configuration reference

See `backend/app/config.py` for the full dataclass structure. All settings are
environment-variable driven with safe defaults; nothing here is secret.

---

*End of document. Solar Energy Prediction and Analysis Platform, project
documentation, compiled 2026-08-21.*
