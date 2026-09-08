"""Every default this platform uses, in one place, with its provenance attached.

The reason this module exists rather than the values living inline: a consumer result is
only trustworthy if the reader can see what was assumed to produce it. §28 requires an
assumptions panel and §29 requires data-source transparency, and both are rendered from
the ledger this module builds — not from a list retyped in the frontend that silently
drifts out of step with the maths.

A second reason matters more for correctness. §19 requires a confidence rating, and
confidence depends heavily on *how much of the input the user actually supplied* versus
how much was defaulted. That is only measurable if defaulting is recorded as it happens,
which is what :class:`AssumptionLedger` does.

Honesty rules applied throughout:

- A value taken from a published model names that model.
- A value that is a market-typical planning figure says so and is editable. It is never
  presented as a quotation, a tariff schedule, or a measurement.
- No citation is invented. Where a figure is a broad regional average, it is labelled a
  regional average and nothing stronger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# --------------------------------------------------------------------------------------
# Provenance vocabulary
# --------------------------------------------------------------------------------------

Provenance = Literal[
    "measured",           # observed data retrieved from an upstream source
    "published_model",    # a named, peer-reviewed or standard engineering model
    "market_typical",     # representative planning figure; editable, not a quotation
    "regional_default",   # broad regional average; editable
    "user_supplied",      # the user stated it
    "derived",            # computed from other assumptions or from user input
]

PROVENANCE_LABELS: dict[str, str] = {
    "measured": "Measured data",
    "published_model": "Published model",
    "market_typical": "Typical market value",
    "regional_default": "Regional default",
    "user_supplied": "You told us",
    "derived": "Calculated",
}


@dataclass(frozen=True)
class Assumption:
    """One declared assumption behind a result."""

    key: str
    label: str
    value: Any
    unit: str | None = None
    provenance: Provenance = "market_typical"
    source: str | None = None
    rationale: str | None = None
    editable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "provenance": self.provenance,
            "provenance_label": PROVENANCE_LABELS.get(self.provenance, self.provenance),
            "source": self.source,
            "rationale": self.rationale,
            "editable": self.editable,
        }


class AssumptionLedger:
    """Accumulates the assumptions used during one estimate.

    Ordering is insertion order, which is the order the calculation actually consumed
    them, so the rendered panel reads as the pipeline ran rather than alphabetically.
    """

    def __init__(self) -> None:
        self._items: dict[str, Assumption] = {}

    def record(self, assumption: Assumption) -> Assumption:
        self._items[assumption.key] = assumption
        return assumption

    def add(
        self,
        key: str,
        label: str,
        value: Any,
        *,
        unit: str | None = None,
        provenance: Provenance = "market_typical",
        source: str | None = None,
        rationale: str | None = None,
        editable: bool = True,
    ) -> Any:
        """Record an assumption and return its value, so call sites read naturally."""
        self.record(
            Assumption(
                key=key,
                label=label,
                value=value,
                unit=unit,
                provenance=provenance,
                source=source,
                rationale=rationale,
                editable=editable,
            )
        )
        return value

    def user_value(
        self,
        key: str,
        label: str,
        value: Any,
        *,
        unit: str | None = None,
        rationale: str | None = None,
    ) -> Any:
        """Record something the user stated. Recorded distinctly because it raises confidence."""
        return self.add(
            key,
            label,
            value,
            unit=unit,
            provenance="user_supplied",
            source="Provided by you",
            rationale=rationale,
        )

    def get(self, key: str) -> Assumption | None:
        return self._items.get(key)

    @property
    def defaulted_keys(self) -> list[str]:
        """Keys the user did not supply. Feeds the confidence rating (§19)."""
        return [k for k, a in self._items.items() if a.provenance != "user_supplied"]

    @property
    def user_supplied_keys(self) -> list[str]:
        return [k for k, a in self._items.items() if a.provenance == "user_supplied"]

    def to_list(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self._items.values()]

    def __len__(self) -> int:
        return len(self._items)


# --------------------------------------------------------------------------------------
# Module technology
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PanelTechnology:
    """A module technology option offered in the detailed workflow (§15)."""

    key: str
    display_name: str
    plain_name: str
    efficiency: float                     # STC module efficiency, fraction
    temperature_coefficient_per_c: float  # /degC, negative
    degradation_rate_per_year: float      # fraction/year
    bifacial: bool                        # collects on the rear face too
    note: str

    @property
    def area_per_kwp_m2(self) -> float:
        """Module glass area per kWp, derived rather than tabulated.

        At standard test conditions the reference irradiance is 1000 W/m², so a kilowatt of
        modules at efficiency e occupies 1/e square metres. Deriving it keeps efficiency and
        area from ever disagreeing — which they will, if both are typed by hand.
        """
        return 1.0 / self.efficiency


PANEL_TECHNOLOGIES: dict[str, PanelTechnology] = {
    "mono_perc": PanelTechnology(
        key="mono_perc",
        display_name="Monocrystalline PERC",
        plain_name="Modern high-efficiency panel",
        efficiency=0.205,
        temperature_coefficient_per_c=-0.0035,
        degradation_rate_per_year=0.005,
        bifacial=False,
        note="The mainstream rooftop module today. Good efficiency, widely available.",
    ),
    "mono_topcon": PanelTechnology(
        key="mono_topcon",
        display_name="Monocrystalline TOPCon",
        plain_name="Latest-generation high-efficiency panel",
        efficiency=0.225,
        temperature_coefficient_per_c=-0.0029,
        degradation_rate_per_year=0.004,
        bifacial=False,
        note="Higher efficiency and a gentler heat penalty than PERC. Costs more per panel.",
    ),
    "polycrystalline": PanelTechnology(
        key="polycrystalline",
        display_name="Polycrystalline silicon",
        plain_name="Older, lower-cost panel",
        efficiency=0.170,
        temperature_coefficient_per_c=-0.0040,
        degradation_rate_per_year=0.006,
        bifacial=False,
        note="Cheaper per panel but needs more roof area for the same output.",
    ),
    "thin_film_cdte": PanelTechnology(
        key="thin_film_cdte",
        display_name="Thin film (CdTe)",
        plain_name="Thin-film panel",
        efficiency=0.185,
        temperature_coefficient_per_c=-0.0028,
        degradation_rate_per_year=0.005,
        bifacial=False,
        note="Holds up better in high heat; less common on small rooftops.",
    ),
    "bifacial_mono": PanelTechnology(
        key="bifacial_mono",
        display_name="Bifacial monocrystalline",
        plain_name="Double-sided panel",
        efficiency=0.215,
        temperature_coefficient_per_c=-0.0030,
        degradation_rate_per_year=0.004,
        bifacial=True,
        note=(
            "Collects light on the rear face too. The gain depends on the ground surface "
            "and mounting height, so it is not credited here unless ground-mounted."
        ),
    ),
}

DEFAULT_PANEL_KEY = "mono_perc"


# Rated power of a single module, in watts.
#
# These are real market standards, not a fabricated product database. A panel's *model*
# cannot be resolved to a wattage here, because this platform holds no manufacturer
# catalogue and inventing one would put made-up specifications behind a user's energy
# figure. Where a model is given it is recorded verbatim for traceability and the user is
# asked to confirm the wattage, which is printed on the panel's own label.
PANEL_WATTAGE_OPTIONS: tuple[dict[str, Any], ...] = (
    {"watts": 330, "label": "330 W", "note": "Older residential panel, still widely installed."},
    {"watts": 400, "label": "400 W", "note": "Common on rooftops installed a few years ago."},
    {"watts": 450, "label": "450 W", "note": "A typical mid-range panel."},
    {"watts": 540, "label": "540 W", "note": "Large-format panel, common on commercial roofs."},
    {"watts": 550, "label": "550 W", "note": "The mainstream size for new installations."},
    {"watts": 600, "label": "600 W", "note": "Large-format, usually ground-mounted or commercial."},
)

# What a new installation would most likely use, per technology. Used only when the user
# does not know their panel wattage, and always recorded as an assumption when it is.
TYPICAL_PANEL_WATTS: dict[str, int] = {
    "mono_perc": 550,
    "mono_topcon": 580,
    "polycrystalline": 330,
    "thin_film_cdte": 460,
    "bifacial_mono": 570,
}

DEFAULT_PANEL_WATTS = 550

# Physically possible bounds for a single module. Outside these the user has almost
# certainly entered system capacity rather than panel rating.
MIN_PANEL_WATTS = 50
MAX_PANEL_WATTS = 1000


#: Electrical characteristics an expert reads off a datasheet (§14).
#:
#: These are **accepted, never invented**. Open-circuit voltage and short-circuit current
#: depend on cell count and cell chemistry, which this platform does not hold for any
#: specific product — deriving them from wattage alone would be fabrication. They are
#: recorded when supplied and displayed with their source, and the energy model is driven
#: by the quantities that genuinely determine output: rated power, efficiency and the
#: temperature coefficient.
DATASHEET_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "voc", "label": "Open-circuit voltage (Voc)", "unit": "V",
     "note": "Sets the maximum string length against the inverter's DC voltage window."},
    {"key": "isc", "label": "Short-circuit current (Isc)", "unit": "A",
     "note": "Sets the current limit per string."},
    {"key": "vmp", "label": "Voltage at max power (Vmp)", "unit": "V",
     "note": "Operating voltage at the maximum power point."},
    {"key": "imp", "label": "Current at max power (Imp)", "unit": "A",
     "note": "Operating current at the maximum power point."},
)


def typical_panel_watts(panel_key: str | None) -> int:
    """Rated power to assume when the user does not know theirs."""
    return TYPICAL_PANEL_WATTS.get(panel_key or DEFAULT_PANEL_KEY, DEFAULT_PANEL_WATTS)


# --------------------------------------------------------------------------------------
# Loss stack
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LossItem:
    key: str
    label: str
    fraction: float
    plain_explanation: str


# PVWatts v5 (Dobos 2014, NREL/TP-6A20-62641) default loss stack.
#
# Temperature and inverter conversion are deliberately ABSENT from this list. Both are
# modelled explicitly by the physical chain — Faiman cell temperature feeding the PVWatts
# DC model, then inverter efficiency and clipping — so including them here would apply
# each penalty twice. This is the single easiest way to build a solar calculator that
# quietly understates output by 15 %, and it is why the stack is itemised rather than
# carried as one opaque number.
DEFAULT_LOSS_STACK: tuple[LossItem, ...] = (
    LossItem("soiling", "Dust and dirt", 0.02,
             "Dust settling on the glass. Worse in dry, dusty seasons; rain washes it off."),
    LossItem("shading", "Shading", 0.03,
             "Trees, poles, parapets or nearby buildings blocking part of the array."),
    LossItem("mismatch", "Panel mismatch", 0.02,
             "No two panels are identical; the string performs slightly below the best panel."),
    LossItem("wiring", "Wiring resistance", 0.02,
             "Energy lost as heat in the DC and AC cabling."),
    LossItem("connections", "Connections", 0.005,
             "Small losses at every plug and terminal."),
    LossItem("light_induced_degradation", "First-year settling", 0.015,
             "Silicon loses a little output in its first weeks of sunlight, then stabilises."),
    LossItem("nameplate", "Nameplate tolerance", 0.01,
             "Panels are sold with a tolerance; the real rating can sit slightly under the label."),
    LossItem("availability", "Downtime", 0.03,
             "Days the system is off for maintenance, a grid outage or a fault."),
)


# Shading described the way a person can actually answer it (§12: every technical question
# needs a route for someone who does not know the number). The fractions are deliberately
# coarse, because the honest resolution of "a tree shades part of it in the afternoon" is
# coarse. A shading analysis proper needs a horizon survey, which this platform does not do
# and does not pretend to.
SHADING_LEVELS: dict[str, dict[str, Any]] = {
    "none": {
        "label": "Nothing shades it",
        "description": "Open sky all day — no trees, walls, tanks or towers nearby.",
        "fraction": 0.005,
    },
    "light": {
        "label": "A little shade",
        "description": "Something clips the edge early or late in the day.",
        "fraction": 0.03,
    },
    "moderate": {
        "label": "Some shade",
        "description": "A tree, tank or nearby building shades part of the area for a few hours.",
        "fraction": 0.08,
    },
    "heavy": {
        "label": "A lot of shade",
        "description": "Much of the area is shaded for a good part of the day.",
        "fraction": 0.18,
    },
    "unknown": {
        "label": "I'm not sure",
        "description": "We will assume a typical amount of shading and widen the range to match.",
        "fraction": 0.03,
    },
}


def shading_fraction(level: str | None) -> float:
    entry = SHADING_LEVELS.get(level or "unknown") or SHADING_LEVELS["unknown"]
    return float(entry["fraction"])


def combine_losses(items: tuple[LossItem, ...] | list[LossItem]) -> float:
    """Combine fractional losses multiplicatively.

    Adding them is wrong and always overstates the penalty: two independent 10 % losses
    leave 81 % of the input, not 80 %. With the default stack the difference is under a
    percentage point, which is exactly why it gets done wrong and never noticed.
    """
    remaining = 1.0
    for item in items:
        remaining *= 1.0 - float(item.fraction)
    return 1.0 - remaining


DEFAULT_SYSTEM_LOSS_FRACTION = combine_losses(DEFAULT_LOSS_STACK)  # ~0.1365


# --------------------------------------------------------------------------------------
# Space
# --------------------------------------------------------------------------------------

# Area required per kWp, including the spacing a real installation needs. Module area
# alone (PanelTechnology.area_per_kwp_m2) is not enough: rooftop arrays need walkways and
# setbacks, and ground mounts need row spacing so one row does not shade the next.
AREA_FACTORS: dict[str, dict[str, Any]] = {
    "rooftop": {
        "label": "Rooftop",
        "spacing_multiplier": 1.35,
        "note": "Includes walkways, edge setbacks and mounting clearance.",
    },
    "ground_mounted": {
        "label": "Ground-mounted",
        "spacing_multiplier": 2.6,
        "note": "Rows must be spaced so they do not shade each other through the winter.",
    },
    "farm_land": {
        "label": "Farm land",
        "spacing_multiplier": 2.6,
        "note": "Row spacing as for ground mounting; crops or grazing may continue between rows.",
    },
    "parking_structure": {
        "label": "Parking structure",
        "spacing_multiplier": 1.15,
        "note": "Carport canopies pack tightly because the structure sets the geometry.",
    },
    "mixed": {
        "label": "Mixed",
        "spacing_multiplier": 1.8,
        "note": "A blend of rooftop and ground mounting; spacing sits between the two.",
    },
    "not_sure": {
        "label": "Not sure yet",
        "spacing_multiplier": 1.6,
        "note": (
            "A cautious middle figure, since the mounting type is not yet decided. "
            "Tell us the mounting type later for a tighter number."
        ),
    },
}

DEFAULT_INSTALLATION_TYPE = "not_sure"


# --------------------------------------------------------------------------------------
# System economics
# --------------------------------------------------------------------------------------

# Installed cost per kWp, before subsidy, as a planning range. These are market-typical
# figures that fall with system size because fixed costs — design, travel, commissioning,
# grid paperwork — are spread over more capacity.
#
# They are NOT quotations and NOT sourced from any specific vendor or scheme. They exist
# so a first estimate is not blank, and they are editable. §20 forbids fabricating
# financial data; presenting an editable planning default, labelled as such, with the
# resulting figures moving when the user corrects it, is the honest form of this.
# Keyed by currency, because a figure quoted in the wrong currency is not an
# approximation — it is off by a factor of eighty.
COST_TIERS_PER_KWP: dict[str, tuple[tuple[float, float], ...]] = {
    # (upper bound of system size in kWp, indicative installed cost per kWp)
    "INR": (
        (3.0, 62_000.0),
        (10.0, 55_000.0),
        (50.0, 48_000.0),
        (250.0, 42_000.0),
        (float("inf"), 38_000.0),
    ),
    "USD": (
        (3.0, 2_600.0),
        (10.0, 2_300.0),
        (50.0, 1_800.0),
        (250.0, 1_400.0),
        (float("inf"), 1_100.0),
    ),
}

BATTERY_COST_PER_KWH: dict[str, float] = {
    "INR": 22_000.0,
    "USD": 350.0,
}

# Conversion rates live in app.estimate.tariffs, which owns the currency domain. Keeping a
# second copy here is how the cost of a system and the price of a unit end up quoted on
# different exchange rates.

DEFAULT_SYSTEM_LIFETIME_YEARS = 25
DEFAULT_DEGRADATION_RATE_PER_YEAR = 0.005
DEFAULT_ANNUAL_OM_FRACTION_OF_CAPEX = 0.01
DEFAULT_TARIFF_ESCALATION_PER_YEAR = 0.03


def _currency_scale(currency_code: str) -> float:
    """Multiplier converting a USD figure into ``currency_code``."""
    from app.estimate.tariffs import units_per_usd

    return units_per_usd(currency_code or "USD") or 1.0


def indicative_cost_per_kwp(capacity_kwp: float, currency_code: str = "INR") -> float:
    """Installed cost per kWp for a system of this size, before subsidy."""
    code = (currency_code or "INR").upper()
    tiers = COST_TIERS_PER_KWP.get(code)
    scale = 1.0
    if tiers is None:
        tiers = COST_TIERS_PER_KWP["USD"]
        scale = _currency_scale(code)
    for upper, rate in tiers:
        if capacity_kwp <= upper:
            return rate * scale
    return tiers[-1][1] * scale


def battery_cost_per_kwh(currency_code: str = "INR") -> float:
    """Installed storage cost per usable kWh of nameplate capacity."""
    code = (currency_code or "INR").upper()
    direct = BATTERY_COST_PER_KWH.get(code)
    if direct is not None:
        return direct
    return BATTERY_COST_PER_KWH["USD"] * _currency_scale(code)


# --------------------------------------------------------------------------------------
# Emissions
# --------------------------------------------------------------------------------------

# Grid emission factors, kg CO2 per kWh displaced. Broad national averages for planning
# only: the true figure varies by regional grid, by time of day, and year to year as the
# generation mix changes. Editable, and labelled a regional average rather than a
# measurement.
GRID_EMISSION_FACTORS_KG_PER_KWH: dict[str, float] = {
    "IN": 0.71,
    "US": 0.37,
    "GB": 0.21,
    "AU": 0.63,
    "DE": 0.35,
    "ZA": 0.90,
    "BR": 0.10,
    "default": 0.45,
}


def grid_emission_factor(country_code: str | None) -> float:
    if not country_code:
        return GRID_EMISSION_FACTORS_KG_PER_KWH["default"]
    return GRID_EMISSION_FACTORS_KG_PER_KWH.get(
        country_code.upper(), GRID_EMISSION_FACTORS_KG_PER_KWH["default"]
    )


# --------------------------------------------------------------------------------------
# Data-source declarations (§29)
# --------------------------------------------------------------------------------------

def data_sources(*, used_forecast: bool = False, used_ml: bool = False) -> list[dict[str, str]]:
    """Declare where the data behind a result actually came from.

    Only sources genuinely integrated into this platform appear here. Nothing is listed
    that was not used to produce the result being described.
    """
    sources: list[dict[str, str]] = [
        {
            "category": "Solar resource and weather",
            "name": "Open-Meteo Historical Weather API (ERA5 / ERA5-Land reanalysis)",
            "detail": (
                "Hourly global horizontal, direct normal and diffuse irradiance, air "
                "temperature, humidity, wind, cloud cover and precipitation."
            ),
            "licence": "Open-Meteo data CC-BY 4.0; ERA5 © ECMWF / Copernicus Climate Change Service.",
            "caveat": (
                "Reanalysis is a modelled gridded product, not a ground pyranometer "
                "measurement at your exact address."
            ),
        },
        {
            "category": "Geographic data",
            "name": "Open-Meteo Geocoding API",
            "detail": "Place name, coordinates, elevation and timezone.",
            "licence": "Data derived from GeoNames, CC-BY 4.0.",
            "caveat": "A place name resolves to a settlement centroid, not your rooftop.",
        },
        {
            "category": "Photovoltaic conversion",
            "name": "Published engineering models",
            "detail": (
                "Erbs decomposition, HDKR transposition, Faiman cell temperature and the "
                "PVWatts v5 DC model (Dobos 2014, NREL/TP-6A20-62641)."
            ),
            "licence": "Published literature.",
            "caveat": (
                "Modelled output. This platform has no metered generation data and does "
                "not claim validation against measured production."
            ),
        },
        {
            "category": "Electricity and cost assumptions",
            "name": "Editable planning defaults",
            "detail": (
                "Tariff, installed cost, grid emission factor and system lifetime are "
                "representative planning values, not quotations or utility schedules."
            ),
            "licence": "Not applicable.",
            "caveat": "Replace them with your own bill and quotes for a figure you can rely on.",
        },
    ]

    if used_forecast:
        sources.insert(
            1,
            {
                "category": "Weather forecast",
                "name": "Open-Meteo Forecast API",
                "detail": "Operational numerical weather prediction, hourly, up to 16 days.",
                "licence": "Open-Meteo data CC-BY 4.0.",
                "caveat": "Forecast skill falls with horizon; beyond 7 days it is unvalidated here.",
            },
        )

    if used_ml:
        sources.append(
            {
                "category": "Machine-learning correction",
                "name": "Model trained on this location's own history",
                "detail": (
                    "Trained on the earlier portion of the retrieved record and tested on "
                    "the most recent portion, never on shuffled hours."
                ),
                "licence": "Not applicable.",
                "caveat": (
                    "Trained per location. Accuracy measured at this location does not "
                    "transfer to another one."
                ),
            }
        )

    return sources


ATTRIBUTION_NOTE = (
    "Weather and irradiance data from Open-Meteo (CC-BY 4.0), derived from ECMWF ERA5 / "
    "ERA5-Land reanalysis (Copernicus Climate Change Service)."
)
