# Research Synthesis & Evidence Matrix

This document records what was extracted from the six supplied papers and the project
abstract, and maps every capability implemented in this platform back to its source.
It is the governing document for the codebase: **if a capability is not justified here,
it is not implemented, or it is explicitly labelled as an engineering choice.**

Evidence classes used throughout:

| Class | Meaning |
|---|---|
| **A** | Explicitly supported by a supplied paper |
| **B** | Scientifically implied by the supplied research |
| **C** | Technically necessary, not research-specific |
| **D** | Proposed enhancement — labelled as such in the UI |

---

## 1. The supplied sources

| # | Short key | Full title | Venue / Year |
|---|---|---|---|
| P1 | `hobbs2026` | Using Open-Source Forecasts for Solar Plant Maintenance Outage Scheduling Can Reduce Lost Energy — Hobbs & Joshi | IEEE J. Photovoltaics, 2026 (accepted) |
| P2 | `mabodi2024` | Solar Irradiance Forecasting for Informed Solar Systems Design and Financing Decisions — Mabodi & Hammujuddy | SAIEE Africa Research Journal, Vol. 115(3), 2024 |
| P3 | `lyu2024` | Probabilistic Solar Generation Forecasting for Rapidly Changing Weather Conditions — Lyu & Eftekharnejad | IEEE Access, Vol. 12, 2024 |
| P4 | `rosales2025` | Efficient ML Models for Solar Radiation Prediction Using Ensemble Techniques: A Case Study in Low-Rainfall Arid Climates — Rosales Huamani et al. | IEEE Access, Vol. 13, 2025 |
| P5 | `babu2025` | Solar Energy Forecasting Using Machine Learning Techniques for Enhanced Grid Stability — Vijay Babu et al. | IEEE Access, Vol. 13, 2025 |
| P6 | `hayajneh2024` | Intelligent Solar Forecasts: Modern ML Models and TinyML Role for Improved Solar Energy Yield Predictions — Hayajneh et al. | IEEE Access, Vol. 12, 2024 |
| — | `abstract` | Supplied project abstract (Random Forest solar prediction & monitoring system) | — |

---

## 2. Prediction targets across the corpus

| Paper | Target | Unit | Resolution |
|---|---|---|---|
| P1 | PV plant power → daily energy | MW, MWh | hourly → daily |
| P2 | Global Horizontal Irradiance (GHI) | W/m² | hourly, aggregated monthly |
| P3 | GHI *and* PV power | W/m², kW | hourly / 5-min |
| P4 | Global solar radiation | W/m² | hourly |
| P5 | PV power output | W | hourly |
| P6 | Solar farm power yield | MW | 15-min → averaged |

**Reconciliation.** Four of six papers target irradiance (GHI, W/m²); the others target PV
power, which is derived from irradiance through a deterministic physical chain (P1 §II-B3).
This platform therefore adopts:

- **Primary scientific target: GHI in W/m²** — the quantity that is actually measured,
  is location-independent in meaning, and is common to P2/P3/P4 and the input side of P1.
- **Derived engineering target: PV energy in kWh** — obtained from predicted GHI via an
  explicit, user-visible system model with a declared array size. This is what the supplied
  **abstract** asks for, and it is only meaningful once system size is declared.

This split is the central scientific correction relative to the reference application,
which reports "kWh" with no declared system, no array size, and no stated period.

---

## 3. Input parameters — consolidated evidence

Union of predictor variables named across the corpus, with evidence and implementation status.

| Parameter | Unit | Evidence | Sources | Implemented |
|---|---|---|---|---|
| Air temperature (2 m) | °C | **A** | P1, P2, P3, P4, P5, P6, abstract | Yes |
| Relative humidity | % | **A** | P2, P3, P4, P5, P6 | Yes |
| Surface / barometric pressure | hPa | **A** | P2, P3, P4, P6 | Yes |
| Wind speed (10 m) | m/s | **A** | P1, P2, P3, P4, abstract | Yes |
| Cloud cover | % | **A** | P3, P5 | Yes |
| Precipitation | mm | **A** | P3, P4 | Yes |
| Solar zenith angle | ° | **A** | P3 (§II-A, 87° day filter), P5 (dominant feature) | Yes |
| Solar azimuth angle | ° | **A** | P5 | Yes |
| Angle of incidence (AOI) | ° | **A** | P5 (highest permutation importance) | Yes |
| Clear-sky GHI | W/m² | **A** | P1 (§II-B2, Haurwitz model) | Yes |
| Clear-sky index `kt` | – | **A** | P1 (§II-B2b) | Yes |
| Direct normal irradiance (DNI) | W/m² | **A** | P3 (future work), P6 | Yes (as diagnostic) |
| Diffuse horizontal irradiance (DHI) | W/m² | **A** | P1 (Erbs model), P6 | Yes (as diagnostic) |
| Dew point | °C | **A** | P3, P4 | Yes |
| Month / hour / seasonal index | – | **A** | P2 (Month = 10.75 % importance), P4 | Yes |
| Wind direction | ° | **A** | P2, P4 | Yes |
| Wind direction std. dev. | ° | **A** | P2 (14.34 % importance) | **No** — not available from the data source; documented as unavailable |
| Wind chill / heat index | °C | **A** | P4 | **No** — derived comfort indices, collinear with T & RH; documented |
| Total solar irradiance (TSI) | W/m² | **A** | P6 | **No** — extraterrestrial constant is computed, not a predictor |

Parameters listed as **No** are surfaced in the UI parameter dictionary as
*"Named in source research, not available in the current dataset"* rather than silently dropped.

---

## 4. Preprocessing methodology — reconciled

| Step | What the papers do | What this platform does | Why |
|---|---|---|---|
| **Night exclusion** | P3: retain only zenith < 87°. P2: sunrise–sunset only, "evening data … considered as noise". P4: 05:00–18:00 only. | Zenith < 87° (P3), applied to training **and** to every reported metric. | P3's criterion is the only physically-defined one; clock-hour windows (P4) are location-dependent and wrong at high latitude. |
| **Missing values** | P2: drop (<1 % of records). P4: seasonal-mean imputation for short gaps, noise-injected fill for long gaps. | Report and drop for training; never fabricate. Gaps are surfaced in the Data Quality report. | P4's noise-injection creates synthetic observations; this platform does not manufacture data it will then report metrics on. |
| **Outliers** | P2: IQR on target, none found. P4: IQR with bounds 165–331 W/m², removing 10.16 % of observations. | **Physical-range validation only** (0 ≤ GHI ≤ 1.5 × extraterrestrial). No statistical truncation of the target. | See §7 — P4's truncation is not physically defensible and materially changes the reported error scale. |
| **Scaling** | P2: z-score. P6: min–max. | Standardisation fitted **inside** each CV fold on training data only. | Fitting a scaler on the full dataset before splitting leaks test-set statistics. |
| **Dimensionality reduction** | P4: PCA, 11 → 8 variables, 3 components (66.55 % variance). | PCA offered as an optional, reported diagnostic; not applied by default. | With ~10 informative predictors and tree ensembles, PCA discards axis-alignment that trees exploit; P4 itself notes the loss of cloud-cover information. |

---

## 5. Models — evidence and inclusion

The project's model is XGBoost, trained on measured plant output. The models below are the comparison baselines: four estimators and one ensemble of those four. What follows records
both the evidence for each model and, where a model was withdrawn, why the evidence did not
make it load-bearing. A longer table is not a stronger result: a reader given ten rows looks
for the best number, where a reader given five asks whether the complexity was necessary.

| Model | Evidence | Sources | Included | Rationale |
|---|---|---|---|---|
| XGBoost | **A** | P2, P3 (XGBoost), **abstract** | **Yes - the project model** | Trained on measured plant output and served by default. Chosen for built-in regularisation and use in the solar forecasting literature. Scored against the five models below on a held-out week (R² 0.856 against 0.862 for the best tree baseline) and across plants (R² 0.52-0.73). |
| Random Forest | **A** | P2, P4, P5, **abstract** | **Yes** | Named by the project abstract as the core method. |
| Histogram Gradient Boosting | **A** | P2, P3 (XGBoost); P4, P5 (boosting) | **Yes** | The boosted-tree family the cited papers use. Boosting fits residuals sequentially where bagging averages independent fits, so it fails differently from the forest rather than redundantly. |
| Extra Trees | **B** | Ensemble family of P4 | **Yes** | Randomised split thresholds decorrelate its errors from RF's — the property that makes it useful inside an ensemble. |
| Ridge | **A** | P5 (MLR, Ridge, Lasso) | **Yes** | The required linear reference point. Kept to be a floor, not a contender. |
| Four-Model Stacking Ensemble | **A** | P4 (stacking best overall, R²=0.92) | **Yes** | P4's headline result, with this platform's four kept models as the base set and a Ridge meta-learner for stability under collinear base predictions. Weights are learned, never uniform. |
| Gradient Boosting (exact) | **A** | P4, P5 (best model, R²=0.827) | **No** | The boosted-tree argument is made by `hist_gradient_boosting`, the same family an order of magnitude faster on hourly samples. Two boosters would be one argument twice. |
| k-Nearest Neighbours | **A** | P2 (best model), P4 | **No** | Withdrawn with the rest of the second representatives. Its distance weighting also makes its training-set metrics near-perfect and uninformative — P2 reports 0.41 % training rRMSE against 5.77 % on test. |
| Support Vector Regression | **A** | P2, P4, P5 | **No** | Training cost grows super-linearly with sample size, and P5 found it significantly worse than boosting (paired t-test, p = 1.19e-6). |
| Ordinary Least Squares | **A** | P5 | **No** | Ridge already occupies the linear-reference slot, and does so without collapsing when the geometry features are collinear — which they are by construction. |
| Decision Tree | **A** | P4, P5 | **No** | A single tree next to two tree ensembles adds interpretability the permutation-importance view already supplies. |
| Voting Regressor | **A** | P4 | **No** | An unweighted mean of models that disagree systematically. `ensemble_four` does the same job with weights that are fitted rather than assumed. |
| Quantile Gradient Boosting | **A** | P3 (quantile forecasts, pinball loss) | **Yes** | Supplies prediction intervals. Lives in `models.uncertainty`, not in the registry: it is interval machinery, not an entry in the comparison. |
| LSTM / BiGRU / BiLSTM | **A** | P6 | **No** | Requires a deep-learning runtime for a marginal gain over ensembles on tabular exogenous features; declared **Future Work** in the UI rather than faked. |
| Copula + XGBoost | **A** | P3 | **No** | Full vine-copula machinery is out of scope; the *weather-regime conditioning* idea from P3 **is** implemented (§6). Declared **Research-Inspired**. |

### Baselines (mandatory reference points)

| Baseline | Evidence | Source |
|---|---|---|
| Persistence | **A** | P6 ("persistence benchmark") |
| Smart / clear-sky persistence | **A** | P1 (clear-sky index framing), P3 |
| Climatology (hour-of-year mean) | **B** | Standard reference implied by P3's PeEn |
| Persistence Ensemble (PeEn) | **A** | P3 (§III-B3) — probabilistic baseline |

---

## 6. Weather-regime conditioning

P3 (§II-A) classifies data into **sunny** (cloud cover < 25 %), **cloudy**, and **other**
(precipitation / snowfall), and demonstrates that the optimal feature set changes by regime.

Implemented as: regime labelling using P3's exact thresholds, per-regime error reporting,
and per-regime feature-importance. Full copula-based dynamic feature selection is **not**
implemented and is labelled *Research-Inspired* in the Literature view.

---

## 7. Methodological weaknesses identified in the corpus

These are recorded because the platform is explicitly designed to **not** repeat them. They
are stated as observations about method, not as accusations of error.

**W1 — Random splitting of temporal data (P2 §III-B, P5 §V-D).**
P2 uses `train_test_split` and describes it as preventing leakage; for autocorrelated
time series a random split places observations minutes apart on both sides of the split,
so test-set performance is optimistic. P5 explicitly acknowledges this: *"the current
validation was performed using random sampling, future work will involve testing
generalization using time-based … data splits."*
→ **Platform response:** chronological split + rolling-origin CV by default, with a
built-in experiment that *quantifies* the optimism gap on the user's own data.

**W2 — Target truncation by IQR (P4 §III-B1).**
Outlier bounds of 165–331 W/m² were applied to solar radiation and 10.16 % of observations
removed. Clear-sky midday GHI at Lima's latitude exceeds 900 W/m², so this removes
physically valid high-irradiance data and compresses the target range against which
RMSE = 47.30 W/m² is later reported.
→ **Platform response:** physical-range validation only; no statistical truncation of the
target. Error metrics are always reported alongside the target's observed range.

**W3 — Metric naming (P2 eq. 9).**
The quantity defined as "relative MAE" is `mean(|O−F| / F)`, which is MAPE, not
MAE normalised by the mean of observations (the definition used in eq. 7 for rRMSE).
→ **Platform response:** MAE, rMAE (÷ mean of observations) and MAPE are computed and
labelled separately, each with its formula shown in the UI.

**W4 — Night-hour inclusion inflates goodness-of-fit.**
Any model trivially predicts zero at night. Including night hours in the evaluation set
inflates R² because the between-group (day/night) variance dominates the total sum of
squares. P2, P3 and P4 all exclude night, but not all published solar-ML results do.
→ **Platform response:** night exclusion enforced, and the platform can report the
day-only vs all-hours R² difference so the effect is visible rather than hidden.

**W5 — Train/test optimism with distance-weighted KNN (P2 Tables II–IV).**
Distance-weighted KNN reproduces training points almost exactly (train rRMSE 0.41 %,
R² 0.997); train-set metrics for such models are not informative about generalisation.
→ **Platform response:** train-set metrics are shown only next to validation metrics,
never alone, and the UI flags a large train/validation gap.

---

## 8. Evaluation metrics — evidence

| Metric | Evidence | Sources | Included |
|---|---|---|---|
| MAE | **A** | P2, P4, P5 | Yes |
| RMSE | **A** | P1–P6 | Yes |
| rRMSE (÷ mean obs.) | **A** | P2 (eq. 7) | Yes |
| rMAE (÷ mean obs.) | **A** | P2 | Yes |
| MAPE | **A** | P4, P2 (as eq. 9) | Yes, with a zero-denominator guard |
| R² | **A** | P2, P4, P5, P6 | Yes |
| Nash–Sutcliffe Efficiency | **A** | P4 | Yes |
| MBE (bias) | **B** | Implied by P1's over/under-forecast discussion | Yes |
| Forecast skill vs baseline | **A** | P1 (RLR is a skill score), P6 | Yes |
| Pinball loss | **A** | P3 (eq. 28) | Yes |
| PICP / PINAW | **B** | Implied by P3's prediction-interval critique | Yes |
| nCRPS | **A** | P3 (eq. 27) | Yes (empirical, from quantiles) |
| Relative / Absolute Loss Reduction | **A** | P1 (eqs. 1–2) | Yes — in the Outage Scheduling view |
| Ensemble selection confidence | **A** | P1 (§II-C1) | Yes |

---

## 9. Capability → evidence map (implementation register)

| Capability | Class | Source | Status |
|---|---|---|---|
| GHI point forecasting | A | P2, P3, P4 | Implemented |
| Clear-sky index modelling | A | P1 | Implemented |
| Solar-geometry features | A | P5 | Implemented |
| PV energy conversion (declared system) | A | P1 | Implemented |
| Prediction intervals via quantile regression | A | P3 | Implemented |
| Weather-regime error decomposition | A | P3 | Implemented |
| Time-aware CV / rolling origin | A | P5 (stated as future work) | Implemented |
| Leakage demonstration (random vs chronological) | B | P2, P5 | Implemented |
| Permutation feature importance | A | P2, P5 | Implemented |
| Partial dependence | B | Implied by P5's feature discussion | Implemented |
| Baseline comparison + skill score | A | P1, P3, P6 | Implemented |
| Data quality scoring | C | — | Implemented (transparent formula) |
| Physical sanity checks | B | P3, P4 (range discussion) | Implemented |
| Residual-based anomaly detection | B | P3 (rapid-change events) | Implemented |
| Outage scheduling (RLR/ALR) | A | P1 | Implemented |
| Scenario simulation | D | — | Implemented, labelled **SIMULATION** |
| Experiment tracking | C | — | Implemented |
| Reproducibility manifest | C | — | Implemented |
| Report export | C | — | Implemented |
| Deep sequence models (LSTM family) | A | P6 | **Future Work** — declared, not faked |
| Copula-based dynamic feature selection | A | P3 | **Research-Inspired** — regime conditioning only |
| TinyML / edge deployment | A | P6 | **Future Work** — declared, not faked |

---

## 10. Data source

**Open-Meteo Historical Weather API** (ERA5 / ERA5-Land reanalysis), accessed without an
API key. Provides hourly `shortwave_radiation` (GHI, W/m²), `direct_normal_irradiance`,
`diffuse_radiation`, `temperature_2m`, `relative_humidity_2m`, `dew_point_2m`,
`surface_pressure`, `wind_speed_10m`, `wind_direction_10m`, `cloud_cover`, `precipitation`.

This is **reanalysis data, not ground-station pyranometer data.** That distinction is
stated in the UI and in the model card, because it bounds what may be claimed: results are
not directly comparable to P2's SAURAN ground measurements or P4's on-site weather station.

Licensing: Open-Meteo data is provided under CC-BY 4.0; ERA5 is © ECMWF / Copernicus.
Attribution is rendered in the application footer and in every exported report.

---

## 11. Findings measured during implementation

These were produced by the platform itself during development. They are recorded here
because several of them changed design decisions, and because a reviewer is entitled to
see the evidence rather than the conclusion alone.

### F1 — The archive's interval-labelling convention (empirical)

Irradiance is an interval average; solar position is instantaneous. Evaluating position at
the interval label rather than its representative instant produces a systematic phase
error. The convention was measured rather than assumed, by sweeping candidate offsets over
a full year at Hyderabad:

| Offset | Clear-sky exceedances | Apparent night-time irradiance | corr(GHI, clear-sky) |
|---|---|---|---|
| −60 min | 360 | 289 | 0.9340 |
| −30 min | **0** | **216** | **0.9490** |
| 0 min | 264 | 265 | 0.9372 |
| +30 min | 697 | 428 | 0.8998 |

**Conclusion:** hourly radiation is the mean over the *preceding* hour; the representative
instant is 30 minutes before the label. Applying the correction raised the data-quality
score from 97.7 % to 99.9 %. Reproduce with `backend/scripts/calibrate_interval.py`.

This also surfaced a genuine defect: `pv_power_chain` was evaluating solar position at the
raw label while the feature pipeline used the midpoint, a 30-minute inconsistency that
shifted the day/night boundary by a full hour at the terminator. Caught by a test asserting
zero PV output at night, and fixed.

### F2 — Random splitting inflates reported accuracy (measured)

Identical model, seed and dataset; only the split differs. Two years, Hyderabad:

| Strategy | RMSE (W/m²) | R² |
|---|---|---|
| Chronological | 74.68 | 0.9160 |
| Blocked random (whole days) | 68.97 | 0.9376 |
| Random (hour-level) | 66.03 | 0.9427 |

Random splitting understates RMSE by **11.6 %** and overstates R² by **+0.027**. This
substantiates W1 quantitatively rather than by assertion, and is exactly the comparison
Vijay Babu et al. [P5, Sec. V-D] name as future work.

### F3 — Plain quantile regression was badly mis-calibrated (measured, then fixed)

An 80 % prediction interval from uncalibrated quantile gradient boosting achieved **66.3 %**
empirical coverage — an interval that would mislead anyone sizing a reserve margin.

Conformalized quantile regression (Romano et al. 2019) was added to correct this. It is
**not** drawn from the supplied papers and is labelled an *enhancement* in the Literature
view. Final measured coverage: **80.2 %** against 80 % nominal, and within 2 points inside
every weather regime (clear 80.3 %, cloudy 80.0 %, precipitation 80.9 %).

A seasonally-stratified calibration split was also implemented and tested. It did **not**
robustly improve coverage — results were non-monotone in its parameters (0.700 / 0.725 /
0.706 / 0.790 as the embargo widened; 0.767 vs 0.834 for six vs eight blocks) — which is
instability, not signal. Selecting the best-scoring configuration would have been tuning on
the test set, so the simpler contiguous split was kept and the reasoning recorded in the
code.

### F4 — Feature importance depends on the choice of target

Grouped permutation importance on Hyderabad, predicting the **clear-sky index**:

| Group | Share of measured effect |
|---|---|
| Temperature & moisture | 52 % |
| Cloud & precipitation | 21 % |
| Solar geometry | 17 % |
| Time of year / day | 6 % |
| Pressure | 3 % |
| Wind | 1.5 % |

Solar geometry ranks third here, whereas Vijay Babu et al. [P5] found it dominant. The
two results are consistent rather than contradictory: [P5] predict raw PV power, in which
geometry is the largest single driver, while this platform divides geometry out *before*
fitting. What remains for the model to explain is the atmospheric component, and there
humidity and cloud dominate — consistent with Mabodi & Hammujuddy [P2] finding temperature
and humidity the leading meteorological predictors.

### F5 — Naive and smart persistence coincide at a 24-hour horizon

Both score 143.4 W/m² and 143.3 W/m² respectively at day-ahead. This is expected, not a
bug: solar declination changes by at most ~0.4°/day, so clear-sky irradiance at the same
clock hour one day apart is nearly identical and `kt(t−24h)·GHIcs(t) ≈ GHI(t−24h)`. The two
diverge sharply at intra-day horizons. It is also why baselines are formed in physical
units — in clear-sky-index space they are algebraically the same function and the
comparison would be vacuous.

### F6 — Scenario responses combine a correlational and a causal pathway

A +6 °C / halved-wind "heatwave" scenario returned a net energy change of **+0.29 %**, which
is counter-intuitive and would rightly be challenged. Decomposition shows why:

| Pathway | Effect |
|---|---|
| Statistical (learned correlation: warm hours tend to be sunny hours) | **+114.3 kWh** |
| Physical (causal: hotter modules are less efficient) | **−105.7 kWh** |
| Net | +8.6 kWh |

Two large opposing effects nearly cancelling. Reporting only the net figure would conceal
this, so both pathways are surfaced separately in the Scenarios view. Doubling wind speed
shows the causal pathway dominating instead (+43.2 kWh thermal against −7.0 kWh
statistical), which is the physically expected result.
