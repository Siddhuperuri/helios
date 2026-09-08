"""Scenario simulation.

Every output of this module is a **modelled counterfactual**, not an observation. The
distinction is enforced structurally rather than left to a UI label: results are returned
in a ``ScenarioResult`` whose payload always carries ``is_simulation: True``, a stated
assumption list, and a validity assessment. There is no code path by which a scenario
value can be returned looking like a measurement.

Two kinds of scenario are supported, and they are not equivalent.

**Meteorological scenarios** perturb the weather inputs and re-run the fitted model. These
are only trustworthy inside the range the model was trained on. Pushing temperature +10 °C
beyond anything in the training data asks the model to extrapolate, and tree ensembles do
not extrapolate — they saturate at the edge of their training range. The engine measures
how far each perturbation moves inputs outside the observed envelope and downgrades the
result's validity accordingly, rather than returning a confident-looking number.

**System scenarios** change the PV system — capacity, tilt, azimuth, losses — and re-run
the deterministic physics. These are far more reliable, because no statistical
extrapolation is involved: the transposition and PVWatts models are closed-form and valid
across the whole parameter space.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.features.parameters import PARAMETERS
from app.features.solar_geometry import PVSystem, pv_power_chain
from app.models.trainer import CLEAR_SKY_CEILING_FACTOR, TrainingResult

ScenarioKind = Literal["meteorological", "system"]


@dataclass
class Perturbation:
    """A single change applied to a baseline."""

    variable: str
    mode: Literal["delta", "scale", "set"]
    value: float

    def apply(self, series: np.ndarray) -> np.ndarray:
        if self.mode == "delta":
            return series + self.value
        if self.mode == "scale":
            return series * self.value
        return np.full_like(series, self.value)

    def describe(self) -> str:
        param = PARAMETERS.get(self.variable)
        name = param.display_name if param else self.variable
        unit = (param.unit or "") if param else ""
        if self.mode == "delta":
            return f"{name} {self.value:+g} {unit}".strip()
        if self.mode == "scale":
            return f"{name} × {self.value:g}"
        return f"{name} set to {self.value:g} {unit}".strip()


@dataclass
class ScenarioResult:
    name: str
    kind: ScenarioKind
    baseline: dict[str, Any]
    scenario: dict[str, Any]
    difference: dict[str, Any]
    perturbations: list[str]
    assumptions: list[str]
    validity: dict[str, Any]
    is_simulation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "is_simulation": True,
            "label": "SIMULATION — MODELLED SCENARIO",
            "baseline": self.baseline,
            "scenario": self.scenario,
            "difference": self.difference,
            "perturbations": self.perturbations,
            "assumptions": self.assumptions,
            "validity": self.validity,
            "disclaimer": (
                "These figures are modelled counterfactuals produced by re-running the "
                "fitted model and the physical chain under altered inputs. They are not "
                "observations, and they are conditional on every assumption listed."
            ),
        }


def _extrapolation_check(
    perturbed: pd.DataFrame, training_frame: pd.DataFrame, variables: list[str]
) -> dict[str, Any]:
    """Measure how far a perturbation pushes inputs outside the training envelope.

    Tree ensembles cannot extrapolate: beyond the training range every split has already
    been taken, so the prediction flattens to the boundary leaf value. A scenario that
    leaves the envelope will therefore look reassuringly stable while actually being
    uninformative. This check exists to say so.
    """
    findings: list[dict[str, Any]] = []
    worst = 0.0

    for var in variables:
        if var not in perturbed.columns or var not in training_frame.columns:
            continue
        train_vals = training_frame[var].to_numpy(dtype=np.float64)
        train_vals = train_vals[np.isfinite(train_vals)]
        if train_vals.size < 10:
            continue

        lo, hi = float(np.min(train_vals)), float(np.max(train_vals))
        span = hi - lo if hi > lo else 1.0
        new_vals = perturbed[var].to_numpy(dtype=np.float64)
        new_vals = new_vals[np.isfinite(new_vals)]
        if new_vals.size == 0:
            continue

        below = float(np.mean(new_vals < lo))
        above = float(np.mean(new_vals > hi))
        outside = below + above
        excess = max(
            (lo - float(np.min(new_vals))) / span if np.min(new_vals) < lo else 0.0,
            (float(np.max(new_vals)) - hi) / span if np.max(new_vals) > hi else 0.0,
        )
        worst = max(worst, excess)

        if outside > 0.001:
            param = PARAMETERS.get(var)
            findings.append(
                {
                    "variable": var,
                    "display_name": param.display_name if param else var,
                    "training_range": [round(lo, 3), round(hi, 3)],
                    "fraction_outside": round(outside, 4),
                    "max_excess_fraction_of_range": round(excess, 4),
                }
            )

    if worst == 0.0:
        level, message = "high", (
            "All perturbed inputs remain inside the range the model was trained on."
        )
    elif worst < 0.1:
        level, message = "moderate", (
            "Some perturbed inputs fall marginally outside the training range. Tree "
            "ensembles saturate rather than extrapolate, so the response may be understated."
        )
    else:
        level, message = "low", (
            "Perturbed inputs fall substantially outside the training range. Tree "
            "ensembles cannot extrapolate: predictions flatten at the boundary, so this "
            "scenario understates the true effect and should be read as indicative only."
        )

    return {
        "level": level,
        "message": message,
        "max_excess_fraction_of_range": round(worst, 4),
        "variables_outside_range": findings,
    }


def _predict_with_fixed_irradiance(
    frame: pd.DataFrame,
    fixed_ghi: np.ndarray,
    system: PVSystem,
    times: np.ndarray,
    lat: float,
    lon: float,
    day_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Re-run only the PV physics under perturbed weather, holding irradiance fixed.

    Isolates the causal thermal pathway from the model's learned correlations.
    """
    pv = pv_power_chain(
        ghi=fixed_ghi,
        air_temp_c=frame["temperature_c"].to_numpy(dtype=np.float64),
        wind_speed_ms=frame["wind_speed_ms"].to_numpy(dtype=np.float64),
        times_utc=times,
        latitude=lat,
        longitude=lon,
        system=system,
    )
    return fixed_ghi, pv.ac_power_kw


def run_meteorological_scenario(
    *,
    trained: TrainingResult,
    base_frame: pd.DataFrame,
    training_frame: pd.DataFrame,
    perturbations: list[Perturbation],
    name: str,
    system: PVSystem,
    location_lat: float,
    location_lon: float,
) -> ScenarioResult:
    """Perturb weather inputs and re-run the fitted model plus the physical chain."""
    if not perturbations:
        raise ValueError("A scenario requires at least one perturbation.")

    # The counterfactual re-runs the fitted model and then the physical chain on top of its
    # irradiance. A model trained on energy skips the irradiance step entirely, so there is
    # nothing for the chain to consume and the comparison cannot be formed here.
    if trained.target_name not in {"clear_sky_index", "ghi_wm2"}:
        raise ValueError(
            f"Meteorological scenarios re-run the model's predicted irradiance through the "
            f"PV chain, and this model was trained on '{trained.target_name}'. Re-run the "
            f"analysis with target 'clear_sky_index' or 'ghi_wm2' to explore scenarios."
        )

    feature_names = trained.feature_names
    clear_sky = base_frame["clear_sky_ghi_wm2"].to_numpy(dtype=np.float64)
    day_mask = base_frame["is_daytime"].to_numpy(dtype=bool) if "is_daytime" in base_frame else np.ones(len(base_frame), bool)
    times = base_frame.index.to_numpy()

    def _predict(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        X = frame[feature_names].to_numpy(dtype=np.float64)
        kt = np.zeros(len(frame))
        if day_mask.any():
            kt[day_mask] = trained.estimator.predict(X[day_mask])
        ghi = np.clip(kt * clear_sky, 0.0, clear_sky * CLEAR_SKY_CEILING_FACTOR)
        ghi[~day_mask] = 0.0
        pv = pv_power_chain(
            ghi=ghi,
            air_temp_c=frame["temperature_c"].to_numpy(dtype=np.float64),
            wind_speed_ms=frame["wind_speed_ms"].to_numpy(dtype=np.float64),
            times_utc=times,
            latitude=location_lat,
            longitude=location_lon,
            system=system,
        )
        return ghi, pv.ac_power_kw

    base_ghi, base_power = _predict(base_frame)

    perturbed = base_frame.copy()
    touched: list[str] = []
    for p in perturbations:
        if p.variable not in perturbed.columns:
            raise ValueError(f"Cannot perturb unknown variable '{p.variable}'.")
        perturbed[p.variable] = p.apply(perturbed[p.variable].to_numpy(dtype=np.float64))

        # Respect physical bounds: a scenario must not create impossible weather.
        param = PARAMETERS.get(p.variable)
        if param is not None:
            perturbed[p.variable] = perturbed[p.variable].clip(
                lower=param.valid_min, upper=param.valid_max
            )
        touched.append(p.variable)

    # Derived features must be rebuilt from the perturbed values, not carried over.
    if "temperature_c" in touched or "relative_humidity_pct" in touched:
        pass  # dew point is supplied independently; not recomputed here (see assumptions)
    if "wind_direction_deg" in touched:
        rad = np.radians(perturbed["wind_direction_deg"].to_numpy(dtype=np.float64))
        perturbed["wind_dir_sin"] = np.sin(rad)
        perturbed["wind_dir_cos"] = np.cos(rad)

    scen_ghi, scen_power = _predict(perturbed)

    # Decompose the change into its two pathways. This matters: a temperature perturbation
    # moves the result through two quite different mechanisms, and they can cancel.
    #
    #   Statistical pathway - the model has learned that warm hours tend to be sunny hours.
    #     Perturbing temperature therefore raises predicted irradiance. That is a learned
    #     *correlation*, not a causal effect: making the air warmer does not make the sun
    #     brighter. Both are driven by the same underlying clear-sky conditions.
    #   Physical pathway - higher module temperature reduces conversion efficiency. This
    #     one is causal and is computed from the Faiman and PVWatts models.
    #
    # Reporting only the net change would hide a sign flip that a reviewer would rightly
    # challenge, so both are surfaced separately.
    _, power_physics_only = _predict_with_fixed_irradiance(
        perturbed, base_ghi, system, times, location_lat, location_lon, day_mask
    )
    energy_base = float(np.sum(base_power))
    energy_total = float(np.sum(scen_power))
    energy_physics = float(np.sum(power_physics_only))

    pathway = {
        "statistical_pathway_kwh": round(energy_total - energy_physics, 3),
        "physical_pathway_kwh": round(energy_physics - energy_base, 3),
        "net_kwh": round(energy_total - energy_base, 3),
        "explanation": (
            "The statistical pathway is the change in predicted irradiance, which comes "
            "from correlations the model learned between weather variables. It is not a "
            "causal effect: warmer air does not cause stronger sunlight, and both respond "
            "to the same underlying conditions. The physical pathway is the change in "
            "conversion efficiency from module temperature, which is causal and comes from "
            "the Faiman and PVWatts models. Read them separately."
        ),
    }

    validity = _extrapolation_check(perturbed, training_frame, touched)

    baseline_stats = _summarise(base_ghi, base_power, day_mask, system)
    scenario_stats = _summarise(scen_ghi, scen_power, day_mask, system)
    difference = {
        key: {
            "absolute": round(scenario_stats[key] - baseline_stats[key], 4),
            "relative_pct": (
                round((scenario_stats[key] - baseline_stats[key]) / baseline_stats[key] * 100.0, 2)
                if baseline_stats[key] not in (0, None)
                else None
            ),
        }
        for key in baseline_stats
        if isinstance(baseline_stats[key], (int, float)) and baseline_stats[key] is not None
    }

    assumptions = [
        "Every meteorological variable not named in the perturbation list is held fixed.",
        (
            "Physical correlations between variables are not enforced. Raising temperature "
            "without adjusting dew point implicitly lowers relative humidity in reality, "
            "but the model is fed the values as specified."
        ),
        "Solar geometry is unchanged: the same timestamps and location are used throughout.",
        (
            "The PV system specification is held constant, so differences reflect weather "
            "alone."
        ),
        (
            "The fitted model is treated as valid under the perturbed conditions. See the "
            "validity assessment for how far this holds."
        ),
        (
            "The model encodes correlation, not causation. Perturbing one weather variable "
            "invokes every relationship it has learned with the others, so the change in "
            "predicted irradiance is not a causal consequence of the perturbation. The "
            "pathway decomposition separates this from the genuinely causal thermal effect."
        ),
    ]

    result = ScenarioResult(
        name=name,
        kind="meteorological",
        baseline=baseline_stats,
        scenario=scenario_stats,
        difference=difference,
        perturbations=[p.describe() for p in perturbations],
        assumptions=assumptions,
        validity=validity,
    )
    result.validity["pathway_decomposition"] = pathway
    return result


def run_system_scenario(
    *,
    base_frame: pd.DataFrame,
    baseline_system: PVSystem,
    scenario_system: PVSystem,
    name: str,
    location_lat: float,
    location_lon: float,
    ghi_column: str = "ghi_wm2",
) -> ScenarioResult:
    """Change the PV system and re-run the deterministic physics.

    More reliable than a meteorological scenario: no statistical model is involved, so
    there is no extrapolation risk. The transposition and PVWatts models are closed-form
    and valid across the whole parameter range.
    """
    times = base_frame.index.to_numpy()
    ghi = base_frame[ghi_column].to_numpy(dtype=np.float64)
    temp = base_frame["temperature_c"].to_numpy(dtype=np.float64)
    wind = base_frame["wind_speed_ms"].to_numpy(dtype=np.float64)
    day_mask = base_frame["is_daytime"].to_numpy(dtype=bool) if "is_daytime" in base_frame else np.ones(len(base_frame), bool)

    def _run(system: PVSystem) -> np.ndarray:
        return pv_power_chain(
            ghi=ghi, air_temp_c=temp, wind_speed_ms=wind, times_utc=times,
            latitude=location_lat, longitude=location_lon, system=system,
        ).ac_power_kw

    base_power = _run(baseline_system)
    scen_power = _run(scenario_system)

    baseline_stats = _summarise(ghi, base_power, day_mask, baseline_system)
    scenario_stats = _summarise(ghi, scen_power, day_mask, scenario_system)
    difference = {
        key: {
            "absolute": round(scenario_stats[key] - baseline_stats[key], 4),
            "relative_pct": (
                round((scenario_stats[key] - baseline_stats[key]) / baseline_stats[key] * 100.0, 2)
                if baseline_stats[key] not in (0, None)
                else None
            ),
        }
        for key in baseline_stats
        if isinstance(baseline_stats[key], (int, float)) and baseline_stats[key] is not None
    }

    changes: list[str] = []
    for field_name in (
        "dc_capacity_kwp", "surface_tilt_deg", "surface_azimuth_deg",
        "system_losses_fraction", "inverter_efficiency", "temperature_coefficient_per_c",
    ):
        before = getattr(baseline_system, field_name)
        after = getattr(scenario_system, field_name)
        if before != after:
            changes.append(f"{field_name.replace('_', ' ')}: {before} → {after}")

    return ScenarioResult(
        name=name,
        kind="system",
        baseline=baseline_stats,
        scenario=scenario_stats,
        difference=difference,
        perturbations=changes or ["No system parameters changed."],
        assumptions=[
            "Irradiance and weather are held exactly as observed or forecast.",
            "The array is unshaded and the modules are uniformly clean.",
            (
                "Ground albedo is fixed at the declared value; seasonal surface changes "
                "such as snow cover are not modelled."
            ),
            "Inverter efficiency is treated as constant rather than load-dependent.",
            (
                "No statistical model is involved in this scenario, so there is no "
                "extrapolation risk — only the accuracy of the physical models themselves."
            ),
        ],
        validity={
            "level": "high",
            "message": (
                "Deterministic physical models are used throughout, with no statistical "
                "extrapolation. Accuracy is bounded by the transposition and PVWatts models "
                "rather than by training-data coverage."
            ),
            "max_excess_fraction_of_range": 0.0,
            "variables_outside_range": [],
        },
    )


def _summarise(
    ghi: np.ndarray, power_kw: np.ndarray, day_mask: np.ndarray, system: PVSystem
) -> dict[str, Any]:
    """Comparable summary statistics for a baseline or scenario run."""
    energy = float(np.sum(power_kw))  # hourly kW over 1-hour steps -> kWh
    lit = ghi[day_mask] if day_mask.any() else ghi
    return {
        "energy_kwh": round(energy, 2),
        "peak_power_kw": round(float(np.max(power_kw)) if power_kw.size else 0.0, 3),
        "mean_daylight_ghi_wm2": round(float(np.mean(lit)) if lit.size else 0.0, 1),
        "peak_ghi_wm2": round(float(np.max(ghi)) if ghi.size else 0.0, 1),
        "specific_yield_kwh_per_kwp": round(energy / system.dc_capacity_kwp, 3),
        "capacity_factor": round(
            energy / (system.ac_capacity_kw * len(power_kw)), 4
        ) if len(power_kw) else None,
    }


PRESET_SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "key": "warming_2c",
        "name": "Ambient warming +2 °C",
        "kind": "meteorological",
        "description": (
            "Uniform 2 °C increase in air temperature. Tests the combined effect of the "
            "model's learned temperature-irradiance relationship and physical thermal "
            "derating of the modules."
        ),
        "perturbations": [{"variable": "temperature_c", "mode": "delta", "value": 2.0}],
    },
    {
        "key": "heatwave",
        "name": "Heatwave +6 °C, calm",
        "kind": "meteorological",
        "description": (
            "Six degrees warmer with wind reduced by half. Isolates the compounding of "
            "thermal derating with the loss of convective cooling."
        ),
        "perturbations": [
            {"variable": "temperature_c", "mode": "delta", "value": 6.0},
            {"variable": "wind_speed_ms", "mode": "scale", "value": 0.5},
        ],
    },
    {
        "key": "increased_cloud",
        "name": "Cloudier conditions (+25 percentage points)",
        "kind": "meteorological",
        "description": (
            "Increases cloud cover by 25 percentage points, bounded at 100 %. Represents a "
            "persistently more overcast period."
        ),
        "perturbations": [{"variable": "cloud_cover_pct", "mode": "delta", "value": 25.0}],
    },
    {
        "key": "clearer_skies",
        "name": "Clearer skies (−25 percentage points)",
        "kind": "meteorological",
        "description": "Reduces cloud cover by 25 percentage points, bounded at 0 %.",
        "perturbations": [{"variable": "cloud_cover_pct", "mode": "delta", "value": -25.0}],
    },
    {
        "key": "windy",
        "name": "Doubled wind speed",
        "kind": "meteorological",
        "description": (
            "Doubles wind speed. Chiefly a test of convective cooling: modules run cooler "
            "and therefore more efficiently."
        ),
        "perturbations": [{"variable": "wind_speed_ms", "mode": "scale", "value": 2.0}],
    },
)
