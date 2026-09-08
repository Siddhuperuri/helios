"""Farm output: what the energy actually does, not just how many kilowatt-hours it is.

§24 asks for this and then immediately constrains it: *do not invent agricultural
performance without sufficient inputs*. That constraint shapes the whole module. Every
function here checks that it was given enough to answer, and when it was not it returns
what is missing rather than a plausible-looking number.

A farmer told "your system generates 18,400 kWh a year" has learned almost nothing. The
same farmer told "this runs your 5 HP pump for about six hours on a typical day, and about
three hours in the monsoon" can make a decision. That translation is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.estimate.demand import DEFAULT_MOTOR_EFFICIENCY, WATTS_PER_HP

# Gravity times the density of water, over 1000, giving kW directly from m³/s and metres.
HYDRAULIC_CONSTANT = 9.81

# Wire-to-water efficiency for a typical agricultural pumpset: the pump end alone, before
# the motor. Field-installed pumpsets frequently do worse, especially older ones with a
# worn impeller or an oversized pipe run.
DEFAULT_PUMP_EFFICIENCY = 0.55


@dataclass
class PumpingCapability:
    """What the modelled generation can pump, given what the user told us."""

    sufficient_inputs: bool
    missing: list[str] = field(default_factory=list)
    pump_input_kw: float | None = None
    typical_daily_hours: float | None = None
    best_month_hours: float | None = None
    worst_month_hours: float | None = None
    daily_water_m3: float | None = None
    irrigable_area_hectares: float | None = None
    meets_requirement: bool | None = None
    notes: list[str] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sufficient_inputs": self.sufficient_inputs,
            "missing": self.missing,
            "pump_input_kw": round(self.pump_input_kw, 2) if self.pump_input_kw else None,
            "typical_daily_hours": (
                round(self.typical_daily_hours, 1) if self.typical_daily_hours else None
            ),
            "best_month_hours": (
                round(self.best_month_hours, 1) if self.best_month_hours else None
            ),
            "worst_month_hours": (
                round(self.worst_month_hours, 1) if self.worst_month_hours else None
            ),
            "daily_water_m3": round(self.daily_water_m3, 1) if self.daily_water_m3 else None,
            "daily_water_litres": (
                round(self.daily_water_m3 * 1000, 0) if self.daily_water_m3 else None
            ),
            "irrigable_area_hectares": (
                round(self.irrigable_area_hectares, 2) if self.irrigable_area_hectares else None
            ),
            "irrigable_area_acres": (
                round(self.irrigable_area_hectares * 2.4711, 2)
                if self.irrigable_area_hectares
                else None
            ),
            "meets_requirement": self.meets_requirement,
            "notes": self.notes,
            "assumptions": self.assumptions,
        }


def pump_input_kw(
    *,
    horsepower: float | None = None,
    motor_efficiency: float = DEFAULT_MOTOR_EFFICIENCY,
) -> float | None:
    """Electrical input a pump draws, from its horsepower rating."""
    if not horsepower or horsepower <= 0:
        return None
    return (horsepower * WATTS_PER_HP / motor_efficiency) / 1000.0


def capability(
    *,
    daily_generation_kwh: float,
    best_month_daily_kwh: float | None = None,
    worst_month_daily_kwh: float | None = None,
    horsepower: float | None = None,
    motor_efficiency: float = DEFAULT_MOTOR_EFFICIENCY,
    pump_efficiency: float = DEFAULT_PUMP_EFFICIENCY,
    head_metres: float | None = None,
    required_daily_water_m3: float | None = None,
    crop_water_requirement_mm_per_day: float | None = None,
    other_daily_load_kwh: float = 0.0,
) -> PumpingCapability:
    """Translate generation into pumping, refusing to guess what was not supplied."""
    missing: list[str] = []
    notes: list[str] = []
    assumptions: list[dict[str, Any]] = []

    if not horsepower or horsepower <= 0:
        missing.append("The pump's horsepower rating")

    if missing:
        return PumpingCapability(
            sufficient_inputs=False,
            missing=missing,
            notes=[
                "Tell us about your pump and we can show how long this system could run it, "
                "and how much water that moves."
            ],
        )

    input_kw = pump_input_kw(horsepower=horsepower, motor_efficiency=motor_efficiency)
    assert input_kw is not None

    assumptions.append(
        {
            "key": "motor_efficiency",
            "label": "Pump motor efficiency",
            "value": motor_efficiency,
            "note": (
                "A pump's horsepower is its shaft output, so it draws more electricity than "
                "that. Older field pumpsets are often less efficient than this."
            ),
        }
    )

    # Energy left for pumping after whatever else runs on the same system.
    available = max(0.0, daily_generation_kwh - max(0.0, other_daily_load_kwh))
    typical_hours = available / input_kw if input_kw > 0 else 0.0

    best_hours = (
        max(0.0, best_month_daily_kwh - other_daily_load_kwh) / input_kw
        if best_month_daily_kwh and input_kw > 0
        else None
    )
    worst_hours = (
        max(0.0, worst_month_daily_kwh - other_daily_load_kwh) / input_kw
        if worst_month_daily_kwh and input_kw > 0
        else None
    )

    notes.append(
        f"A {horsepower:g} HP pump draws about {input_kw:.2f} kW while running. On a typical "
        f"day this system generates enough to run it for roughly {typical_hours:.1f} hours."
    )
    if worst_hours is not None and best_hours is not None:
        notes.append(
            f"That varies through the year — about {best_hours:.1f} hours a day in the "
            f"sunniest month and {worst_hours:.1f} in the dullest. Plan irrigation around "
            f"the dull months, not the average."
        )
    notes.append(
        "Pumping happens while the sun is up unless you add storage. If you need to irrigate "
        "before dawn or after dark, you would need a battery or a grid connection."
    )

    # ------------------------------------------------------------------ water volume
    daily_water: float | None = None
    irrigable: float | None = None
    meets: bool | None = None

    if head_metres and head_metres > 0:
        # Hydraulic power = rho*g*Q*H. Rearranged for flow, given the shaft power the
        # motor delivers and the pump end's efficiency.
        shaft_kw = input_kw * motor_efficiency
        hydraulic_kw = shaft_kw * pump_efficiency
        flow_m3_per_s = hydraulic_kw / (HYDRAULIC_CONSTANT * head_metres)
        flow_m3_per_hour = flow_m3_per_s * 3600.0
        daily_water = flow_m3_per_hour * typical_hours

        assumptions.append(
            {
                "key": "pump_efficiency",
                "label": "Pump efficiency",
                "value": pump_efficiency,
                "note": (
                    "How much of the shaft power actually becomes water pressure and flow. "
                    "Worn impellers and undersized pipes push this lower."
                ),
            }
        )
        notes.append(
            f"At a head of {head_metres:g} m this works out to roughly "
            f"{flow_m3_per_hour:,.1f} m³ per hour, or about {daily_water:,.0f} m³ "
            f"({daily_water * 1000:,.0f} litres) on a typical day."
        )

        if crop_water_requirement_mm_per_day and crop_water_requirement_mm_per_day > 0:
            # 1 mm of depth over 1 hectare is 10 m³.
            irrigable = daily_water / (crop_water_requirement_mm_per_day * 10.0)
            notes.append(
                f"At {crop_water_requirement_mm_per_day:g} mm per day, that covers about "
                f"{irrigable:.2f} hectares ({irrigable * 2.4711:.2f} acres). Crop water need "
                f"changes with the crop, the soil and the season, so treat this as a guide."
            )

        if required_daily_water_m3 and required_daily_water_m3 > 0:
            meets = daily_water >= required_daily_water_m3
            if meets:
                notes.append(
                    f"That covers the {required_daily_water_m3:,.0f} m³ a day you said you "
                    f"need, with room to spare."
                )
            else:
                shortfall = required_daily_water_m3 - daily_water
                notes.append(
                    f"That falls about {shortfall:,.0f} m³ a day short of the "
                    f"{required_daily_water_m3:,.0f} m³ you said you need. A larger system, "
                    f"or pumping over more hours, would close the gap."
                )
    else:
        missing.append("The depth or head the pump lifts water from")
        notes.append(
            "Tell us how deep your borewell is, or how high the water is lifted, and we can "
            "estimate how much water this pumps rather than only how long it runs."
        )

    return PumpingCapability(
        sufficient_inputs=True,
        missing=missing,
        pump_input_kw=input_kw,
        typical_daily_hours=typical_hours,
        best_month_hours=best_hours,
        worst_month_hours=worst_hours,
        daily_water_m3=daily_water,
        irrigable_area_hectares=irrigable,
        meets_requirement=meets,
        notes=notes,
        assumptions=assumptions,
    )
