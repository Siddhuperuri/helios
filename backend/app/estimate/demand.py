"""Electricity demand: how much the user actually consumes, and when.

Three routes in, because §11 requires all three and because they carry genuinely different
accuracy:

1. **From the bill** — one number the user certainly has, divided by a tariff they may not
   know exactly. Good enough to size a system; stated as an estimate.
2. **From metered units** — the best input available short of interval data.
3. **From equipment** — for the user who knows neither. Built from what they can see and
   count: pumps, lights, a refrigerator, an air conditioner.

The *when* matters as much as the how much. Solar generates in the middle of the day; a
household that consumes mostly after dark cannot self-consume much of it without storage.
Reporting only annual totals hides that entirely, so every estimate here also carries an
hourly shape.

Those shapes are archetypes, not measurements, and they are labelled as such wherever they
reach the user. A real interval meter would beat them and this module says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

DemandMethod = Literal["bill", "metered_units", "equipment", "benchmark"]

# Conversion for motor ratings. A pump's horsepower rating is its shaft output, so the
# electrical input is larger by the motor's efficiency. Agricultural pumpsets in the field
# are frequently far less efficient than their nameplate, which is why this is a declared,
# editable assumption rather than a constant folded into the arithmetic.
WATTS_PER_HP = 745.7
DEFAULT_MOTOR_EFFICIENCY = 0.75


# --------------------------------------------------------------------------------------
# Equipment catalogue
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ApplianceSpec:
    key: str
    label: str
    typical_watts: float
    category: str
    user_types: tuple[str, ...]
    default_hours_per_day: float
    default_days_per_month: int = 30
    plain_hint: str = ""
    # Refrigeration and similar cycle on and off around a thermostat, so nameplate watts
    # times running hours would badly overstate them. The duty cycle corrects that.
    duty_cycle: float = 1.0

    def daily_kwh(self, *, count: float, hours_per_day: float, watts: float | None = None) -> float:
        w = self.typical_watts if watts is None else watts
        return (w * count * hours_per_day * self.duty_cycle) / 1000.0


ALL_TYPES = ("home", "farm", "shop", "commercial", "institution", "exploring")

APPLIANCES: dict[str, ApplianceSpec] = {
    # ---------------------------------------------------------------- lighting & comfort
    "led_light": ApplianceSpec(
        "led_light", "LED light", 12, "Lighting", ALL_TYPES, 6,
        plain_hint="A typical LED bulb or tube.",
    ),
    "tube_light": ApplianceSpec(
        "tube_light", "Tube light (older type)", 45, "Lighting", ALL_TYPES, 6,
        plain_hint="An older fluorescent tube, not an LED.",
    ),
    "ceiling_fan": ApplianceSpec(
        "ceiling_fan", "Ceiling fan", 70, "Comfort", ALL_TYPES, 10,
        plain_hint="A standard ceiling fan.",
    ),
    "air_conditioner_1t": ApplianceSpec(
        "air_conditioner_1t", "Air conditioner (1 ton)", 1_200, "Comfort", ALL_TYPES, 6,
        plain_hint="About 1 ton or 12,000 BTU. Count each indoor unit.",
        duty_cycle=0.65,
    ),
    "air_conditioner_15t": ApplianceSpec(
        "air_conditioner_15t", "Air conditioner (1.5 ton)", 1_800, "Comfort", ALL_TYPES, 6,
        plain_hint="About 1.5 ton or 18,000 BTU. The most common size.",
        duty_cycle=0.65,
    ),
    "air_cooler": ApplianceSpec(
        "air_cooler", "Evaporative air cooler", 200, "Comfort", ALL_TYPES, 8,
    ),
    # ---------------------------------------------------------------- household
    "refrigerator": ApplianceSpec(
        "refrigerator", "Refrigerator", 150, "Appliances", ALL_TYPES, 24,
        plain_hint="Leave the hours at 24 — it runs all day, we account for the cycling.",
        duty_cycle=0.35,
    ),
    "television": ApplianceSpec(
        "television", "Television", 90, "Appliances", ("home", "shop", "institution", "exploring"), 5,
    ),
    "washing_machine": ApplianceSpec(
        "washing_machine", "Washing machine", 500, "Appliances", ("home", "exploring"), 1,
        default_days_per_month=12,
    ),
    "water_heater": ApplianceSpec(
        "water_heater", "Electric water heater (geyser)", 2_000, "Appliances",
        ("home", "shop", "institution", "exploring"), 1,
    ),
    "mixer_grinder": ApplianceSpec(
        "mixer_grinder", "Mixer or grinder", 500, "Appliances", ("home", "shop", "exploring"), 0.5,
    ),
    "microwave": ApplianceSpec(
        "microwave", "Microwave oven", 1_200, "Appliances",
        ("home", "shop", "commercial", "institution", "exploring"), 0.5,
    ),
    # ---------------------------------------------------------------- work equipment
    "computer_desktop": ApplianceSpec(
        "computer_desktop", "Desktop computer", 150, "Equipment",
        ("shop", "commercial", "institution", "home", "exploring"), 8,
        default_days_per_month=26,
    ),
    "laptop": ApplianceSpec(
        "laptop", "Laptop", 50, "Equipment",
        ("shop", "commercial", "institution", "home", "exploring"), 8,
        default_days_per_month=26,
    ),
    "printer_copier": ApplianceSpec(
        "printer_copier", "Printer or photocopier", 400, "Equipment",
        ("shop", "commercial", "institution"), 2, default_days_per_month=26,
        duty_cycle=0.4,
    ),
    "commercial_freezer": ApplianceSpec(
        "commercial_freezer", "Commercial freezer or cold display", 600, "Refrigeration",
        ("shop", "commercial", "farm", "institution"), 24,
        plain_hint="A shop chiller, deep freezer or cold display cabinet.",
        duty_cycle=0.45,
    ),
    "cold_room": ApplianceSpec(
        "cold_room", "Cold room / cold storage", 3_500, "Refrigeration",
        ("farm", "commercial", "institution"), 24,
        duty_cycle=0.5,
    ),
    "milking_machine": ApplianceSpec(
        "milking_machine", "Milking machine", 1_500, "Farm equipment", ("farm",), 3,
    ),
    "chaff_cutter": ApplianceSpec(
        "chaff_cutter", "Chaff cutter", 1_500, "Farm equipment", ("farm",), 2,
    ),
    "thresher": ApplianceSpec(
        "thresher", "Thresher", 5_000, "Farm equipment", ("farm",), 4,
        default_days_per_month=6,
        plain_hint="Usually seasonal — set the days per month to match harvest use.",
    ),
    "poultry_ventilation": ApplianceSpec(
        "poultry_ventilation", "Poultry shed ventilation", 2_000, "Farm equipment", ("farm",), 12,
    ),
    "welding_machine": ApplianceSpec(
        "welding_machine", "Welding machine", 4_000, "Equipment", ("commercial", "farm", "shop"), 2,
        default_days_per_month=20, duty_cycle=0.5,
    ),
    "industrial_motor_5hp": ApplianceSpec(
        "industrial_motor_5hp", "Industrial motor (5 HP)", 4_970, "Machinery",
        ("commercial", "farm"), 8, default_days_per_month=26,
    ),
}


def appliances_for(user_type: str) -> list[ApplianceSpec]:
    """The equipment worth offering to this kind of user, in catalogue order."""
    return [a for a in APPLIANCES.values() if user_type in a.user_types]


# --------------------------------------------------------------------------------------
# Hourly load shapes
# --------------------------------------------------------------------------------------

# Normalised 24-hour archetypes, local clock time. Each is scaled to sum to 1.0 on use.
#
# These decide how much generation is consumed on site rather than exported, which changes
# the savings figure materially. They are stated as archetypes everywhere they surface —
# a household that runs its washing at noon behaves nothing like one that runs it at 21:00,
# and no archetype can know which.
_RAW_PROFILES: dict[str, list[float]] = {
    # Morning peak before work, deep evening peak after dark.
    "home": [
        0.6, 0.5, 0.45, 0.45, 0.5, 0.9, 1.4, 1.5, 1.2, 0.9, 0.85, 0.85,
        0.9, 0.9, 0.85, 0.85, 0.95, 1.3, 1.9, 2.2, 2.0, 1.6, 1.1, 0.8,
    ],
    # Pumping and field work concentrated in daylight; little at night.
    "farm": [
        0.3, 0.3, 0.3, 0.35, 0.6, 1.2, 1.8, 2.0, 2.0, 1.9, 1.7, 1.5,
        1.4, 1.4, 1.5, 1.6, 1.5, 1.1, 0.7, 0.5, 0.45, 0.4, 0.35, 0.3,
    ],
    # Shop hours, with a long evening tail — retail stays open after dark.
    "shop": [
        0.2, 0.2, 0.2, 0.2, 0.25, 0.4, 0.7, 1.1, 1.6, 1.9, 2.0, 2.0,
        1.9, 1.8, 1.8, 1.9, 2.0, 2.0, 1.9, 1.6, 1.2, 0.7, 0.35, 0.25,
    ],
    # Office and industrial: strong, flat working day.
    "commercial": [
        0.5, 0.5, 0.5, 0.5, 0.6, 0.8, 1.2, 1.7, 2.1, 2.2, 2.2, 2.2,
        1.9, 2.1, 2.2, 2.1, 1.9, 1.5, 1.0, 0.8, 0.7, 0.6, 0.55, 0.5,
    ],
    # School or college: sharp start, ends mid-afternoon, quiet evening.
    "institution": [
        0.25, 0.25, 0.25, 0.25, 0.3, 0.5, 0.9, 1.6, 2.2, 2.4, 2.4, 2.3,
        2.0, 2.1, 2.0, 1.6, 1.0, 0.7, 0.5, 0.45, 0.4, 0.35, 0.3, 0.25,
    ],
}
_RAW_PROFILES["exploring"] = _RAW_PROFILES["home"]

PROFILE_DESCRIPTIONS: dict[str, str] = {
    "home": "Light use overnight, a morning peak, and the heaviest use in the evening.",
    "farm": "Most use during daylight, when pumps and equipment run.",
    "shop": "Steady use through trading hours, continuing into the evening.",
    "commercial": "A strong, flat working day with a quieter night.",
    "institution": "Busy from morning to mid-afternoon, quiet after closing.",
    "exploring": "Light use overnight, a morning peak, and the heaviest use in the evening.",
}


def hourly_profile(user_type: str) -> np.ndarray:
    """A 24-element load shape summing to 1.0, indexed by local hour."""
    raw = np.asarray(_RAW_PROFILES.get(user_type, _RAW_PROFILES["home"]), dtype=np.float64)
    total = raw.sum()
    if total <= 0:
        return np.full(24, 1.0 / 24.0)
    return raw / total


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------

@dataclass
class DemandEstimate:
    """Estimated electricity demand, with the route that produced it."""

    annual_kwh: float
    monthly_kwh: float
    daily_kwh: float
    method: DemandMethod
    method_label: str
    confidence: Literal["high", "medium", "low"]
    notes: list[str] = field(default_factory=list)
    breakdown: list[dict[str, Any]] = field(default_factory=list)
    profile_key: str = "home"

    def to_dict(self) -> dict[str, Any]:
        return {
            "annual_kwh": round(self.annual_kwh, 1),
            "monthly_kwh": round(self.monthly_kwh, 1),
            "daily_kwh": round(self.daily_kwh, 2),
            "method": self.method,
            "method_label": self.method_label,
            "confidence": self.confidence,
            "notes": self.notes,
            "breakdown": self.breakdown,
            "profile_key": self.profile_key,
            "profile_description": PROFILE_DESCRIPTIONS.get(self.profile_key, ""),
            # The actual 24 hourly values used to compute self-consumption, in kWh.
            #
            # Returned rather than left for the client to reconstruct: the day-profile
            # chart overlays demand on generation, and a chart drawing a shape the
            # calculation did not use is a chart that lies. Shipping the numbers is also
            # the only way the two cannot drift apart later.
            "hourly_kwh": [
                round(float(v), 4) for v in hourly_profile(self.profile_key) * self.daily_kwh
            ],
        }


def _finish(
    monthly_kwh: float,
    *,
    method: DemandMethod,
    method_label: str,
    confidence: Literal["high", "medium", "low"],
    notes: list[str],
    breakdown: list[dict[str, Any]],
    profile_key: str,
) -> DemandEstimate:
    monthly = max(0.0, float(monthly_kwh))
    return DemandEstimate(
        annual_kwh=monthly * 12.0,
        monthly_kwh=monthly,
        daily_kwh=monthly * 12.0 / 365.0,
        method=method,
        method_label=method_label,
        confidence=confidence,
        notes=notes,
        breakdown=breakdown,
        profile_key=profile_key,
    )


def from_metered_units(monthly_kwh: float, *, user_type: str = "home") -> DemandEstimate:
    """The user read the units off their bill. Best available input."""
    if monthly_kwh <= 0:
        raise ValueError("Monthly consumption must be greater than zero.")
    return _finish(
        monthly_kwh,
        method="metered_units",
        method_label="From the units on your bill",
        confidence="high",
        notes=[
            "Based on the units you entered. Consumption varies through the year — a "
            "summer month with heavy cooling can run well above the average."
        ],
        breakdown=[],
        profile_key=user_type,
    )


def from_bill(
    *,
    monthly_bill: float,
    rate_per_kwh: float,
    fixed_monthly_charge: float = 0.0,
    user_type: str = "home",
) -> DemandEstimate:
    """The user knows what they pay, not what they use."""
    from app.estimate.tariffs import consumption_from_bill

    if monthly_bill <= 0:
        raise ValueError("The monthly bill must be greater than zero.")

    kwh, notes = consumption_from_bill(
        monthly_bill=monthly_bill,
        rate_per_kwh=rate_per_kwh,
        fixed_monthly_charge=fixed_monthly_charge,
    )
    return _finish(
        kwh,
        method="bill",
        method_label="Estimated from your monthly bill",
        confidence="medium",
        notes=notes,
        breakdown=[],
        profile_key=user_type,
    )


@dataclass
class EquipmentItem:
    """One line of declared equipment."""

    key: str
    count: float = 1.0
    hours_per_day: float | None = None
    days_per_month: int | None = None
    watts_override: float | None = None


def from_equipment(
    items: list[EquipmentItem],
    *,
    user_type: str = "home",
    pumps: list[dict[str, Any]] | None = None,
    motor_efficiency: float = DEFAULT_MOTOR_EFFICIENCY,
) -> DemandEstimate:
    """Build consumption up from what the user can see and count.

    ``pumps`` is handled separately from the appliance catalogue because a pump is rated in
    horsepower rather than watts, and because the conversion involves motor efficiency that
    the user should be able to see and change.
    """
    breakdown: list[dict[str, Any]] = []
    monthly_total = 0.0
    notes: list[str] = []

    for item in items:
        spec = APPLIANCES.get(item.key)
        if spec is None:
            notes.append(f"Ignored an unrecognised equipment type: '{item.key}'.")
            continue
        hours = spec.default_hours_per_day if item.hours_per_day is None else item.hours_per_day
        days = spec.default_days_per_month if item.days_per_month is None else item.days_per_month
        if hours < 0 or hours > 24:
            raise ValueError(
                f"Hours per day for '{spec.label}' must be between 0 and 24; got {hours}."
            )
        if days < 0 or days > 31:
            raise ValueError(
                f"Days per month for '{spec.label}' must be between 0 and 31; got {days}."
            )
        daily = spec.daily_kwh(count=item.count, hours_per_day=hours, watts=item.watts_override)
        monthly = daily * days
        monthly_total += monthly
        breakdown.append(
            {
                "key": spec.key,
                "label": spec.label,
                "category": spec.category,
                "count": item.count,
                "watts_each": item.watts_override or spec.typical_watts,
                "hours_per_day": hours,
                "days_per_month": days,
                "duty_cycle": spec.duty_cycle,
                "monthly_kwh": round(monthly, 1),
            }
        )

    for pump in pumps or []:
        hp = float(pump.get("horsepower", 0) or 0)
        count = float(pump.get("count", 1) or 1)
        hours = float(pump.get("hours_per_day", 0) or 0)
        days = float(pump.get("days_per_month", 26) or 26)
        eff = float(pump.get("motor_efficiency") or motor_efficiency)
        if hp <= 0 or hours <= 0:
            continue
        if not 0.2 <= eff <= 1.0:
            raise ValueError(
                f"Motor efficiency must be between 0.2 and 1.0; got {eff}."
            )
        input_kw = (hp * WATTS_PER_HP / eff) / 1000.0
        monthly = input_kw * count * hours * days
        monthly_total += monthly
        breakdown.append(
            {
                "key": "water_pump",
                "label": f"Water pump ({hp:g} HP)",
                "category": "Pumping",
                "count": count,
                "watts_each": round(input_kw * 1000.0, 0),
                "hours_per_day": hours,
                "days_per_month": days,
                "duty_cycle": 1.0,
                "monthly_kwh": round(monthly, 1),
                "motor_efficiency": eff,
            }
        )

    if not breakdown:
        raise ValueError(
            "No equipment was entered, so consumption cannot be estimated this way. Enter "
            "at least one item, or tell us your bill or your monthly units instead."
        )

    notes.append(
        "Built up from the equipment you listed. Real use is usually a little higher, "
        "because small items are easy to forget."
    )
    return _finish(
        monthly_total,
        method="equipment",
        method_label="Estimated from your equipment",
        confidence="medium",
        notes=notes,
        breakdown=sorted(breakdown, key=lambda b: -b["monthly_kwh"]),
        profile_key=user_type,
    )


# Floor-area benchmarks, kWh per square metre per year. Used only when the user can give
# nothing else. Coarse by nature, and reported with low confidence.
_AREA_BENCHMARKS_KWH_PER_M2_YEAR: dict[str, float] = {
    "home": 45.0,
    "shop": 120.0,
    "commercial": 150.0,
    "institution": 80.0,
    "farm": 30.0,
    "exploring": 45.0,
}


def from_floor_area(
    *,
    floor_area_m2: float,
    user_type: str = "commercial",
    occupants: int | None = None,
) -> DemandEstimate:
    """Last resort: infer demand from building size."""
    if floor_area_m2 <= 0:
        raise ValueError("Floor area must be greater than zero.")

    intensity = _AREA_BENCHMARKS_KWH_PER_M2_YEAR.get(user_type, 100.0)
    annual = floor_area_m2 * intensity
    notes = [
        f"Estimated from a floor area of {floor_area_m2:,.0f} m² at roughly "
        f"{intensity:g} kWh per m² per year for this kind of building. This is a coarse "
        f"benchmark — your bill or your units would give a much better answer."
    ]
    if occupants:
        notes.append(
            f"You told us about {occupants} people use the building. We have not adjusted "
            f"the benchmark for that, because occupancy and floor area usually move "
            f"together and counting both would double it."
        )
    return _finish(
        annual / 12.0,
        method="benchmark",
        method_label="Estimated from building size",
        confidence="low",
        notes=notes,
        breakdown=[],
        profile_key=user_type,
    )
