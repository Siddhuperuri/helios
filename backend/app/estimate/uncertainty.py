"""How much to trust the number, and why (§19).

Mandatory, and treated as such: no figure leaves this platform without a range around it
and a confidence rating attached.

The range is built from components that are each named and each defensible:

- **Weather variability** is *measured*, not assumed — the spread between what the years in
  the record actually delivered at these coordinates. This is normally the largest term,
  and it is the one no amount of better modelling can remove: next year's weather is not
  knowable.
- **Resource data uncertainty** covers the gap between a reanalysis grid cell and a
  pyranometer on the user's roof.
- **Conversion-model uncertainty** covers the physical chain itself.
- **Assumption uncertainty** grows with every question the user could not answer. This is
  what makes "I don't know" honest rather than free: the estimate still runs, and the band
  around it widens to say so.

Components combine in quadrature, which assumes they are independent. They are not
perfectly independent, so the combined figure is a slight understatement — stated here
rather than glossed over.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

Confidence = Literal["high", "medium", "low"]

# z for a central 80 % interval under a normal approximation. 80 % rather than 95 % because
# a 95 % band on a solar estimate is so wide it stops being decision-useful, and because
# the platform's conformal intervals elsewhere are calibrated at 80 % — one nominal level
# across the product, so two numbers on two screens mean the same thing.
Z_80 = 1.2816
NOMINAL_COVERAGE = 0.80

# Standing uncertainty in the reanalysis resource itself: a grid-cell average against a
# point measurement. Order of magnitude, stated as such, not a validated figure for this
# location — the platform has no ground measurement to validate against.
RESOURCE_UNCERTAINTY = 0.05

# The published conversion chain (Erbs, HDKR, Faiman, PVWatts) applied to correct inputs.
MODEL_UNCERTAINTY = 0.05


@dataclass
class UncertaintyFactor:
    key: str
    label: str
    explanation: str
    relative: float
    kind: Literal["irreducible", "data", "model", "assumption"]
    reducible_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "explanation": self.explanation,
            "relative_pct": round(self.relative * 100, 1),
            "kind": self.kind,
            "reducible_by": self.reducible_by,
        }


@dataclass
class UncertaintyResult:
    expected: float
    lower: float
    upper: float
    relative: float
    confidence: Confidence
    confidence_reason: str
    coverage: float
    factors: list[UncertaintyFactor] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    # Everything except year-to-year weather, combined. Kept separate because weather
    # variability is the one term that differs month by month — a monsoon July is far less
    # predictable than a dry January — and applying one annual figure to all twelve draws
    # error bars that are wrong in both directions.
    non_weather_relative: float = 0.0

    def band_for(self, value: float, weather_relative: float) -> tuple[float, float]:
        """Lower and upper bound for a sub-annual figure with its own weather variability."""
        combined = math.sqrt(weather_relative**2 + self.non_weather_relative**2)
        margin = Z_80 * combined * value
        return max(0.0, value - margin), value + margin

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": round(self.expected, 0),
            "lower": round(self.lower, 0),
            "upper": round(self.upper, 0),
            "relative_pct": round(self.relative * 100, 1),
            "confidence": self.confidence,
            "confidence_reason": self.confidence_reason,
            "coverage": self.coverage,
            "coverage_label": f"{int(self.coverage * 100)}% likely range",
            "factors": [f.to_dict() for f in self.factors],
            "improvements": self.improvements,
        }


def assess(
    *,
    expected_annual_kwh: float,
    measured_annual_std_kwh: float,
    variability_basis: str,
    complete_calendar_years: int,
    data_completeness: float,
    shading_known: bool,
    orientation_known: bool,
    system_specified: bool,
    demand_confidence: str | None,
    used_ml: bool = False,
) -> UncertaintyResult:
    """Assemble the range and the confidence rating for an annual generation figure."""
    factors: list[UncertaintyFactor] = []
    improvements: list[str] = []

    # ------------------------------------------------------- measured weather variability
    weather_rel = (
        measured_annual_std_kwh / expected_annual_kwh if expected_annual_kwh > 0 else 0.10
    )
    factors.append(
        UncertaintyFactor(
            key="weather_variability",
            label="Year-to-year weather",
            explanation=(
                "No two years are the same. A cloudier-than-usual monsoon or a clear winter "
                "moves the total, and next year's weather cannot be known in advance. "
                + variability_basis
            ),
            relative=weather_rel,
            kind="irreducible",
            reducible_by=None,
        )
    )

    # ------------------------------------------------------------------ resource and model
    factors.append(
        UncertaintyFactor(
            key="resource_data",
            label="Solar resource data",
            explanation=(
                "The irradiance behind this estimate comes from a reanalysis grid cell "
                "covering an area around you, not from a sensor at your address. Local "
                "haze, dust or coastal cloud can differ from the cell average."
            ),
            relative=RESOURCE_UNCERTAINTY,
            kind="data",
            reducible_by="A ground measurement or a nearby monitored installation.",
        )
    )
    factors.append(
        UncertaintyFactor(
            key="conversion_model",
            label="Panel and inverter modelling",
            explanation=(
                "Converting sunlight into delivered electricity uses published engineering "
                "models. They are well tested, but no model reproduces real hardware exactly."
            ),
            relative=MODEL_UNCERTAINTY,
            kind="model",
            reducible_by="Measured output from the installed system.",
        )
    )

    # ------------------------------------------------------------------- assumption terms
    if not shading_known:
        factors.append(
            UncertaintyFactor(
                key="shading",
                label="Shading",
                explanation=(
                    "We do not know what stands near your array. A tree, a water tank or a "
                    "neighbouring wall can take a surprising bite out of output, because "
                    "shading part of a panel affects more than that part."
                ),
                relative=0.06,
                kind="assumption",
                reducible_by="Telling us what shades the area, and when.",
            )
        )
        improvements.append("Tell us about anything that shades the roof or land.")

    if not orientation_known:
        factors.append(
            UncertaintyFactor(
                key="orientation",
                label="Panel angle and direction",
                explanation=(
                    "We used the best angle and direction for your location rather than a "
                    "measured one. A real roof may not face that way, which usually costs a "
                    "few percent."
                ),
                relative=0.04,
                kind="assumption",
                reducible_by="Telling us which way the roof faces and how steep it is.",
            )
        )
        improvements.append("Tell us which way your roof faces and roughly how steep it is.")

    if not system_specified:
        factors.append(
            UncertaintyFactor(
                key="equipment",
                label="Equipment specification",
                explanation=(
                    "Panel and inverter models were assumed from typical current equipment. "
                    "Real hardware varies in efficiency and in how well it holds up in heat."
                ),
                relative=0.03,
                kind="assumption",
                reducible_by="Entering the actual panel and inverter you plan to install.",
            )
        )
        improvements.append("Enter the actual panel and inverter once you have a quote.")

    if complete_calendar_years < 3:
        factors.append(
            UncertaintyFactor(
                key="short_record",
                label="Length of weather record",
                explanation=(
                    f"Only {complete_calendar_years} complete year(s) of weather were "
                    f"available, so the year-to-year spread is less well established than "
                    f"it would be over a longer record."
                ),
                relative=0.04,
                kind="data",
                reducible_by="A longer historical record for this location.",
            )
        )

    if data_completeness < 0.95:
        factors.append(
            UncertaintyFactor(
                key="data_gaps",
                label="Gaps in the weather record",
                explanation=(
                    f"About {(1 - data_completeness):.0%} of the hourly record was missing "
                    f"and was left out rather than filled in with invented values."
                ),
                relative=min(0.10, (1.0 - data_completeness) * 0.5),
                kind="data",
                reducible_by=None,
            )
        )

    # ------------------------------------------------------------------------- combine
    combined = math.sqrt(sum(f.relative ** 2 for f in factors))
    non_weather = math.sqrt(
        sum(f.relative ** 2 for f in factors if f.key != "weather_variability")
    )

    if used_ml:
        # The ML path sharpens the forward-looking forecast; it does not narrow the
        # year-to-year weather spread, which dominates an annual figure. Claiming
        # otherwise would be exactly the overselling §18 warns against.
        improvements.append(
            "The detailed analysis improves short-term forecasts, but the yearly range is "
            "set mostly by weather that has not happened yet."
        )

    expected = max(0.0, expected_annual_kwh)
    margin = Z_80 * combined * expected
    lower = max(0.0, expected - margin)
    upper = expected + margin

    # ---------------------------------------------------------------------- confidence
    if combined < 0.09:
        confidence: Confidence = "high"
        reason = (
            "Built on a good weather record for your exact location, with most of the "
            "important details supplied."
        )
    elif combined < 0.15:
        confidence = "medium"
        reason = (
            "A sound estimate, but some details were assumed rather than measured. Filling "
            "those in would tighten the range."
        )
    else:
        confidence = "low"
        reason = (
            "Treat this as a rough indication. Several important inputs were assumed, and "
            "the range around the figure is wide as a result."
        )

    # Hard downgrades: a percentage cannot rescue a thin record.
    if data_completeness < 0.75 or complete_calendar_years < 1:
        confidence = "low"
        reason = (
            "The weather record for this location is incomplete, so this figure is a rough "
            "indication only."
        )
    elif demand_confidence == "low" and confidence == "high":
        confidence = "medium"
        reason = (
            "The generation figure is solid, but your consumption was estimated roughly, so "
            "the savings and offset figures are less certain than the generation one."
        )

    return UncertaintyResult(
        expected=expected,
        lower=lower,
        upper=upper,
        relative=combined,
        confidence=confidence,
        confidence_reason=reason,
        coverage=NOMINAL_COVERAGE,
        factors=factors,
        improvements=improvements,
        non_weather_relative=non_weather,
    )
