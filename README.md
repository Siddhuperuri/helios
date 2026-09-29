# Helios — Solar Energy Intelligence Platform

Two surfaces over one engine.

**A solar calculator** for anyone deciding whether to install: *how much can I generate
here, what will it save me, and should I believe the number?* Answered in about two
minutes, in plain language, with an honest range and every assumption on the table.

**An analysis console** for the people who need to check it: hourly irradiance forecasting
with time-aware validation, calibrated prediction intervals, and results that can be traced
back to the data and code that produced them.

**[`docs/DELIVERY.md`](docs/DELIVERY.md)** is the delivery report: what changed, what was
kept, how the prediction is calculated, the assumptions, the limitations, and how to run and
deploy it.

**[`docs/PRODUCTION_ARCHITECTURE.md`](docs/PRODUCTION_ARCHITECTURE.md)** covers the second
phase of the work: optional accounts, and the move from a single process to a horizontally
scaled fleet. The solar engine is unchanged by it — the physical chain was already a set of
pure functions, so it never had an opinion about where a result was stored or who it
belonged to. Alongside it:
[`DEPLOYMENT.md`](docs/DEPLOYMENT.md),
[`SECURITY.md`](docs/SECURITY.md),
[`BACKUP_AND_RECOVERY.md`](docs/BACKUP_AND_RECOVERY.md),
[`LOAD_TESTING.md`](docs/LOAD_TESTING.md).

The research work is documented against its sources in
[`docs/RESEARCH_SYNTHESIS.md`](docs/RESEARCH_SYNTHESIS.md), and the platform's own
Literature view renders that map at runtime. The consumer layer's audit and design
rationale are in
[`docs/PRODUCT_TRANSFORMATION_AUDIT.md`](docs/PRODUCT_TRANSFORMATION_AUDIT.md).

---

## 0. The product

> **Tell us what you have. We'll figure out the solar.**

A farmer answers what they can — where the land is, what the pump is rated at, roughly how
long it runs — and gets back how many hours that pump can run on solar, how much water that
moves, and what it costs. A commercial site manager enters a bill and a roof area and gets
generation, offset, payback and a report to hand upward. Neither is asked what a
kilowatt-peak is.

Three rules hold across the consumer surface:

1. **Every question can be declined.** Anything technical carries an explicit *I don't
   know*, which states what the platform will assume instead — and widens the uncertainty
   band to match. Skipping is honest, not free.
2. **Every number traces to an assumption**, recorded as the calculation runs and rendered
   from that record. Change the tariff and every figure moves.
3. **Nothing modelled is presented as measured.** The range around a figure is built from
   the weather that actually occurred at those coordinates, not a round plus-or-minus ten
   per cent.

**An account is optional and always will be.** The calculator does not ask who you are, and
an estimate produced without one keeps working — it gets its own unguessable link, exactly
as before accounts existed. What an account adds is one thing: your estimates follow you
between devices instead of living in a link you have to keep. The prompt to create one
appears *after* an estimate has been produced, never in front of it.

---

## 1. Problem

Solar generation is weather-dependent and therefore uncertain, which makes it hard to
schedule maintenance, size a system, or balance a grid. A forecast is only useful if three
things are true at once: it is genuinely predictive of the future rather than interpolating
the past, it states how uncertain it is, and its accuracy has actually been measured.

The reference application this project supersedes met none of the three. Its date and time
controls did not affect the output at all — the same figure was returned for 06:51 and
13:51 — and it reported 16.79 kWh alongside a stated irradiance of 0 %, which is physically
impossible. Full audit, with the controlled experiments that established it, is in
[`docs/REFERENCE_AUDIT.md`](docs/REFERENCE_AUDIT.md).

## 2. Research motivation

The corpus splits on what to predict: four papers target irradiance in W/m², two target PV
power. This platform reconciles them by predicting **global horizontal irradiance** — the
quantity that is actually measured and is location-independent in meaning — and deriving PV
energy from it through an explicit physical chain with a user-declared array.

Three findings drove the core design:

- **Hobbs & Joshi** form a *clear-sky index* (observed ÷ clear-sky irradiance) before
  forecasting. This platform adopts that as the modelling target: the deterministic
  diurnal and seasonal signal is divided out, so the model only has to learn atmospheric
  attenuation, which is the genuinely uncertain part.
- **Vijay Babu et al.** found solar-geometry features (angle of incidence, azimuth, zenith)
  carried the highest permutation importance of any variable. Those are computed in closed
  form here, never learned.
- **Vijay Babu et al.** also state plainly that time-based splits are future work:
  *"the current validation was performed using random sampling, future work will involve
  testing generalization using time-based … data splits."* This platform implements that
  and measures the difference on the user's own data.

## 3. Architecture

```
backend/                 FastAPI + scikit-learn
  app/
    estimate/            consumer domain: demand, sizing, storage, economics, uncertainty
    features/            solar geometry, clear-sky, PV chain, feature pipeline
    data/                Open-Meteo ingestion, caching, geocoding
    quality/             transparent data-quality scoring
    models/              model registry, trainer, uncertainty, forecast service
    evaluation/          metrics, time-aware splitters, baselines, leakage experiment
    explain/             permutation importance, partial dependence
    anomaly/             physical, residual, ramp and drift detectors
    scenario/            counterfactual engine with causal pathway decomposition
    experiments/         run persistence and comparison
    reports/             Markdown report generation
    api/                 routes and analysis orchestration
    auth/                accounts, sessions, Google and GitHub sign-in
    security/            Argon2id hashing, JWT and refresh tokens, rate limiting, CSRF
    db/                  SQLAlchemy models, engine, session-per-request
    infra/               Redis client and the shared upstream-response cache
    email/               provider abstraction: SES / SendGrid / Postmark / Resend
    observability/       JSON logging, Prometheus metrics, tracing, error reporting
  alembic/               database migrations
  scripts/               calibrate_interval.py, seed.py
  tests/                 388 tests

frontend/                Next.js 15 + React 19 + TypeScript + Tailwind
  app/(site)/            consumer surface: landing, interview, results, dashboard
  app/advanced/          the analysis console
  components/estimate/   interview, location, map (hand-rolled tiles + Leaflet adapter)
  components/result/     result dashboard and charts
  components/charts/     custom SVG charts for the console (no charting library)
  components/views/      14 analysis views
  app/(auth)/            sign in, register, password reset, email confirmation
  app/account/           account settings and connected providers
  lib/                   typed API clients, session client, i18n scaffold, drafts
  tests/                 70 tests

deploy/                  Nginx and PgBouncer configuration
loadtest/                consumer and analysis-console load profiles
docs/                    delivery report, research synthesis, audits, production architecture
```

The split exists because the ML must be Python and the interface quality bar requires a
real frontend framework. They communicate over a typed JSON API.

### The two surfaces

| | Consumer calculator | Analysis console |
|---|---|---|
| Route | `/` | `/advanced` |
| Reader | Farmer, homeowner, business, installer | Researcher, engineer |
| Question | "What will this save me?" | "What is the rolling-origin RMSE?" |
| Path | Physics over cached climatology, no training | Full train, validate, calibrate |
| Latency | ~1 s cached, ~15 s for a new location | 10-40 s |
| Theme | Light, mobile-first | Dark instrument palette |

Neither was diluted for the other. The console kept all fourteen views; it simply moved off
the front door, because the person asking what solar will save them and the person auditing
a prediction interval are not the same person.

### Why the fast path does not train a model

A consumer asks what a system will produce *in a typical year*. That is a climatology
question, and the honest answer is the published physical chain run over years of observed
weather — which is what `app/estimate/climatology.py` does, in about a second against
cached data. A model trained to forecast hour-ahead irradiance would spend thirty seconds
saying the same thing about an annual average.

Machine learning earns its place on the forward-looking path, where predicting a specific
future day is the actual task. That is the hybrid the brief asks for, and it is what the
platform already did internally — the consumer layer exposes it rather than inventing it.

### The consumer domain

`app/estimate/` composes the existing physics rather than replacing any of it:

| Module | Responsibility |
|---|---|
| `assumptions.py` | Every default, with provenance. The assumptions and data-source panels render from this rather than from a list retyped in the frontend. |
| `climatology.py` | The fast path: the physical chain over years of hourly weather, aggregated to a typical year. Inter-annual variability is measured here. |
| `demand.py` | Consumption from a bill, from metered units, or built up from equipment. Hourly load archetypes. |
| `sizing.py` | Area to capacity, and an empirical orientation search against the location's own weather. |
| `balance.py` | Hourly self-consumption, export and import; battery dispatch and sizing. |
| `economics.py` | Capex, savings, payback, ROI, LCOE, lifetime yield with degradation, emissions. |
| `uncertainty.py` | The range and the confidence rating, assembled from named components. |
| `farm.py` | Pumping hours, water volume and irrigable area — gated on having the inputs. |
| `personas.py` | The interview itself, as data. |
| `report.py`, `store.py`, `engine.py` | Shareable report, durable storage, orchestration. |

## 4. Dataset

**Open-Meteo Historical Weather API** (ERA5 / ERA5-Land reanalysis), keyless and public.
Hourly, global, from 2000 onward. Provides GHI, DNI, DHI, air temperature, relative
humidity, dew point, surface pressure, wind speed and direction, cloud cover and
precipitation.

> **This is reanalysis, not ground-station pyranometer measurement.** Grid-cell averages
> differ systematically from point observations. Results here are therefore *not* directly
> comparable to studies using measured irradiance, and the platform does not present them
> as such.

Place search and elevation come from the Open-Meteo Geocoding API (GeoNames, CC-BY 4.0);
reverse geocoding, which turns a GPS fix or a dropped map pin back into a place name, comes
from OpenStreetMap Nominatim. Coordinates are rounded before that request, which improves
the cache hit rate and sends a third party less precision about where the user is standing.

Licensing: Open-Meteo data under CC-BY 4.0; ERA5 © ECMWF / Copernicus. Attribution appears
in the application footer and in every exported report.

### An empirically determined detail

Irradiance in the archive is an *interval average*, but solar position is *instantaneous*.
Evaluating position at the interval label rather than its midpoint introduces a half-hour
phase error. Rather than assume the convention, it was measured — sweeping candidate
offsets over a full year:

| offset | clear-sky exceedances | corr(GHI, clear-sky) |
|---|---|---|
| 0 min | 264 | 0.9372 |
| **−30 min** | **0** | **0.9490** |
| +30 min | 697 | 0.8998 |

Reproduce with `python scripts/calibrate_interval.py`. Applying the correction raised the
data-quality score from 97.7 % to 99.9 %.

## 5. Features

Meteorological inputs plus deterministic solar geometry (zenith, azimuth, angle of
incidence, optical air mass, clear-sky GHI, extraterrestrial irradiance) and cyclical time
encodings.

**No lagged values of the target are used.** This is deliberate. At a day-ahead issue time
the recent observed irradiance does not exist, so an autoregressive feature would improve
every offline metric while being unavailable in deployment. It is the most common way solar
forecasting results are quietly inflated. Persistence baselines *do* use past observations —
that is what makes them baselines — and are held to the same horizon accounting.

## 6. Methodology

| Stage | Choice | Rationale |
|---|---|---|
| Night exclusion | zenith ≥ 87° removed | Follows Lyu & Eftekharnejad. Predicting zero after dark is trivial and inflates R². |
| Missing values | dropped, never imputed | A fabricated value must not propagate into a reported metric. |
| Outliers | physical-range validation only | No statistical truncation of the target — see §10. |
| Scaling | inside the model pipeline | Refitted per fold, so test statistics never leak into training. |
| Target | clear-sky index | Removes the deterministic signal; results reported back in W/m². `ghi_wm2` and `pv_kwh` are also available — see §7a. |
| Split | chronological + 24 h embargo | Mirrors deployment; the embargo stops adjacent hours sharing weather across the boundary. |

## 7. Models

**XGBoost is the project's model** (§7b). It is trained on measured plant output and serves the
web interface by default. The five entries below are comparison baselines, scored on the same
held-out data. Four estimators, plus one ensemble of exactly those four. Every entry appears in at least
one supplied paper, and where a paper reports tuned hyperparameters those exact values are
used and attributed.

| Key | Family | Why it is in the set |
|---|---|---|
| `xgboost_plants` | Boosted trees, regularised | **The project model.** Trained offline on measured output from two plants, fed panel temperature from the NOCT model. Chosen for built-in regularisation and use in the solar forecasting literature ([P2], [P3]). |
| `random_forest` | Bagged trees | The method the project abstract names. |
| `hist_gradient_boosting` | Boosted trees | The boosted-tree family the cited papers use ([P2], [P3] run XGBoost). Boosting and bagging fail differently, so one of each is informative rather than redundant. |
| `extra_trees` | Bagged trees | Randomised split thresholds decorrelate its errors from the forest's — which is exactly what makes it worth something to an ensemble. |
| `ridge` | Linear | The linear baseline, kept so the non-linear models have to prove they earn their complexity. |
| `ensemble_four` | Stacked ensemble | The four above, blended by a Ridge meta-learner on out-of-fold predictions. **Learned weights, not a simple average** — an unweighted mean would let Ridge drag the tree models down on the non-linear hours they exist to handle. Each base model's own prediction and its weight are reported, so the blend is inspectable. |

The set was cut from ten. Gradient Boosting, k-NN, SVR, OLS, Decision Tree and the previous
Stacking and Voting entries were withdrawn: each duplicated an argument a kept model already
makes, and a ten-row comparison table invites reading off the winner rather than asking
whether the complexity was necessary. They are listed with their reason under Future Work in
`/api/meta/models` rather than disappearing silently.

Deliberately **not** implemented, and declared as such in the UI: LSTM/BiGRU sequence models
(this platform forecasts from exogenous weather, where recurrent structure has nothing to
consume), full copula-based dynamic feature selection (regime conditioning *is* implemented),
and TinyML edge deployment.

## 7a. Targets, and predicting kWh end to end

Three modelling targets are available on every analysis, and the choice is additive: the
irradiance paths behave exactly as they always did.

| Target | Unit | What the model learns |
|---|---|---|
| `clear_sky_index` | dimensionless | The atmosphere's attenuation. The default, and the one the headline figures come from. |
| `ghi_wm2` | W/m² | Irradiance directly. |
| `pv_kwh` | kWh | Hourly AC energy for the declared array, end to end. |

`pv_kwh` closes the gap between what the model predicts and what anybody actually asked for.
Its labels are produced by running the deterministic PV chain (Erbs → HDKR → Faiman →
PVWatts v5 → inverter) over the *observed* reanalysis weather for the declared system; the
model then maps weather and solar geometry straight onto that energy. Features are unchanged,
no lagged target values are used, and night hours are excluded at zenith ≥ 87° exactly as
before.

**For the `ensemble_four` and single-baseline paths, the labels are modelled, not metered.** The default
XGBoost model is the exception: it is trained on measured plant output (§7b). With no measured
generation to fit against, every kilowatt-hour reported on those paths carries the chain's assumptions as well as
the model's error. That is limitation 2 in §10, and it is repeated in the model card and in
every `/api/point-forecast` response rather than left in the documentation.

Two consequences follow from the target's own unit being the physical one. Metrics stay in
kilowatt-hours — there is nothing to convert back to, and no W/m² twin is manufactured.
And the baselines are persistence and climatology only: a physics-chain baseline would
reproduce labels the same chain generated and score near-zero error by construction, which
is circular rather than informative. Predictions are bounded after inference the same way
the irradiance path is — no negative energy, nothing above the inverter's AC rating in an
hour — and the number of clipped predictions is reported.

## 7b. Predicting a specific date and time

`POST /api/point-forecast` answers the question the interface always implied: *how much will
this array make at two o'clock on the fourteenth?* It is the path the web page at `/predict`
drives, and it is the pipeline the project abstract describes:

```
place (city name, GPS or map pin) + local date + hour
  -> irradiance, air temperature and wind speed from Open-Meteo for that place and time
  -> panel temperature from the NOCT model (wind cooling enters here)
  -> XGBoost on (irradiance, air temperature, panel temperature)
  -> energy in kWh for a 5 kW reference system
```

**The default model is XGBoost** (`xgboost_plants`), trained offline by
`train_model_plants.py` on measured inverter output from two solar plants (44 inverters,
rescaled to a 5 kW reference system) and saved with its hold-out results in
`backend/app/models/artifacts/`. Nothing is trained per request, so an answer takes as long
as the weather fetch. Random Forest, Extremely Randomized Trees, Histogram Gradient Boosting
and Ridge Regression, and their stacking ensemble, are kept only as comparison baselines,
scored on the same held-out week:

| Model | R² | MAE (kWh per 15 min) |
|---|---|---|
| **XGBoost (project model)** | 0.856 | 0.0399 |
| Random Forest | 0.862 | 0.0391 |
| Extremely Randomized Trees | 0.862 | 0.0387 |
| Histogram Gradient Boosting | 0.861 | 0.0391 |
| Stacking ensemble of the four | 0.861 | 0.0431 |
| Ridge Regression | 0.822 | 0.0753 |

The tree models sit within 0.006 R² of each other. XGBoost was chosen for its built-in
regularisation and its use in the solar forecasting literature, not for a lead in accuracy.
The last seven days of the data were held out in date order (11-17 June 2020).

**Accuracy drops on a plant the model has not seen.** Trained on Plant 1 and tested on
Plant 2, XGBoost scores R² 0.52; trained on Plant 2 and tested on Plant 1, 0.73 — against 0.86
on the held-out week. The response and the page both report this rather than leaving it in
the documentation.

The response carries the hour's energy and its day's total, the inputs (irradiance, air
temperature, wind speed, panel temperature), the resolved place and coordinates, operating
insights (safe operating range, wind cooling, thermal derating, each with its threshold
stated), a prediction interval taken from the hourly hold-out errors, and the baselines table.
Insights use an 85 °C panel limit (IEC 61215 test limit) and a 20 m/s wind stow threshold.

Two limits are stated in every payload. The model predicts for the 5 kW reference system it was
trained on, so a different declared capacity is reported, not applied. And because the weather
comes from the archive (reanalysis, about a week behind), a datetime it does not cover is
refused with a message naming the window that is available.

Any other registry key (`ensemble_four`, `random_forest`, ...) is still accepted and takes the
older path: train that model on archive data ending strictly before the hour, with
`target="pv_kwh"`, chronological split and 24-hour embargo. Those labels are modelled, not
metered (§7a).

## 8. Metrics

MAE, RMSE, MBE, R², rRMSE, rMAE, MAPE, sMAPE, forecast skill score. Probabilistic: pinball
loss, PICP, PINAW, CRPS.

Two honesty notes carried in the UI:

- **NSE and R² are the same quantity.** Reporting both looks like two confirmations; it is
  one number twice. Computed once, alias labelled.
- **MAPE is unstable for irradiance** — the denominator approaches zero at sunrise. Computed
  for comparability with the literature, always with its exclusion count, never as headline.

## 9. Validation

Chronological hold-out plus rolling-origin cross-validation with an embargo gap. A
five-check leakage audit (target, future information, preprocessing, boundary
contamination, trivial observations) reports the mechanism preventing each.

The **split-strategy experiment** fits the identical model on the identical data under
three splitting strategies. On two years at Hyderabad, random splitting understated RMSE by
**11.6 %** and overstated R² by **+0.027** — measured, not asserted.

Prediction intervals use **conformalized quantile regression**, an enhancement not drawn
from the supplied papers, introduced because plain quantile regression measured 66.3 %
empirical coverage against an 80 % nominal level. After calibration: **80.2 %**, and within
2 points across all three weather regimes.

## 10. Limitations

1. Reanalysis, not ground measurement (§4).
2. **No metered PV output was available.** All PV figures are physically modelled from
   predicted irradiance and have *not* been validated against measured generation. This
   extends to the `pv_kwh` modelling target (§7a): its training labels are produced by the
   PV chain from reanalysis weather, so a model fitted on them learns to reproduce that
   chain rather than a real inverter.
3. Intervals cover model error given the supplied weather; they exclude error in the
   weather forecast itself, which grows with horizon.
4. Trained per location. No cross-location generalisation is claimed.
5. Conformal coverage is marginal, not conditional, and assumes exchangeability that a
   seasonal series satisfies only approximately.
6. Aerosol optical depth, sunshine duration and wind-direction standard deviation are named
   in the source research but unavailable from this data source. Surfaced in the UI rather
   than silently omitted.

### Methodological observations on the source corpus

Recorded because this platform is designed not to repeat them, and stated as observations
about method rather than as accusations of error:

- **Random splitting of temporal data.** Mabodi & Hammujuddy describe `train_test_split` as
  preventing leakage; for autocorrelated series it places observations minutes apart on both
  sides of the split.
- **Target truncation by IQR.** Rosales Huamani et al. apply outlier bounds of 165–331 W/m²
  to solar radiation, removing 10.16 % of observations. Clear-sky midday GHI at Lima's
  latitude exceeds 900 W/m², so this discards physically valid data and compresses the range
  against which RMSE = 47.30 W/m² is reported. This platform performs no statistical
  truncation of the target.
- **Metric naming.** The quantity Mabodi & Hammujuddy define as "relative MAE" in eq. 9 is
  MAPE, not MAE normalised by the mean. Both are computed and labelled separately here.

## 11. Reproducibility

Every run records a dataset fingerprint (SHA-256 over the feature matrix, target, feature
names and period), random seed, library versions and platform. Identical fingerprint plus
identical seed reproduces the numbers exactly. Experiments persist automatically; the
comparison endpoint **refuses to rank runs that are not comparable** — different locations,
periods or targets — rather than producing a meaningless ordering.

## 12. Setup

Requirements: Python 3.11+, Node 20+. Nothing to provision and no keys to obtain: the
weather and geocoding services are still keyless and public, and for local development the
backend falls back to a SQLite file and an in-process stand-in for Redis.

```bash
make install
make dev
```

Or without `make`:

```bash
cd backend && python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>. API docs at <http://localhost:8000/api/docs>.

`make seed` creates sample accounts and estimates — including an unconfirmed one and an
anonymous one — and prints the shared password.

Verification and password-reset emails are **printed to the backend log** rather than sent
(`EMAIL_PROVIDER=console` is the default), so a signup can be completed without configuring
a mail provider. Copy the link out of the log.

`frontend/.env.local` leaves `NEXT_PUBLIC_API_BASE` empty on purpose. Empty means
*same origin*: a Next.js rewrite proxies `/api/*` to the backend in development, and Nginx
does the same job in production. The refresh cookie is `SameSite=Lax`, and
`localhost:3000` → `127.0.0.1:8000` is cross-site, so a split-origin setup silently breaks
silent refresh — everything works until an access token expires fifteen minutes later.

For a stack closer to production — real PostgreSQL, real Redis, migrations as their own
step — use `make stack`.

### Tests

```bash
cd backend && python -m pytest
```

465 tests, and no service needs to be running to execute them. The original 133 cover solar
geometry against known astronomical values, the PV chain, metrics, split leakage properties,
quality detection of eight distinct corruptions, feature-pipeline leakage guards, and API
validation. The 126 for the consumer domain are weighted toward failures that would be
*silently* wrong rather than loudly broken: an energy ledger that does not balance, losses
added instead of compounded, a battery that returns more than it stored, a bill converted
without removing the fixed charge, a currency symbol beside a figure from a different
currency.

The 129 added with accounts and horizontal scaling follow the same principle — they target
the failures that look fine until they matter:

| File | What it pins down |
|---|---|
| `test_auth.py` | registration answers identically for a known and an unknown address; a password reset revokes every existing session; an expired link is distinguishable from an invalid one |
| `test_oauth.py` | a matching email never merges accounts; the last sign-in method cannot be removed; a redirect outside the allowlist is replaced |
| `test_ownership.py` | one user cannot list or modify another's estimates; deleting an account orphans its estimates instead of destroying them |
| `test_cross_instance.py` | two independently built application instances share state only through PostgreSQL and Redis — sessions, OAuth flows and rate limits all cross between them |
| `test_health_and_config.py` | liveness survives the database being down; readiness does not; production startup refuses a development default |

The 60 added with the four-model set, the energy target and the point-forecast endpoint
target the ways each of those could go quietly wrong:

| File | What it pins down |
|---|---|
| `test_models.py` | the registry holds exactly five entries and each withdrawn key stays withdrawn; the ensemble's weights are learned rather than uniform and every base model reports its own prediction; the ensemble's inner folds partition the training rows, which is what `cross_val_predict` requires and what decides their shape; a `pv_kwh` run reports kilowatt-hours on both sides with no W/m² twin, gets persistence and climatology only, and still passes the five-check leakage audit; the irradiance path publishes exactly the columns, units and baselines it always did |
| `test_point_forecast.py` | the requested hour is read in the location's time zone and changes the answer; the training window ends strictly before the target hour and no fetched window reaches the target date; a night hour returns zero and says why; four base models are reported beside the ensemble; a date outside the archive is refused with the window that is available named; a repeat question reuses the trained model instead of paying for it twice; XGBoost is the default, reports panel temperature and the baselines table, states the safe range and wind cooling, and returns zero at night |

`test_cross_instance.py` is the one that earns its keep. It builds two complete application
objects against the same infrastructure and proves a rate limit is one shared budget rather
than one per replica, and that an OAuth flow started on one instance can be finished by the
other. CI runs the whole suite a second time against real PostgreSQL and real Redis.

```bash
cd frontend && npm run typecheck && npm test && npm run build
```

100 frontend tests covering the Web Mercator projection and polygon area (an error there
does not throw — it puts the pin in the wrong field), the draft-to-request mapping, and the
component promises: that a rejected value says what to type instead, that every technical
question can be declined, that a denied location permission offers a way forward, and that
a loading stage is never shown as finished before it is. The session client is tested for
the three things that are expensive when wrong: the access token never reaches
`localStorage`, several simultaneous 401s produce exactly one refresh, and a failed refresh
stops rather than looping.

`predict.test.tsx` pins the promises of the prediction page: that the chosen hour reaches
the server rather than only the chosen date, that a different hour produces a different
request, that XGBoost is the default model, that the baselines table and cross-plant scores
stay on the page, and that the provenance statements survive.

### Configuration

All settings are environment variables with safe defaults; see [`.env.example`](.env.example),
`backend/app/config.py` and `frontend/.env.example`.

The *data* services are still keyless and public — Open-Meteo and Nominatim need no
credential, and that has not changed. Accounts did change the picture around them: a JWT
signing key, a database password, a mail-provider key and the OAuth client secrets are all
required for a real deployment. None has a usable default, and with `SOLAR_ENV=production`
the backend **refuses to start** while any of them is still a development value — naming
each problem and what it would cause rather than failing with "invalid configuration".

Nothing secret belongs in the frontend's environment: every `NEXT_PUBLIC_` variable is
compiled into the browser bundle.

`NEXT_PUBLIC_MAP_ENGINE=leaflet` swaps the hand-rolled tile map for a Leaflet-backed
adapter behind the same interface. The default is the built-in map, which is around 250
lines and costs nothing in bundle size; the adapter exists so that a device the built-in
map mishandles is a one-line change rather than a rewrite. Leaflet is dynamically imported,
so it is absent from every bundle unless selected.

## 13. Deployment

```bash
cp .env.example .env.production   # fill in; every secret is required
make prod
```

Three backends and two frontends behind Nginx, with PgBouncer in front of PostgreSQL:

```
Nginx  ──/api/*──▶  backend1..3   (FastAPI, stateless)
       ──/*─────▶  frontend1..2  (Next.js, stateless)

backend  ──▶  PgBouncer ──▶ PostgreSQL     users, estimates, experiments
         ──▶  Redis                        cache, rate limits, sessions, OAuth state
         ──▶  email provider               verification and password reset
```

The replica counts live in `docker-compose.prod.yml` and nothing in the application knows
them. They are a **starting point, not a measured answer** —
[`LOAD_TESTING.md`](docs/LOAD_TESTING.md) is how to replace them with one.

Every backend instance is interchangeable: no estimate, session, rate-limit counter or
OAuth flow depends on which one serves a request. `test_cross_instance.py` is what keeps
that true.

What has changed since the single-process notes that used to be here:

- The rate limiter counts in Redis, so it is one budget per client across the whole fleet
  rather than one per process.
- Estimates and experiments are rows in PostgreSQL, not files on a container's disk.
- Liveness and readiness are separate endpoints. Liveness deliberately touches nothing —
  a liveness probe that queried PostgreSQL would turn a database blip into every container
  restarting at once.
- `SIGTERM` flips readiness to 503 first, then drains for up to 45 seconds, so a rolling
  deploy does not cut off a console training run mid-flight.

Still true, and still the main architectural weakness: **training is CPU-bound and runs
inside the request.** The API is shaped so that moving it to a queue is additive rather than
breaking — see [`PRODUCTION_ARCHITECTURE.md §7`](docs/PRODUCTION_ARCHITECTURE.md). It is
prepared for, not implemented.

`docker-compose.prod.yml` still has one PostgreSQL, one Redis and one Nginx. That is honest
for a single host and is **not** what production should run;
[`DEPLOYMENT.md §4`](docs/DEPLOYMENT.md) sets out the HA topology that replaces each.

## 14. What this platform will not do

It will not present a scenario as an observation, report a metric without the data behind
it, rank incomparable experiments, impute a value and then score itself on it, or claim an
accuracy it has not measured. Where a capability is unavailable it says so — for example,
PV output is physically modelled and explicitly *not* validated against metered generation,
because no metered data was supplied.
