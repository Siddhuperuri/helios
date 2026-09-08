"""The fast path: expected yield from years of real weather, without training anything.

§17 forbids a `sunlight × capacity` calculator, and this is the module that has to make
good on that. It runs the same published physical chain the research surface uses —
Erbs decomposition, HDKR transposition, Faiman cell temperature, PVWatts v5 DC, inverter
efficiency and clipping — over several years of hourly reanalysis for the user's exact
coordinates, and then aggregates.

Why no machine learning here. The consumer question is *what will this system produce in a
typical year?* That is a climatology question, and the honest answer comes from running the
physics over years of observed weather. A model trained to forecast hour-ahead irradiance
adds nothing to a 20-year average and would cost 30 seconds of training to say the same
thing. ML earns its place on the forward-looking path (`/refine`), where predicting a
specific future day is the actual task.

The other reason this design matters: **inter-annual variability is measured here, not
invented.** The spread between what 2019 produced and what 2021 produced at these
coordinates is a real, observed quantity, and it is what §19's expected range is built
from. No arbitrary ±10 % band appears anywhere in this platform.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.data.sources import Location, fetch_archive, latest_available_archive_date
from app.features.solar_geometry import PVSystem, pv_power_chain

logger = logging.getLogger(__name__)

# Years of history behind a quick estimate. Three captures genuine year-to-year weather
# variation — a strong monsoon against a weak one — without the fetch and the arithmetic
# growing enough to be felt. The deeper analysis path uses more.
DEFAULT_HISTORY_YEARS = 3

# A month is only counted if this fraction of its hours survived. Partial months at the
# edges of the fetched window would otherwise drag a monthly average down and look like a
# seasonal effect.
MONTH_COMPLETENESS_THRESHOLD = 0.90

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


@dataclass
class ClimatologyResult:
    """Expected production for a declared system, from observed weather."""

    annual_kwh: float
    annual_std_kwh: float
    monthly_kwh: list[float]           # 12 values, mean across years
    monthly_std_kwh: list[float]       # 12 values, std across years
    daily_profile_kwh: list[float]     # 24 values, mean day, local time
    monthly_daily_profiles: dict[int, list[float]]  # month -> 24 values
    best_month: int
    worst_month: int
    specific_yield_kwh_per_kwp: float
    capacity_factor: float
    performance_ratio: float
    mean_poa_kwh_per_m2_year: float
    mean_ghi_kwh_per_m2_year: float
    clipped_fraction: float
    hourly_ac_kw: pd.Series = field(repr=False, default_factory=pd.Series)
    years_used: int = 0
    complete_calendar_years: int = 0
    period_start: str = ""
    period_end: str = ""
    rows_used: int = 0
    rows_dropped: int = 0
    variability_basis: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "annual_kwh": round(self.annual_kwh, 0),
            "annual_std_kwh": round(self.annual_std_kwh, 0),
            "monthly_kwh": [round(v, 0) for v in self.monthly_kwh],
            "monthly_std_kwh": [round(v, 0) for v in self.monthly_std_kwh],
            "month_names": list(MONTH_NAMES),
            "daily_profile_kwh": [round(v, 3) for v in self.daily_profile_kwh],
            "best_month": self.best_month,
            "best_month_name": MONTH_NAMES[self.best_month - 1],
            "worst_month": self.worst_month,
            "worst_month_name": MONTH_NAMES[self.worst_month - 1],
            "specific_yield_kwh_per_kwp": round(self.specific_yield_kwh_per_kwp, 0),
            "capacity_factor": round(self.capacity_factor, 4),
            "performance_ratio": round(self.performance_ratio, 3),
            "mean_poa_kwh_per_m2_year": round(self.mean_poa_kwh_per_m2_year, 0),
            "mean_ghi_kwh_per_m2_year": round(self.mean_ghi_kwh_per_m2_year, 0),
            "clipped_fraction": round(self.clipped_fraction, 4),
            "years_used": self.years_used,
            "complete_calendar_years": self.complete_calendar_years,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "rows_used": self.rows_used,
            "rows_dropped": self.rows_dropped,
            "variability_basis": self.variability_basis,
            "warnings": self.warnings,
        }


def _local_index(frame: pd.DataFrame, location: Location) -> pd.DatetimeIndex:
    """Convert a UTC index to local clock time.

    Local time is what a person means by "morning" and by "January", so every aggregation
    that a user reads is done on it. Where the geocoder gave no timezone, longitude gives a
    solar-time approximation, which is the right fallback for a solar calculation — it puts
    noon at solar noon, which is exactly the alignment the daily profile needs.
    """
    idx = frame.index
    tz = getattr(location, "timezone", None)
    if tz:
        try:
            return idx.tz_convert(tz)
        except Exception:  # noqa: BLE001 - any bad zone name from upstream falls through
            logger.info("Unknown timezone '%s'; falling back to longitude offset", tz)
    offset_hours = round(location.longitude / 15.0)
    return idx + pd.Timedelta(hours=int(offset_hours))


def fetch_history(
    location: Location,
    *,
    years: int = DEFAULT_HISTORY_YEARS,
    end: date | None = None,
) -> tuple[pd.DataFrame, date, date]:
    """Retrieve the hourly record a quick estimate is built on.

    Separated from :func:`compute` so one estimate fetches once and then reuses the same
    frame for the orientation search, the yield calculation and any later refinement.
    """
    end_date = end or latest_available_archive_date()
    start_date = end_date - timedelta(days=int(365.25 * years))
    raw = fetch_archive(location, start_date, end_date)
    if raw.empty:
        raise ValueError(
            "No weather data was returned for this location and period, so production "
            "cannot be estimated."
        )
    return raw, start_date, end_date


def usable_hours(raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop hours the physical chain cannot use, and report how many went.

    Nothing is imputed. A fabricated irradiance value would flow straight into an annual
    energy figure and the user would have no way to see it.
    """
    needed = ["ghi_wm2", "temperature_c", "wind_speed_ms"]
    missing_cols = [c for c in needed if c not in raw.columns]
    if missing_cols:
        raise ValueError(
            "The weather record is missing required variables: " + ", ".join(missing_cols)
        )
    n_before = len(raw)
    frame = raw.dropna(subset=needed)
    return frame, n_before - len(frame)


def compute(
    location: Location,
    system: PVSystem,
    *,
    years: int = DEFAULT_HISTORY_YEARS,
    end: date | None = None,
    raw: pd.DataFrame | None = None,
    period: tuple[date, date] | None = None,
) -> ClimatologyResult:
    """Run the physical chain over historical weather and aggregate to a typical year."""
    warnings: list[str] = []

    if raw is None:
        raw, start_date, end_date = fetch_history(location, years=years, end=end)
    else:
        if period is not None:
            start_date, end_date = period
        else:
            start_date = raw.index.min().date()
            end_date = raw.index.max().date()

    n_before = len(raw)
    frame, dropped = usable_hours(raw)
    if dropped:
        share = dropped / max(1, n_before)
        if share > 0.10:
            warnings.append(
                f"{share:.0%} of the hourly weather record was incomplete and was left out. "
                f"The estimate rests on the remaining {len(frame):,} hours."
            )
        logger.info("Dropped %d incomplete hours of %d", dropped, n_before)

    if len(frame) < 24 * 300:
        raise ValueError(
            f"Only {len(frame):,} complete hours of weather were available for this "
            f"location — under a year. A yearly estimate needs at least a full annual cycle."
        )

    pv = pv_power_chain(
        ghi=frame["ghi_wm2"].to_numpy(dtype=np.float64),
        air_temp_c=frame["temperature_c"].to_numpy(dtype=np.float64),
        wind_speed_ms=frame["wind_speed_ms"].to_numpy(dtype=np.float64),
        times_utc=frame.index.to_numpy(),
        latitude=location.latitude,
        longitude=location.longitude,
        system=system,
    )

    local_idx = _local_index(frame, location)
    # Hourly AC power in kW equals kWh over a one-hour interval, which is what every
    # aggregation below sums.
    energy = pd.Series(pv.ac_power_kw, index=local_idx, name="kwh")
    poa = pd.Series(pv.poa_wm2, index=local_idx, name="poa")
    ghi = pd.Series(frame["ghi_wm2"].to_numpy(dtype=np.float64), index=local_idx, name="ghi")

    # ------------------------------------------------------------------ monthly totals
    grouped = energy.groupby([local_idx.year, local_idx.month])
    monthly_totals = grouped.sum()
    monthly_counts = grouped.count()

    expected_hours = pd.Series(
        [
            pd.Period(year=y, month=m, freq="M").days_in_month * 24
            for (y, m) in monthly_totals.index
        ],
        index=monthly_totals.index,
        dtype=np.float64,
    )
    complete = monthly_counts >= expected_hours * MONTH_COMPLETENESS_THRESHOLD
    monthly_totals = monthly_totals[complete]

    if monthly_totals.empty:
        raise ValueError(
            "No complete month of weather data was available, so a monthly breakdown "
            "cannot be produced."
        )

    by_month = monthly_totals.groupby(level=1)
    monthly_mean = by_month.mean().reindex(range(1, 13))
    monthly_std = by_month.std(ddof=0).reindex(range(1, 13)).fillna(0.0)

    if monthly_mean.isna().any():
        absent = [MONTH_NAMES[m - 1] for m in monthly_mean.index[monthly_mean.isna()]]
        warnings.append(
            "The weather record held no complete data for " + ", ".join(absent) +
            ". Those months are estimated from the annual average, so the seasonal shape "
            "is less reliable than usual."
        )
        monthly_mean = monthly_mean.fillna(monthly_mean.mean())
        monthly_std = monthly_std.fillna(monthly_std.mean())

    annual_kwh = float(monthly_mean.sum())

    # ------------------------------------------------- inter-annual variability (§19)
    year_totals = monthly_totals.groupby(level=0).sum()
    year_month_counts = monthly_totals.groupby(level=0).count()
    full_years = year_totals[year_month_counts == 12]

    if len(full_years) >= 3:
        annual_std = float(full_years.std(ddof=1))
        basis = (
            f"Measured from {len(full_years)} complete years of weather at this location."
        )
        complete_years = int(len(full_years))
    else:
        # Combining monthly standard deviations in quadrature assumes months vary
        # independently. They do not entirely — a weak monsoon depresses several months
        # together — so this understates the true annual spread slightly. Stated, not hidden.
        annual_std = float(np.sqrt(np.square(monthly_std.to_numpy()).sum()))
        basis = (
            "Estimated by combining month-to-month variation, because fewer than three "
            "complete years of weather were available. The real year-to-year spread is "
            "likely a little wider."
        )
        complete_years = int(len(full_years))

    # ----------------------------------------------------------------- daily profiles
    hour_of_day = local_idx.hour
    n_days = max(1, len(frame) / 24.0)
    daily_profile = (
        energy.groupby(hour_of_day).sum().reindex(range(24)).fillna(0.0) / n_days
    )

    monthly_profiles: dict[int, list[float]] = {}
    for month in range(1, 13):
        mask = local_idx.month == month
        if not mask.any():
            monthly_profiles[month] = [0.0] * 24
            continue
        sub = energy[mask]
        sub_days = max(1, mask.sum() / 24.0)
        prof = sub.groupby(local_idx[mask].hour).sum().reindex(range(24)).fillna(0.0) / sub_days
        monthly_profiles[month] = [round(float(v), 4) for v in prof.to_numpy()]

    # ---------------------------------------------------------------------- resource
    years_span = len(frame) / (365.25 * 24.0)
    poa_kwh_m2_year = float(poa.sum()) / 1000.0 / max(years_span, 1e-9)
    ghi_kwh_m2_year = float(ghi.sum()) / 1000.0 / max(years_span, 1e-9)

    # Performance ratio: delivered AC energy against what the array would make at its
    # nameplate efficiency under the plane-of-array irradiance it actually received.
    reference = poa_kwh_m2_year * system.dc_capacity_kwp / 1.0  # 1 kW/m^2 at STC
    performance_ratio = float(annual_kwh / reference) if reference > 0 else 0.0

    best_month = int(monthly_mean.idxmax())
    worst_month = int(monthly_mean.idxmin())

    if system.inverter_ac_capacity_kw is None:
        warnings.append(
            "No inverter size was given, so a standard 1.2 DC-to-AC ratio was assumed."
        )

    return ClimatologyResult(
        annual_kwh=annual_kwh,
        annual_std_kwh=annual_std,
        monthly_kwh=[float(v) for v in monthly_mean.to_numpy()],
        monthly_std_kwh=[float(v) for v in monthly_std.to_numpy()],
        daily_profile_kwh=[float(v) for v in daily_profile.to_numpy()],
        monthly_daily_profiles=monthly_profiles,
        best_month=best_month,
        worst_month=worst_month,
        specific_yield_kwh_per_kwp=annual_kwh / system.dc_capacity_kwp,
        capacity_factor=annual_kwh / (system.dc_capacity_kwp * 8766.0),
        performance_ratio=performance_ratio,
        mean_poa_kwh_per_m2_year=poa_kwh_m2_year,
        mean_ghi_kwh_per_m2_year=ghi_kwh_m2_year,
        clipped_fraction=pv.clipped_fraction,
        hourly_ac_kw=energy,
        years_used=int(round(years_span)),
        complete_calendar_years=complete_years,
        period_start=start_date.isoformat(),
        period_end=end_date.isoformat(),
        rows_used=len(frame),
        rows_dropped=dropped,
        variability_basis=basis,
        warnings=warnings,
    )
