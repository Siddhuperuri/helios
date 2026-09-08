"""The operational forecasting workflow.

This is what the reference application attempted: give it a place and a time, get back an
expected solar output. The differences are that here the requested time actually changes
the answer, the answer carries an interval, the PV system is declared, and every number
can be traced to the model run that produced it.

Forecast chain
--------------
1. Fetch numerical weather prediction for the requested horizon.
2. Build the same features the model was trained on, from that NWP.
3. Predict the clear-sky index, then multiply by clear-sky irradiance for the target hour.
4. Apply physical bounds.
5. Convert irradiance to AC power for the declared PV system.
6. Integrate power to energy over the requested period.

What the intervals do and do not cover
--------------------------------------
The interval reflects the model's error given the supplied weather. It does **not** include
error in the weather forecast itself, which grows with horizon and eventually dominates.
A day-7 interval is therefore materially narrower than the true uncertainty. This is stated
in the response payload, not buried, and the response degrades its own confidence label
beyond the validated horizon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.config import get_settings
from app.data.sources import Location, fetch_forecast
from app.features.pipeline import build_features
from app.features.solar_geometry import PVSystem, pv_power_chain
from app.models.trainer import CLEAR_SKY_CEILING_FACTOR, TrainingResult


@dataclass
class ForecastResult:
    """An operational forecast with its provenance and caveats."""

    frame: pd.DataFrame = field(repr=False)
    location: Location
    system: PVSystem
    horizon_hours: int
    issued_at: str
    model_key: str
    validated_horizon_hours: int
    warnings: list[str] = field(default_factory=list)
    daily: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    totals: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issued_at": self.issued_at,
            "horizon_hours": self.horizon_hours,
            "validated_horizon_hours": self.validated_horizon_hours,
            "beyond_validated_horizon": self.horizon_hours > self.validated_horizon_hours,
            "location": self.location.to_dict(),
            "system": self.system.describe(),
            "model": self.model_key,
            "series": _frame_to_records(self.frame),
            "daily": _frame_to_records(self.daily, index_name="date"),
            "totals": self.totals,
            "warnings": self.warnings,
            "provenance": self.provenance,
            "interval_scope": (
                "Prediction intervals describe the model's error given the supplied weather "
                "forecast. They do not include uncertainty in that weather forecast, which "
                "grows with horizon and dominates beyond roughly three days. Treat "
                "long-horizon intervals as a lower bound on true uncertainty."
            ),
        }


def _frame_to_records(frame: pd.DataFrame, *, index_name: str = "timestamp") -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.reset_index()
    first = out.columns[0]
    out = out.rename(columns={first: index_name})
    out[index_name] = out[index_name].astype(str)
    return out.replace({np.nan: None}).to_dict(orient="records")


def generate_forecast(
    *,
    trained: TrainingResult,
    location: Location,
    horizon_hours: int = 48,
    system: PVSystem | None = None,
    nominal_coverage: float = 0.8,
    interval_scale_from_residuals: bool = True,
) -> ForecastResult:
    """Produce a forward-looking forecast using an already-trained model."""
    settings = get_settings()
    system = system or PVSystem()
    warnings: list[str] = []

    validated = settings.limits.validated_horizon_hours
    if horizon_hours > validated:
        warnings.append(
            f"The requested horizon of {horizon_hours} hours exceeds the validated horizon "
            f"of {validated} hours. Accuracy beyond the validated range has not been "
            f"measured on this dataset and is expected to degrade."
        )

    nwp = fetch_forecast(location, horizon_hours=horizon_hours)

    # Keep only hours from now forward, out to the requested horizon.
    now = pd.Timestamp.now(tz="UTC").floor("h")
    end = now + pd.Timedelta(hours=horizon_hours)
    nwp = nwp[(nwp.index >= now) & (nwp.index <= end)]
    if nwp.empty:
        raise ValueError(
            "The weather service returned no forecast hours within the requested window."
        )

    fs = build_features(
        nwp,
        location,
        target="clear_sky_index",
        system=system,
        feature_names=tuple(trained.feature_names),
        daytime_only=False,  # keep night hours so the series is continuous for plotting
    )

    day_mask = fs.frame["is_daytime"].to_numpy(dtype=bool)
    X = fs.frame[trained.feature_names].to_numpy(dtype=np.float64)
    clear_sky = fs.frame["clear_sky_ghi_wm2"].to_numpy(dtype=np.float64)

    raw_pred = np.zeros(len(fs.frame), dtype=np.float64)
    if day_mask.any():
        raw_pred[day_mask] = trained.estimator.predict(X[day_mask])

    # This chain runs on irradiance: it predicts GHI, then converts it to power for the
    # declared array. A model trained directly on energy has no irradiance to hand over, so
    # it is turned away here rather than having its kilowatt-hours silently read as W/m².
    if trained.target_name == "clear_sky_index":
        ghi_pred = raw_pred * clear_sky
    elif trained.target_name == "ghi_wm2":
        ghi_pred = raw_pred
    else:
        raise ValueError(
            f"This forecast is built from predicted irradiance, and the model was trained "
            f"on '{trained.target_name}'. Re-run the analysis with target "
            f"'clear_sky_index' or 'ghi_wm2', or use POST /api/point-forecast, which "
            f"predicts energy for a single hour directly."
        )

    ghi_pred = np.clip(ghi_pred, 0.0, clear_sky * CLEAR_SKY_CEILING_FACTOR)
    ghi_pred[~day_mask] = 0.0

    # Interval width transferred from measured test-set residuals. Refitting quantile
    # models here would be more principled but far slower; scaling the validated residual
    # spread is transparent and stated as such.
    lower = np.zeros_like(ghi_pred)
    upper = np.zeros_like(ghi_pred)
    if interval_scale_from_residuals and not trained.predictions.empty:
        residuals = trained.predictions["residual_wm2"].to_numpy(dtype=np.float64)
        cs_test = trained.predictions["clear_sky_ghi_wm2"].to_numpy(dtype=np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.where(cs_test > 50.0, residuals / cs_test, np.nan)
        rel = rel[np.isfinite(rel)]
        if rel.size > 30:
            lo_q = np.quantile(rel, (1.0 - nominal_coverage) / 2.0)
            hi_q = np.quantile(rel, 1.0 - (1.0 - nominal_coverage) / 2.0)
            lower = np.clip(ghi_pred + lo_q * clear_sky, 0.0, clear_sky * CLEAR_SKY_CEILING_FACTOR)
            upper = np.clip(ghi_pred + hi_q * clear_sky, 0.0, clear_sky * CLEAR_SKY_CEILING_FACTOR)
        else:
            warnings.append(
                "Too few validated residuals to derive a prediction interval; the forecast "
                "is reported as a point estimate only."
            )
    lower[~day_mask] = 0.0
    upper[~day_mask] = 0.0

    times = fs.frame.index.to_numpy()
    temp = fs.frame["temperature_c"].to_numpy(dtype=np.float64)
    wind = fs.frame["wind_speed_ms"].to_numpy(dtype=np.float64)

    pv = pv_power_chain(
        ghi=ghi_pred,
        air_temp_c=temp,
        wind_speed_ms=wind,
        times_utc=times,
        latitude=location.latitude,
        longitude=location.longitude,
        system=system,
    )
    pv_lower = pv_power_chain(
        ghi=lower, air_temp_c=temp, wind_speed_ms=wind, times_utc=times,
        latitude=location.latitude, longitude=location.longitude, system=system,
    )
    pv_upper = pv_power_chain(
        ghi=upper, air_temp_c=temp, wind_speed_ms=wind, times_utc=times,
        latitude=location.latitude, longitude=location.longitude, system=system,
    )

    frame = pd.DataFrame(
        {
            "ghi_wm2": np.round(ghi_pred, 1),
            "ghi_lower_wm2": np.round(lower, 1),
            "ghi_upper_wm2": np.round(upper, 1),
            "clear_sky_ghi_wm2": np.round(clear_sky, 1),
            "clear_sky_index": np.round(np.where(clear_sky > 1.0, ghi_pred / np.maximum(clear_sky, 1e-9), 0.0), 3),
            "poa_wm2": np.round(pv.poa_wm2, 1),
            "ac_power_kw": np.round(pv.ac_power_kw, 3),
            "ac_power_lower_kw": np.round(pv_lower.ac_power_kw, 3),
            "ac_power_upper_kw": np.round(pv_upper.ac_power_kw, 3),
            "cell_temperature_c": np.round(pv.cell_temperature_c, 1),
            "temperature_c": np.round(temp, 1),
            "wind_speed_ms": np.round(wind, 2),
            "cloud_cover_pct": fs.frame["cloud_cover_pct"].to_numpy(),
            "solar_zenith_deg": np.round(fs.frame["solar_zenith_deg"].to_numpy(), 2),
            "is_daytime": day_mask,
            "weather_regime": fs.frame["weather_regime"].to_numpy(),
        },
        index=fs.frame.index,
    )
    frame.index.name = "timestamp"

    # Hourly power in kW integrated over one-hour steps gives kWh directly.
    daily = frame.groupby(frame.index.date).agg(
        energy_kwh=("ac_power_kw", "sum"),
        energy_lower_kwh=("ac_power_lower_kw", "sum"),
        energy_upper_kwh=("ac_power_upper_kw", "sum"),
        peak_power_kw=("ac_power_kw", "max"),
        mean_ghi_wm2=("ghi_wm2", "mean"),
        peak_ghi_wm2=("ghi_wm2", "max"),
        daylight_hours=("is_daytime", "sum"),
    )
    daily = daily.round(
        {"energy_kwh": 2, "energy_lower_kwh": 2, "energy_upper_kwh": 2,
         "peak_power_kw": 3, "mean_ghi_wm2": 1, "peak_ghi_wm2": 1}
    )
    daily.index.name = "date"

    # A day is only comparable with others if it is fully covered by the forecast window.
    complete_days = daily[daily["daylight_hours"] > 0]
    best_day = complete_days["energy_kwh"].idxmax() if not complete_days.empty else None
    worst_day = complete_days["energy_kwh"].idxmin() if not complete_days.empty else None

    total_energy = float(frame["ac_power_kw"].sum())
    totals = {
        "energy_kwh": round(total_energy, 2),
        "energy_lower_kwh": round(float(frame["ac_power_lower_kw"].sum()), 2),
        "energy_upper_kwh": round(float(frame["ac_power_upper_kw"].sum()), 2),
        "peak_power_kw": round(float(frame["ac_power_kw"].max()), 3),
        "peak_power_at": str(frame["ac_power_kw"].idxmax()),
        "specific_yield_kwh_per_kwp": round(total_energy / system.dc_capacity_kwp, 2),
        "capacity_factor": round(
            total_energy / (system.ac_capacity_kw * len(frame)), 4
        ) if len(frame) else None,
        "mean_daily_energy_kwh": round(float(complete_days["energy_kwh"].mean()), 2) if not complete_days.empty else None,
        "best_day": str(best_day) if best_day is not None else None,
        "worst_day": str(worst_day) if worst_day is not None else None,
        "inverter_clipping_fraction": round(pv.clipped_fraction, 4),
        "period_start": str(frame.index.min()),
        "period_end": str(frame.index.max()),
        "n_hours": int(len(frame)),
        "n_daylight_hours": int(day_mask.sum()),
    }

    if pv.clipped_fraction > 0.05:
        warnings.append(
            f"The inverter limits output in {pv.clipped_fraction * 100:.1f}% of daylight "
            f"hours. Energy above {system.ac_capacity_kw:.2f} kW AC is not delivered — "
            f"consider whether the declared DC/AC ratio matches the real system."
        )

    provenance = {
        "weather_source": nwp.attrs.get("source"),
        "weather_kind": "numerical weather prediction (forecast)",
        "attribution": nwp.attrs.get("attribution"),
        "retrieved_at": nwp.attrs.get("retrieved_at"),
        "model_manifest": trained.manifest,
        "model_test_rmse_wm2": trained.test_metrics_physical.get("rmse"),
        "model_test_mae_wm2": trained.test_metrics_physical.get("mae"),
        "interval_method": (
            "Empirical quantiles of validated test-set residuals, expressed relative to "
            "clear-sky irradiance and reapplied to the forecast hours."
        ),
        "pv_chain": (
            "Erbs decomposition -> HDKR transposition -> Faiman cell temperature -> "
            "PVWatts v5 DC model -> inverter efficiency and AC clipping."
        ),
    }

    return ForecastResult(
        frame=frame,
        location=location,
        system=system,
        horizon_hours=horizon_hours,
        issued_at=datetime.now(timezone.utc).isoformat(),
        model_key=trained.model_key,
        validated_horizon_hours=validated,
        warnings=warnings,
        daily=daily,
        totals=totals,
        provenance=provenance,
    )


def operating_conditions(frame: pd.DataFrame, system: PVSystem) -> list[dict[str, Any]]:
    """Derive operating notes from the forecast, each with its threshold shown.

    The reference application displayed "Safe Operation" with no stated criteria and
    returned the same verdict for a 28 °C site and an 8 °C one. Every note here names the
    quantity, the threshold, and the physical consequence, so a reader can disagree with
    the threshold rather than having to trust the label.
    """
    notes: list[dict[str, Any]] = []
    day = frame[frame["is_daytime"]]
    if day.empty:
        return notes

    # Thermal derating. PVWatts references efficiency to 25 °C cell temperature.
    peak_cell = float(day["cell_temperature_c"].max())
    if np.isfinite(peak_cell):
        derate_pct = abs(system.temperature_coefficient_per_c) * max(0.0, peak_cell - 25.0) * 100.0
        notes.append(
            {
                "key": "thermal_derating",
                "title": "Thermal derating",
                "severity": "warn" if derate_pct > 12.0 else "info",
                "value": round(peak_cell, 1),
                "unit": "°C",
                "threshold": "25 °C reference cell temperature",
                "message": (
                    f"Peak module temperature reaches {peak_cell:.1f} °C, about "
                    f"{derate_pct:.1f}% below rated efficiency at a temperature "
                    f"coefficient of {system.temperature_coefficient_per_c * 100:.2f}%/°C."
                ),
            }
        )

    # Wind cooling — the mechanism the project abstract refers to, quantified.
    mean_wind = float(day["wind_speed_ms"].mean())
    notes.append(
        {
            "key": "wind_cooling",
            "title": "Wind cooling",
            "severity": "info",
            "value": round(mean_wind, 2),
            "unit": "m/s",
            "threshold": "Faiman model: T_cell = T_air + POA / (25.0 + 6.84·v)",
            "message": (
                f"Mean daytime wind of {mean_wind:.2f} m/s raises the convective heat-loss "
                f"coefficient to {25.0 + 6.84 * mean_wind:.1f} W/m²K, holding modules "
                f"{float((day['cell_temperature_c'] - day['temperature_c']).mean()):.1f} °C "
                f"above ambient on average."
            ),
        }
    )

    # High wind. 20 m/s is a common operational threshold for tracker stow.
    max_wind = float(day["wind_speed_ms"].max())
    if max_wind > 20.0:
        notes.append(
            {
                "key": "high_wind",
                "title": "High wind",
                "severity": "warn",
                "value": round(max_wind, 2),
                "unit": "m/s",
                "threshold": "20 m/s — a common tracker stow threshold",
                "message": (
                    f"Forecast wind reaches {max_wind:.1f} m/s. Tracking systems commonly "
                    f"stow above 20 m/s; verify the threshold for the installed hardware."
                ),
            }
        )

    # Variability — the regime [P3] identifies as hardest to forecast.
    kt = day["clear_sky_index"].to_numpy(dtype=np.float64)
    if kt.size > 3:
        variability = float(np.std(np.diff(kt)))
        notes.append(
            {
                "key": "variability",
                "title": "Expected variability",
                "severity": "warn" if variability > 0.15 else "info",
                "value": round(variability, 3),
                "unit": "clear-sky index, hour-to-hour σ",
                "threshold": "0.15 — above this, ramping is material",
                "message": (
                    f"Hour-to-hour clear-sky-index changes have a standard deviation of "
                    f"{variability:.3f}. "
                    + (
                        "Broken-cloud conditions like these are where forecast error is "
                        "largest [P3]."
                        if variability > 0.15
                        else "Conditions are relatively stable across the period."
                    )
                ),
            }
        )

    return notes
