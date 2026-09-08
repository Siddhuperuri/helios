"""How big a system, at what tilt, facing where — and what limits it.

Two decisions live here, and both are ones a beginner should never have to make.

**Orientation.** Rather than applying a latitude rule of thumb, the optimum is *searched*
against this location's own weather using the same physical chain that produces the yield
figure. That matters where the climate is seasonally asymmetric: under a monsoon the
best fixed tilt is not the one a clear-sky rule predicts, because the cloudiest months
contribute little and the optimum shifts toward the seasons that actually deliver. The
search is cheap because solar position depends only on time and place, so it is computed
once and reused across every candidate orientation.

**Capacity.** Three things independently limit a system: the demand worth offsetting, the
space available, and the budget. The recommendation is the smallest of them, and which one
bound the result is reported — "your roof is the limit, not your budget" is far more useful
than a bare number.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.data.sources import Location
from app.estimate import assumptions as A
from app.estimate import space
from app.features.solar_geometry import (
    PVSystem,
    pv_power_chain,
    representative_times,
    solar_position,
)

logger = logging.getLogger(__name__)

BindingConstraint = Literal[
    "demand", "space", "budget", "user_specified", "default", "existing_system"
]


# --------------------------------------------------------------------------------------
# Area
# --------------------------------------------------------------------------------------

SQFT_PER_SQM = 10.7639


def to_square_metres(value: float, unit: str) -> float:
    """Normalise an area to m². Users think in whichever unit their region uses (§13)."""
    unit = (unit or "sqm").strip().lower()
    if unit in {"sqm", "m2", "sq_m", "square_metres", "square_meters"}:
        return float(value)
    if unit in {"sqft", "ft2", "sq_ft", "square_feet"}:
        return float(value) / SQFT_PER_SQM
    if unit in {"acre", "acres"}:
        return float(value) * 4046.86
    if unit in {"hectare", "hectares", "ha"}:
        return float(value) * 10_000.0
    if unit in {"cent", "cents"}:  # common in south India: 1/100 acre
        return float(value) * 40.4686
    if unit in {"guntha", "gunthas"}:  # common in Maharashtra/Karnataka
        return float(value) * 101.17
    raise ValueError(f"Unrecognised area unit '{unit}'.")


def polygon_area_m2(coordinates: list[tuple[float, float]]) -> float:
    """Area of a polygon drawn on the map, in m² (§13).

    Uses an equirectangular projection about the polygon's own centroid, with longitude
    scaled by cos(latitude). For a rooftop or a field — hundreds of metres across — the
    error against a proper geodesic area is far below the error in the user's tracing, and
    it needs no projection library.
    """
    if len(coordinates) < 3:
        raise ValueError("An area needs at least three points. Add another corner.")

    lats = np.array([c[0] for c in coordinates], dtype=np.float64)
    lons = np.array([c[1] for c in coordinates], dtype=np.float64)

    if np.any(np.abs(lats) > 90) or np.any(np.abs(lons) > 180):
        raise ValueError("The drawn shape contains an invalid coordinate.")

    lat0 = float(lats.mean())
    metres_per_deg_lat = 111_320.0
    metres_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))

    x = (lons - lons.mean()) * metres_per_deg_lon
    y = (lats - lat0) * metres_per_deg_lat

    # Shoelace formula.
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return float(area)


def area_from_dimensions(length: float, width: float, unit: str = "m") -> float:
    """Area in m² from a length and a width, for users who measured with a tape."""
    if length <= 0 or width <= 0:
        raise ValueError("Length and width must both be greater than zero.")
    unit = (unit or "m").strip().lower()
    if unit in {"m", "metre", "meter", "metres", "meters"}:
        return float(length * width)
    if unit in {"ft", "foot", "feet"}:
        return float(length * width) / SQFT_PER_SQM
    raise ValueError(f"Unrecognised length unit '{unit}'.")


def area_per_kwp(installation_type: str, panel_key: str = A.DEFAULT_PANEL_KEY) -> float:
    """Buildable area occupied per kWp, including row spacing and walkways.

    Note this is *footprint* per kWp, not stated roof area per kWp — see
    :func:`app.estimate.space.available_area_for_capacity` for the latter.
    """
    return space.area_for_capacity(1.0, installation_type, panel_key)


def capacity_from_area(
    area_m2: float, installation_type: str, panel_key: str = A.DEFAULT_PANEL_KEY
) -> float:
    """Largest system a stated available area can hold.

    Delegates to the space model, which applies the usable fraction before spacing. Sizing
    straight from stated area treats a roof as if it were empty, and produces
    recommendations that do not fit (§6).
    """
    return space.capacity_from_available_area(area_m2, installation_type, panel_key)


def area_for_capacity(
    capacity_kwp: float, installation_type: str, panel_key: str = A.DEFAULT_PANEL_KEY
) -> float:
    """Buildable footprint a system of this size will occupy."""
    return space.area_for_capacity(capacity_kwp, installation_type, panel_key)


# --------------------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------------------

@dataclass
class Orientation:
    tilt_deg: float
    azimuth_deg: float
    annual_kwh_per_kwp: float
    gain_over_flat_pct: float
    method: str
    candidates: list[dict[str, float]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tilt_deg": round(self.tilt_deg, 1),
            "azimuth_deg": round(self.azimuth_deg, 1),
            "azimuth_compass": compass_label(self.azimuth_deg),
            "annual_kwh_per_kwp": round(self.annual_kwh_per_kwp, 0),
            "gain_over_flat_pct": round(self.gain_over_flat_pct, 1),
            "method": self.method,
            "note": self.note,
            "candidates": self.candidates,
        }


def compass_label(azimuth_deg: float) -> str:
    """Plain-language compass direction. A beginner does not read degrees (§9, §31)."""
    points = [
        (0, "north"), (45, "north-east"), (90, "east"), (135, "south-east"),
        (180, "south"), (225, "south-west"), (270, "west"), (315, "north-west"), (360, "north"),
    ]
    best = min(points, key=lambda p: abs(p[0] - (azimuth_deg % 360)))
    return best[1]


def _annual_yield_per_kwp(
    *,
    frame: pd.DataFrame,
    location: Location,
    base_system: PVSystem,
    tilt: float,
    azimuth: float,
    position: Any,
) -> float:
    """Annual AC kWh per kWp for one candidate orientation."""
    candidate = PVSystem(
        dc_capacity_kwp=1.0,
        surface_tilt_deg=tilt,
        surface_azimuth_deg=azimuth,
        temperature_coefficient_per_c=base_system.temperature_coefficient_per_c,
        system_losses_fraction=base_system.system_losses_fraction,
        inverter_efficiency=base_system.inverter_efficiency,
        # Deliberately unconstrained during the search. A clipping limit would penalise
        # the orientations that produce the sharpest midday peak, which is an artefact of
        # inverter sizing rather than a property of the orientation.
        inverter_ac_capacity_kw=None,
        albedo=base_system.albedo,
    )
    out = pv_power_chain(
        ghi=frame["ghi_wm2"].to_numpy(dtype=np.float64),
        air_temp_c=frame["temperature_c"].to_numpy(dtype=np.float64),
        wind_speed_ms=frame["wind_speed_ms"].to_numpy(dtype=np.float64),
        times_utc=frame.index.to_numpy(),
        latitude=location.latitude,
        longitude=location.longitude,
        system=candidate,
        position=position,
    )
    years = len(frame) / (365.25 * 24.0)
    return float(out.ac_power_kw.sum()) / max(years, 1e-9)


def _search_sample(frame: pd.DataFrame, max_rows: int = 9_000) -> pd.DataFrame:
    """Thin the record for the orientation search without biasing it.

    The search compares orientations against each other, so it does not need every hour —
    but *how* it is thinned matters. Taking every third hour would sample the same eight
    clock hours forever, which is precisely the bias that decides a tilt comparison. A
    stride coprime with 24 rotates through every hour of the day instead, and keeps the
    full multi-year seasonal span.
    """
    if len(frame) <= max_rows:
        return frame
    stride = max(2, len(frame) // max_rows)
    while math.gcd(stride, 24) != 1:
        stride += 1
    return frame.iloc[::stride]


def optimal_orientation(
    frame: pd.DataFrame,
    location: Location,
    base_system: PVSystem,
    *,
    tilt_step: float = 5.0,
    max_tilt: float = 60.0,
) -> Orientation:
    """Search this location's own weather for the best fixed tilt and azimuth.

    Two passes: tilt at an equator-facing azimuth, then azimuth at the winning tilt. A full
    grid would cost an order of magnitude more for a gain of a fraction of a percent, since
    the two interact weakly for fixed arrays.
    """
    frame = _search_sample(frame)

    # Solar position is invariant to orientation, so it is computed once and handed to
    # every candidate. This is what makes an empirical search affordable.
    position = solar_position(
        representative_times(frame.index.to_numpy()), location.latitude, location.longitude
    )

    equator_azimuth = 180.0 if location.latitude >= 0 else 0.0
    candidates: list[dict[str, float]] = []

    tilts = np.arange(0.0, max_tilt + tilt_step, tilt_step)
    tilt_yields = []
    for tilt in tilts:
        y = _annual_yield_per_kwp(
            frame=frame, location=location, base_system=base_system,
            tilt=float(tilt), azimuth=equator_azimuth, position=position,
        )
        tilt_yields.append(y)
        candidates.append({"tilt_deg": float(tilt), "azimuth_deg": equator_azimuth,
                           "annual_kwh_per_kwp": round(y, 1)})

    best_tilt = float(tilts[int(np.argmax(tilt_yields))])
    flat_yield = float(tilt_yields[0])

    azimuth_offsets = np.array([-30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0])
    azimuth_yields = []
    for offset in azimuth_offsets:
        az = (equator_azimuth + offset) % 360.0
        y = _annual_yield_per_kwp(
            frame=frame, location=location, base_system=base_system,
            tilt=best_tilt, azimuth=az, position=position,
        )
        azimuth_yields.append(y)
        candidates.append({"tilt_deg": best_tilt, "azimuth_deg": float(az),
                           "annual_kwh_per_kwp": round(y, 1)})

    best_idx = int(np.argmax(azimuth_yields))

    # Yield is very flat around the azimuth optimum, so the winning candidate is often
    # ahead of straight equator-facing by a fraction of a percent — inside the noise of
    # everything else in this estimate. Telling somebody to face their panels 170° when
    # 180° is within a tenth of a percent is false precision, and "face south" is an
    # instruction a builder can actually follow. So a negligible win snaps back.
    equator_idx = int(np.argmin(np.abs(azimuth_offsets)))
    equator_yield = float(azimuth_yields[equator_idx])
    if equator_yield > 0 and (azimuth_yields[best_idx] / equator_yield - 1.0) < 0.005:
        best_idx = equator_idx

    best_azimuth = float((equator_azimuth + azimuth_offsets[best_idx]) % 360.0)
    best_yield = float(azimuth_yields[best_idx])

    gain = ((best_yield / flat_yield) - 1.0) * 100.0 if flat_yield > 0 else 0.0

    note = (
        f"Found by testing {len(candidates)} orientations against {len(frame):,} hours of "
        f"real weather at your location, not from a rule of thumb."
    )
    offset_from_equator = abs(azimuth_offsets[best_idx])
    if offset_from_equator >= 10.0:
        direction = "west" if (azimuth_offsets[best_idx] > 0) == (location.latitude >= 0) else "east"
        note += (
            f" The best direction sits {offset_from_equator:.0f}° toward the {direction} of "
            f"straight {compass_label(equator_azimuth)}, because this location's cloud "
            f"pattern is not the same in the morning as in the afternoon."
        )

    return Orientation(
        tilt_deg=best_tilt,
        azimuth_deg=best_azimuth,
        annual_kwh_per_kwp=best_yield,
        gain_over_flat_pct=gain,
        method="empirical_search",
        candidates=candidates,
        note=note,
    )


# --------------------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------------------

@dataclass
class PanelConfiguration:
    """A whole number of panels, and the capacity they actually add up to."""

    count: int
    watts: int
    capacity_kwp: float
    watts_known: bool
    source: Literal["existing_system", "recommended", "user_specified"]
    model: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "watts": self.watts,
            "capacity_kwp": round(self.capacity_kwp, 3),
            "watts_known": self.watts_known,
            "source": self.source,
            "model": self.model,
            "note": self.note,
            "summary": f"{self.count} × {self.watts} W ≈ {self.capacity_kwp:.2f} kW DC",
        }


def capacity_from_panels(count: int, watts: int) -> float:
    """Total DC capacity in kWp. The one place this arithmetic lives."""
    if count <= 0:
        raise ValueError("The number of panels must be at least 1.")
    if watts <= 0:
        raise ValueError("Panel wattage must be greater than zero.")
    return (count * watts) / 1000.0


def panels_for_capacity(target_kwp: float, watts: int) -> int:
    """How many panels of this rating make up a target capacity.

    Rounded to the nearest whole panel, never below one. Rounding *down* would
    systematically undersize every recommendation by up to half a panel, and there is no
    such thing as most of a panel.
    """
    if watts <= 0:
        raise ValueError("Panel wattage must be greater than zero.")
    return max(1, round((target_kwp * 1000.0) / watts))


def configure_panels(
    *,
    target_kwp: float,
    watts: int | None,
    panel_key: str = A.DEFAULT_PANEL_KEY,
    count_override: int | None = None,
    source: Literal["existing_system", "recommended", "user_specified"] = "recommended",
    model: str | None = None,
) -> PanelConfiguration:
    """Turn a capacity target into a whole number of real panels.

    The returned capacity is recomputed **from the rounded count**, not carried over from
    the target. This matters more than it looks: a sizing pass might land on 15.37 kW, but
    28 panels of 550 W are 15.40 kW, and the generation figure has to belong to the
    configuration the user is actually shown. Reporting the target while quoting the panel
    count would be two different systems on one page.
    """
    watts_known = watts is not None
    resolved_watts = int(watts) if watts else A.typical_panel_watts(panel_key)

    if count_override is not None and count_override > 0:
        count = int(count_override)
    else:
        count = panels_for_capacity(target_kwp, resolved_watts)

    capacity = capacity_from_panels(count, resolved_watts)

    if not watts_known:
        note = (
            f"Panel wattage was not given, so a typical {resolved_watts} W panel was "
            f"assumed. The real figure is printed on the panel label and on any quote — "
            f"entering it will sharpen this estimate."
        )
    elif source == "existing_system":
        note = f"Your existing array: {count} panels rated {resolved_watts} W each."
    else:
        note = f"{count} panels of {resolved_watts} W make up {capacity:.2f} kW of capacity."

    return PanelConfiguration(
        count=count,
        watts=resolved_watts,
        capacity_kwp=capacity,
        watts_known=watts_known,
        source=source,
        model=model,
        note=note,
    )


# --------------------------------------------------------------------------------------
# Capacity
# --------------------------------------------------------------------------------------

@dataclass
class SizingResult:
    capacity_kwp: float
    binding_constraint: BindingConstraint
    reason: str
    area_required_m2: float
    area_available_m2: float | None
    capacity_from_demand_kwp: float | None
    capacity_from_area_kwp: float | None
    capacity_from_budget_kwp: float | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capacity_kwp": round(self.capacity_kwp, 2),
            "binding_constraint": self.binding_constraint,
            "reason": self.reason,
            "area_required_m2": round(self.area_required_m2, 1),
            "area_required_sqft": round(self.area_required_m2 * SQFT_PER_SQM, 0),
            "area_available_m2": (
                round(self.area_available_m2, 1) if self.area_available_m2 else None
            ),
            "capacity_from_demand_kwp": (
                round(self.capacity_from_demand_kwp, 2) if self.capacity_from_demand_kwp else None
            ),
            "capacity_from_area_kwp": (
                round(self.capacity_from_area_kwp, 2) if self.capacity_from_area_kwp else None
            ),
            "capacity_from_budget_kwp": (
                round(self.capacity_from_budget_kwp, 2) if self.capacity_from_budget_kwp else None
            ),
            "notes": self.notes,
        }


# Smallest system worth installing. Below this the fixed costs of inverter, structure,
# wiring and paperwork dominate and the economics stop making sense.
MIN_PRACTICAL_KWP = 0.5


def recommend_capacity(
    *,
    annual_demand_kwh: float | None,
    specific_yield_kwh_per_kwp: float,
    available_area_m2: float | None,
    installation_type: str,
    panel_key: str = A.DEFAULT_PANEL_KEY,
    budget: float | None = None,
    requested_kwp: float | None = None,
    offset_target: float = 1.0,
    currency_code: str = "INR",
) -> SizingResult:
    """Recommend a system size, and name what limited it."""
    if specific_yield_kwh_per_kwp <= 0:
        raise ValueError("Specific yield must be positive to size a system.")

    notes: list[str] = []
    per_kwp_area = area_per_kwp(installation_type, panel_key)

    from_demand = (
        (annual_demand_kwh * offset_target) / specific_yield_kwh_per_kwp
        if annual_demand_kwh and annual_demand_kwh > 0
        else None
    )
    from_area = (
        capacity_from_area(available_area_m2, installation_type, panel_key)
        if available_area_m2 and available_area_m2 > 0
        else None
    )
    from_budget = None
    if budget and budget > 0:
        # Cost per kWp falls with size, so solve iteratively: guess a tier, recompute.
        guess = budget / A.indicative_cost_per_kwp(5.0, currency_code)
        for _ in range(4):
            guess = budget / A.indicative_cost_per_kwp(guess, currency_code)
        from_budget = guess

    if requested_kwp and requested_kwp > 0:
        capacity = float(requested_kwp)
        constraint: BindingConstraint = "user_specified"
        reason = "This is the system size you asked us to model."
        if from_area and capacity > from_area * 1.02:
            notes.append(
                f"A {capacity:,.1f} kW system needs about "
                f"{area_for_capacity(capacity, installation_type, panel_key):,.0f} m², which "
                f"is more than the space you told us about. The estimate still runs, but "
                f"the array may not physically fit."
            )
    else:
        options: list[tuple[float, BindingConstraint, str]] = []
        if from_demand:
            options.append((
                from_demand, "demand",
                "Sized to cover the electricity you use. A larger system would export more "
                "than it saves.",
            ))
        if from_area:
            options.append((
                from_area, "space",
                "Sized to fit the space you have. With more space you could install more.",
            ))
        if from_budget:
            options.append((
                from_budget, "budget",
                "Sized to your budget. This is what that amount typically installs.",
            ))

        if not options:
            capacity = 3.0
            constraint = "default"
            reason = (
                "We had nothing to size against, so this is a common starting size. Tell us "
                "your consumption or your available space for a figure meant for you."
            )
        else:
            capacity, constraint, reason = min(options, key=lambda o: o[0])

    if capacity < MIN_PRACTICAL_KWP:
        notes.append(
            f"The calculation pointed to {capacity:.2f} kW, which is below the smallest "
            f"system worth installing. We have used {MIN_PRACTICAL_KWP} kW instead."
        )
        capacity = MIN_PRACTICAL_KWP

    # Round to something an installer would actually quote.
    if capacity < 10:
        capacity = round(capacity * 4) / 4      # nearest 0.25 kW
    elif capacity < 100:
        capacity = round(capacity * 2) / 2      # nearest 0.5 kW
    else:
        capacity = float(round(capacity))

    area_required = capacity * per_kwp_area

    if from_demand and from_area and from_area < from_demand * 0.8:
        notes.append(
            f"Your space allows about {from_area:,.1f} kW but covering your consumption "
            f"would need around {from_demand:,.1f} kW, so this system will offset part of "
            f"your bill rather than all of it."
        )

    return SizingResult(
        capacity_kwp=capacity,
        binding_constraint=constraint,
        reason=reason,
        area_required_m2=area_required,
        area_available_m2=available_area_m2,
        capacity_from_demand_kwp=from_demand,
        capacity_from_area_kwp=from_area,
        capacity_from_budget_kwp=from_budget,
        notes=notes,
    )


# --------------------------------------------------------------------------------------
# Inverter
# --------------------------------------------------------------------------------------

# Arrays are normally oversized against the inverter, because the array only reaches its
# rated output in a narrow band of conditions. A ratio near 1.2 trades a little clipped
# midday peak for materially better output through the rest of the day.
DEFAULT_DC_AC_RATIO = 1.2

# Inverters are sold in steps, not to three decimal places.
_INVERTER_STEPS_KW = (
    1, 1.5, 2, 3, 3.68, 4, 5, 6, 8, 10, 12, 15, 17, 20, 25, 30, 36, 40, 50, 60, 75,
    80, 100, 110, 125, 150, 175, 200, 250, 300,
)


def recommend_inverter_kw(capacity_kwp: float, dc_ac_ratio: float = DEFAULT_DC_AC_RATIO) -> float:
    """Nearest inverter size at or above the target, so the ratio never drifts upward."""
    if capacity_kwp <= 0:
        raise ValueError("Capacity must be greater than zero to size an inverter.")
    target = capacity_kwp / max(dc_ac_ratio, 0.1)
    for step in _INVERTER_STEPS_KW:
        if step >= target:
            return float(step)
    # Beyond the tabulated range, round to the nearest 50 kW — multiple units by then.
    return float(round(target / 50.0) * 50.0)


def describe_inverter(capacity_kwp: float, ac_capacity_kw: float) -> dict[str, Any]:
    """Validate the array against the inverter, and say so plainly (§11).

    The governing rule: **warn, never reject.** A DC/AC ratio of 1.6 is unusual and worth
    flagging, but it is a real design somebody may have chosen deliberately — for a
    north-facing array, or a site with a hard export limit where clipping is the point.
    Refusing to model it would be substituting our judgement for an engineer's.

    Severity is separated from the explanation so the interface can style a caution
    differently from a note, without parsing prose.
    """
    ratio = capacity_kwp / ac_capacity_kw if ac_capacity_kw > 0 else 0.0

    if ratio <= 0:
        severity, verdict, plain = (
            "error",
            "No inverter capacity is available, so the ratio cannot be checked.",
            "We could not check the inverter against the panels.",
        )
    elif ratio < 0.9:
        severity = "caution"
        verdict = (
            f"At {ratio:.2f}, the inverter is materially larger than the array. Nothing is "
            f"clipped, but you are paying for capacity that will never be used."
        )
        plain = "Your inverter is bigger than it needs to be for this many panels."
    elif ratio < 1.0:
        severity = "note"
        verdict = (
            f"At {ratio:.2f}, the inverter slightly exceeds the array. Nothing is clipped."
        )
        plain = "The inverter comfortably handles these panels."
    elif ratio <= 1.35:
        severity = "ok"
        verdict = (
            f"A ratio of {ratio:.2f} is the normal design range. A little of the midday "
            f"peak is clipped on the clearest days, which is a deliberate trade."
        )
        plain = "The inverter is well matched to these panels."
    elif ratio <= 1.5:
        severity = "note"
        verdict = (
            f"A ratio of {ratio:.2f} is on the high side of normal. Expect to lose a "
            f"noticeable part of clear midday peaks to clipping."
        )
        plain = "You have slightly more panels than the inverter can pass at full sun."
    else:
        severity = "caution"
        verdict = (
            f"A ratio of {ratio:.2f} is unusual. A significant share of generation will be "
            f"clipped. This is a valid design in some cases — a hard export limit, or an "
            f"array facing away from the sun — so it is modelled as given rather than "
            f"refused, with the clipped share reported below."
        )
        plain = "You have many more panels than the inverter can pass; some output is lost."

    return {
        "ac_capacity_kw": round(ac_capacity_kw, 2),
        "dc_ac_ratio": round(ratio, 3),
        "severity": severity,
        "verdict": verdict,
        # The same finding without the vocabulary, for the beginner surface (§13).
        "plain": plain,
        "typical_range": [1.0, 1.35],
    }
