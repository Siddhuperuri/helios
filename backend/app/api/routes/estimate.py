"""Consumer estimate endpoints.

One call produces a complete answer. That is a deliberate contrast with the research
surface next door, where an analysis is created and then interrogated through a dozen
follow-up requests: an analyst wants to pull on threads, while somebody who just told us
about their farm wants the answer.

Every route here returns errors in the same structured envelope the rest of the API uses —
message, detail, remedy — because §30 requires a human-readable failure and the frontend
renders that envelope directly.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.auth.deps import current_user, optional_user
from app.data.sources import DataSourceError, reverse_geocode
from app.db.models import User
from app.estimate import engine, personas, report, sizing
from app.estimate import store as estimate_store
from app.observability import metrics
from app.schemas.estimate import (
    AreaSpec,
    CompareRequest,
    EstimateRequest,
    EstimateUpdateRequest,
    RenameRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["estimate"])


# --------------------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------------------

def _require_estimate(estimate_id: str) -> estimate_store.StoredEstimate:
    record = estimate_store.get(estimate_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "We could not find that estimate. The link may be incomplete, or the "
                "estimate may have been deleted. Running a new one takes a minute or two."
            ),
        )
    return record


def _require_write_access(
    record: estimate_store.StoredEstimate, user: User | None
) -> None:
    """Decide whether this caller may change this estimate.

    The rule, and why it is this rule:

    *An estimate with no owner* is writable by whoever holds the link, exactly as it was
    before accounts existed. That is what keeps the anonymous flow whole — the result page
    lets you rename an estimate, edit its assumptions and delete it, and none of that
    should suddenly require signing up.

    *An estimate with an owner* is readable by whoever holds the link and writable only by
    its owner. Reading has to stay open, or every link already sent to an installer would
    break. Writing must not be, or anybody holding a link could delete somebody else's
    saved work.
    """
    if record.owner_id is None:
        return
    if user is not None and str(user.id) == record.owner_id:
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "This estimate belongs to a Helios account, so only that account can change "
            "it. You can still view it, and you can run your own estimate from the same "
            "details."
        ),
    )


# --------------------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------------------

def _area_to_input(area: AreaSpec | None) -> tuple[float | None, str, list[tuple[float, float]] | None]:
    """Reduce the three ways of giving an area (§13) to one number in one unit."""
    if area is None:
        return None, "sqm", None
    if area.polygon:
        return None, "sqm", [tuple(p) for p in area.polygon]
    if area.length and area.width:
        return (
            sizing.area_from_dimensions(area.length, area.width, area.dimension_unit),
            "sqm",
            None,
        )
    return area.value, area.unit, None


def _to_input(req: EstimateRequest) -> engine.EstimateInput:
    available_area, area_unit, polygon = _area_to_input(req.area)

    return engine.EstimateInput(
        user_type=req.user_type,
        mode=req.mode,
        goal=req.goal,
        location_query=req.location.query,
        latitude=req.location.latitude,
        longitude=req.location.longitude,
        consumption_method=req.consumption_method,
        monthly_bill=req.monthly_bill,
        monthly_kwh=req.monthly_kwh,
        equipment=[e.model_dump() for e in req.equipment],
        pumps=[p.model_dump() for p in req.pumps],
        floor_area_m2=req.floor_area_m2,
        occupants=req.occupants,
        installation_type=req.installation_type,
        available_area=available_area,
        area_unit=area_unit,
        area_polygon=polygon,
        requested_capacity_kwp=req.system.capacity_kwp,
        panel_count=req.system.panel_count,
        panel_watts=req.system.panel_watts,
        panel_model=req.system.panel_model,
        panel_length_m=req.system.panel_length_m,
        panel_width_m=req.system.panel_width_m,
        panel_voc=req.system.panel_voc,
        panel_isc=req.system.panel_isc,
        panel_vmp=req.system.panel_vmp,
        panel_imp=req.system.panel_imp,
        panel_key=req.system.panel_key,
        tilt_deg=req.system.tilt_deg,
        azimuth_deg=req.system.azimuth_deg,
        shading_level=req.system.shading_level,
        inverter_efficiency=req.system.inverter_efficiency,
        inverter_ac_capacity_kw=req.system.inverter_ac_capacity_kw,
        dc_ac_ratio=req.system.dc_ac_ratio,
        loss_overrides=req.system.loss_overrides,
        degradation_rate=req.system.degradation_rate,
        lifetime_years=req.system.lifetime_years,
        wants_battery=req.battery.wanted,
        battery_capacity_kwh=req.battery.capacity_kwh,
        desired_backup_hours=req.battery.desired_backup_hours,
        critical_load_kw=req.battery.critical_load_kw,
        grid_connected=req.battery.grid_connected,
        export_allowed=req.export_allowed,
        tariff_per_kwh=req.money.tariff_per_kwh,
        fixed_monthly_charge=req.money.fixed_monthly_charge,
        export_rate_per_kwh=req.money.export_rate_per_kwh,
        budget=req.money.budget,
        system_cost_override=req.money.system_cost,
        operating_hours=req.operations.operating_hours,
        peak_demand_kw=req.operations.peak_demand_kw,
        connected_load_kw=req.operations.connected_load_kw,
        offset_target_pct=req.operations.offset_target_pct,
        grid_connection=req.operations.grid_connection,
        farm_loads=list(req.operations.farm_loads),
        business_type=req.operations.business_type,
        facility_type=req.operations.facility_type,
        pump_horsepower=req.farm.pump_horsepower,
        pump_head_metres=req.farm.pump_head_metres,
        required_daily_water_m3=req.farm.required_daily_water_m3,
        crop_water_mm_per_day=req.farm.crop_water_mm_per_day,
        history_years=req.history_years,
        label=req.label,
    )


def _run(inp: engine.EstimateInput) -> dict[str, Any]:
    """Run the pipeline, translating internal failures into guidance a person can act on."""
    try:
        return engine.run(inp)
    except DataSourceError:
        raise  # handled by the application-level handler, which already speaks plainly
    except ValueError as exc:
        # Domain refusals — too little weather, an impossible input — carry their own
        # explanation, written for a user. Pass it through rather than flattening it.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------------------
# Interview
# --------------------------------------------------------------------------------------

@router.get("/meta/interview")
def interview() -> dict[str, Any]:
    """The whole question flow as data, so the interface can render it (§8, §33, §34)."""
    return personas.catalogue()


# --------------------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------------------

@router.get("/locations/reverse")
def reverse(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
) -> dict[str, Any]:
    """Name the place at a coordinate, for *Use my location* and map pins (§9)."""
    location = reverse_geocode(latitude, longitude)
    return {"location": location.to_dict()}


# --------------------------------------------------------------------------------------
# Estimates
# --------------------------------------------------------------------------------------

def _ownership_fields(
    record: estimate_store.StoredEstimate, user: User | None
) -> dict[str, Any]:
    """The two flags the interface reads to decide what it may offer.

    Computed in one place because the create and read responses must agree. They did not:
    `create` reported `owned` but omitted `editable`, so a client that trusted the create
    response saw `undefined` where the read response said `true`. Nothing broke — the
    result page loads through `read` — but two endpoints describing the same estimate
    differently is a bug waiting for its first consumer.

    `editable` is not merely `owned` inverted. An anonymous estimate is editable by whoever
    holds the link; an owned one only by its owner.
    """
    return {
        "owned": record.owner_id is not None,
        "editable": record.owner_id is None
        or (user is not None and str(user.id) == record.owner_id),
    }


@router.post("/estimate")
def create(
    request: EstimateRequest, user: User | None = Depends(optional_user)
) -> dict[str, Any]:
    """Run an estimate, and save it if asked to.

    ``optional_user`` rather than ``current_user``, and that one choice is what keeps the
    promise the product makes: somebody who has not signed up gets the same answer, saved
    the same way, reachable at the same kind of link. Signing in adds exactly one thing —
    the estimate also appears in their dashboard.
    """
    payload = _run(_to_input(request))

    if not request.save:
        return {"estimate_id": None, "saved": False, **payload}

    record = estimate_store.save(
        payload, label=request.label, owner_id=user.id if user else None
    )
    metrics.count_estimate(owned=user is not None)
    return {
        "estimate_id": record.estimate_id,
        "saved": True,
        **record.to_dict(),
        **_ownership_fields(record, user),
    }


@router.get("/estimate/{estimate_id}")
def read(
    estimate_id: str, user: User | None = Depends(optional_user)
) -> dict[str, Any]:
    """Read an estimate by its opaque link.

    Not gated by ownership, deliberately. The identifier *is* the capability, and that is
    the property that lets somebody send their result to an installer who has no account.
    See :func:`_require_write_access` for where ownership does apply.
    """
    record = _require_estimate(estimate_id)
    return {**record.to_dict(), **_ownership_fields(record, user)}


@router.post("/estimate/{estimate_id}/rename")
def rename(
    estimate_id: str,
    request: RenameRequest,
    user: User | None = Depends(optional_user),
) -> dict[str, Any]:
    _require_write_access(_require_estimate(estimate_id), user)
    record = estimate_store.rename(estimate_id, request.label)
    if record is None:
        raise HTTPException(status_code=404, detail="That estimate no longer exists.")
    return {"estimate_id": record.estimate_id, "label": record.label}


@router.delete("/estimate/{estimate_id}")
def remove(
    estimate_id: str, user: User | None = Depends(optional_user)
) -> dict[str, Any]:
    _require_write_access(_require_estimate(estimate_id), user)
    if not estimate_store.delete(estimate_id):
        raise HTTPException(status_code=404, detail="That estimate no longer exists.")
    return {"deleted": True, "estimate_id": estimate_id}


@router.get("/estimates")
def my_estimates(
    limit: int = Query(default=25, ge=1, le=100),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """The signed-in user's own estimates.

    This endpoint used to list every estimate the server held. That was honest for a
    single-user deployment and the response said so, but it cannot survive accounts: it
    would show one person another person's location, electricity bill and system design.
    There is now no way to ask this API for estimates that are not yours — not with a
    parameter, not by omitting one. Anonymous estimates stay reachable only by their link.
    """
    return {
        "estimates": estimate_store.list_for_owner(user.id, limit),
        "owner": str(user.id),
    }


@router.get("/estimate/{estimate_id}/report", response_class=PlainTextResponse)
def professional_report(estimate_id: str) -> str:
    """A report fit to hand to a customer, a manager or an installer (§36)."""
    record = estimate_store.get(estimate_id)
    if record is None:
        raise HTTPException(status_code=404, detail="That estimate no longer exists.")
    return report.build(record.to_dict())


# --------------------------------------------------------------------------------------
# Comparison (§27)
# --------------------------------------------------------------------------------------

@router.post("/estimate/compare")
def compare(request: CompareRequest) -> dict[str, Any]:
    """Run the same situation at several system sizes, side by side."""
    base_input = _to_input(request.base)
    rows: list[dict[str, Any]] = []
    currency: dict[str, Any] | None = None

    for scenario in request.scenarios:
        changes: dict[str, Any] = {}
        if scenario.capacity_kwp:
            changes["requested_capacity_kwp"] = scenario.capacity_kwp
        if scenario.battery_kwh is not None:
            changes["wants_battery"] = scenario.battery_kwh > 0
            changes["battery_capacity_kwh"] = scenario.battery_kwh or None

        payload = _run(replace(base_input, **changes))
        currency = currency or payload.get("currency")
        generation = payload["generation"]
        system = payload["system"]
        balance = payload.get("balance") or {}
        money = payload.get("economics") or {}

        rows.append(
            {
                "name": scenario.name,
                "capacity_kwp": system["capacity_kwp"],
                "battery_kwh": (system.get("battery") or {}).get("capacity_kwh"),
                "annual_kwh": generation["annual_kwh"],
                "annual_kwh_lower": payload["uncertainty"]["lower"],
                "annual_kwh_upper": payload["uncertainty"]["upper"],
                "solar_offset_pct": balance.get("solar_offset_pct"),
                "self_consumption_pct": balance.get("self_consumption_pct"),
                "total_capex": money.get("total_capex"),
                "annual_savings": money.get("annual_savings_year1"),
                "payback_years": money.get("payback_years"),
                "roi_pct": money.get("roi_pct"),
                "co2_tonnes_per_year": (payload.get("emissions") or {}).get(
                    "co2_avoided_tonnes_per_year"
                ),
                "area_required_m2": system["sizing"]["area_required_m2"],
                "confidence": payload["uncertainty"]["confidence"],
            }
        )

    return {
        "scenarios": rows,
        "currency": currency,
        "note": (
            "Every option uses the same location, the same weather record and the same "
            "assumptions, so the differences between them come only from the system itself."
        ),
    }


@router.post("/estimate/{estimate_id}/update")
def update(
    estimate_id: str,
    request: EstimateUpdateRequest,
    user: User | None = Depends(optional_user),
) -> dict[str, Any]:
    """Edit the assumptions behind a saved estimate and re-run it (§28).

    Not implemented as a partial recompute: changing a tariff changes the savings, changing
    a panel changes the yield, and a half-updated result would be worse than none. The whole
    pipeline runs again against the cached weather, which costs a second or two.
    """
    record = _require_estimate(estimate_id)
    _require_write_access(record, user)

    snapshot = record.payload.get("input")
    if not snapshot:
        raise HTTPException(
            status_code=409,
            detail=(
                "This estimate was saved before editing was supported, so we cannot re-run "
                "it. Run a new estimate to change its assumptions."
            ),
        )

    try:
        base = engine.EstimateInput(**snapshot)
    except TypeError as exc:
        logger.warning("Stored estimate %s is not loadable: %s", estimate_id, exc)
        raise HTTPException(
            status_code=409,
            detail=(
                "This estimate was saved by an older version of the platform and cannot be "
                "re-run. Run a new estimate to change its assumptions."
            ),
        ) from exc

    changes: dict[str, Any] = {}
    if request.system is not None:
        system = request.system
        for source, target in (
            ("capacity_kwp", "requested_capacity_kwp"),
            ("panel_count", "panel_count"),
            ("panel_watts", "panel_watts"),
            ("panel_model", "panel_model"),
            ("panel_length_m", "panel_length_m"),
            ("panel_width_m", "panel_width_m"),
            ("panel_voc", "panel_voc"),
            ("panel_isc", "panel_isc"),
            ("panel_vmp", "panel_vmp"),
            ("panel_imp", "panel_imp"),
            ("panel_key", "panel_key"),
            ("tilt_deg", "tilt_deg"),
            ("azimuth_deg", "azimuth_deg"),
            ("shading_level", "shading_level"),
            ("inverter_efficiency", "inverter_efficiency"),
            ("inverter_ac_capacity_kw", "inverter_ac_capacity_kw"),
            ("dc_ac_ratio", "dc_ac_ratio"),
            ("degradation_rate", "degradation_rate"),
            ("lifetime_years", "lifetime_years"),
        ):
            value = getattr(system, source)
            if value is not None:
                changes[target] = value
        if system.loss_overrides:
            changes["loss_overrides"] = {**base.loss_overrides, **system.loss_overrides}

    if request.money is not None:
        for source, target in (
            ("tariff_per_kwh", "tariff_per_kwh"),
            ("fixed_monthly_charge", "fixed_monthly_charge"),
            ("export_rate_per_kwh", "export_rate_per_kwh"),
            ("budget", "budget"),
            ("system_cost", "system_cost_override"),
        ):
            value = getattr(request.money, source)
            if value is not None:
                changes[target] = value

    if request.operations is not None:
        for source, target in (
            ("operating_hours", "operating_hours"),
            ("peak_demand_kw", "peak_demand_kw"),
            ("connected_load_kw", "connected_load_kw"),
            ("offset_target_pct", "offset_target_pct"),
            ("grid_connection", "grid_connection"),
            ("business_type", "business_type"),
            ("facility_type", "facility_type"),
        ):
            value = getattr(request.operations, source)
            if value is not None:
                changes[target] = value
        if request.operations.farm_loads:
            changes["farm_loads"] = list(request.operations.farm_loads)

    if request.battery is not None:
        changes["wants_battery"] = request.battery.wanted
        changes["battery_capacity_kwh"] = request.battery.capacity_kwh
        changes["desired_backup_hours"] = request.battery.desired_backup_hours
        changes["critical_load_kw"] = request.battery.critical_load_kw
        changes["grid_connected"] = request.battery.grid_connected

    payload = _run(replace(base, **changes))
    updated = estimate_store.update_payload(estimate_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="That estimate no longer exists.")
    if request.label:
        updated = estimate_store.rename(estimate_id, request.label) or updated

    return updated.to_dict()
