"""The live forecast endpoint.

A separate router rather than an addition to ``estimate.py``, so that this feature is
additive in the literal sense: nothing in the existing estimate surface changes shape, and
removing this file plus its one registration line removes the feature completely.

Access follows the same rule as reading the estimate itself — the opaque identifier in the
URL is the capability. Somebody holding a link can see the forecast for that system, which
is the same thing they can already see by reading the estimate.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.data.sources import DataSourceError, Location
from app.estimate import live_forecast as live_forecast_mod
from app.estimate import store as estimate_store
from app.features.solar_geometry import PVSystem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["live-forecast"])


def _location_from_payload(payload: dict[str, Any]) -> Location:
    """Rebuild the resolved location from a stored estimate.

    ``label`` is deliberately not passed: it is a computed property on :class:`Location`,
    not a field, and handing it to the constructor would raise.
    """
    stored = payload.get("location") or {}
    latitude = stored.get("latitude")
    longitude = stored.get("longitude")
    if latitude is None or longitude is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This estimate does not carry the coordinates a forecast needs. Run a new "
                "estimate to get one."
            ),
        )

    return Location(
        latitude=float(latitude),
        longitude=float(longitude),
        name=str(stored.get("name") or "this location"),
        country=stored.get("country"),
        country_code=stored.get("country_code"),
        admin1=stored.get("admin1"),
        elevation_m=stored.get("elevation_m"),
        timezone=stored.get("timezone"),
        source=str(stored.get("source") or "stored"),
    )


def _system_from_payload(payload: dict[str, Any]) -> PVSystem:
    """Rebuild the declared PV system from a stored estimate.

    Every key read here comes from ``PVSystem.describe()``, which is what the engine
    embeds under ``payload["system"]``. Defaults match the dataclass, so an estimate saved
    before a field existed still resolves rather than failing.
    """
    stored = payload.get("system") or {}

    def _number(key: str, default: float) -> float:
        value = stored.get(key)
        return float(value) if isinstance(value, (int, float)) else default

    # `dc_capacity_kwp` is the system's own declaration; `capacity_kwp` is the sized
    # figure the engine records alongside it. They agree, and the first is preferred
    # because it is the name PVSystem itself uses.
    capacity = stored.get("dc_capacity_kwp")
    if not isinstance(capacity, (int, float)):
        capacity = stored.get("capacity_kwp")
    if not isinstance(capacity, (int, float)) or capacity <= 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "This estimate does not declare a system size, so a forecast cannot be "
                "produced for it. Run a new estimate to get one."
            ),
        )

    ac_capacity = stored.get("ac_capacity_kw")
    try:
        return PVSystem(
            dc_capacity_kwp=float(capacity),
            surface_tilt_deg=_number("surface_tilt_deg", 20.0),
            surface_azimuth_deg=_number("surface_azimuth_deg", 180.0),
            temperature_coefficient_per_c=_number("temperature_coefficient_per_c", -0.0035),
            system_losses_fraction=_number("system_losses_fraction", 0.14),
            inverter_efficiency=_number("inverter_efficiency", 0.96),
            inverter_ac_capacity_kw=(
                float(ac_capacity) if isinstance(ac_capacity, (int, float)) else None
            ),
            albedo=_number("albedo", 0.2),
        )
    except ValueError as exc:
        # PVSystem validates its own ranges. A stored estimate that cannot rebuild into a
        # valid system is a data problem, not a server fault.
        logger.info("Stored system is not rebuildable: %s", exc)
        raise HTTPException(
            status_code=409,
            detail=(
                "This estimate's system details cannot be used for a forecast. Run a new "
                "estimate to get one."
            ),
        ) from exc


@router.get("/estimate/{estimate_id}/live-forecast")
def live_forecast(
    estimate_id: str,
    horizon_hours: int = Query(
        default=live_forecast_mod.DEFAULT_HORIZON_HOURS, ge=24, le=384
    ),
) -> dict[str, Any]:
    """Expected daily generation for the days ahead, for a saved estimate's system."""
    record = estimate_store.get(estimate_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "We could not find that estimate, so there is nothing to forecast for. "
                "The link may be incomplete."
            ),
        )

    location = _location_from_payload(record.payload)
    system = _system_from_payload(record.payload)

    try:
        return live_forecast_mod.physics_forecast(
            location, system, horizon_hours=horizon_hours
        )
    except DataSourceError:
        # Handled by the application-level handler, which already renders the upstream
        # failure in the platform's standard envelope.
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
