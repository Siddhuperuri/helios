"""The scientific parameter dictionary.

One authoritative definition per physical quantity: name, symbol, unit, plausible range,
provenance, and role in the pipeline. The API serves this table to the frontend, so the
labels a user reads are the same objects the validator enforces and the model card cites.
There is exactly one place to change a unit or a bound.

Ranges are *physical plausibility* bounds, not statistical ones. Values outside them are
flagged as suspect because they are physically improbable at Earth's surface, never
because they are statistically unusual. That distinction is deliberate: Rosales Huamani
et al. [P4] removed 10.16 % of solar-radiation observations by an IQR rule with an upper
bound of 331 W/m², which discards physically valid clear-sky midday values. This platform
does not do that (see docs/RESEARCH_SYNTHESIS.md, W2).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ParameterRole(str, Enum):
    TARGET = "target"
    PREDICTOR = "predictor"
    DERIVED = "derived"
    DIAGNOSTIC = "diagnostic"
    GEOMETRY = "geometry"


class ParameterOrigin(str, Enum):
    MEASURED = "measured"        # supplied by the upstream reanalysis / forecast
    COMPUTED = "computed"        # deterministic, from geometry or physics
    ENGINEERED = "engineered"    # constructed from measured values


@dataclass(frozen=True)
class Parameter:
    key: str
    display_name: str
    symbol: str | None
    unit: str | None
    definition: str
    role: ParameterRole
    origin: ParameterOrigin
    valid_min: float | None
    valid_max: float | None
    typical_min: float | None = None
    typical_max: float | None = None
    resolution: str = "hourly"
    required: bool = False
    used_in_training: bool = False
    used_in_inference: bool = False
    effect: str | None = None
    sources: tuple[str, ...] = ()
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        d["origin"] = self.origin.value
        d["sources"] = list(self.sources)
        return d


_PARAMETERS: tuple[Parameter, ...] = (
    # ---------------------------------------------------------------- targets
    Parameter(
        key="ghi_wm2",
        display_name="Global Horizontal Irradiance",
        symbol="GHI",
        unit="W/m²",
        definition=(
            "Total shortwave solar power arriving on a horizontal surface per unit area, "
            "combining the direct beam and the diffuse sky component."
        ),
        role=ParameterRole.TARGET,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=1500.0,
        typical_min=0.0,
        typical_max=1100.0,
        required=True,
        used_in_training=True,
        effect=(
            "The primary scientific target. PV energy is derived from it through an "
            "explicit physical chain rather than predicted directly."
        ),
        sources=("mabodi2024", "lyu2024", "rosales2025", "hobbs2026"),
        notes=(
            "Upper bound of 1500 W/m² allows for cloud-enhancement events, where forward "
            "scattering off cloud edges briefly exceeds the clear-sky value."
        ),
    ),
    Parameter(
        key="clear_sky_index",
        display_name="Clear-Sky Index",
        symbol="kt",
        unit="dimensionless",
        definition=(
            "Ratio of observed GHI to modelled clear-sky GHI. Isolates atmospheric "
            "attenuation by dividing out the deterministic solar-geometry signal."
        ),
        role=ParameterRole.TARGET,
        origin=ParameterOrigin.ENGINEERED,
        valid_min=0.0,
        valid_max=1.5,
        typical_min=0.0,
        typical_max=1.1,
        used_in_training=True,
        effect=(
            "Preferred modelling target. Because the diurnal and seasonal cycle is removed "
            "before fitting, the model spends its capacity on the genuinely uncertain part "
            "of the problem — cloud and aerosol attenuation."
        ),
        sources=("hobbs2026",),
        notes="Undefined at night; those hours are excluded rather than filled with zero.",
    ),
    # ------------------------------------------------------------- predictors
    Parameter(
        key="temperature_c",
        display_name="Air Temperature (2 m)",
        symbol="T",
        unit="°C",
        definition="Dry-bulb air temperature measured two metres above ground level.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=-90.0,
        valid_max=60.0,
        typical_min=-40.0,
        typical_max=50.0,
        required=True,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "Correlates positively with irradiance because sunlight heats the surface. "
            "Also drives PV efficiency directly: higher module temperature reduces output."
        ),
        sources=("mabodi2024", "rosales2025", "babu2025", "hayajneh2024", "hobbs2026"),
        notes=(
            "Mabodi & Hammujuddy [P2] report temperature as the strongest single predictor "
            "of GHI at 42.45 % permutation importance. Bounds span the Vostok and "
            "Furnace Creek records with margin."
        ),
    ),
    Parameter(
        key="relative_humidity_pct",
        display_name="Relative Humidity",
        symbol="RH",
        unit="%",
        definition="Water-vapour content of the air as a percentage of saturation at that temperature.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=100.0,
        typical_min=5.0,
        typical_max=100.0,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "Generally negatively correlated with irradiance: humid air scatters and "
            "absorbs shortwave radiation, and high humidity often accompanies cloud."
        ),
        sources=("mabodi2024", "lyu2024", "rosales2025", "hayajneh2024"),
    ),
    Parameter(
        key="cloud_cover_pct",
        display_name="Total Cloud Cover",
        symbol="CC",
        unit="%",
        definition="Fraction of the sky dome covered by cloud, over the reanalysis grid cell.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=100.0,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "The dominant control on short-term irradiance variability and the variable "
            "that separates the forecastable from the unforecastable."
        ),
        sources=("lyu2024", "babu2025"),
        notes=(
            "Used to assign the sunny / cloudy / other weather regimes of Lyu & "
            "Eftekharnejad [P3], who place the sunny threshold at cloud cover < 25 %. "
            "Note this is a grid-cell fraction, so 100 % cover can coexist with high "
            "irradiance when the cloud is thin or high."
        ),
    ),
    Parameter(
        key="surface_pressure_hpa",
        display_name="Surface Pressure",
        symbol="P",
        unit="hPa",
        definition="Atmospheric pressure at the station's surface elevation.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=500.0,
        valid_max=1100.0,
        typical_min=850.0,
        typical_max=1050.0,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "A proxy for synoptic weather state; high pressure tends to accompany settled, "
            "clear conditions."
        ),
        sources=("mabodi2024", "rosales2025", "hayajneh2024"),
        notes="Surface pressure falls with elevation, so its absolute level is site-specific.",
    ),
    Parameter(
        key="wind_speed_ms",
        display_name="Wind Speed (10 m)",
        symbol="v",
        unit="m/s",
        definition="Horizontal wind speed ten metres above ground level.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=120.0,
        typical_min=0.0,
        typical_max=25.0,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "Weak direct predictor of irradiance, but a strong control on PV output: wind "
            "cools the module, and cooler modules are more efficient. This is the physical "
            "mechanism behind the wind-cooling effect described in the project abstract."
        ),
        sources=("hobbs2026", "mabodi2024", "rosales2025"),
    ),
    Parameter(
        key="wind_direction_deg",
        display_name="Wind Direction (10 m)",
        symbol="φ",
        unit="° from north",
        definition="Compass direction the wind blows from, degrees clockwise from true north.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=360.0,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "Encodes air-mass origin, which can carry a regional signal. Decomposed into "
            "sine and cosine components before use so that 359° and 1° are near-neighbours."
        ),
        sources=("mabodi2024", "rosales2025"),
    ),
    Parameter(
        key="dew_point_c",
        display_name="Dew Point",
        symbol="Td",
        unit="°C",
        definition="Temperature to which air must cool at constant pressure to reach saturation.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=-90.0,
        valid_max=45.0,
        used_in_training=True,
        used_in_inference=True,
        effect="Absolute moisture measure; together with temperature it constrains humidity.",
        sources=("lyu2024", "rosales2025"),
    ),
    Parameter(
        key="precipitation_mm",
        display_name="Precipitation",
        symbol="Pr",
        unit="mm",
        definition="Total liquid-equivalent precipitation accumulated over the hour.",
        role=ParameterRole.PREDICTOR,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=250.0,
        typical_min=0.0,
        typical_max=50.0,
        used_in_training=True,
        used_in_inference=True,
        effect="Marks the heavily attenuated 'other' weather regime of [P3].",
        sources=("lyu2024", "rosales2025"),
    ),
    # -------------------------------------------------------------- geometry
    Parameter(
        key="solar_zenith_deg",
        display_name="Solar Zenith Angle",
        symbol="θz",
        unit="°",
        definition="Angle between the sun and the vertical. 0° is directly overhead, 90° the horizon.",
        role=ParameterRole.GEOMETRY,
        origin=ParameterOrigin.COMPUTED,
        valid_min=0.0,
        valid_max=180.0,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "Sets the geometric ceiling on available irradiance and the atmospheric path "
            "length. Known exactly for any time and place, so it is computed, never learned."
        ),
        sources=("lyu2024", "babu2025"),
        notes="Values above 87° are treated as night, following [P3, Sec. II-A].",
    ),
    Parameter(
        key="solar_azimuth_deg",
        display_name="Solar Azimuth Angle",
        symbol="γs",
        unit="° from north",
        definition="Compass bearing of the sun, degrees clockwise from true north.",
        role=ParameterRole.GEOMETRY,
        origin=ParameterOrigin.COMPUTED,
        valid_min=0.0,
        valid_max=360.0,
        used_in_training=True,
        used_in_inference=True,
        effect="With zenith, fixes the sun's position; required for angle of incidence.",
        sources=("babu2025",),
    ),
    Parameter(
        key="aoi_deg",
        display_name="Angle of Incidence",
        symbol="AOI",
        unit="°",
        definition="Angle between the direct beam and the normal to the panel surface.",
        role=ParameterRole.GEOMETRY,
        origin=ParameterOrigin.COMPUTED,
        valid_min=0.0,
        valid_max=180.0,
        used_in_training=True,
        used_in_inference=True,
        effect=(
            "Controls how much of the beam the array actually intercepts. Vijay Babu et al. "
            "[P5] found this the highest-importance feature of any variable in their study."
        ),
        sources=("babu2025",),
    ),
    Parameter(
        key="clear_sky_ghi_wm2",
        display_name="Clear-Sky GHI",
        symbol="GHIcs",
        unit="W/m²",
        definition="Modelled global horizontal irradiance under a cloud-free sky (Haurwitz 1945).",
        role=ParameterRole.DERIVED,
        origin=ParameterOrigin.COMPUTED,
        valid_min=0.0,
        valid_max=1200.0,
        used_in_training=True,
        used_in_inference=True,
        effect="The reference against which the clear-sky index is formed.",
        sources=("hobbs2026",),
    ),
    # ------------------------------------------------------------ diagnostics
    Parameter(
        key="dni_wm2",
        display_name="Direct Normal Irradiance",
        symbol="DNI",
        unit="W/m²",
        definition="Beam irradiance on a surface held perpendicular to the sun.",
        role=ParameterRole.DIAGNOSTIC,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=1200.0,
        effect=(
            "Reported as a diagnostic. Excluded from the predictor set because it is a "
            "component of the target and would constitute target leakage."
        ),
        sources=("hayajneh2024", "lyu2024"),
    ),
    Parameter(
        key="dhi_wm2",
        display_name="Diffuse Horizontal Irradiance",
        symbol="DHI",
        unit="W/m²",
        definition="Scattered sky irradiance on a horizontal surface, excluding the direct beam.",
        role=ParameterRole.DIAGNOSTIC,
        origin=ParameterOrigin.MEASURED,
        valid_min=0.0,
        valid_max=800.0,
        effect="Diagnostic only, for the same leakage reason as DNI.",
        sources=("hayajneh2024", "hobbs2026"),
    ),
    # ------------------------------------------------------------ PV outputs
    Parameter(
        key="poa_wm2",
        display_name="Plane-of-Array Irradiance",
        symbol="POA",
        unit="W/m²",
        definition="Total irradiance on the tilted module surface (beam + sky diffuse + ground reflected).",
        role=ParameterRole.DERIVED,
        origin=ParameterOrigin.COMPUTED,
        valid_min=0.0,
        valid_max=1600.0,
        effect="The irradiance the modules actually receive; drives DC output.",
        sources=("hobbs2026",),
    ),
    Parameter(
        key="cell_temperature_c",
        display_name="Module Temperature",
        symbol="Tcell",
        unit="°C",
        definition="Photovoltaic cell operating temperature, from the Faiman (2008) model.",
        role=ParameterRole.DERIVED,
        origin=ParameterOrigin.COMPUTED,
        valid_min=-90.0,
        valid_max=110.0,
        effect="Efficiency falls roughly 0.35 % per °C above the 25 °C reference.",
        sources=("hobbs2026",),
    ),
    Parameter(
        key="ac_power_kw",
        display_name="AC Power Output",
        symbol="Pac",
        unit="kW",
        definition="Alternating-current power delivered by the declared PV system after inverter losses.",
        role=ParameterRole.DERIVED,
        origin=ParameterOrigin.COMPUTED,
        valid_min=0.0,
        valid_max=None,
        effect=(
            "Meaningful only relative to a declared system. Every reported figure is "
            "accompanied by the array specification that produced it."
        ),
        sources=("hobbs2026", "abstract"),
    ),
    Parameter(
        key="energy_kwh",
        display_name="Energy Yield",
        symbol="E",
        unit="kWh",
        definition="AC energy delivered over a stated period by the declared PV system.",
        role=ParameterRole.DERIVED,
        origin=ParameterOrigin.COMPUTED,
        valid_min=0.0,
        valid_max=None,
        resolution="hourly, summable",
        effect=(
            "The quantity the project abstract asks for. Reported only alongside the "
            "system specification and the integration period, without which it is undefined."
        ),
        sources=("abstract", "hobbs2026"),
    ),
)


PARAMETERS: dict[str, Parameter] = {p.key: p for p in _PARAMETERS}


# Variables named in the source research that this data source does not supply.
# Surfaced in the UI rather than silently omitted, so the gap is visible.
UNAVAILABLE_PARAMETERS: tuple[dict[str, str], ...] = (
    {
        "display_name": "Wind Direction Standard Deviation",
        "unit": "°",
        "sources": "mabodi2024",
        "reason": (
            "Reported by Mabodi & Hammujuddy [P2] as the second-strongest predictor "
            "(14.34 % importance). It is a sub-hourly turbulence statistic that requires "
            "high-frequency anemometry; hourly reanalysis cannot reconstruct it."
        ),
    },
    {
        "display_name": "Sunshine Duration",
        "unit": "hours",
        "sources": "rosales2025",
        "reason": (
            "Rosales Huamani et al. [P4] identify its absence as a limitation of their own "
            "study. Not published by this data source at hourly resolution."
        ),
    },
    {
        "display_name": "Aerosol Optical Depth",
        "unit": "dimensionless",
        "sources": "—",
        "reason": (
            "A physically important control on clear-sky attenuation, particularly in the "
            "arid and urban settings of [P4]. Requires a separate atmospheric-composition "
            "product; not integrated."
        ),
    },
    {
        "display_name": "Measured Plant Power",
        "unit": "MW",
        "sources": "hobbs2026, babu2025, hayajneh2024",
        "reason": (
            "Real metered PV output, as used by [P1] (ERCOT) and [P6]. Without it, PV "
            "figures in this platform are physically modelled from predicted irradiance "
            "and are not validated against measured generation."
        ),
    },
)


def predictor_keys() -> list[str]:
    """Keys of parameters eligible to be model inputs."""
    return [k for k, p in PARAMETERS.items() if p.used_in_inference]


def parameter_catalogue() -> dict[str, Any]:
    """Serialisable catalogue for the API and the UI parameter reference."""
    return {
        "parameters": [p.to_dict() for p in _PARAMETERS],
        "unavailable": [dict(u) for u in UNAVAILABLE_PARAMETERS],
        "day_mask_threshold_deg": 87.0,
        "day_mask_source": "lyu2024",
    }
