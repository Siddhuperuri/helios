"""The orchestrator: one request in, one complete answer out.

Everything in this package is a component; this is the pipeline that runs them in order and
assembles the result the user reads. The order matters and is not arbitrary:

    location -> tariff & currency -> demand -> weather -> best orientation
        -> yield per kWp -> system size -> yield for that system -> energy balance
        -> economics -> uncertainty -> plain-language explanation

Two design points worth stating.

**Yield is computed twice, deliberately.** First for a 1 kWp reference array, because
specific yield is what sizing needs and it is capacity-invariant; then again for the sized
system, because inverter clipping is *not* capacity-invariant and a system with an
undersized inverter really does lose the top of its midday peak. Sizing from the second
run would be circular; reporting the first would be wrong.

**The weather is fetched once.** The orientation search, the reference yield and the final
yield all run against the same frame, which is why an estimate that touches twenty
candidate orientations still returns in seconds.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.data.sources import Location, resolve_location
from app.estimate import assumptions as A
from app.estimate import balance as balance_mod
from app.estimate import climatology, economics, farm, sizing, space, uncertainty
from app.estimate import demand as demand_mod
from app.estimate import tariffs as tariff_mod
from app.features.solar_geometry import PVSystem

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------------------

@dataclass
class EstimateInput:
    """Everything a caller may supply. Almost all of it is optional by design (§8, §12)."""

    user_type: str = "exploring"
    mode: str = "quick"
    # What the user is actually trying to do. This decides whether panel count is an input
    # (they already own the array) or an output (we are recommending one).
    goal: str = "install"        # existing | install | compare

    # Location
    location_query: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    # Consumption
    consumption_method: str | None = None        # bill | units | equipment | floor_area | unknown
    monthly_bill: float | None = None
    monthly_kwh: float | None = None
    equipment: list[dict[str, Any]] = field(default_factory=list)
    pumps: list[dict[str, Any]] = field(default_factory=list)
    floor_area_m2: float | None = None
    occupants: int | None = None

    # Space
    installation_type: str = A.DEFAULT_INSTALLATION_TYPE
    available_area: float | None = None
    area_unit: str = "sqm"
    area_polygon: list[tuple[float, float]] | None = None

    # System
    requested_capacity_kwp: float | None = None
    panel_count: int | None = None
    panel_watts: int | None = None
    panel_model: str | None = None
    panel_length_m: float | None = None
    panel_width_m: float | None = None
    panel_voc: float | None = None
    panel_isc: float | None = None
    panel_vmp: float | None = None
    panel_imp: float | None = None
    panel_key: str = A.DEFAULT_PANEL_KEY
    tilt_deg: float | None = None
    azimuth_deg: float | None = None
    shading_level: str = "unknown"
    inverter_efficiency: float | None = None
    inverter_ac_capacity_kw: float | None = None
    dc_ac_ratio: float | None = None
    loss_overrides: dict[str, float] = field(default_factory=dict)
    degradation_rate: float | None = None
    lifetime_years: int | None = None

    # Storage
    wants_battery: bool = False
    battery_capacity_kwh: float | None = None
    desired_backup_hours: float | None = None
    critical_load_kw: float | None = None
    grid_connected: bool = True
    export_allowed: bool = True

    # Money
    tariff_per_kwh: float | None = None
    fixed_monthly_charge: float | None = None
    export_rate_per_kwh: float | None = None
    budget: float | None = None
    system_cost_override: float | None = None

    # How the site operates. Absent for personas that are never asked.
    operating_hours: float | None = None
    peak_demand_kw: float | None = None
    connected_load_kw: float | None = None
    offset_target_pct: float | None = None
    grid_connection: str | None = None
    farm_loads: list[str] = field(default_factory=list)
    business_type: str | None = None
    facility_type: str | None = None

    # Farm specifics
    pump_horsepower: float | None = None
    pump_head_metres: float | None = None
    required_daily_water_m3: float | None = None
    crop_water_mm_per_day: float | None = None

    history_years: int = climatology.DEFAULT_HISTORY_YEARS
    label: str | None = None


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------

def _build_system(
    inp: EstimateInput,
    *,
    capacity_kwp: float,
    tilt: float,
    azimuth: float,
    ledger: A.AssumptionLedger,
    record: bool,
) -> PVSystem:
    """Assemble the declared array from user input and stated defaults."""
    panel = A.PANEL_TECHNOLOGIES.get(inp.panel_key) or A.PANEL_TECHNOLOGIES[A.DEFAULT_PANEL_KEY]

    # Build the loss stack, swapping in the user's shading answer and any explicit overrides.
    losses: list[A.LossItem] = []
    for item in A.DEFAULT_LOSS_STACK:
        fraction = item.fraction
        if item.key == "shading":
            fraction = A.shading_fraction(inp.shading_level)
        if item.key in inp.loss_overrides:
            fraction = float(inp.loss_overrides[item.key])
        losses.append(A.LossItem(item.key, item.label, fraction, item.plain_explanation))

    total_losses = A.combine_losses(losses)
    inverter_efficiency = inp.inverter_efficiency or 0.96

    ac_capacity = inp.inverter_ac_capacity_kw
    if ac_capacity is None and inp.dc_ac_ratio:
        ac_capacity = capacity_kwp / float(inp.dc_ac_ratio)

    if record:
        ledger.add(
            "panel_technology", "Panel type", panel.display_name,
            provenance="user_supplied" if inp.panel_key != A.DEFAULT_PANEL_KEY else "market_typical",
            source="Your selection" if inp.panel_key != A.DEFAULT_PANEL_KEY else "Typical current equipment",
            rationale=panel.note,
        )
        ledger.add(
            "panel_efficiency", "Panel efficiency", round(panel.efficiency * 100, 1), unit="%",
            provenance="market_typical",
            rationale="How much of the sunlight hitting the panel becomes electricity.",
        )
        ledger.add(
            "inverter_efficiency", "Inverter efficiency", round(inverter_efficiency * 100, 1),
            unit="%",
            provenance="user_supplied" if inp.inverter_efficiency else "market_typical",
            rationale="Losses converting the panels' DC output into usable AC electricity.",
        )
        ledger.add(
            "system_losses", "Total system losses", round(total_losses * 100, 1), unit="%",
            provenance="derived",
            source="PVWatts v5 default loss stack (Dobos 2014), adjusted for your shading answer",
            rationale=(
                "Dust, shading, wiring, mismatch and downtime combined. Heat and inverter "
                "losses are modelled separately, hour by hour, and are not in this figure."
            ),
        )
        for item in losses:
            ledger.add(
                f"loss_{item.key}", item.label, round(item.fraction * 100, 2), unit="%",
                provenance="user_supplied" if item.key in inp.loss_overrides else "market_typical",
                rationale=item.plain_explanation,
            )

    return PVSystem(
        dc_capacity_kwp=capacity_kwp,
        surface_tilt_deg=tilt,
        surface_azimuth_deg=azimuth,
        temperature_coefficient_per_c=panel.temperature_coefficient_per_c,
        system_losses_fraction=total_losses,
        inverter_efficiency=inverter_efficiency,
        inverter_ac_capacity_kw=ac_capacity,
        albedo=0.2,
    )


def _resolve_demand(
    inp: EstimateInput,
    tariff: tariff_mod.TariffDefault,
    ledger: A.AssumptionLedger,
) -> demand_mod.DemandEstimate | None:
    """Run whichever consumption route the user chose. None means they told us nothing."""
    method = (inp.consumption_method or "").strip().lower()

    if method == "units" and inp.monthly_kwh:
        ledger.user_value(
            "monthly_consumption", "Your monthly electricity use", round(inp.monthly_kwh, 1),
            unit="kWh",
        )
        return demand_mod.from_metered_units(inp.monthly_kwh, user_type=inp.user_type)

    if method == "bill" and inp.monthly_bill:
        ledger.user_value("monthly_bill", "Your monthly electricity bill", inp.monthly_bill)
        return demand_mod.from_bill(
            monthly_bill=inp.monthly_bill,
            rate_per_kwh=inp.tariff_per_kwh or tariff.rate_per_kwh,
            fixed_monthly_charge=(
                inp.fixed_monthly_charge
                if inp.fixed_monthly_charge is not None
                else tariff.fixed_monthly_charge
            ),
            user_type=inp.user_type,
        )

    if method == "equipment" and (inp.equipment or inp.pumps):
        items = [
            demand_mod.EquipmentItem(
                key=str(e.get("key")),
                count=float(e.get("count", 1) or 1),
                hours_per_day=e.get("hours_per_day"),
                days_per_month=e.get("days_per_month"),
                watts_override=e.get("watts"),
            )
            for e in inp.equipment
        ]
        return demand_mod.from_equipment(items, user_type=inp.user_type, pumps=inp.pumps)

    if method == "floor_area" and inp.floor_area_m2:
        return demand_mod.from_floor_area(
            floor_area_m2=inp.floor_area_m2,
            user_type=inp.user_type,
            occupants=inp.occupants,
        )

    return None


def run(inp: EstimateInput) -> dict[str, Any]:
    """Produce a complete consumer estimate."""
    started = time.perf_counter()
    ledger = A.AssumptionLedger()
    warnings: list[str] = []
    timings: dict[str, float] = {}

    # ------------------------------------------------------------------- 1. location
    t0 = time.perf_counter()
    # The grid answer overrides the plain export flag: "no export" means surplus is
    # simply lost, and "off grid" means there is nothing to export to.
    export_allowed = inp.export_allowed
    grid_connected = inp.grid_connected
    if inp.grid_connection == "no_export":
        export_allowed = False
    elif inp.grid_connection == "off_grid":
        export_allowed = False
        grid_connected = False

    location = resolve_location(
        query=inp.location_query, latitude=inp.latitude, longitude=inp.longitude
    )
    timings["location_s"] = round(time.perf_counter() - t0, 3)

    ledger.user_value(
        "location", "Location", location.label,
        rationale="Everything below is calculated for this point on the map.",
    )

    country = _country_code(location)
    currency = tariff_mod.currency_for_country(country)
    tariff = tariff_mod.default_tariff(country, inp.user_type)

    import_rate = inp.tariff_per_kwh or tariff.rate_per_kwh
    ledger.add(
        "electricity_tariff", "Electricity rate", round(import_rate, 3),
        unit=f"{currency.symbol}/kWh",
        provenance="user_supplied" if inp.tariff_per_kwh else "regional_default",
        source="Your bill" if inp.tariff_per_kwh else "Representative regional rate, editable",
        rationale=tariff.note,
    )
    export_rate = (
        inp.export_rate_per_kwh if inp.export_rate_per_kwh is not None else tariff.export_rate_per_kwh
    )

    if inp.offset_target_pct:
        ledger.user_value(
            "offset_target", "Share of your electricity to cover",
            round(inp.offset_target_pct), unit="%",
            rationale="The system is sized to aim at this share of your consumption.",
        )
    if inp.grid_connection:
        ledger.user_value(
            "grid_connection", "Grid connection",
            {
                "net_metering": "Connected, exports credited",
                "no_export": "Connected, no export allowed",
                "off_grid": "Not connected to the grid",
            }.get(inp.grid_connection, inp.grid_connection),
            rationale="Decides whether surplus generation is worth anything.",
        )
    if inp.facility_type or inp.business_type:
        ledger.user_value(
            "site_type", "Type of site", inp.facility_type or inp.business_type,
            rationale="Used to choose the daily demand pattern applied to your consumption.",
        )
    if inp.farm_loads:
        ledger.user_value(
            "farm_loads", "What you are powering", ", ".join(inp.farm_loads),
            rationale="Used to choose the daily demand pattern applied to your consumption.",
        )

    # ------------------------------------------------------------------- 2. demand
    demand = _resolve_demand(inp, tariff, ledger)
    if demand is None:
        warnings.append(
            "You did not tell us how much electricity you use, so we sized the system to "
            "the space available instead. Adding your consumption changes the "
            "recommendation and makes the savings figure meaningful."
        )

    # --------------------------------------------------------------- 3. weather once
    t0 = time.perf_counter()
    raw, period_start, period_end = climatology.fetch_history(
        location, years=inp.history_years
    )
    usable, dropped = climatology.usable_hours(raw)
    completeness = len(usable) / max(1, len(raw))
    timings["weather_s"] = round(time.perf_counter() - t0, 3)

    ledger.add(
        "weather_period", "Weather data period",
        f"{period_start.isoformat()} to {period_end.isoformat()}",
        provenance="measured",
        source=A.ATTRIBUTION_NOTE,
        rationale=(
            f"{len(usable):,} hours of real weather at your location, used to work out what "
            f"a typical year looks like."
        ),
        editable=False,
    )

    # ------------------------------------------------------------- 4. orientation
    t0 = time.perf_counter()
    orientation_known = inp.tilt_deg is not None and inp.azimuth_deg is not None
    reference_system = _build_system(
        inp, capacity_kwp=1.0, tilt=20.0, azimuth=180.0, ledger=ledger, record=False
    )

    if orientation_known:
        tilt = float(inp.tilt_deg)
        azimuth = float(inp.azimuth_deg)
        orientation_payload = {
            "tilt_deg": tilt,
            "azimuth_deg": azimuth,
            "azimuth_compass": sizing.compass_label(azimuth),
            "method": "user_specified",
            "note": "The angle and direction you told us.",
        }
        ledger.user_value("tilt", "Panel tilt", tilt, unit="°")
        ledger.user_value("azimuth", "Panel direction", f"{azimuth:g}° ({sizing.compass_label(azimuth)})")
    else:
        best = sizing.optimal_orientation(usable, location, reference_system)
        tilt, azimuth = best.tilt_deg, best.azimuth_deg
        orientation_payload = best.to_dict()
        ledger.add(
            "tilt", "Panel tilt", round(tilt, 1), unit="°",
            provenance="derived", source="Chosen by testing this location's own weather",
            rationale=best.note,
        )
        ledger.add(
            "azimuth", "Panel direction", f"{azimuth:g}° ({sizing.compass_label(azimuth)})",
            provenance="derived", source="Chosen by testing this location's own weather",
            rationale="The direction that collected the most energy across the whole record.",
        )
    timings["orientation_s"] = round(time.perf_counter() - t0, 3)

    # --------------------------------------------------------- 5. yield per kWp
    t0 = time.perf_counter()
    reference = climatology.compute(
        location,
        _build_system(inp, capacity_kwp=1.0, tilt=tilt, azimuth=azimuth,
                      ledger=ledger, record=False),
        raw=raw,
        period=(period_start, period_end),
    )
    timings["reference_yield_s"] = round(time.perf_counter() - t0, 3)

    # ------------------------------------------------------------------ 6. space
    available_area_m2 = _resolve_area(inp, ledger)

    # ------------------------------------------------------------------- 7. sizing
    has_existing_array = (
        inp.goal == "existing" and inp.panel_count is not None and inp.panel_count > 0
    )

    if has_existing_array:
        # The array exists. Its capacity is a measurement of what is on the roof, not a
        # recommendation, so the sizer is bypassed rather than asked to agree with reality.
        panels = sizing.configure_panels(
            target_kwp=0.0,
            watts=inp.panel_watts,
            panel_key=inp.panel_key,
            count_override=inp.panel_count,
            source="existing_system",
            model=inp.panel_model,
        )
        sized = sizing.SizingResult(
            capacity_kwp=panels.capacity_kwp,
            binding_constraint="existing_system",
            reason=(
                f"This is the system you already have: {panels.count} panels rated "
                f"{panels.watts} W each."
            ),
            area_required_m2=sizing.area_for_capacity(
                panels.capacity_kwp, inp.installation_type, inp.panel_key
            ),
            area_available_m2=available_area_m2,
            capacity_from_demand_kwp=None,
            capacity_from_area_kwp=None,
            capacity_from_budget_kwp=None,
            notes=[],
        )
    else:
        sized = sizing.recommend_capacity(
            annual_demand_kwh=demand.annual_kwh if demand else None,
            specific_yield_kwh_per_kwp=reference.annual_kwh,
            available_area_m2=available_area_m2,
            installation_type=inp.installation_type,
            panel_key=inp.panel_key,
            budget=inp.budget,
            requested_kwp=inp.requested_capacity_kwp,
            offset_target=(inp.offset_target_pct / 100.0) if inp.offset_target_pct else 1.0,
            currency_code=currency.code,
        )
        # Capacity is quantised to whole panels, and the panel count wins: an array of 28
        # modules is 15.4 kW whatever the sizer wanted, and every figure below must be for
        # the system actually described.
        panels = sizing.configure_panels(
            target_kwp=sized.capacity_kwp,
            watts=inp.panel_watts,
            panel_key=inp.panel_key,
            count_override=inp.panel_count,
            source="user_specified" if inp.panel_count else "recommended",
            model=inp.panel_model,
        )
        sized.capacity_kwp = panels.capacity_kwp
        sized.area_required_m2 = sizing.area_for_capacity(
            panels.capacity_kwp, inp.installation_type, inp.panel_key
        )
        if inp.panel_count:
            sized.binding_constraint = "user_specified"
            sized.reason = (
                f"You chose {panels.count} panels, which comes to "
                f"{panels.capacity_kwp:.2f} kW."
            )

    ledger.add(
        "panel_count", "Number of panels", panels.count,
        provenance=(
            "user_supplied"
            if has_existing_array or inp.panel_count
            else "derived"
        ),
        source=(
            "Your existing system" if has_existing_array
            else "Your choice" if inp.panel_count
            else "Recommended by us"
        ),
        rationale=panels.note,
    )
    ledger.add(
        "panel_watts", "Rated power per panel", panels.watts, unit="W",
        provenance="user_supplied" if panels.watts_known else "market_typical",
        source="You told us" if panels.watts_known else "Typical current panel",
        rationale=(
            "Printed on the panel label and on any quote."
            if panels.watts_known
            else "Assumed, because the wattage was not known. Entering it sharpens the result."
        ),
    )
    if panels.model:
        ledger.add(
            "panel_model", "Panel model", panels.model,
            provenance="user_supplied", source="You told us",
            rationale=(
                "Recorded for your reference. We do not hold a manufacturer catalogue, so "
                "the wattage above is what the calculation actually used."
            ),
        )
    # --------------------------------------------------------------- space (§6)
    # Computed from the final panel count, so it is the array actually being reported that
    # is checked against the roof — not the sizing target that preceded it.
    footprint = space.assess(
        count=panels.count,
        watts=panels.watts,
        installation_type=inp.installation_type,
        panel_key=inp.panel_key,
        available_area_m2=available_area_m2,
        panel_length_m=inp.panel_length_m,
        panel_width_m=inp.panel_width_m,
    )
    sized.area_required_m2 = footprint.footprint_m2

    if footprint.fits is False:
        warnings.append(
            f"This array needs about {footprint.footprint_m2:,.0f} m² of buildable space "
            f"and we estimate you have {footprint.usable_area_m2:,.0f} m². Around "
            f"{footprint.max_panels_in_space} panels would fit — the figures below are for "
            f"the {panels.count} you asked for."
        )

    ledger.add(
        "panel_area", "Area of one panel", round(footprint.panel_area_m2, 2), unit="m²",
        provenance="user_supplied" if footprint.panel_dimensions_known else "derived",
        source=(
            "Panel dimensions you gave" if footprint.panel_dimensions_known
            else "Calculated from the panel's rating and efficiency"
        ),
        rationale=(
            "At standard test conditions 1 kW of panel occupies 1/efficiency square metres, "
            "so the rating and the efficiency fix the size."
        ),
    )
    ledger.add(
        "usable_area_fraction", "Share of your space that is buildable",
        round(footprint.usable_fraction * 100), unit="%",
        provenance="market_typical",
        source="Typical for this mounting type",
        rationale=space.usable_note(inp.installation_type),
    )

    ledger.add(
        "system_capacity", "System size", round(sized.capacity_kwp, 2), unit="kWp",
        provenance=(
            "user_supplied" if (has_existing_array or inp.panel_count or inp.requested_capacity_kwp)
            else "derived"
        ),
        source=f"{panels.count} panels × {panels.watts} W",
        rationale=sized.reason,
    )

    # ------------------------------------------------------------ 8. final yield
    t0 = time.perf_counter()
    system = _build_system(
        inp, capacity_kwp=sized.capacity_kwp, tilt=tilt, azimuth=azimuth,
        ledger=ledger, record=True,
    )
    result = climatology.compute(
        location, system, raw=raw, period=(period_start, period_end)
    )
    inverter = sizing.describe_inverter(sized.capacity_kwp, system.ac_capacity_kw)
    timings["final_yield_s"] = round(time.perf_counter() - t0, 3)
    warnings.extend(result.warnings)

    if inverter["severity"] == "caution":
        warnings.append(inverter["verdict"])

    if result.clipped_fraction > 0.02:
        # The remedy has to scale with the problem: "slightly larger" is right at 3 %
        # clipping and absurd at 100 %, where the inverter is the entire constraint.
        remedy = (
            "A slightly larger inverter would capture some of that."
            if result.clipped_fraction < 0.15
            else "A substantially larger inverter would be needed to capture it."
        )
        warnings.append(
            f"The inverter limits output in about {result.clipped_fraction:.0%} of daylight "
            f"hours. {remedy}"
        )

    # ------------------------------------------------------------- 9. storage
    battery_recommendation = None
    battery_kwh = 0.0
    if inp.wants_battery:
        rec = balance_mod.recommend_battery(
            demand=demand or demand_mod.from_floor_area(
                floor_area_m2=100, user_type=inp.user_type
            ),
            generation=result.hourly_ac_kw,
            desired_backup_hours=inp.desired_backup_hours,
            critical_load_kw=inp.critical_load_kw,
            stated_capacity_kwh=inp.battery_capacity_kwh,
            grid_connected=grid_connected,
        )
        battery_recommendation = rec.to_dict()
        battery_kwh = rec.capacity_kwh
        ledger.add(
            "battery_capacity", "Battery size", round(battery_kwh, 1), unit="kWh",
            provenance="user_supplied" if inp.battery_capacity_kwh else "derived",
            rationale=rec.basis,
        )

    # -------------------------------------------------------- 10. energy balance
    energy_balance = None
    if demand is not None:
        energy_balance = balance_mod.energy_balance(
            result.hourly_ac_kw,
            demand,
            battery_kwh=battery_kwh or None,
            export_allowed=export_allowed,
        )

    # ------------------------------------------------------------- 11. economics
    money = None
    if energy_balance is not None:
        money = economics.compute(
            balance=energy_balance,
            capacity_kwp=sized.capacity_kwp,
            currency_code=currency.code,
            currency_symbol=currency.symbol,
            import_rate_per_kwh=import_rate,
            export_rate_per_kwh=export_rate,
            country_code=country,
            battery_kwh=battery_kwh,
            system_cost_override=inp.system_cost_override,
            lifetime_years=inp.lifetime_years or A.DEFAULT_SYSTEM_LIFETIME_YEARS,
            degradation_rate=inp.degradation_rate or A.DEFAULT_DEGRADATION_RATE_PER_YEAR,
            tariff_is_subsidised=tariff.subsidised and inp.tariff_per_kwh is None,
        )
        ledger.add(
            "system_lifetime", "System lifetime",
            inp.lifetime_years or A.DEFAULT_SYSTEM_LIFETIME_YEARS, unit="years",
            provenance="market_typical",
            rationale="Panels are typically warranted for 25 years and often outlast it.",
        )
        ledger.add(
            "degradation", "Annual output loss",
            round((inp.degradation_rate or A.DEFAULT_DEGRADATION_RATE_PER_YEAR) * 100, 2),
            unit="%/year",
            provenance="market_typical",
            rationale="Panels lose a little output each year as they age.",
        )

    # ---------------------------------------------------------- 12. uncertainty
    band = uncertainty.assess(
        expected_annual_kwh=result.annual_kwh,
        measured_annual_std_kwh=result.annual_std_kwh,
        variability_basis=result.variability_basis,
        complete_calendar_years=result.complete_calendar_years,
        data_completeness=completeness,
        shading_known=inp.shading_level not in {"unknown", None},
        orientation_known=orientation_known,
        system_specified=inp.mode == "detailed",
        demand_confidence=demand.confidence if demand else None,
    )

    # ------------------------------------------------------------------ 13. farm
    farm_payload = None
    if inp.user_type == "farm":
        best_daily = result.monthly_kwh[result.best_month - 1] / 30.4
        worst_daily = result.monthly_kwh[result.worst_month - 1] / 30.4
        farm_payload = farm.capability(
            daily_generation_kwh=result.annual_kwh / 365.25,
            best_month_daily_kwh=best_daily,
            worst_month_daily_kwh=worst_daily,
            horsepower=inp.pump_horsepower,
            head_metres=inp.pump_head_metres,
            required_daily_water_m3=inp.required_daily_water_m3,
            crop_water_requirement_mm_per_day=inp.crop_water_mm_per_day,
        ).to_dict()

    timings["total_s"] = round(time.perf_counter() - started, 3)

    # -------------------------------------------------------------- 14. assemble
    payload: dict[str, Any] = {
        "user_type": inp.user_type,
        "mode": inp.mode,
        "goal": inp.goal,
        "label": inp.label,
        "location": location.to_dict(),
        "currency": currency.to_dict(),
        "system": {
            **system.describe(),
            "capacity_kwp": sized.capacity_kwp,
            "panel_technology": inp.panel_key,
            "installation_type": inp.installation_type,
            "sizing": sized.to_dict(),
            "panels": {**panels.to_dict(), **_panel_specification(inp, panels)},
            "space": footprint.to_dict(),
            "inverter": inverter,
            "orientation": orientation_payload,
            "battery": battery_recommendation,
        },
        "generation": {
            **result.to_dict(),
            "daily_average_kwh": round(result.annual_kwh / 365.25, 1),
            "monthly_average_kwh": round(result.annual_kwh / 12.0, 0),
            # Each month gets the spread its own weather actually showed, not a twelfth of
            # the annual band. A monsoon July genuinely varies more than a dry January, and
            # flattening that hides the months a farmer most needs to plan around.
            "monthly_ranges": _monthly_ranges(result, band),
        },
        "demand": demand.to_dict() if demand else None,
        "balance": energy_balance.to_dict() if energy_balance else None,
        "economics": money.to_dict() if money else None,
        "emissions": (
            {
                "co2_avoided_kg_per_year": round(money.co2_avoided_kg_per_year, 0),
                "co2_avoided_tonnes_per_year": round(money.co2_avoided_kg_per_year / 1000, 2),
                "equivalences": economics.equivalence(money.co2_avoided_kg_per_year),
            }
            if money
            else None
        ),
        "uncertainty": band.to_dict(),
        "farm": farm_payload,
        "assumptions": ledger.to_list(),
        "data_sources": A.data_sources(),
        "attribution": A.ATTRIBUTION_NOTE,
        "operations": {
            "operating_hours": inp.operating_hours,
            "peak_demand_kw": inp.peak_demand_kw,
            "connected_load_kw": inp.connected_load_kw,
            "offset_target_pct": inp.offset_target_pct,
            "grid_connection": inp.grid_connection,
            "facility_type": inp.facility_type,
            "business_type": inp.business_type,
            "farm_loads": inp.farm_loads,
            "peak_demand_note": (
                "Solar rarely reduces peak demand much, because the peak often falls "
                "outside daylight hours. Any demand charge on your bill is therefore left "
                "out of the savings rather than assumed away."
                if inp.peak_demand_kw
                else None
            ),
        },
        "warnings": warnings + sized.notes + (energy_balance.notes if energy_balance else []),
        "timings": timings,
        "data_completeness": round(completeness, 4),
        # The inputs are stored with the result so a saved estimate can be re-run with an
        # edited assumption (§28) without the user answering the interview again.
        "input": asdict(inp),
    }
    payload["explanation"] = build_narrative(payload)
    return payload



def _panel_specification(inp: EstimateInput, panels: sizing.PanelConfiguration) -> dict[str, Any]:
    """The panel's full specification, each field labelled with where it came from (§9).

    Three provenances are distinguished, because they carry different weight: a value the
    user typed, a value read off a datasheet they gave us, and a value this platform
    assumed. Presenting all three identically would let an assumed temperature coefficient
    look like a measured one.
    """
    panel = A.PANEL_TECHNOLOGIES.get(inp.panel_key) or A.PANEL_TECHNOLOGIES[A.DEFAULT_PANEL_KEY]
    chose_technology = inp.panel_key != A.DEFAULT_PANEL_KEY
    dimensions_known = bool(inp.panel_length_m and inp.panel_width_m)

    def entry(label: str, value: Any, provenance: str, unit: str | None = None) -> dict[str, Any]:
        return {
            "label": label,
            "value": value,
            "unit": unit,
            "provenance": provenance,
            "provenance_label": {
                "user_provided": "User provided",
                "datasheet": "Datasheet",
                "estimated": "Estimated",
            }[provenance],
        }

    datasheet = [
        {
            "key": entry["key"],
            "label": entry["label"],
            "unit": entry["unit"],
            "note": entry["note"],
            "value": getattr(inp, f"panel_{entry['key']}"),
            "provenance": (
                "user_provided" if getattr(inp, f"panel_{entry['key']}") is not None
                else "not_supplied"
            ),
        }
        for entry in A.DATASHEET_FIELDS
    ]

    return {
        "datasheet": datasheet,
        "datasheet_note": (
            "These are recorded for your reference. The energy model is driven by rated "
            "power, efficiency and the temperature coefficient; open-circuit voltage and "
            "short-circuit current matter for string sizing against a specific inverter, "
            "which this platform does not attempt."
        ),
        "specification": [
            entry("Panels", panels.count,
                  "user_provided" if panels.source != "recommended" else "estimated"),
            entry("Power per panel", panels.watts,
                  "user_provided" if panels.watts_known else "estimated", "W"),
            entry("Total DC capacity", round(panels.capacity_kwp, 2), "user_provided", "kW"),
            entry("Technology", panel.display_name,
                  "user_provided" if chose_technology else "estimated"),
            entry("Efficiency", round(panel.efficiency * 100, 1),
                  "user_provided" if chose_technology else "estimated", "%"),
            entry("Bifacial", "Yes" if panel.bifacial else "No",
                  "user_provided" if chose_technology else "estimated"),
            entry("Temperature coefficient",
                  round(panel.temperature_coefficient_per_c * 100, 2),
                  "user_provided" if chose_technology else "estimated", "%/°C"),
            entry("Annual degradation",
                  round(panel.degradation_rate_per_year * 100, 2),
                  "user_provided" if chose_technology else "estimated", "%/year"),
            entry("Panel dimensions",
                  (f"{inp.panel_length_m} × {inp.panel_width_m} m" if dimensions_known
                   else "Derived from rating and efficiency"),
                  "datasheet" if dimensions_known else "estimated"),
        ],
    }


def _monthly_ranges(
    result: climatology.ClimatologyResult, band: uncertainty.UncertaintyResult
) -> list[dict[str, Any]]:
    """Month-by-month expectation with a range built from that month's own variability."""
    rows: list[dict[str, Any]] = []
    for index in range(12):
        expected = result.monthly_kwh[index]
        measured_std = result.monthly_std_kwh[index]
        weather_relative = (measured_std / expected) if expected > 0 else band.relative
        lower, upper = band.band_for(expected, weather_relative)
        rows.append(
            {
                "month": index + 1,
                "month_name": climatology.MONTH_NAMES[index],
                "expected_kwh": round(expected, 0),
                "lower_kwh": round(lower, 0),
                "upper_kwh": round(upper, 0),
                "daily_average_kwh": round(expected / 30.4, 1),
                "variability_pct": round(weather_relative * 100, 1),
            }
        )
    return rows


def _country_code(location: Location) -> str | None:
    """ISO country code for the location, which selects currency and tariff defaults.

    Both geocoders supply the code directly, so that is used first. The name table behind
    it is a fallback for a Location built some other way — and it is a fallback rather than
    the primary path because country names arrive translated, and matching "भारत" against
    a table of English names silently yields dollars for an Indian farm.
    """
    code = getattr(location, "country_code", None)
    if code:
        return str(code).upper()

    names = {
        "india": "IN", "united states": "US", "united kingdom": "GB",
        "australia": "AU", "germany": "DE", "south africa": "ZA", "brazil": "BR",
    }
    country = (getattr(location, "country", None) or "").strip().lower()
    return names.get(country)


def _resolve_area(inp: EstimateInput, ledger: A.AssumptionLedger) -> float | None:
    """Work out available area from whichever way the user gave it (§13)."""
    if inp.area_polygon:
        area = sizing.polygon_area_m2([tuple(p) for p in inp.area_polygon])
        ledger.user_value(
            "available_area", "Area you marked on the map", round(area, 0), unit="m²",
            rationale="Measured from the shape you drew.",
        )
        return area
    if inp.available_area and inp.available_area > 0:
        area = sizing.to_square_metres(inp.available_area, inp.area_unit)
        ledger.user_value(
            "available_area", "Available area", round(area, 0), unit="m²",
            rationale=f"You entered {inp.available_area:g} {inp.area_unit}.",
        )
        return area
    return None


# --------------------------------------------------------------------------------------
# Plain-language explanation (§22)
# --------------------------------------------------------------------------------------

def build_narrative(payload: dict[str, Any]) -> dict[str, Any]:
    """Say what the result means, in the words a person would use.

    Written from the computed payload rather than alongside the calculation, so the prose
    cannot drift away from the numbers it describes.
    """
    gen = payload["generation"]
    loc = payload["location"]
    system = payload["system"]
    band = payload["uncertainty"]
    balance = payload.get("balance")
    money = payload.get("economics")

    annual = gen["annual_kwh"]
    capacity = system["capacity_kwp"]
    yield_per_kwp = gen["specific_yield_kwh_per_kwp"]

    if yield_per_kwp >= 1600:
        resource = "an excellent solar resource"
    elif yield_per_kwp >= 1300:
        resource = "a strong solar resource"
    elif yield_per_kwp >= 1000:
        resource = "a decent solar resource"
    else:
        resource = "a modest solar resource"

    panels = system.get("panels", {})
    count = panels.get("count")
    watts = panels.get("watts")

    # §15: the result has to connect the number of panels to the generation figure, not
    # present a capacity out of nowhere.
    array = (
        f"{count} × {watts} W panels ({capacity:g} kW in total)"
        if count and watts
        else f"a {capacity:g} kW system"
    )

    # Not `str.capitalize()`: it lowercases everything after the first character, which
    # turns "550 W panels (11 kW in total)" into "550 w panels (11 kw in total)".
    array_sentence = array[:1].upper() + array[1:]

    summary = (
        f"{loc.get('label', 'Your location')} has {resource}. {array_sentence} there "
        f"should generate around {annual:,.0f} units (kWh) of electricity in a typical year — "
        f"about {gen['daily_average_kwh']:,.1f} units on an average day. "
        f"{gen['best_month_name']} is usually the best month and {gen['worst_month_name']} the "
        f"weakest."
    )

    if balance:
        summary += (
            f" That covers roughly {balance['solar_offset_pct']:.0f}% of the electricity you "
            f"use."
        )
        if balance["exported_kwh"] > balance["self_consumed_kwh"]:
            summary += (
                " More than half of it would be exported rather than used on site, because "
                "your heaviest use does not line up with the middle of the day."
            )

    if money and money.get("payback_years"):
        summary += (
            f" At the assumed electricity rate it would pay back its cost in about "
            f"{money['payback_years']:.1f} years."
        )

    # ------------------------------------------------------------ what could change it
    clipped_pct = gen.get("clipped_fraction", 0.0) * 100

    affects: list[dict[str, str]] = [
        {
            "key": "panel_count",
            "title": "Adding panels does not add output in proportion",
            "body": (
                "More panels raise the DC capacity and the generation that is possible, but "
                "what actually reaches your meter is limited by the sunlight available, how "
                "hot the panels get, which way they face, what shades them, dust, wiring, "
                "downtime and the inverter's own limit. "
                + (
                    f"On this configuration the inverter already clips about "
                    f"{clipped_pct:.1f}% of daylight hours, so further panels would return "
                    f"progressively less."
                    if clipped_pct >= 1.0
                    else "On this configuration the inverter is not yet limiting output."
                )
            ),
        },
        {
            "key": "weather",
            "title": "Cloudy spells and season",
            "body": (
                f"A cloudier year than usual will produce less. Across the years we looked "
                f"at, the yearly total moved by roughly "
                f"{band['relative_pct']:.0f}% either side of the figure above."
            ),
        },
        {
            "key": "heat",
            "title": "Extreme heat",
            "body": (
                "Panels lose efficiency as they get hot, so the hottest days are not the "
                "best days. This is already modelled hour by hour using recorded "
                "temperature and wind."
            ),
        },
        {
            "key": "shading",
            "title": "Shading",
            "body": (
                "A tree, a water tank or a new building next door can cost far more than its "
                "size suggests, because shading part of a panel drags down the rest of its "
                "string."
            ),
        },
        {
            "key": "soiling",
            "title": "Dust and dirt",
            "body": (
                "Dust on the glass blocks light. In dry, dusty conditions a wash every few "
                "weeks pays for itself; rain does the job in wetter months."
            ),
        },
        {
            "key": "orientation",
            "title": "Angle and direction",
            "body": (
                f"This estimate assumes the panels sit at {system['orientation']['tilt_deg']:g}° "
                f"facing {system['orientation'].get('azimuth_compass', 'the equator')}. A roof "
                f"that faces elsewhere will produce somewhat less."
            ),
        },
        {
            "key": "equipment",
            "title": "Equipment quality",
            "body": (
                "Panels and inverters differ in efficiency and in how gracefully they handle "
                "heat. A cheap inverter that fails in year six costs more than it saved."
            ),
        },
        {
            "key": "maintenance",
            "title": "Maintenance",
            "body": (
                "Systems that are checked occasionally keep producing. Faults on an unmonitored "
                "array can go unnoticed for months — the electricity simply stops arriving."
            ),
        },
    ]

    return {
        "summary": summary,
        "confidence": band["confidence"],
        "confidence_reason": band["confidence_reason"],
        "what_affects_this": affects,
        "how_to_improve": band.get("improvements", []),
    }
