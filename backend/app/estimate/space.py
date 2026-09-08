"""Space: four different areas that are routinely confused for one.

The mistake §6 names — treating a roof as if panels could cover all of it — is the most
common way a solar estimate promises a system that will not physically fit. A 100 m² roof
does not hold 100 m² of panels. It holds panels on the part that is not a water tank, a
stairwell head, a parapet setback, an air-conditioning unit or a walkway, and those panels
need gaps between rows so they do not shade each other.

So four quantities are tracked separately and never collapsed:

1. **Available area** — what the user told us they have. The whole roof, the whole plot.
2. **Usable area** — the part an installer could actually build on, after obstructions,
   setbacks and access. Always a fraction of available, and the fraction depends on the
   mounting type.
3. **Module area** — the glass itself: panel area × number of panels. This is the smallest
   of the four and the one people mistake for the footprint.
4. **Installation footprint** — what the array occupies once rows are spaced and walkways
   are left. Larger than module area, and the number that must fit inside usable area.

Feasibility is footprint ≤ usable area. Any other comparison is optimistic.

Panel area itself is *derived*, not looked up. At standard test conditions the reference
irradiance is 1000 W/m², so a module's area is exactly its rated power divided by its
efficiency times 1000. Checked against four real datasheets (Waaree 550 W, Trina 545 W,
Jinko 580 W TOPCon, Adani 330 W poly), the relation reproduces the published dimensions to
within 1.1 %. A datasheet length and width override it when the user has them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.estimate import assumptions as A

SQFT_PER_SQM = 10.7639


# How much of a stated area is realistically buildable. These are planning figures, and
# every result that uses one says which was applied and what it means.
USABLE_FRACTIONS: dict[str, dict[str, Any]] = {
    "rooftop": {
        "fraction": 0.70,
        "note": (
            "Roofs are rarely empty. Water tanks, stairwell heads, parapet setbacks, "
            "air-conditioning units and a walkway to reach the array all take space."
        ),
    },
    "ground_mounted": {
        "fraction": 0.85,
        "note": "Boundary setbacks and an access track around the array.",
    },
    "farm_land": {
        "fraction": 0.85,
        "note": "Boundary margins and access for equipment between sections.",
    },
    "parking_structure": {
        "fraction": 0.90,
        "note": "A carport canopy is built to the structure, so little is wasted.",
    },
    "mixed": {
        "fraction": 0.75,
        "note": "A blend of rooftop and ground constraints.",
    },
    "not_sure": {
        "fraction": 0.75,
        "note": "A cautious middle figure until the mounting type is decided.",
    },
}


def usable_fraction(installation_type: str) -> float:
    entry = USABLE_FRACTIONS.get(installation_type) or USABLE_FRACTIONS["not_sure"]
    return float(entry["fraction"])


def usable_note(installation_type: str) -> str:
    entry = USABLE_FRACTIONS.get(installation_type) or USABLE_FRACTIONS["not_sure"]
    return str(entry["note"])


def spacing_multiplier(installation_type: str) -> float:
    """Footprint per unit of module area, once rows are spaced and walkways left."""
    factors = A.AREA_FACTORS.get(installation_type) or A.AREA_FACTORS[A.DEFAULT_INSTALLATION_TYPE]
    return float(factors["spacing_multiplier"])


# --------------------------------------------------------------------------------------
# Panel geometry
# --------------------------------------------------------------------------------------

def panel_area_m2(
    watts: int,
    panel_key: str = A.DEFAULT_PANEL_KEY,
    *,
    length_m: float | None = None,
    width_m: float | None = None,
) -> float:
    """Physical area of one module.

    Derived from rated power and efficiency unless real dimensions are supplied. The
    derivation is not an approximation: STC defines 1000 W/m², so a module rated at W watts
    with efficiency e occupies W / (e × 1000) square metres by definition.
    """
    if length_m and width_m:
        if length_m <= 0 or width_m <= 0:
            raise ValueError("Panel length and width must both be greater than zero.")
        return float(length_m * width_m)

    panel = A.PANEL_TECHNOLOGIES.get(panel_key) or A.PANEL_TECHNOLOGIES[A.DEFAULT_PANEL_KEY]
    if watts <= 0:
        raise ValueError("Panel wattage must be greater than zero.")
    return float(watts) / (panel.efficiency * 1000.0)


def module_area_m2(count: int, watts: int, panel_key: str = A.DEFAULT_PANEL_KEY, **kwargs: Any) -> float:
    """Total glass area: panel area × number of panels."""
    if count <= 0:
        raise ValueError("The number of panels must be at least 1.")
    return panel_area_m2(watts, panel_key, **kwargs) * count


# --------------------------------------------------------------------------------------
# Assessment
# --------------------------------------------------------------------------------------

@dataclass
class SpaceAssessment:
    """The four areas, and whether the array fits in the space described."""

    panel_area_m2: float
    module_area_m2: float
    footprint_m2: float
    available_area_m2: float | None
    usable_area_m2: float | None
    usable_fraction: float
    installation_type: str
    fits: bool | None                # None when no available area was given
    utilisation: float | None        # footprint as a share of usable area
    max_panels_in_space: int | None
    panel_dimensions_known: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "panel_area_m2": round(self.panel_area_m2, 3),
            "module_area_m2": round(self.module_area_m2, 1),
            "module_area_sqft": round(self.module_area_m2 * SQFT_PER_SQM, 0),
            "footprint_m2": round(self.footprint_m2, 1),
            "footprint_sqft": round(self.footprint_m2 * SQFT_PER_SQM, 0),
            "available_area_m2": (
                round(self.available_area_m2, 1) if self.available_area_m2 else None
            ),
            "usable_area_m2": round(self.usable_area_m2, 1) if self.usable_area_m2 else None,
            "usable_fraction": self.usable_fraction,
            "usable_pct": round(self.usable_fraction * 100),
            "spacing_multiplier": spacing_multiplier(self.installation_type),
            "installation_type": self.installation_type,
            "fits": self.fits,
            "utilisation": round(self.utilisation, 3) if self.utilisation is not None else None,
            "utilisation_pct": (
                round(self.utilisation * 100, 1) if self.utilisation is not None else None
            ),
            "max_panels_in_space": self.max_panels_in_space,
            "panel_dimensions_known": self.panel_dimensions_known,
            "usable_note": usable_note(self.installation_type),
            "notes": self.notes,
        }


def assess(
    *,
    count: int,
    watts: int,
    installation_type: str,
    panel_key: str = A.DEFAULT_PANEL_KEY,
    available_area_m2: float | None = None,
    panel_length_m: float | None = None,
    panel_width_m: float | None = None,
) -> SpaceAssessment:
    """Work out what the array occupies, and whether it fits."""
    dimensions_known = bool(panel_length_m and panel_width_m)
    single = panel_area_m2(
        watts, panel_key, length_m=panel_length_m, width_m=panel_width_m
    )
    modules = single * count
    spacing = spacing_multiplier(installation_type)
    footprint = modules * spacing

    fraction = usable_fraction(installation_type)
    usable = available_area_m2 * fraction if available_area_m2 else None

    notes: list[str] = []
    fits: bool | None = None
    utilisation: float | None = None
    max_panels: int | None = None

    if usable is not None and usable > 0:
        fits = footprint <= usable
        utilisation = footprint / usable
        max_panels = max(0, int(usable / (single * spacing)))

        if fits:
            notes.append(
                f"{count} panels occupy about {footprint:,.0f} m² once rows are spaced, "
                f"inside the {usable:,.0f} m² we estimate is actually buildable."
            )
            if utilisation < 0.5:
                notes.append(
                    f"There is room for roughly {max_panels} panels in that space, so the "
                    f"array could be larger if you wanted it to be."
                )
        elif max_panels == 0:
            # "Around 0 panels would fit" is true and useless. Say what is actually wrong.
            notes.append(
                f"{count} panels need about {footprint:,.0f} m² of buildable space, and we "
                f"estimate you have {usable:,.0f} m² — not enough for even one panel. "
                f"Check the area you entered, or the unit it was in."
            )
        else:
            shortfall = footprint - usable
            notes.append(
                f"{count} panels need about {footprint:,.0f} m² of buildable space, which "
                f"is {shortfall:,.0f} m² more than we estimate you have. Around "
                f"{max_panels} panel{'s' if max_panels != 1 else ''} would fit."
            )

        notes.append(
            f"Of the {available_area_m2:,.0f} m² you told us about, we treat "
            f"{fraction:.0%} — {usable:,.0f} m² — as buildable. {usable_note(installation_type)}"
        )
    else:
        notes.append(
            f"{count} panels occupy about {footprint:,.0f} m² once rows are spaced "
            f"({modules:,.0f} m² of panel, plus access and row gaps). Tell us how much "
            f"space you have and we will check it fits."
        )

    if not dimensions_known:
        notes.append(
            f"Panel size was worked out from its {watts} W rating and its efficiency, "
            f"which gives {single:.2f} m² per panel. Entering the real dimensions from a "
            f"datasheet would replace that."
        )

    return SpaceAssessment(
        panel_area_m2=single,
        module_area_m2=modules,
        footprint_m2=footprint,
        available_area_m2=available_area_m2,
        usable_area_m2=usable,
        usable_fraction=fraction,
        installation_type=installation_type,
        fits=fits,
        utilisation=utilisation,
        max_panels_in_space=max_panels,
        panel_dimensions_known=dimensions_known,
        notes=notes,
    )


def capacity_from_available_area(
    available_area_m2: float,
    installation_type: str,
    panel_key: str = A.DEFAULT_PANEL_KEY,
) -> float:
    """Largest system a stated area can hold, in kWp.

    Applies the usable fraction *and* row spacing. The earlier version of this calculation
    applied spacing only, which quietly assumed every square metre of a roof was buildable
    and so recommended systems that would not fit (§6).
    """
    if available_area_m2 <= 0:
        raise ValueError("Available area must be greater than zero.")
    panel = A.PANEL_TECHNOLOGIES.get(panel_key) or A.PANEL_TECHNOLOGIES[A.DEFAULT_PANEL_KEY]

    usable = available_area_m2 * usable_fraction(installation_type)
    # Area occupied per kWp: 1 kWp is 1000 W, which at this efficiency is 1/efficiency m²
    # of glass, times the spacing allowance.
    area_per_kwp = (1.0 / panel.efficiency) * spacing_multiplier(installation_type)
    return usable / area_per_kwp


def area_for_capacity(
    capacity_kwp: float,
    installation_type: str,
    panel_key: str = A.DEFAULT_PANEL_KEY,
) -> float:
    """Buildable area a system of this size occupies, in m² (footprint, not glass)."""
    panel = A.PANEL_TECHNOLOGIES.get(panel_key) or A.PANEL_TECHNOLOGIES[A.DEFAULT_PANEL_KEY]
    return capacity_kwp * (1.0 / panel.efficiency) * spacing_multiplier(installation_type)


def available_area_for_capacity(
    capacity_kwp: float,
    installation_type: str,
    panel_key: str = A.DEFAULT_PANEL_KEY,
) -> float:
    """How much *stated* area a system needs, grossing the footprint back up.

    This is the figure to quote at somebody asking "how big a roof do I need?", because
    they will measure the whole roof, not the buildable part of it.
    """
    return area_for_capacity(capacity_kwp, installation_type, panel_key) / usable_fraction(
        installation_type
    )
