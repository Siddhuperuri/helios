# Reference System Audit & Gap Analysis

**Subject:** `https://smart-energy-predictor-mtjlyfacsxpkynva6j7eff.streamlit.app/`
**Method:** live interaction, DOM inspection, and controlled input-perturbation testing.
**Date of audit:** 2026-08-19.

Every finding below is backed by an observation recorded during the session. Where a
finding is an inference rather than a direct observation, it is marked *(inferred)*.

---

## 1. Observed interface

The application is a single Streamlit screen.

**Sidebar — "📍 Regional Command Center"**
- Location Mode: radio, `By City Name` / `By GPS Coordinates`
- Region/City: free-text input
- Schedule Date: date picker (defaulted to the current date, 2026/08/19)
- Schedule Time: time spinner (defaulted to current local time)

**Main panel — "🛡️ Energy Resilience & Disaster AI"**
- "Target Source: Selected Energy Type"
- `Choose Resource` — combobox. The listbox announced *"3 options available"* but only one
  option, **Solar Panels**, was ever rendered or selectable.
- `Run Real-Time Analysis` — button
- Result: a status banner, one headline sentence, and three metric tiles
- A Mapbox/deck.gl canvas is present in the DOM (`canvas.mapboxgl-canvas`)

**Total rendered text content of the entire application after a successful run: 544 characters.**

---

## 2. Controlled experiments

Three runs were executed, changing exactly one input at a time.

| # | City | Date | Time | Result | Sun Intensity | Wind | Air Temp |
|---|---|---|---|---|---|---|---|
| 1 | Hyderabad | 2026/08/19 | **06:51** | 16.79 kWh | 0 % | 4.61 m/s | 28.46 °C |
| 2 | Hyderabad | 2026/08/19 | **13:51** | **16.79 kWh** | **0 %** | **4.61 m/s** | **28.46 °C** |
| 3 | **Reykjavik** | 2026/08/19 | 13:51 | 145.32 kWh | 100 % | 0.65 m/s | 8.81 °C |

Input state was verified directly from the DOM before each run
(`input[4].value === "13:51:00"` for runs 2–3).

### Finding A — the date and time controls do not affect the output

Runs 1 and 2 differ only in the scheduled time (06:51 → 13:51) and produced **byte-identical**
output across all four reported values. The prediction is therefore a function of location
only. The "Schedule Date" and "Schedule Time" controls are inert with respect to the result.

*Consequence:* the application presents itself as a scheduling/forecasting tool
("Schedule Date", "Schedule Time", "Run Real-Time Analysis") but performs neither
scheduling nor time-resolved forecasting. *(Inferred mechanism: the backend fetches
current-conditions weather for the resolved coordinates and ignores the datetime inputs.)*

### Finding B — a physically impossible prediction

Run 1 and Run 2 report **Sun Intensity = 0 %** and simultaneously
**Predicted Solar Panels Output = 16.79 kWh**.

Photovoltaic output at zero irradiance is zero. A model that returns a substantial positive
energy figure at zero reported irradiance has no physical floor constraint and is not
conditioned on its own headline input. This is the single most serious defect found.

### Finding C — directionally implausible cross-location behaviour

Reykjavik (64.1 °N, 8.81 °C) is reported at **145.32 kWh** versus Hyderabad
(17.4 °N, 28.46 °C) at **16.79 kWh** — a factor of 8.7 in Iceland's favour, in August.
Hyderabad receives substantially more daily insolation than Reykjavik at essentially every
time of year. The reported ordering is not consistent with solar geometry.
*(Inferred cause: the prediction keys off an instantaneous "sun intensity" snapshot with no
solar-position or day-length awareness.)*

### Finding D — "Sun Intensity" is not a scientific quantity

Reported as `0 %` and `100 %` — both saturation endpoints across only two samples, which is
characteristic of a clipped ratio. There is no unit, no definition, and no denominator.
Irradiance is measurable in W/m²; a percentage with an undeclared reference is not
interpretable and cannot be validated.

### Finding E — undefined output quantity

"16.79 kWh" declares no system. kWh **of what?** No array size, no module rating, no
inverter, no tilt/azimuth, and no integration period are stated anywhere in the interface.
Without a declared system the number has no defined meaning, and consequently cannot be
verified, reproduced, or compared against anything.

### Finding F — unjustified numerical precision

Four significant figures (16.79, 145.32, 28.46, 4.61) are presented for a quantity with no
stated uncertainty, produced by a model with no reported validation error.

### Finding G — an unsubstantiated safety verdict

The banner reads **"Safe Operation: …"**. No criteria, thresholds, or standards are shown.
The same verdict was returned for Hyderabad at 28.46 °C and Reykjavik at 8.81 °C.

### Finding H — no scientific accountability surface whatsoever

Absent from the entire application: model identity, training data, data provenance, date
range, temporal resolution, accuracy metrics, validation methodology, uncertainty,
feature importance, residuals, baselines, limitations, and assumptions.

### Finding I — incoherent product identity

Three unrelated framings coexist: "Regional Command Center" (sidebar), "Energy Resilience
& **Disaster AI**" (main heading), and solar energy prediction (the abstract). Neither the
abstract nor any of the six supplied papers concerns disaster response.

### Finding J — dead affordance

The resource combobox announces three options and exposes one. Either two options are
broken or the announcement is wrong; both are defects.

### Finding K — accessibility and structure

The page has **no `<title>`** (browser tab renders as "Streamlit"), no landmark structure
beyond Streamlit defaults, and no heading hierarchy below `h1`. The result banner is not an
ARIA live region, so screen-reader users receive no announcement when a prediction completes.

---

## 3. Gap analysis

| # | Reference capability | Scientific limitation | User problem | Required improvement | Implementation in this platform |
|---|---|---|---|---|---|
| 1 | Single point prediction | No uncertainty | User cannot tell whether ±2 % or ±60 % | Prediction intervals | Quantile GBR intervals; pinball loss, PICP, PINAW (P3) |
| 2 | Datetime inputs are inert (**A**) | Not a forecast at all | Cannot plan for a future hour | Real horizon-based forecasting | Horizon selection with issue-time semantics; forecast valid-time axis |
| 3 | 0 % irradiance → 16.79 kWh (**B**) | No physical constraint | Output is not believable | Physical sanity layer | Hard physical bounds; night mask by zenith ≥ 87° (P3); non-negativity |
| 4 | Implausible location ordering (**C**) | No solar geometry | Wrong answers by latitude | Solar position modelling | NOAA solar position + Haurwitz clear-sky (P1); zenith/azimuth/AOI features (P5) |
| 5 | "Sun Intensity %" (**D**) | Undefined quantity | Uninterpretable | Named scientific parameters | GHI in W/m²; clear-sky index `kt` as an explicit, defined ratio |
| 6 | Undefined "kWh" (**E**) | No declared system | Meaningless magnitude | Explicit PV system model | User-declared array kWp, tilt, azimuth, losses; energy stated per declared system |
| 7 | 4 s.f. precision (**F**) | Fake precision | Overstates confidence | Precision tied to error | Significant figures derived from validation RMSE |
| 8 | "Safe Operation" (**G**) | No criteria | Unfalsifiable claim | Explicit rule display | Operating-condition rules shown with thresholds and source, or omitted |
| 9 | No metrics (**H**) | Unvalidated | Reviewer cannot trust it | First-class validation | Model Performance, Baselines, Cross-Validation, Leakage views |
| 10 | No model identity (**H**) | Not reproducible | Cannot be audited | Model card + run manifest | Model card, dataset version, seed, feature set, run manifest |
| 11 | No baselines (**H**) | Cannot judge value | Unknown whether ML helps | Baseline suite + skill | Persistence, smart persistence, climatology, PeEn + skill score |
| 12 | Random-split-era practice (*inferred*) | Temporal leakage | Optimistic accuracy | Time-aware validation | Chronological split, rolling-origin CV, explicit leakage experiment |
| 13 | No explainability (**H**) | Black box | "Why this number?" | XAI layer | Permutation importance, partial dependence, per-prediction contribution |
| 14 | No data quality view | Hidden data problems | Silent failure | Data quality engine | Transparent scored report with per-check contribution |
| 15 | Single screen, 544 chars | No workflow | No analytical depth | Real information architecture | Multi-view workspace with progressive disclosure |
| 16 | No `<title>`, no live region (**K**) | — | Screen-reader users lose results | Accessibility baseline | Semantic landmarks, `aria-live` results, focus states, reduced-motion |
| 17 | Dead combobox (**J**) | — | Broken affordance | Honest capability surface | Capabilities either work or are labelled unavailable |
| 18 | "Disaster AI" framing (**I**) | Unsupported by sources | Misleading scope | Coherent identity | Scope limited to what the corpus supports |

---

## 4. What the reference system does well

Recorded for fairness, and preserved in the new system:

1. **Location-first interaction.** Entering a city name is the right entry point for a
   location-based tool, and it works — geocoding resolved both test cities correctly.
2. **A map is the correct spatial affordance,** and one is present.
3. **The three headline variables it chose** (irradiance proxy, wind speed, air temperature)
   are exactly the three NWP parameters used by P1 (§II-B1). The *selection* is well-aligned
   with the literature; the treatment of them is what falls short.
4. **Immediate result on one action.** The time-to-first-answer is short. The new system
   keeps a fast default path rather than forcing configuration before any output.
