"""
Solar geometry, clear-sky modelling, and the deterministic PV conversion chain.

This module contains the physics of the platform. Everything here is deterministic and
closed-form: given a timestamp and a location, the solar position is *known*, not learned.
Isolating it from the statistical layer is deliberate — it means the machine-learning models
are only ever asked to predict the genuinely uncertain part of the problem (the atmospheric
attenuation), never the part that celestial mechanics already determines exactly.

Method provenance
-----------------
Solar position      NOAA Solar Calculator formulation (Michalsky 1988; NOAA ESRL).
                    Accuracy ~0.01 deg for years 1900-2100, which is far below the
                    resolution at which any of the meteorological inputs vary.
Clear-sky GHI       Haurwitz (1945). Selected because Hobbs & Joshi [P1, Sec. II-B2b]
                    use exactly this model to form the clear-sky index that underpins
                    their operational forecast chain.
Diffuse split       Erbs et al. (1982). Used by [P1, Sec. II-B2d] for the same purpose.
Transposition       HDKR (Hay-Davies-Klucher-Reindl). [P1] uses Perez-Driesse; HDKR is the
                    next model down in complexity, needs no empirical coefficient tables,
                    and its error is small relative to the forecast error of the irradiance
                    input itself. This substitution is recorded in the model card.
Cell temperature    Faiman (2008) - the model named in [P1, Sec. II-B3].
DC / AC conversion  PVWatts v5 (Dobos 2014, NREL/TP-6A20-62641) - named in [P1].

References are keyed to docs/RESEARCH_SYNTHESIS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Solar constant, W/m^2 (WMO / Kopp & Lean 2011).
SOLAR_CONSTANT = 1361.0

# Haurwitz coefficients (Haurwitz 1945).
_HAURWITZ_A = 1098.0
_HAURWITZ_B = 0.059

# Faiman (2008) combined heat-loss coefficients for open-rack modules.
FAIMAN_U0 = 25.0  # W/(m^2 K)
FAIMAN_U1 = 6.84  # W/(m^3 s K)

# Beyond this zenith angle the sun is at or below the horizon for modelling purposes.
# Lyu & Eftekharnejad [P3, Sec. II-A] retain only data with zenith < 87 deg to
# "eliminate the confounding effects of night-time conditions". We adopt that threshold
# verbatim so that our day-mask is directly comparable to theirs.
DAYTIME_ZENITH_THRESHOLD_DEG = 87.0

# Interval-labelling correction.
#
# Irradiance in the source archive is an *average over an interval*, but solar position is
# an *instantaneous* quantity. Evaluating the position at the interval label rather than at
# its midpoint introduces a systematic half-hour phase error, which shows up as apparent
# night-time irradiance and as spurious exceedance of the clear-sky ceiling.
#
# Hobbs & Joshi [P1, Sec. II-B2] handle this by converting forecasts to "hour-interval
# averages with center-labeled time stamps". We determine the convention empirically rather
# than assume it: sweeping candidate offsets over a full year at Hyderabad, an offset of
# -30 min minimises clear-sky exceedance (264 hours -> 0), maximises the correlation between
# observed and clear-sky irradiance (0.9372 -> 0.9490), and reduces apparent night-time
# irradiance. That identifies the archive's hourly radiation as the mean over the *preceding*
# hour, whose representative instant is 30 minutes before the label.
#
# The procedure that established this is reproducible via scripts/calibrate_interval.py.
IRRADIANCE_INTERVAL_OFFSET_MINUTES = -30.0


def representative_times(
    index_or_array, offset_minutes: float = IRRADIANCE_INTERVAL_OFFSET_MINUTES
) -> np.ndarray:
    """Instants at which to evaluate solar position for interval-averaged irradiance.

    Accepts a pandas ``DatetimeIndex`` (timezone-aware or naive, treated as UTC) or a
    numpy ``datetime64`` array, and returns a ``datetime64[s]`` array shifted to the
    representative instant of each interval.
    """
    arr = getattr(index_or_array, "to_numpy", lambda: index_or_array)()
    # tz-aware pandas indexes convert cleanly to UTC-based datetime64 via astype.
    arr = np.asarray(arr).astype("datetime64[s]")
    return arr + np.timedelta64(int(round(offset_minutes * 60)), "s")


# --------------------------------------------------------------------------------------
# Solar position
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SolarPosition:
    """Solar position for a set of timestamps at one location. All angles in degrees."""

    zenith: np.ndarray
    apparent_zenith: np.ndarray
    elevation: np.ndarray
    apparent_elevation: np.ndarray
    azimuth: np.ndarray
    declination: np.ndarray
    equation_of_time: np.ndarray
    hour_angle: np.ndarray

    @property
    def cos_zenith(self) -> np.ndarray:
        """cos(zenith), clipped at zero. Zero below the horizon rather than negative."""
        return np.clip(np.cos(np.radians(self.zenith)), 0.0, None)

    @property
    def is_daytime(self) -> np.ndarray:
        """Boolean day mask using the 87-degree threshold of [P3]."""
        return self.apparent_zenith < DAYTIME_ZENITH_THRESHOLD_DEG


def _julian_day(dt64: np.ndarray) -> np.ndarray:
    """Julian Day from numpy datetime64 values interpreted as UTC.

    Uses the Unix epoch offset directly, which avoids the calendar-branch bugs that
    hand-rolled Gregorian conversions tend to carry.
    """
    seconds = dt64.astype("datetime64[s]").astype(np.float64)
    return seconds / 86400.0 + 2440587.5


def solar_position(times_utc: np.ndarray, latitude: float, longitude: float) -> SolarPosition:
    """Compute solar position using the NOAA Solar Calculator formulation.

    Parameters
    ----------
    times_utc
        ``datetime64`` array of timestamps, interpreted as UTC.
    latitude
        Degrees north, in [-90, 90].
    longitude
        Degrees east, in [-180, 180].

    Notes
    -----
    Refraction is applied to produce ``apparent_zenith``. The day mask and the clear-sky
    model both use the apparent (refracted) position, because that is what determines
    whether sunlight is actually reaching the surface.
    """
    jd = _julian_day(np.asarray(times_utc))
    jc = (jd - 2451545.0) / 36525.0  # Julian century since J2000.0

    # Geometric mean longitude of the sun (deg), wrapped to [0, 360).
    geom_mean_long = np.mod(280.46646 + jc * (36000.76983 + jc * 0.0003032), 360.0)

    # Geometric mean anomaly (deg).
    geom_mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    gma_rad = np.radians(geom_mean_anom)

    # Eccentricity of Earth's orbit (unitless).
    eccentricity = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)

    # Sun equation of centre (deg).
    sun_eq_centre = (
        np.sin(gma_rad) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + np.sin(2.0 * gma_rad) * (0.019993 - 0.000101 * jc)
        + np.sin(3.0 * gma_rad) * 0.000289
    )

    sun_true_long = geom_mean_long + sun_eq_centre

    # Apparent longitude, correcting for nutation and aberration (deg).
    sun_app_long = (
        sun_true_long
        - 0.00569
        - 0.00478 * np.sin(np.radians(125.04 - 1934.136 * jc))
    )

    # Mean obliquity of the ecliptic (deg) and its nutation correction.
    mean_obliquity = 23.0 + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0) / 60.0
    obliquity_corr = mean_obliquity + 0.00256 * np.cos(np.radians(125.04 - 1934.136 * jc))

    obl_rad = np.radians(obliquity_corr)
    app_long_rad = np.radians(sun_app_long)

    # Solar declination (deg).
    declination = np.degrees(np.arcsin(np.sin(obl_rad) * np.sin(app_long_rad)))

    # Equation of time (minutes).
    var_y = np.tan(obl_rad / 2.0) ** 2
    gml_rad = np.radians(geom_mean_long)
    eq_time = 4.0 * np.degrees(
        var_y * np.sin(2.0 * gml_rad)
        - 2.0 * eccentricity * np.sin(gma_rad)
        + 4.0 * eccentricity * var_y * np.sin(gma_rad) * np.cos(2.0 * gml_rad)
        - 0.5 * var_y * var_y * np.sin(4.0 * gml_rad)
        - 1.25 * eccentricity * eccentricity * np.sin(2.0 * gma_rad)
    )

    # True solar time (minutes past local midnight) and hour angle (deg).
    minutes_utc = (jd - np.floor(jd - 0.5) - 0.5) * 1440.0
    true_solar_time = np.mod(minutes_utc + eq_time + 4.0 * longitude, 1440.0)
    hour_angle = np.where(
        true_solar_time / 4.0 < 0.0,
        true_solar_time / 4.0 + 180.0,
        true_solar_time / 4.0 - 180.0,
    )

    lat_rad = np.radians(latitude)
    dec_rad = np.radians(declination)
    ha_rad = np.radians(hour_angle)

    cos_zenith = np.sin(lat_rad) * np.sin(dec_rad) + np.cos(lat_rad) * np.cos(dec_rad) * np.cos(ha_rad)
    cos_zenith = np.clip(cos_zenith, -1.0, 1.0)
    zenith = np.degrees(np.arccos(cos_zenith))
    elevation = 90.0 - zenith

    refraction = _atmospheric_refraction(elevation)
    apparent_elevation = elevation + refraction
    apparent_zenith = 90.0 - apparent_elevation

    azimuth = _solar_azimuth(lat_rad, dec_rad, np.radians(zenith), hour_angle)

    return SolarPosition(
        zenith=zenith,
        apparent_zenith=apparent_zenith,
        elevation=elevation,
        apparent_elevation=apparent_elevation,
        azimuth=azimuth,
        declination=declination,
        equation_of_time=eq_time,
        hour_angle=hour_angle,
    )


def _atmospheric_refraction(elevation_deg: np.ndarray) -> np.ndarray:
    """Atmospheric refraction correction in degrees (NOAA piecewise approximation).

    Refraction lifts the apparent sun above its geometric position near the horizon by
    roughly half a degree, which is why sunrise appears earlier than geometry predicts.
    """
    e = np.asarray(elevation_deg, dtype=np.float64)
    te = np.tan(np.radians(np.clip(e, -1.0, None)))

    refraction = np.zeros_like(e)

    high = e > 85.0
    mid = (e > 5.0) & ~high
    low = (e > -0.575) & ~high & ~mid
    very_low = ~high & ~mid & ~low

    with np.errstate(divide="ignore", invalid="ignore"):
        refraction = np.where(
            mid,
            58.1 / te - 0.07 / te**3 + 0.000086 / te**5,
            refraction,
        )
        refraction = np.where(
            low,
            1735.0 + e * (-518.2 + e * (103.4 + e * (-12.79 + e * 0.711))),
            refraction,
        )
        refraction = np.where(very_low, -20.774 / te, refraction)

    refraction = np.where(high, 0.0, refraction)
    return np.nan_to_num(refraction) / 3600.0


def _solar_azimuth(
    lat_rad: float, dec_rad: np.ndarray, zenith_rad: np.ndarray, hour_angle_deg: np.ndarray
) -> np.ndarray:
    """Solar azimuth in degrees clockwise from true north."""
    sin_zenith = np.sin(zenith_rad)
    # Guard the pole/zenith singularity where azimuth is undefined.
    safe = np.where(np.abs(sin_zenith) < 1e-9, 1e-9, sin_zenith)

    cos_az = (np.sin(np.radians(90.0) - zenith_rad) * np.sin(lat_rad) - np.sin(dec_rad)) / (
        np.cos(np.radians(90.0) - zenith_rad) * np.cos(lat_rad)
    )
    cos_az = np.clip(cos_az, -1.0, 1.0)
    azimuth = np.degrees(np.arccos(cos_az))
    azimuth = np.where(hour_angle_deg > 0.0, np.mod(azimuth + 180.0, 360.0), np.mod(540.0 - azimuth, 360.0))
    return np.where(np.abs(safe) < 1e-8, 0.0, azimuth)


# --------------------------------------------------------------------------------------
# Extraterrestrial and clear-sky irradiance
# --------------------------------------------------------------------------------------

def extraterrestrial_normal(times_utc: np.ndarray) -> np.ndarray:
    """Extraterrestrial irradiance on a surface normal to the beam, W/m^2.

    Varies by about +/-3.3 % over the year because Earth's orbit is elliptical.
    """
    doy = (
        np.asarray(times_utc).astype("datetime64[D]")
        - np.asarray(times_utc).astype("datetime64[Y]")
    ).astype(np.float64) + 1.0
    return SOLAR_CONSTANT * (1.0 + 0.033 * np.cos(2.0 * np.pi * doy / 365.0))


def clear_sky_ghi_haurwitz(apparent_zenith_deg: np.ndarray) -> np.ndarray:
    """Clear-sky GHI (W/m^2) from the Haurwitz (1945) model.

    ``GHI_cs = 1098 * cos(z) * exp(-0.059 / cos(z))``

    A single-parameter model with no site tuning. It is used here for the same reason
    [P1] uses it: the *ratio* of observed to clear-sky irradiance is far more stable and
    more predictable than raw irradiance, and forming that ratio needs a clear-sky
    reference that behaves identically at every location.
    """
    cos_z = np.cos(np.radians(np.asarray(apparent_zenith_deg, dtype=np.float64)))
    cos_z = np.clip(cos_z, 0.0, None)
    out = np.zeros_like(cos_z)
    lit = cos_z > 1e-6
    out[lit] = _HAURWITZ_A * cos_z[lit] * np.exp(-_HAURWITZ_B / cos_z[lit])
    return np.clip(out, 0.0, None)


def clear_sky_index(ghi: np.ndarray, clear_sky: np.ndarray, *, cap: float = 1.5) -> np.ndarray:
    """Clear-sky index kt = GHI / GHI_clearsky, following [P1, Sec. II-B2b].

    Where the clear-sky reference is ~0 (night, or sun on the horizon) the ratio is
    undefined; those entries are returned as NaN rather than as a fabricated zero, so
    downstream code is forced to make an explicit decision about them.

    ``cap`` bounds the index against cloud-enhancement events, where forward scattering
    off cloud edges can briefly push measured GHI above the clear-sky value. Values above
    1.0 are physically real and are retained; the cap only rejects the non-physical tail.
    """
    ghi = np.asarray(ghi, dtype=np.float64)
    clear_sky = np.asarray(clear_sky, dtype=np.float64)

    out = np.full(ghi.shape, np.nan, dtype=np.float64)
    valid = clear_sky > 1.0  # W/m^2 - below this the ratio is numerically meaningless
    out[valid] = ghi[valid] / clear_sky[valid]
    return np.clip(out, 0.0, cap)


def erbs_decomposition(
    ghi: np.ndarray, apparent_zenith_deg: np.ndarray, extraterrestrial_normal_irr: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Split GHI into (DHI, DNI) using Erbs et al. (1982), as in [P1, Sec. II-B2d].

    Returns
    -------
    (dhi, dni) in W/m^2.
    """
    ghi = np.asarray(ghi, dtype=np.float64)
    cos_z = np.clip(np.cos(np.radians(apparent_zenith_deg)), 0.0, None)
    e0h = extraterrestrial_normal_irr * cos_z  # extraterrestrial horizontal

    kt = np.zeros_like(ghi)
    lit = e0h > 1.0
    kt[lit] = np.clip(ghi[lit] / e0h[lit], 0.0, 1.0)

    # Erbs piecewise diffuse fraction.
    df = np.where(
        kt <= 0.22,
        1.0 - 0.09 * kt,
        np.where(
            kt <= 0.80,
            0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4,
            0.165,
        ),
    )
    df = np.clip(df, 0.0, 1.0)

    dhi = np.where(lit, ghi * df, 0.0)
    dni = np.zeros_like(ghi)
    beam_ok = lit & (cos_z > 0.01)
    dni[beam_ok] = (ghi[beam_ok] - dhi[beam_ok]) / cos_z[beam_ok]
    return np.clip(dhi, 0.0, None), np.clip(dni, 0.0, None)


# --------------------------------------------------------------------------------------
# Plane-of-array transposition and the PV conversion chain
# --------------------------------------------------------------------------------------

def angle_of_incidence(
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    solar_zenith_deg: np.ndarray,
    solar_azimuth_deg: np.ndarray,
) -> np.ndarray:
    """Angle between the beam and the array normal, in degrees.

    Vijay Babu et al. [P5, Fig. 5] found angle of incidence to carry the single highest
    permutation importance of any feature, ahead of every meteorological variable, which
    is why it is computed explicitly rather than left for a model to infer from the clock.
    """
    beta = np.radians(surface_tilt_deg)
    gamma = np.radians(surface_azimuth_deg)
    theta_z = np.radians(np.asarray(solar_zenith_deg, dtype=np.float64))
    gamma_s = np.radians(np.asarray(solar_azimuth_deg, dtype=np.float64))

    cos_aoi = np.cos(theta_z) * np.cos(beta) + np.sin(theta_z) * np.sin(beta) * np.cos(gamma_s - gamma)
    return np.degrees(np.arccos(np.clip(cos_aoi, -1.0, 1.0)))


def poa_irradiance_hdkr(
    *,
    ghi: np.ndarray,
    dhi: np.ndarray,
    dni: np.ndarray,
    solar_zenith_deg: np.ndarray,
    aoi_deg: np.ndarray,
    extraterrestrial_normal_irr: np.ndarray,
    albedo: float = 0.2,
    surface_tilt_deg: float = 20.0,
) -> np.ndarray:
    """Plane-of-array irradiance (W/m^2) via the HDKR anisotropic sky model.

    HDKR adds two effects that an isotropic model misses: circumsolar brightening (light
    concentrated near the solar disc) and horizon brightening. Both matter for tilted
    arrays under partly cloudy skies, which is precisely the regime [P3] identifies as
    hardest to forecast.
    """
    cos_z = np.clip(np.cos(np.radians(solar_zenith_deg)), 0.0, None)
    cos_aoi = np.clip(np.cos(np.radians(aoi_deg)), 0.0, None)
    beta = np.radians(surface_tilt_deg)

    beam = dni * cos_aoi

    # Anisotropy index: fraction of extraterrestrial beam reaching the surface.
    with np.errstate(divide="ignore", invalid="ignore"):
        ai = np.where(extraterrestrial_normal_irr > 0.0, dni / extraterrestrial_normal_irr, 0.0)
    ai = np.clip(np.nan_to_num(ai), 0.0, 1.0)

    # Horizon-brightening modulation factor.
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(ghi > 1.0, np.sqrt(np.clip(dni * cos_z / ghi, 0.0, 1.0)), 0.0)
    f = np.nan_to_num(f)

    # Geometric factor Rb, guarded near sunrise/sunset where cos_z -> 0.
    rb = np.where(cos_z > 0.01, cos_aoi / np.maximum(cos_z, 0.01), 0.0)

    sky_diffuse = dhi * (
        (1.0 - ai) * ((1.0 + np.cos(beta)) / 2.0) * (1.0 + f * np.sin(beta / 2.0) ** 3)
        + ai * rb
    )
    ground = ghi * albedo * (1.0 - np.cos(beta)) / 2.0

    return np.clip(beam + sky_diffuse + ground, 0.0, None)


def cell_temperature_faiman(
    poa: np.ndarray,
    air_temp_c: np.ndarray,
    wind_speed_ms: np.ndarray,
    u0: float = FAIMAN_U0,
    u1: float = FAIMAN_U1,
) -> np.ndarray:
    """Module temperature (deg C) from the Faiman (2008) model, as used in [P1].

    ``T_cell = T_air + POA / (u0 + u1 * v_wind)``

    This is the mechanism behind the wind-cooling effect the project abstract refers to:
    wind raises the denominator, lowering cell temperature, which raises efficiency.
    """
    poa = np.asarray(poa, dtype=np.float64)
    air = np.asarray(air_temp_c, dtype=np.float64)
    wind = np.clip(np.asarray(wind_speed_ms, dtype=np.float64), 0.0, None)
    return air + poa / (u0 + u1 * wind)


@dataclass(frozen=True)
class PVSystem:
    """A photovoltaic system, declared explicitly.

    Every field here has to be stated before an energy figure in kWh means anything.
    The reference application reports kWh with none of these declared, which is why its
    output cannot be verified (see docs/REFERENCE_AUDIT.md, Finding E).
    """

    dc_capacity_kwp: float = 5.0
    surface_tilt_deg: float = 20.0
    surface_azimuth_deg: float = 180.0  # 180 = due south
    temperature_coefficient_per_c: float = -0.0035  # /degC; [P1] uses -0.35 %/degC
    system_losses_fraction: float = 0.14  # PVWatts v5 default stack
    inverter_efficiency: float = 0.96
    inverter_ac_capacity_kw: float | None = None
    albedo: float = 0.2

    def __post_init__(self) -> None:
        if self.dc_capacity_kwp <= 0:
            raise ValueError("dc_capacity_kwp must be positive")
        if not 0.0 <= self.surface_tilt_deg <= 90.0:
            raise ValueError("surface_tilt_deg must be within [0, 90]")
        if not 0.0 <= self.surface_azimuth_deg < 360.0:
            raise ValueError("surface_azimuth_deg must be within [0, 360)")
        if not 0.0 <= self.system_losses_fraction < 1.0:
            raise ValueError("system_losses_fraction must be within [0, 1)")
        if not 0.0 < self.inverter_efficiency <= 1.0:
            raise ValueError("inverter_efficiency must be within (0, 1]")

    @property
    def ac_capacity_kw(self) -> float:
        """AC capacity, defaulting to a 1.2 DC/AC ratio when not declared."""
        if self.inverter_ac_capacity_kw is not None:
            return self.inverter_ac_capacity_kw
        return self.dc_capacity_kwp / 1.2

    def describe(self) -> dict[str, object]:
        """Human-readable declaration, embedded in every report and prediction response."""
        return {
            "dc_capacity_kwp": self.dc_capacity_kwp,
            "ac_capacity_kw": round(self.ac_capacity_kw, 3),
            "surface_tilt_deg": self.surface_tilt_deg,
            "surface_azimuth_deg": self.surface_azimuth_deg,
            "temperature_coefficient_per_c": self.temperature_coefficient_per_c,
            "system_losses_fraction": self.system_losses_fraction,
            "inverter_efficiency": self.inverter_efficiency,
            "albedo": self.albedo,
            "dc_model": "PVWatts v5 (Dobos 2014)",
            "cell_temperature_model": "Faiman (2008)",
            "transposition_model": "HDKR",
        }


@dataclass
class PVOutput:
    """Result of the PV conversion chain, with intermediates retained for traceability."""

    poa_wm2: np.ndarray
    cell_temperature_c: np.ndarray
    dc_power_kw: np.ndarray
    ac_power_kw: np.ndarray
    clipping_mask: np.ndarray = field(repr=False)

    @property
    def clipped_fraction(self) -> float:
        """Fraction of lit hours where the inverter limited output."""
        lit = self.dc_power_kw > 1e-6
        return float(self.clipping_mask[lit].mean()) if lit.any() else 0.0


def pv_power_chain(
    *,
    ghi: np.ndarray,
    air_temp_c: np.ndarray,
    wind_speed_ms: np.ndarray,
    times_utc: np.ndarray,
    latitude: float,
    longitude: float,
    system: PVSystem,
    position: SolarPosition | None = None,
) -> PVOutput:
    """Convert GHI plus weather into AC power for a declared PV system.

    The chain is: GHI -> (Erbs) DHI/DNI -> (HDKR) POA -> (Faiman) cell temperature
    -> (PVWatts) DC -> inverter -> AC. Each stage is a published model, and each
    intermediate is returned so that a reviewer can inspect where a number came from.
    """
    # Solar position is evaluated at the interval midpoint, matching the convention the
    # feature pipeline uses. Evaluating at the raw label instead shifts the day/night
    # boundary by a full hour at the terminator, which lets a non-zero power value appear
    # in an hour the rest of the system considers night.
    representative = representative_times(times_utc)
    pos = position if position is not None else solar_position(representative, latitude, longitude)
    e0n = extraterrestrial_normal(representative)

    dhi, dni = erbs_decomposition(ghi, pos.apparent_zenith, e0n)
    aoi = angle_of_incidence(
        system.surface_tilt_deg, system.surface_azimuth_deg, pos.apparent_zenith, pos.azimuth
    )
    poa = poa_irradiance_hdkr(
        ghi=np.asarray(ghi, dtype=np.float64),
        dhi=dhi,
        dni=dni,
        solar_zenith_deg=pos.apparent_zenith,
        aoi_deg=aoi,
        extraterrestrial_normal_irr=e0n,
        albedo=system.albedo,
        surface_tilt_deg=system.surface_tilt_deg,
    )

    # No sun below the horizon, regardless of what the irradiance input claims.
    poa = np.where(pos.is_daytime, poa, 0.0)

    t_cell = cell_temperature_faiman(poa, air_temp_c, wind_speed_ms)

    # PVWatts DC model, referenced to 1000 W/m^2 and 25 degC.
    dc = (poa / 1000.0) * system.dc_capacity_kwp * (
        1.0 + system.temperature_coefficient_per_c * (t_cell - 25.0)
    )
    dc = np.clip(dc, 0.0, None) * (1.0 - system.system_losses_fraction)

    ac_uncapped = dc * system.inverter_efficiency
    cap = system.ac_capacity_kw
    ac = np.minimum(ac_uncapped, cap)
    clipping = ac_uncapped > cap

    return PVOutput(
        poa_wm2=poa,
        cell_temperature_c=t_cell,
        dc_power_kw=dc,
        ac_power_kw=ac,
        clipping_mask=clipping,
    )
