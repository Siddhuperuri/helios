"""Feature engineering: raw weather records to a model matrix.

A load-bearing design decision
------------------------------
**No lagged values of the target are used as features.**

This is not an oversight. The forecasting task this platform implements is the one all of
[P1], [P3] and [P5] actually perform: numerical weather prediction for a future hour is
available, and the model maps that weather onto irradiance for the same hour. Recent
*observed* irradiance is not available at a day-ahead issue time.

Adding a `ghi(t-1)` feature would improve every offline metric dramatically and would be
meaningless, because at a 24-hour horizon that value does not exist when the forecast is
made. It is the most common way solar-forecasting results are quietly inflated. The
persistence baselines in `evaluation.baselines` do use the last observed value — that is
exactly what makes them baselines, and they are held to the same horizon accounting.

The consequence is that reported skill is genuinely attainable at the stated horizon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.data.sources import Location
from app.features.solar_geometry import (
    DAYTIME_ZENITH_THRESHOLD_DEG,
    IRRADIANCE_INTERVAL_OFFSET_MINUTES,
    PVSystem,
    angle_of_incidence,
    clear_sky_ghi_haurwitz,
    clear_sky_index,
    extraterrestrial_normal,
    pv_power_chain,
    representative_times,
    solar_position,
)

# Targets the pipeline can build. ``clear_sky_index`` is the default and the recommended
# one; ``pv_kwh`` is the end-to-end energy target described in :func:`add_pv_energy`.
SUPPORTED_TARGETS: tuple[str, ...] = ("clear_sky_index", "ghi_wm2", "pv_kwh")

# The archive is hourly, so a mean power in kW over one interval is that many kWh. Named
# rather than written as a bare 1.0 so the assumption is visible if the resolution changes.
HOURS_PER_INTERVAL = 1.0

# The unit each target is measured in. Metrics are reported in these units directly; for
# ``pv_kwh`` that unit *is* the physical one, so nothing is converted back afterwards.
TARGET_UNITS: dict[str, str] = {
    "clear_sky_index": "dimensionless",
    "ghi_wm2": "W/m²",
    "pv_kwh": "kWh",
}

# Weather-regime thresholds, taken verbatim from Lyu & Eftekharnejad [P3, Sec. II-A]:
# "the data is considered to be of the 'sunny' type when the cloud cover is less than 25%;
#  otherwise, it is classified as 'cloudy' or 'other'. Precipitation and snowfall are then
#  used to differentiate between 'cloudy' and 'other'."
SUNNY_CLOUD_COVER_MAX_PCT = 25.0
PRECIPITATION_THRESHOLD_MM = 0.1


@dataclass
class FeatureSet:
    """A built model matrix together with everything needed to interpret it."""

    frame: pd.DataFrame
    feature_names: list[str]
    target_name: str
    location: Location
    day_mask: pd.Series
    dropped_rows: dict[str, int] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def X(self) -> pd.DataFrame:
        return self.frame[self.feature_names]

    @property
    def y(self) -> pd.Series:
        return self.frame[self.target_name]

    def describe(self) -> dict[str, Any]:
        return {
            "n_rows": int(len(self.frame)),
            "n_features": len(self.feature_names),
            "feature_names": list(self.feature_names),
            "target": self.target_name,
            "period_start": self.frame.index.min().isoformat() if len(self.frame) else None,
            "period_end": self.frame.index.max().isoformat() if len(self.frame) else None,
            "dropped_rows": dict(self.dropped_rows),
            "provenance": dict(self.provenance),
        }


def add_solar_geometry(
    frame: pd.DataFrame, location: Location, system: PVSystem | None = None
) -> pd.DataFrame:
    """Attach deterministic solar-geometry and clear-sky columns.

    These are computed rather than learned. Given a timestamp and a coordinate the sun's
    position is known exactly, and asking a statistical model to rediscover it from a
    clock feature wastes capacity and generalises worse.
    """
    out = frame.copy()
    system = system or PVSystem()

    # Solar position is evaluated at the midpoint of each averaging interval, not at its
    # label. See IRRADIANCE_INTERVAL_OFFSET_MINUTES for the empirical basis.
    times = representative_times(out.index)

    pos = solar_position(times, location.latitude, location.longitude)
    e0n = extraterrestrial_normal(times)

    out["solar_zenith_deg"] = pos.apparent_zenith
    out["solar_elevation_deg"] = pos.apparent_elevation
    out["solar_azimuth_deg"] = pos.azimuth
    out["cos_zenith"] = pos.cos_zenith
    out["declination_deg"] = pos.declination
    out["hour_angle_deg"] = pos.hour_angle
    out["extraterrestrial_normal_wm2"] = e0n
    out["extraterrestrial_horizontal_wm2"] = e0n * pos.cos_zenith

    out["aoi_deg"] = angle_of_incidence(
        system.surface_tilt_deg, system.surface_azimuth_deg, pos.apparent_zenith, pos.azimuth
    )
    out["cos_aoi"] = np.clip(np.cos(np.radians(out["aoi_deg"].to_numpy())), 0.0, None)

    out["clear_sky_ghi_wm2"] = clear_sky_ghi_haurwitz(pos.apparent_zenith)

    # Relative optical air mass (Kasten & Young 1989). Longer path means more attenuation.
    z = np.clip(pos.apparent_zenith, 0.0, 90.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        airmass = 1.0 / (
            np.cos(np.radians(z)) + 0.50572 * np.power(96.07995 - z, -1.6364)
        )
    out["air_mass"] = np.clip(np.nan_to_num(airmass, nan=0.0, posinf=40.0), 0.0, 40.0)

    out["is_daytime"] = pos.is_daytime

    if "ghi_wm2" in out.columns:
        out["clear_sky_index"] = clear_sky_index(
            out["ghi_wm2"].to_numpy(), out["clear_sky_ghi_wm2"].to_numpy()
        )

    return out


def add_temporal_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Cyclical encodings of clock and calendar position.

    Hour 23 and hour 0 are adjacent in time but maximally distant as integers. Encoding
    each cycle as a (sin, cos) pair restores that adjacency, which matters for the
    distance-based and linear models in the comparison set. Tree models are indifferent,
    so no model is disadvantaged by including them.
    """
    out = frame.copy()
    idx = out.index

    hour = idx.hour.to_numpy() + idx.minute.to_numpy() / 60.0
    out["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)

    doy = idx.dayofyear.to_numpy().astype(np.float64)
    out["doy_sin"] = np.sin(2.0 * np.pi * doy / 365.25)
    out["doy_cos"] = np.cos(2.0 * np.pi * doy / 365.25)

    out["month"] = idx.month.to_numpy()
    out["hour_of_day"] = idx.hour.to_numpy()

    return out


def add_pv_energy(
    frame: pd.DataFrame, location: Location, system: PVSystem | None = None
) -> pd.DataFrame:
    """Attach the AC energy a declared array would have produced, hour by hour.

    This is what makes ``pv_kwh`` a trainable target. The deterministic chain of
    :mod:`app.features.solar_geometry` — Erbs, HDKR, Faiman, PVWatts v5 — is run over the
    *observed* historical weather to produce one hourly AC energy label per row, and the
    model is then fitted to map weather and geometry straight onto that energy.

    What these labels are, stated plainly
    -------------------------------------
    **They are modelled, not metered.** The chain converts reanalysis irradiance into the
    output a declared system would have produced; no measured generation was available to
    fit against. Every figure downstream inherits that, which is why the model card says
    so and README §10 limitation 2 says so. A model trained here learns to reproduce the
    physics chain applied to real weather — useful, and not the same thing as learning
    from a real inverter.

    The labels depend on the declared array. Change the tilt, the azimuth or the capacity
    and the target changes with it, so a model trained for one system does not describe
    another.
    """
    out = frame.copy()
    system = system or PVSystem()

    if "ghi_wm2" not in out.columns:
        raise ValueError(
            "The PV energy target needs observed 'ghi_wm2' to run the conversion chain, "
            "and the dataset does not carry it."
        )

    pv = pv_power_chain(
        ghi=out["ghi_wm2"].to_numpy(dtype=np.float64),
        air_temp_c=out["temperature_c"].to_numpy(dtype=np.float64),
        wind_speed_ms=out["wind_speed_ms"].to_numpy(dtype=np.float64),
        times_utc=out.index.to_numpy(),
        latitude=location.latitude,
        longitude=location.longitude,
        system=system,
    )

    out["poa_wm2"] = pv.poa_wm2
    out["cell_temperature_c"] = pv.cell_temperature_c
    out["dc_power_kw"] = pv.dc_power_kw
    out["ac_power_kw"] = pv.ac_power_kw
    out["pv_kwh"] = pv.ac_power_kw * HOURS_PER_INTERVAL

    return out


def add_wind_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Decompose wind direction into orthogonal components.

    Direction is an angle: 359 deg and 1 deg are two degrees apart, but 358 units apart
    numerically. Sine and cosine components remove that discontinuity.
    """
    out = frame.copy()
    if "wind_direction_deg" in out.columns:
        rad = np.radians(out["wind_direction_deg"].to_numpy(dtype=np.float64))
        out["wind_dir_sin"] = np.sin(rad)
        out["wind_dir_cos"] = np.cos(rad)
    return out


def label_weather_regime(frame: pd.DataFrame) -> pd.Series:
    """Assign the sunny / cloudy / other regimes of [P3, Sec. II-A].

    Reported per-regime error is one of the more useful diagnostics this platform
    produces: aggregate accuracy hides the fact that clear-sky hours are close to
    trivial while broken cloud is where forecasts actually fail.
    """
    n = len(frame)
    regime = pd.Series(np.full(n, "cloudy", dtype=object), index=frame.index, name="weather_regime")

    cloud = frame.get("cloud_cover_pct")
    precip = frame.get("precipitation_mm")

    if cloud is not None:
        regime[cloud.to_numpy() < SUNNY_CLOUD_COVER_MAX_PCT] = "sunny"
    if precip is not None:
        regime[precip.to_numpy() > PRECIPITATION_THRESHOLD_MM] = "other"

    return regime


# Columns never offered to a model as a predictor.
# `dni`/`dhi` are components of GHI; `ghi` is a target; `clear_sky_index` and `pv_kwh` are
# the alternative targets. `pv_kwh` and every intermediate of the PV chain that produces it
# are here for the same reason: each is a monotone transform of the energy label, so a
# model handed one would be reading its own answer. Including any of them would be textbook
# target leakage.
LEAKAGE_EXCLUDED = frozenset(
    {
        "ghi_wm2",
        "dni_wm2",
        "dhi_wm2",
        "clear_sky_index",
        "poa_wm2",
        "cell_temperature_c",
        "dc_power_kw",
        "ac_power_kw",
        "energy_kwh",
        "pv_kwh",
        "is_daytime",
        "weather_regime",
    }
)

DEFAULT_FEATURES: tuple[str, ...] = (
    # Meteorological
    "temperature_c",
    "relative_humidity_pct",
    "dew_point_c",
    "surface_pressure_hpa",
    "wind_speed_ms",
    "wind_dir_sin",
    "wind_dir_cos",
    "cloud_cover_pct",
    "precipitation_mm",
    # Solar geometry (deterministic)
    "cos_zenith",
    "solar_zenith_deg",
    "solar_elevation_deg",
    "cos_aoi",
    "aoi_deg",
    "air_mass",
    "clear_sky_ghi_wm2",
    "extraterrestrial_horizontal_wm2",
    # Temporal
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
)


def build_features(
    raw: pd.DataFrame,
    location: Location,
    *,
    target: str = "clear_sky_index",
    system: PVSystem | None = None,
    feature_names: tuple[str, ...] | None = None,
    daytime_only: bool = True,
) -> FeatureSet:
    """Build the model matrix from a raw hourly weather frame.

    Parameters
    ----------
    target
        One of ``"clear_sky_index"`` (recommended), ``"ghi_wm2"``, or ``"pv_kwh"``. The
        first two are irradiance targets; ``pv_kwh`` is hourly AC energy for the declared
        array, built by :func:`add_pv_energy`, whose labels are modelled rather than
        metered — read that function before reporting anything derived from it.
    daytime_only
        Drop hours with apparent zenith >= 87 deg, per [P3]. Strongly recommended:
        night hours are trivially zero, and including them inflates R-squared because
        the day/night contrast dominates the total sum of squares. See
        docs/RESEARCH_SYNTHESIS.md, W4.
    """
    if target not in SUPPORTED_TARGETS:
        raise ValueError(
            f"Unsupported target '{target}'. Use one of: {', '.join(SUPPORTED_TARGETS)}."
        )

    if raw.empty:
        raise ValueError("Cannot build features from an empty dataset.")

    dropped: dict[str, int] = {}
    n_start = len(raw)
    system = system or PVSystem()

    frame = add_solar_geometry(raw, location, system)
    if target == "pv_kwh":
        frame = add_pv_energy(frame, location, system)
    frame = add_temporal_features(frame)
    frame = add_wind_components(frame)
    frame["weather_regime"] = label_weather_regime(frame)

    day_mask = frame["is_daytime"].astype(bool)

    if daytime_only:
        n_before = len(frame)
        frame = frame[day_mask]
        dropped["night_hours"] = n_before - len(frame)
        day_mask = day_mask[day_mask.index.isin(frame.index)]

    selected = list(feature_names) if feature_names else list(DEFAULT_FEATURES)

    leaked = [f for f in selected if f in LEAKAGE_EXCLUDED]
    if leaked:
        raise ValueError(
            "These columns are components of the target and cannot be used as predictors: "
            + ", ".join(leaked)
        )

    missing = [f for f in selected if f not in frame.columns]
    if missing:
        raise ValueError(
            "Requested features are not present in the dataset: " + ", ".join(missing)
        )

    if target not in frame.columns:
        raise ValueError(f"Target column '{target}' was not produced by the pipeline.")

    # Drop rows with an undefined target or any missing predictor. Nothing is imputed:
    # a fabricated predictor value would propagate into a reported metric.
    needed = selected + [target]
    n_before = len(frame)
    frame = frame.dropna(subset=needed)
    dropped["incomplete_rows"] = n_before - len(frame)

    if frame.empty:
        raise ValueError(
            "No complete observations remain after removing night hours and rows with "
            "missing values. Widen the date range or choose a different location."
        )

    provenance = {
        "source": raw.attrs.get("source"),
        "attribution": raw.attrs.get("attribution"),
        "retrieved_at": raw.attrs.get("retrieved_at"),
        "kind": raw.attrs.get("kind", "archive"),
        "elevation_m": raw.attrs.get("elevation_m"),
        "grid_latitude": raw.attrs.get("latitude"),
        "grid_longitude": raw.attrs.get("longitude"),
        "rows_retrieved": n_start,
        "daytime_only": daytime_only,
        "day_mask_threshold_deg": DAYTIME_ZENITH_THRESHOLD_DEG,
        "interval_offset_minutes": IRRADIANCE_INTERVAL_OFFSET_MINUTES,
        "target_lags_used": False,
        "target_lag_rationale": (
            "Lagged observations of the target are deliberately excluded; they are "
            "unavailable at a day-ahead issue time and would inflate offline metrics."
        ),
        "target_unit": TARGET_UNITS[target],
        "pv_system": system.describe(),
    }
    if target == "pv_kwh":
        provenance["target_construction"] = (
            "Hourly AC energy for the declared array, produced by running the "
            "deterministic PV chain (Erbs -> HDKR -> Faiman -> PVWatts v5 -> inverter) "
            "over the observed reanalysis weather. The labels are modelled, not metered: "
            "no measured generation was available. See README section 10, limitation 2."
        )

    return FeatureSet(
        frame=frame,
        feature_names=selected,
        target_name=target,
        location=location,
        day_mask=day_mask,
        dropped_rows=dropped,
        provenance=provenance,
    )
