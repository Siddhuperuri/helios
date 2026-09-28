"""The project's model: XGBoost trained on measured plant output, fed by the NOCT model.

This is the pipeline the project abstract describes, served to the web interface:

    weather for the chosen place and hour (irradiance, air temperature, wind speed)
      -> panel temperature from the NOCT model, which is where wind cooling enters
      -> XGBoost on (irradiance, air temperature, panel temperature)
      -> energy for the 5 kW reference system, in kWh

The estimator is trained offline by ``train_model_plants.py`` at the repository root, on
measured inverter output from two solar plants rescaled to a 5 kW reference system, and
saved beside this module in ``artifacts/`` together with its hold-out results. Nothing is
trained per request, so a prediction takes as long as the weather fetch.

Two things differ from the platform's other models and are stated in every payload:

* **The labels are metered.** The other estimators learn from energy the PV chain computes
  from reanalysis weather; this one learns from measured generation.
* **It predicts for the reference system, not a declared array.** It was trained on one
  normalised scale, so a declared capacity other than 5 kW is reported, not applied.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.features.solar_geometry import PVSystem

MODEL_KEY = "xgboost_plants"
DISPLAY_NAME = "XGBoost (trained on measured plant output)"

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
DEFAULT_MODEL_PATH = ARTIFACT_DIR / "solar_xgboost_model_plants.joblib"

FEATURES = ("irradiance_w_m2", "air_temp_c", "module_temp_c")
REFERENCE_KW = 5.0
INTERVALS_PER_HOUR = 4          # the model predicts one 15-minute interval
# Training clipped each interval at 1.2x the inverter's rating, so an hour can never
# exceed four of those.
MAX_HOURLY_KWH = REFERENCE_KW * 1.2

# NOCT cell-temperature model. The standard form has no wind term; the (1 + 0.05 v)
# divisor is this project's simple wind-cooling correction, and is named as such wherever
# the formula is shown.
NOCT_C = 45.0
WIND_COOLING_PER_MS = 0.05
NOCT_FORMULA = (
    "NOCT model: T_module = T_air + (NOCT − 20) / 800 × G / (1 + 0.05 × v), NOCT = 45 °C"
)

# Safe-operating thresholds. 85 °C is the upper module temperature in the IEC 61215
# qualification tests; 20 m/s is a common stow threshold for mounted arrays.
MODULE_MAX_OPERATING_C = 85.0
HIGH_WIND_MS = 20.0

BASELINE_NAMES = {
    "random_forest": "Random Forest",
    "hist_gb": "Histogram Gradient Boosting",
    "extra_trees": "Extremely Randomized Trees",
    "ridge": "Ridge Regression",
    "stacking": "Stacking ensemble of the four",
}


class PlantModelUnavailable(RuntimeError):
    """The trained artifact is missing or cannot be loaded."""


@dataclass(frozen=True)
class PlantModel:
    estimator: Any
    metrics: dict[str, Any]
    path: Path


def _model_path() -> Path:
    override = os.environ.get("SOLAR_PLANT_MODEL_PATH", "").strip()
    return Path(override) if override else DEFAULT_MODEL_PATH


@lru_cache(maxsize=1)
def load() -> PlantModel:
    """Load the estimator and its hold-out results once per process."""
    path = _model_path()
    metrics_path = path.with_suffix("").with_suffix(".metrics.json")
    if not path.exists() or not metrics_path.exists():
        raise PlantModelUnavailable(
            f"The trained XGBoost model is not installed (expected {path.name} and "
            f"{metrics_path.name} in {path.parent}). Run `python train_model_plants.py` "
            f"from the repository root to create them."
        )
    try:
        import joblib

        estimator = joblib.load(path)
    except ImportError as exc:
        raise PlantModelUnavailable(
            f"The XGBoost model could not be loaded because a library is missing ({exc}). "
            f"Install the backend requirements, which include xgboost."
        ) from exc
    with open(metrics_path, encoding="utf-8") as fh:
        metrics = json.load(fh)
    return PlantModel(estimator=estimator, metrics=metrics, path=path)


def module_temperature(air_c: Any, irradiance_wm2: Any, wind_ms: Any) -> np.ndarray:
    """Panel temperature from the NOCT model, with the project's wind correction."""
    air = np.asarray(air_c, dtype=np.float64)
    g = np.clip(np.asarray(irradiance_wm2, dtype=np.float64), 0.0, None)
    v = np.clip(np.asarray(wind_ms, dtype=np.float64), 0.0, None)
    return air + (NOCT_C - 20.0) / 800.0 * g / (1.0 + WIND_COOLING_PER_MS * v)


def predict_hourly(
    irradiance_wm2: Any, air_c: Any, wind_ms: Any, *, daytime: Any
) -> dict[str, np.ndarray]:
    """Hourly energy for the 5 kW reference system, bounded as the training target was.

    Hours with the sun down are zero by construction: the plants log irradiance near zero
    at night, and the physical answer is known without asking the model.
    """
    model = load()
    g = np.asarray(irradiance_wm2, dtype=np.float64)
    air = np.asarray(air_c, dtype=np.float64)
    daytime = np.asarray(daytime, dtype=bool) & (g > 0.0)
    t_mod = module_temperature(air, g, wind_ms)

    X = pd.DataFrame({"irradiance_w_m2": g, "air_temp_c": air, "module_temp_c": t_mod})
    raw = np.asarray(model.estimator.predict(X[list(FEATURES)]), dtype=np.float64)
    raw = raw * INTERVALS_PER_HOUR
    kwh = np.clip(raw, 0.0, MAX_HOURLY_KWH)
    kwh[~daytime] = 0.0
    clipped = daytime & ((raw < 0.0) | (raw > MAX_HOURLY_KWH))
    return {"kwh": kwh, "module_temp_c": t_mod, "n_clipped": np.asarray(int(clipped.sum()))}


def interval(point_kwh: float, *, nominal_coverage: float, is_daytime: bool) -> dict[str, Any]:
    """An interval from the model's own hold-out errors, summed to hourly."""
    out: dict[str, Any] = {
        "lower_kwh": None,
        "upper_kwh": None,
        "nominal_coverage": nominal_coverage,
        "method": "",
    }
    if not is_daytime:
        out.update(lower_kwh=0.0, upper_kwh=0.0,
                   method="not applicable — the sun is below the horizon in this hour")
        return out

    residuals = np.asarray(load().metrics.get("hourly_residuals_kwh") or [], dtype=np.float64)
    if residuals.size < 30:
        out["method"] = "unavailable — too few hold-out residuals were saved with the model"
        return out

    tail = (1.0 - nominal_coverage) / 2.0
    lower = point_kwh + float(np.quantile(residuals, tail))
    upper = point_kwh + float(np.quantile(residuals, 1.0 - tail))
    out["lower_kwh"] = round(float(np.clip(lower, 0.0, MAX_HOURLY_KWH)), 3)
    out["upper_kwh"] = round(float(np.clip(upper, 0.0, MAX_HOURLY_KWH)), 3)
    out["method"] = (
        f"Empirical {nominal_coverage:.0%} quantiles of {residuals.size:,} hourly errors "
        f"measured on the held-out week (each inverter's four 15-minute intervals summed), "
        f"added to the point prediction."
    )
    return out


def operating_notes(
    irradiance_wm2: float, air_c: float, wind_ms: float, module_temp_c: float
) -> list[dict[str, Any]]:
    """Operating insights for one hour, each with its threshold stated."""
    coeff = abs(PVSystem().temperature_coefficient_per_c)
    still_air = float(module_temperature(air_c, irradiance_wm2, 0.0))
    cooling = still_air - module_temp_c

    safe = module_temp_c <= MODULE_MAX_OPERATING_C and wind_ms <= HIGH_WIND_MS
    problems = []
    if module_temp_c > MODULE_MAX_OPERATING_C:
        problems.append(f"panel temperature {module_temp_c:.1f} °C is above 85 °C")
    if wind_ms > HIGH_WIND_MS:
        problems.append(f"wind of {wind_ms:.1f} m/s is above 20 m/s")
    notes: list[dict[str, Any]] = [
        {
            "key": "operating_range",
            "title": "Safe operating range",
            "severity": "info" if safe else "warn",
            "value": round(module_temp_c, 1),
            "unit": "°C panel",
            "threshold": "Panel ≤ 85 °C (IEC 61215 test limit) and wind ≤ 20 m/s (stow threshold)",
            "message": (
                f"Within the safe operating range: panel at {module_temp_c:.1f} °C, "
                f"wind {wind_ms:.1f} m/s."
                if safe
                else "Outside the safe operating range: " + "; ".join(problems) + "."
            ),
        }
    ]

    if irradiance_wm2 > 0:
        notes.append(
            {
                "key": "wind_cooling",
                "title": "Wind cooling",
                "severity": "info",
                "value": round(cooling, 1),
                "unit": "°C cooler",
                "threshold": NOCT_FORMULA + " (the wind term is this project's correction)",
                "message": (
                    f"Wind of {wind_ms:.1f} m/s keeps the panels {cooling:.1f} °C cooler than "
                    f"still air would ({still_air:.1f} °C → {module_temp_c:.1f} °C), worth "
                    f"about {cooling * coeff * 100:.1f}% of output at a "
                    f"{coeff * 100:.2f}%/°C temperature coefficient."
                ),
            }
        )
        derate = coeff * max(0.0, module_temp_c - 25.0) * 100.0
        notes.append(
            {
                "key": "thermal_derating",
                "title": "Thermal derating",
                "severity": "warn" if derate > 12.0 else "info",
                "value": round(module_temp_c, 1),
                "unit": "°C",
                "threshold": "25 °C reference cell temperature",
                "message": (
                    f"At {module_temp_c:.1f} °C the panels run about {derate:.1f}% below their "
                    f"rated efficiency."
                ),
            }
        )
    else:
        notes.append(
            {
                "key": "wind_cooling",
                "title": "Wind cooling",
                "severity": "info",
                "value": 0.0,
                "unit": "°C cooler",
                "threshold": NOCT_FORMULA,
                "message": "No sunlight this hour, so the panels are not heated and wind has "
                           "nothing to cool.",
            }
        )
    return notes


def baselines() -> list[dict[str, Any]]:
    """The project model and its baselines, as scored on the same held-out week."""
    m = load().metrics
    rows = [
        {
            "model": MODEL_KEY,
            "display_name": "XGBoost",
            "r2": round(float(m["holdout"]["r2"]), 4),
            "mae_kwh": round(float(m["holdout"]["mae_kwh"]), 4),
            "is_project_model": True,
        }
    ]
    for b in m.get("baselines", []):
        rows.append(
            {
                "model": b["model"],
                "display_name": BASELINE_NAMES.get(b["model"], b["model"]),
                "r2": round(float(b["r2"]), 4),
                "mae_kwh": round(float(b["mae_kwh"]), 4),
                "is_project_model": False,
            }
        )
    return rows


def cross_plant_range() -> tuple[float, float] | None:
    values = [float(c["r2"]) for c in load().metrics.get("cross_plant", [])]
    return (min(values), max(values)) if values else None
