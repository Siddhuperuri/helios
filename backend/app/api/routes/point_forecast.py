"""Energy for one hour, at one place, on one date.

The gap this closes
-------------------
Nothing else in the platform accepts a target *datetime*. ``start_date`` and ``end_date``
on an analysis bound the period a model is trained on; ``/analysis/{id}/forecast`` runs
forward from now over a horizon. Neither answers "how much will this array make at two
o'clock on the fourteenth", which is the question the interface has always implied and
never actually asked.

What this endpoint does
-----------------------
1. Resolve the place, and the hour, in the location's own time zone.
2. Train on archive data ending strictly **before** that hour, with ``target="pv_kwh"`` so
   the model predicts kilowatt-hours rather than irradiance that something else converts.
3. Predict the target hour and the rest of its local day.
4. Bound the result physically, attach an interval, and — when the model is the ensemble —
   report what each of its four base models contributed.

The leakage rule is the load-bearing part. The training window ends the day before the
target date, so no observation the model was fitted on is contemporaneous with or later
than the hour being predicted. The platform's ordinary guards are unchanged underneath
that: chronological split, 24-hour embargo, no lagged targets, night hours excluded.

Two honesty notes travel in the payload rather than living only here. The labels are
modelled by the PV chain from reanalysis weather and are not metered generation
(README §10, limitation 2). And the target hour's *weather* comes from the archive too, so
this is a hindcast of a historical hour, not a forecast of a future one — which is exactly
why an uncovered datetime is refused rather than quietly extrapolated.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from app.api.service import create_analysis, to_pv_system
from app.config import get_settings
from app.data.sources import (
    DataSourceError,
    Location,
    fetch_archive,
    latest_available_archive_date,
    resolve_location,
)
from app.features.pipeline import HOURS_PER_INTERVAL, build_features
from app.models import registry
from app.models.forecast import operating_conditions
from app.schemas.point_forecast import PointForecastRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["point-forecast"])

# The hour is predicted from archive weather, so the whole local day is fetched around it.
# One day either side covers every UTC offset without arithmetic on the offset itself.
_DAY_MARGIN = timedelta(days=1)


def _zone(location: Location) -> tuple[Any, str]:
    """The time zone a bare local datetime should be read in, and where it came from.

    Geocoding by name supplies an IANA zone; a dropped map pin or a GPS fix does not. In
    the second case the zone is approximated from longitude at fifteen degrees per hour,
    which is right to within an hour almost everywhere and can be wrong by more where
    political boundaries and solar time disagree. The caller is told which of the two they
    got rather than being left to assume.
    """
    name = (location.timezone or "").strip()
    if name:
        try:
            return ZoneInfo(name), f"IANA zone '{name}' from the location service"
        except (ZoneInfoNotFoundError, ValueError):
            logger.info("Unknown time zone '%s'; approximating from longitude", name)

    offset_hours = int(round(location.longitude / 15.0))
    offset_hours = max(-12, min(14, offset_hours))
    return (
        timezone(timedelta(hours=offset_hours)),
        (
            f"approximated from longitude as UTC{offset_hours:+d}; this location carries no "
            f"time-zone name, so civil time may differ by an hour or more"
        ),
    )


def _coverage_window() -> tuple[date, date]:
    """The first and last dates a target hour may fall on."""
    settings = get_settings()
    latest = latest_available_archive_date()
    # Enough history has to exist *before* the target for a model to be trained at all.
    earliest = date.fromisoformat(settings.limits.earliest_date) + timedelta(
        days=settings.limits.min_training_days + 1
    )
    return earliest, latest


def _residual_interval(
    predictions: pd.DataFrame,
    point_kwh: float,
    *,
    nominal_coverage: float,
    ceiling_kwh: float,
    is_daytime: bool,
) -> dict[str, Any]:
    """An interval carried over from the hold-out residuals, in kWh.

    Empirical quantiles of the validated residuals rather than a fresh quantile fit: the
    residuals were measured on data the model never saw, and refitting quantile models for
    a single hour would multiply the request's cost for a narrower gain than it sounds.
    The method is named in the payload so nobody has to guess which it was.

    A night hour gets a zero-width interval rather than a missing one — there is no
    uncertainty about an array that is producing nothing.
    """
    interval: dict[str, Any] = {
        "lower_kwh": None,
        "upper_kwh": None,
        "nominal_coverage": nominal_coverage,
        "method": "",
    }

    if not is_daytime:
        interval["lower_kwh"] = 0.0
        interval["upper_kwh"] = 0.0
        interval["method"] = "not applicable — the sun is below the horizon in this hour"
        return interval

    if predictions.empty or "residual_kwh" not in predictions.columns:
        interval["method"] = "unavailable — no validated residuals were produced"
        return interval

    residuals = predictions["residual_kwh"].to_numpy(dtype=np.float64)
    residuals = residuals[np.isfinite(residuals)]
    if residuals.size < 30:
        interval["method"] = "unavailable — too few validated residuals to form a quantile"
        return interval

    tail = (1.0 - nominal_coverage) / 2.0
    lower = point_kwh + float(np.quantile(residuals, tail))
    upper = point_kwh + float(np.quantile(residuals, 1.0 - tail))

    interval["lower_kwh"] = round(float(np.clip(lower, 0.0, ceiling_kwh)), 3)
    interval["upper_kwh"] = round(float(np.clip(upper, 0.0, ceiling_kwh)), 3)
    interval["method"] = (
        f"Empirical {nominal_coverage:.0%} quantiles of {residuals.size:,} hold-out "
        f"residuals in kWh, added to the point prediction."
    )
    return interval


@router.post("/point-forecast")
def point_forecast(request: PointForecastRequest) -> dict[str, Any]:
    """Predict AC energy for one hour at one location, training only on earlier data.

    The response carries the hour's energy and its day's total, the three weather
    parameters that drive them, the resolved place, the operating notes, a prediction
    interval, and — for the ensemble — each base model's own prediction alongside the
    blended one.
    """
    settings = get_settings()
    system = to_pv_system(request.system)

    location = resolve_location(
        query=request.location.query,
        latitude=request.location.latitude,
        longitude=request.location.longitude,
    )
    tzinfo, tz_source = _zone(location)

    # ------------------------------------------------------------------ the target hour
    #
    # Flooring happens in UTC, not in local time, because the archive is hourly *on UTC
    # hours*. In a zone offset by a whole number of hours the two are the same operation;
    # in one offset by thirty minutes they are not, and flooring locally would name an
    # instant the archive has no record for. The resolved hour is echoed back in both
    # frames so a caller in such a zone can see that 13:00 was answered as 12:30.
    requested = request.target_datetime
    aware = requested.replace(tzinfo=tzinfo) if requested.tzinfo is None else requested
    target_utc = pd.Timestamp(aware).tz_convert("UTC").floor("h")
    local_target = target_utc.tz_convert(tzinfo)
    target_date = local_target.date()

    earliest_date, latest_date = _coverage_window()
    if not earliest_date <= target_date <= latest_date:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{target_date.isoformat()} is outside the period this platform can answer "
                f"for. The prediction is made from reanalysis weather, which is published "
                f"on a delay of about {settings.limits.archive_lag_days} days and needs at "
                f"least {settings.limits.min_training_days} days of history before the "
                f"target. Choose a date between {earliest_date.isoformat()} and "
                f"{latest_date.isoformat()}."
            ),
        )

    # ---------------------------------------------------------------------- the model
    #
    # Training ends the day before the target date, so every observation the model sees
    # predates the hour being predicted. Day granularity rather than hour granularity is
    # deliberate: it is unambiguously "strictly before", and it means two requests for
    # different hours of the same day reuse one trained model instead of training twice.
    training_end = target_date - timedelta(days=1)

    try:
        analysis, notes = create_analysis(
            location_query=None,
            latitude=location.latitude,
            longitude=location.longitude,
            start=None,
            end=training_end,
            model_key=request.model_key,
            target="pv_kwh",
            system=system,
            horizon_hours=24,
            test_fraction=0.2,
            cv_splits=settings.modelling.cv_splits,
            nominal_coverage=request.nominal_coverage,
            # A single hour does not need cross-validated fold statistics or a conformal
            # quantile fit, and both are expensive. The hold-out split still runs, which is
            # what the interval and the reported error come from.
            compute_intervals=False,
            run_cv=False,
        )
    except DataSourceError:
        # Rendered by the application-level handler in the platform's standard envelope.
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    training = analysis.training

    # ------------------------------------------------------- weather for the target day
    raw_day = fetch_archive(location, target_date - _DAY_MARGIN, target_date + _DAY_MARGIN)
    day_features = build_features(
        raw_day,
        location,
        target="pv_kwh",
        system=system,
        feature_names=tuple(training.feature_names),
        daytime_only=False,  # the target hour may be at dusk, and the day total needs both
    )

    frame = day_features.frame
    local_index = frame.index.tz_convert(tzinfo)
    day_frame = frame[local_index.date == target_date]
    if day_frame.empty:
        raise HTTPException(
            status_code=422,
            detail=(
                f"The archive returned no complete hourly records for "
                f"{target_date.isoformat()} at {location.label}. Reanalysis is occasionally "
                f"incomplete near the publication boundary; try a slightly earlier date."
            ),
        )

    if target_utc not in day_frame.index:
        raise HTTPException(
            status_code=422,
            detail=(
                f"The archive has no complete record for "
                f"{local_target.strftime('%Y-%m-%d %H:%M')} at {location.label}. Every "
                f"weather input has to be present — nothing is imputed — so this hour "
                f"cannot be predicted. Try another hour on the same day."
            ),
        )

    # ------------------------------------------------------------------------ predict
    ac_capacity_kwh = system.ac_capacity_kw * HOURS_PER_INTERVAL
    day_is_daytime = day_frame["is_daytime"].to_numpy(dtype=bool)
    X_day = day_frame[training.feature_names].to_numpy(dtype=np.float64)

    def _bounded(values: np.ndarray, daytime: np.ndarray) -> np.ndarray:
        """The same constraints the trainer applies: no negative energy, no over-rating.

        Night is zero by construction rather than by prediction. The model never saw a
        night hour — they are excluded at zenith >= 87 deg — so asking it about one would
        be extrapolation, and the physical answer is known anyway.
        """
        out = np.clip(values, 0.0, ac_capacity_kwh)
        out[~daytime] = 0.0
        return out

    raw_day_pred = np.zeros(len(day_frame), dtype=np.float64)
    if day_is_daytime.any():
        raw_day_pred[day_is_daytime] = training.estimator.predict(X_day[day_is_daytime])
    day_kwh = _bounded(raw_day_pred, day_is_daytime)
    n_clipped = int(
        np.sum(
            day_is_daytime
            & ((raw_day_pred < 0.0) | (raw_day_pred > ac_capacity_kwh))
        )
    )

    position = int(day_frame.index.get_loc(target_utc))
    hour_is_daytime = bool(day_is_daytime[position])
    kwh_hour = float(day_kwh[position])

    interval = _residual_interval(
        training.predictions,
        kwh_hour,
        nominal_coverage=request.nominal_coverage,
        ceiling_kwh=ac_capacity_kwh,
        is_daytime=hour_is_daytime,
    )

    # --------------------------------------------------------- per-base-model breakdown
    contributions = registry.base_model_predictions(
        training.estimator, X_day[position : position + 1]
    )
    per_model: list[dict[str, Any]] = []
    if contributions:
        for entry in contributions:
            raw = entry.get("prediction")
            value = (
                float(np.clip(raw, 0.0, ac_capacity_kwh))
                if raw is not None and hour_is_daytime
                else 0.0
            )
            per_model.append(
                {
                    "model": entry["model"],
                    "display_name": entry["display_name"],
                    "weight": round(entry["weight"], 4),
                    "weight_share": (
                        round(entry["weight_share"], 4)
                        if entry["weight_share"] is not None
                        else None
                    ),
                    "kwh_hour": round(value, 3),
                }
            )

    # -------------------------------------------------------------------- the payload
    weather = day_frame.loc[target_utc]
    observed_day_kwh = float(day_frame["pv_kwh"].sum())

    warnings = list(training.warnings)
    warnings.extend(notes)
    if not hour_is_daytime:
        warnings.append(
            f"The sun is below the horizon at {local_target.strftime('%H:%M')} local time "
            f"(solar zenith {float(weather['solar_zenith_deg']):.1f}°), so the array "
            f"produces nothing in this hour. The day total below is unaffected."
        )
    if len(day_frame) < 24:
        warnings.append(
            f"Only {len(day_frame)} of 24 hours were available for "
            f"{target_date.isoformat()}, so the daily total covers part of the day."
        )
    if n_clipped:
        warnings.append(
            f"{n_clipped} predicted hour(s) fell outside physical bounds and were clipped "
            f"to [0, {ac_capacity_kwh:.2f}] kWh."
        )

    return {
        "kwh_hour": round(kwh_hour, 3),
        "kwh_day": round(float(day_kwh.sum()), 3),
        "ghi_wm2": round(float(weather["ghi_wm2"]), 1),
        "air_temperature_c": round(float(weather["temperature_c"]), 1),
        "wind_speed_ms": round(float(weather["wind_speed_ms"]), 2),
        "latitude": location.latitude,
        "longitude": location.longitude,
        "resolved_place_name": location.label,
        "location": location.to_dict(),
        "model_key": training.model_key,
        "model_display_name": training.model_display_name,
        "per_model": per_model,
        "per_model_note": (
            "Each base model's own prediction for this hour, with the weight the "
            "meta-learner learned for it. The ensemble figure is not their average: the "
            "weights are fitted, and a negative one means that model is used to correct "
            "another rather than to predict directly."
            if per_model
            else (
                f"'{training.model_key}' is a single estimator, so there are no base-model "
                f"contributions to report. Request model_key='ensemble_four' for the "
                f"four-model breakdown."
            )
        ),
        "interval": interval,
        "operating_conditions": operating_conditions(day_frame, system),
        "target": {
            "requested": request.target_datetime.isoformat(),
            "resolved_local": local_target.isoformat(),
            "resolved_utc": target_utc.isoformat(),
            "timezone": str(tzinfo),
            "timezone_source": tz_source,
            "is_daytime": hour_is_daytime,
            "solar_zenith_deg": round(float(weather["solar_zenith_deg"]), 2),
            "weather_regime": str(weather["weather_regime"]),
        },
        "system": system.describe(),
        "hours_in_day": int(len(day_frame)),
        "n_clipped_to_physical_bounds": n_clipped,
        "reference": {
            "physics_chain_kwh": round(float(day_frame["pv_kwh"].iloc[position]), 3),
            "physics_chain_day_kwh": round(observed_day_kwh, 3),
            "description": (
                "The PV chain run over the observed weather for this hour — the quantity "
                "the model was trained to reproduce, not a metered reading. Shown so the "
                "model's error on this specific hour is visible rather than implied."
            ),
        },
        "training": {
            "analysis_id": analysis.analysis_id,
            "period_start": training.manifest.get("dataset", {}).get("period_start"),
            "period_end": training.manifest.get("dataset", {}).get("period_end"),
            "n_train": training.manifest.get("validation", {}).get("n_train"),
            "n_test": training.manifest.get("validation", {}).get("n_test"),
            "hold_out_rmse_kwh": training.test_metrics_physical.get("rmse"),
            "hold_out_mae_kwh": training.test_metrics_physical.get("mae"),
            "hold_out_r2": training.test_metrics_physical.get("r2"),
            "skill_scores": training.skill_scores,
            "leakage_rule": (
                f"Trained only on data through {training_end.isoformat()}, which ends "
                f"strictly before the target hour. Chronological split with a "
                f"{settings.modelling.cv_gap_hours}-hour embargo; no lagged target values."
            ),
        },
        "label_provenance": (
            "The model was trained on hourly energy produced by the deterministic PV chain "
            "(Erbs → HDKR → Faiman → PVWatts v5 → inverter) applied to reanalysis weather "
            "for the declared array. These labels are modelled, not metered: no measured "
            "generation was available. See README §10, limitation 2."
        ),
        "warnings": warnings,
    }
