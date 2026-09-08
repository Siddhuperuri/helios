"""Reference forecasts.

A machine-learning model that cannot beat a one-line rule is not a result. These baselines
are what turn an RMSE into evidence: the skill score in ``metrics`` is computed against
them, and the Model Laboratory refuses to describe a model as good without one.

Baselines implemented
---------------------
``persistence``          Tomorrow looks like today, at matching clock hour. The standard
                         reference in [P6] and across the solar-forecasting literature.
``smart_persistence``    Persistence in *clear-sky index* rather than raw irradiance:
                         carry forward the atmospheric attenuation, but recompute the
                         solar geometry. Much stronger than naive persistence and the
                         honest bar for any model that also gets geometry for free.
                         Follows the clear-sky-index framing of [P1, Sec. II-B2b].
``climatology``          Mean of the training data conditioned on hour-of-day and month.
``persistence_ensemble`` PeEn: the distribution of recent same-hour observations, giving a
                         probabilistic reference. Named as an industry benchmark in
                         [P3, Sec. III-B3].

Baselines for the energy target
-------------------------------
``build_for_energy`` supplies persistence and climatology in kWh and stops there. There is
deliberately **no physics-chain baseline** for ``pv_kwh``: the labels for that target are
produced by running the PV chain over observed weather, so a baseline that ran the same
chain over the same weather would reproduce them almost exactly and report near-zero
error. It would be a tautology presented as a reference, and every real model would look
hopeless beside it.

Horizon accounting
------------------
Every baseline is horizon-aware. A "day-ahead" persistence forecast for 14:00 tomorrow
uses the observation from 14:00 today — never 13:00 tomorrow, which would not be available
when the forecast is issued. Getting this wrong makes baselines look far stronger than
they are and understates the model's skill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class BaselineForecast:
    """A baseline's predictions plus the metadata needed to interpret them."""

    name: str
    display_name: str
    predictions: np.ndarray
    description: str
    horizon_hours: int
    coverage: float                       # fraction of test points it could predict
    quantiles: dict[float, np.ndarray] | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "horizon_hours": self.horizon_hours,
            "coverage": round(self.coverage, 4),
            "source": self.source,
            "is_probabilistic": self.quantiles is not None,
        }


def persistence(
    y: pd.Series, test_index: pd.DatetimeIndex, *, horizon_hours: int = 24
) -> BaselineForecast:
    """Carry the observation from ``horizon_hours`` earlier forward.

    Where that lagged observation does not exist the prediction is NaN rather than being
    back-filled; the coverage figure reports how often that happened.
    """
    lookup = y.copy()
    lookup.index = pd.DatetimeIndex(lookup.index)
    offset = pd.Timedelta(hours=horizon_hours)

    source_times = test_index - offset
    values = lookup.reindex(source_times).to_numpy(dtype=np.float64)
    coverage = float(np.isfinite(values).mean()) if values.size else 0.0

    return BaselineForecast(
        name="persistence",
        display_name="Persistence",
        predictions=values,
        description=(
            f"The observation from {horizon_hours} hours earlier at the same clock time. "
            f"The standard naive reference in solar forecasting."
        ),
        horizon_hours=horizon_hours,
        coverage=coverage,
        source="hayajneh2024",
    )


def smart_persistence(
    clear_sky_index_series: pd.Series,
    clear_sky_ghi: pd.Series,
    test_index: pd.DatetimeIndex,
    *,
    horizon_hours: int = 24,
) -> BaselineForecast:
    """Persist the clear-sky index, then reapply the *current* solar geometry.

    This is the baseline that matters, and it must be formed in physical units. Naive
    persistence carries yesterday's raw irradiance forward, so it inherits yesterday's
    solar geometry and fails whenever day length or solar noon has shifted. Smart
    persistence carries forward only the atmospheric attenuation and recomputes geometry
    for the target hour.

    Note the two are algebraically identical when expressed in clear-sky-index space:
    both reduce to kt(t-h). The distinction exists only in W/m^2, which is why every
    baseline in this module predicts GHI regardless of what the model was trained on.
    """
    lookup = clear_sky_index_series.copy()
    lookup.index = pd.DatetimeIndex(lookup.index)
    kt_lagged = lookup.reindex(test_index - pd.Timedelta(hours=horizon_hours)).to_numpy(dtype=np.float64)
    cs_now = clear_sky_ghi.reindex(test_index).to_numpy(dtype=np.float64)
    values = kt_lagged * cs_now

    coverage = float(np.isfinite(values).mean()) if values.size else 0.0
    return BaselineForecast(
        name="smart_persistence",
        display_name="Smart Persistence (clear-sky index)",
        predictions=values,
        description=(
            f"The clear-sky index from {horizon_hours} hours earlier, recombined with the "
            f"clear-sky irradiance computed for the target hour. Persists the weather, not "
            f"the sun's position."
        ),
        horizon_hours=horizon_hours,
        coverage=coverage,
        source="hobbs2026",
    )


def climatology(
    y_train: pd.Series, test_index: pd.DatetimeIndex, *, horizon_hours: int = 24
) -> BaselineForecast:
    """Training-set mean conditioned on hour-of-day and calendar month.

    Uses only training data, so it carries no leakage. Represents "what usually happens
    at this time of year at this hour" and is surprisingly hard to beat in stable climates.
    """
    frame = pd.DataFrame(
        {
            "value": y_train.to_numpy(dtype=np.float64),
            "hour": pd.DatetimeIndex(y_train.index).hour,
            "month": pd.DatetimeIndex(y_train.index).month,
        }
    )
    grouped = frame.groupby(["month", "hour"])["value"].mean()
    hour_only = frame.groupby("hour")["value"].mean()
    global_mean = float(frame["value"].mean()) if len(frame) else np.nan

    values = np.empty(len(test_index), dtype=np.float64)
    for i, ts in enumerate(test_index):
        key = (ts.month, ts.hour)
        if key in grouped.index:
            values[i] = grouped.loc[key]
        elif ts.hour in hour_only.index:
            values[i] = hour_only.loc[ts.hour]
        else:
            values[i] = global_mean

    return BaselineForecast(
        name="climatology",
        display_name="Climatology (month × hour mean)",
        predictions=values,
        description=(
            "Mean of the training observations for the same calendar month and hour of "
            "day. Carries no information about the specific day being forecast."
        ),
        horizon_hours=horizon_hours,
        coverage=float(np.isfinite(values).mean()) if values.size else 0.0,
        source="lyu2024",
    )


def persistence_ensemble(
    y: pd.Series,
    test_index: pd.DatetimeIndex,
    *,
    horizon_hours: int = 24,
    n_members: int = 20,
    quantile_levels: tuple[float, ...] = (0.025, 0.1, 0.5, 0.9, 0.975),
) -> BaselineForecast:
    """Persistence Ensemble (PeEn) — the probabilistic reference from [P3].

    For each target hour, gather the observations at the same clock hour over the previous
    ``n_members`` days and treat their empirical distribution as the forecast. Lyu &
    Eftekharnejad note its weakness plainly — forecasts for different days end up nearly
    identical, and the resulting intervals are too wide to guide decisions — which is
    exactly why it is the right thing to measure a real interval against.
    """
    lookup = y.copy()
    lookup.index = pd.DatetimeIndex(lookup.index)

    members = np.full((len(test_index), n_members), np.nan, dtype=np.float64)
    for k in range(n_members):
        lag = pd.Timedelta(hours=horizon_hours + 24 * k)
        members[:, k] = lookup.reindex(test_index - lag).to_numpy(dtype=np.float64)

    with np.errstate(invalid="ignore"):
        median = np.nanmedian(members, axis=1)
        quantiles = {
            q: np.nanquantile(members, q, axis=1) for q in quantile_levels
        }

    valid_counts = np.isfinite(members).sum(axis=1)
    coverage = float((valid_counts >= 3).mean()) if len(test_index) else 0.0

    return BaselineForecast(
        name="persistence_ensemble",
        display_name="Persistence Ensemble (PeEn)",
        predictions=median,
        description=(
            f"Empirical distribution of the observations at the same clock hour over the "
            f"previous {n_members} days. A probabilistic reference for interval quality."
        ),
        horizon_hours=horizon_hours,
        coverage=coverage,
        quantiles=quantiles,
        source="lyu2024",
    )


def build_for_energy(
    *,
    energy_full: pd.Series,
    energy_train: pd.Series,
    test_index: pd.DatetimeIndex,
    horizon_hours: int = 24,
) -> list[BaselineForecast]:
    """Baselines for the ``pv_kwh`` target, all predicting AC energy in kWh.

    Persistence and climatology only, and both are the same functions used for irradiance —
    they carry a past observation or a conditional mean forward and care nothing about what
    the series measures. Smart persistence is absent because it is defined through the
    clear-sky index, which has no counterpart in energy space; the persistence ensemble is
    absent because it exists to benchmark interval width against [P3]'s reference, which is
    an irradiance comparison. See the module docstring for why no physics-chain baseline
    appears here.
    """
    return [
        persistence(energy_full, test_index, horizon_hours=horizon_hours),
        climatology(energy_train, test_index, horizon_hours=horizon_hours),
    ]


def build_all(
    *,
    ghi_full: pd.Series,
    ghi_train: pd.Series,
    test_index: pd.DatetimeIndex,
    clear_sky_ghi: pd.Series,
    clear_sky_index_series: pd.Series,
    horizon_hours: int = 24,
) -> list[BaselineForecast]:
    """Construct every baseline, all predicting GHI in W/m^2.

    Baselines are deliberately formed in physical units rather than in whatever space the
    model happened to be trained in. That keeps them directly comparable to the model's
    reported figures, and it is the only space in which naive and smart persistence are
    actually different functions.
    """
    return [
        persistence(ghi_full, test_index, horizon_hours=horizon_hours),
        smart_persistence(
            clear_sky_index_series, clear_sky_ghi, test_index, horizon_hours=horizon_hours
        ),
        climatology(ghi_train, test_index, horizon_hours=horizon_hours),
        persistence_ensemble(ghi_full, test_index, horizon_hours=horizon_hours),
    ]
