"""Forecast evaluation metrics.

Every metric returns its formula and its interpretation alongside its value, because a
number like "MAPE = 32 %" is not interpretable without knowing which denominator was used
and how zeros were handled.

Two honesty notes that are surfaced in the UI rather than buried:

1. **NSE and R-squared are the same quantity.** Nash-Sutcliffe Efficiency is
   ``1 - SSE/SST``, which is identical to the coefficient of determination as
   conventionally computed for regression. Rosales Huamani et al. [P4] report both in the
   same table, which reads as two independent confirmations but is one number twice. This
   module computes it once and labels the alias explicitly.

2. **MAPE is unusable for irradiance.** The denominator approaches zero near sunrise and
   sunset, so a 5 W/m^2 error against a 10 W/m^2 observation contributes 50 % while being
   physically negligible. It is computed for comparability with the literature, but it is
   returned with an explicit guard count and a warning, and it is never the headline.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    name: str
    formula: str
    unit_kind: str          # "target", "percent", "dimensionless"
    lower_is_better: bool
    interpretation: str
    caveat: str | None = None


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "mae": MetricDefinition(
        key="mae",
        name="Mean Absolute Error",
        formula="MAE = (1/n) Σ |y − ŷ|",
        unit_kind="target",
        lower_is_better=True,
        interpretation=(
            "Average error magnitude in the target's own units. Robust to outliers and "
            "the easiest metric to communicate."
        ),
    ),
    "rmse": MetricDefinition(
        key="rmse",
        name="Root Mean Squared Error",
        formula="RMSE = √[(1/n) Σ (y − ŷ)²]",
        unit_kind="target",
        lower_is_better=True,
        interpretation=(
            "Error magnitude with large errors penalised quadratically. Always ≥ MAE; "
            "a wide RMSE−MAE gap indicates a few large misses rather than uniform error."
        ),
    ),
    "mbe": MetricDefinition(
        key="mbe",
        name="Mean Bias Error",
        formula="MBE = (1/n) Σ (ŷ − y)",
        unit_kind="target",
        lower_is_better=False,
        interpretation=(
            "Systematic over- or under-prediction. Positive means the model over-forecasts. "
            "Distinct from accuracy: a model can have near-zero bias and large RMSE."
        ),
    ),
    "r2": MetricDefinition(
        key="r2",
        name="Coefficient of Determination (R²)",
        formula="R² = 1 − SSE/SST",
        unit_kind="dimensionless",
        lower_is_better=False,
        interpretation=(
            "Fraction of variance in the observations explained by the model. Identical "
            "to Nash-Sutcliffe Efficiency."
        ),
        caveat=(
            "Depends on the variance of the evaluation set. Including night hours inflates "
            "it substantially because day/night contrast dominates the total sum of squares."
        ),
    ),
    "nse": MetricDefinition(
        key="nse",
        name="Nash-Sutcliffe Efficiency",
        formula="NSE = 1 − SSE/SST",
        unit_kind="dimensionless",
        lower_is_better=False,
        interpretation="Mathematically identical to R²; reported for comparability with [P4].",
        caveat="This is not independent evidence from R² — it is the same quantity.",
    ),
    "rrmse": MetricDefinition(
        key="rrmse",
        name="Relative RMSE",
        formula="rRMSE = RMSE / mean(y) × 100 %",
        unit_kind="percent",
        lower_is_better=True,
        interpretation=(
            "RMSE normalised by the mean observation, enabling comparison across sites "
            "and seasons. This is the definition used by Mabodi & Hammujuddy [P2, eq. 7]."
        ),
    ),
    "rmae": MetricDefinition(
        key="rmae",
        name="Relative MAE",
        formula="rMAE = MAE / mean(y) × 100 %",
        unit_kind="percent",
        lower_is_better=True,
        interpretation="MAE normalised by the mean observation.",
        caveat=(
            "[P2] labels a different quantity 'rMAE' in eq. 9 — mean(|y−ŷ|/ŷ) — which is "
            "a percentage error, not MAE over the mean. Both are reported here separately."
        ),
    ),
    "mape": MetricDefinition(
        key="mape",
        name="Mean Absolute Percentage Error",
        formula="MAPE = (1/n) Σ |y − ŷ| / |y| × 100 %",
        unit_kind="percent",
        lower_is_better=True,
        interpretation="Average relative error against each observation.",
        caveat=(
            "Unstable for targets near zero. Observations below the guard threshold are "
            "excluded and counted; treat with caution for irradiance."
        ),
    ),
    "smape": MetricDefinition(
        key="smape",
        name="Symmetric MAPE",
        formula="sMAPE = (1/n) Σ 2|y − ŷ| / (|y| + |ŷ|) × 100 %",
        unit_kind="percent",
        lower_is_better=True,
        interpretation="Bounded at 200 %, and far better behaved near zero than MAPE.",
    ),
    "skill_score": MetricDefinition(
        key="skill_score",
        name="Forecast Skill Score",
        formula="SS = 1 − RMSE_model / RMSE_reference",
        unit_kind="dimensionless",
        lower_is_better=False,
        interpretation=(
            "Improvement over a reference forecast. 0 means no better than the reference, "
            "1 means perfect, negative means worse than the reference. The single most "
            "important number for judging whether a model is worth its complexity."
        ),
    ),
    "pinball": MetricDefinition(
        key="pinball",
        name="Pinball Loss",
        formula="L_τ = (y−ŷ)τ if y ≥ ŷ, else (ŷ−y)(1−τ)",
        unit_kind="target",
        lower_is_better=True,
        interpretation=(
            "Quantile forecast accuracy, averaged over quantile levels. The metric used "
            "by Lyu & Eftekharnejad [P3, eq. 28]."
        ),
    ),
    "picp": MetricDefinition(
        key="picp",
        name="Prediction Interval Coverage Probability",
        formula="PICP = (1/n) Σ 1[L ≤ y ≤ U]",
        unit_kind="dimensionless",
        lower_is_better=False,
        interpretation=(
            "Fraction of observations that fall inside the interval. Should match the "
            "nominal level: an 80 % interval covering 62 % is overconfident."
        ),
    ),
    "pinaw": MetricDefinition(
        key="pinaw",
        name="Prediction Interval Normalised Average Width",
        formula="PINAW = mean(U − L) / range(y)",
        unit_kind="dimensionless",
        lower_is_better=True,
        interpretation=(
            "Interval sharpness. Must be read together with PICP — an interval spanning "
            "the whole range achieves perfect coverage and is useless."
        ),
    ),
    "crps": MetricDefinition(
        key="crps",
        name="Continuous Ranked Probability Score",
        formula="CRPS ≈ 2 × mean pinball loss over quantiles",
        unit_kind="target",
        lower_is_better=True,
        interpretation=(
            "Single score for the whole predictive distribution, reducing to MAE for a "
            "deterministic forecast. Approximated from the quantile set, per [P3, eq. 27]."
        ),
        caveat="Computed empirically from discrete quantiles, not from a closed-form CDF.",
    ),
}


def _clean_pair(y_true: Iterable[float], y_pred: Iterable[float]) -> tuple[np.ndarray, np.ndarray]:
    yt = np.asarray(y_true, dtype=np.float64).ravel()
    yp = np.asarray(y_pred, dtype=np.float64).ravel()
    if yt.shape != yp.shape:
        raise ValueError(f"Shape mismatch: observations {yt.shape} vs predictions {yp.shape}")
    mask = np.isfinite(yt) & np.isfinite(yp)
    return yt[mask], yp[mask]


def mae(y_true, y_pred) -> float:
    yt, yp = _clean_pair(y_true, y_pred)
    return float(np.mean(np.abs(yt - yp))) if yt.size else float("nan")


def rmse(y_true, y_pred) -> float:
    yt, yp = _clean_pair(y_true, y_pred)
    return float(np.sqrt(np.mean((yt - yp) ** 2))) if yt.size else float("nan")


def mbe(y_true, y_pred) -> float:
    yt, yp = _clean_pair(y_true, y_pred)
    return float(np.mean(yp - yt)) if yt.size else float("nan")


def r2(y_true, y_pred) -> float:
    yt, yp = _clean_pair(y_true, y_pred)
    if yt.size < 2:
        return float("nan")
    sst = float(np.sum((yt - np.mean(yt)) ** 2))
    if sst <= 0.0:
        # Constant observations: R² is undefined, not 1.0.
        return float("nan")
    return float(1.0 - np.sum((yt - yp) ** 2) / sst)


def mape(y_true, y_pred, *, guard: float = 1e-6) -> tuple[float, int]:
    """MAPE with an explicit small-denominator guard. Returns (value, n_excluded)."""
    yt, yp = _clean_pair(y_true, y_pred)
    if yt.size == 0:
        return float("nan"), 0
    usable = np.abs(yt) > guard
    excluded = int((~usable).sum())
    if not usable.any():
        return float("nan"), excluded
    return float(np.mean(np.abs((yt[usable] - yp[usable]) / yt[usable])) * 100.0), excluded


def smape(y_true, y_pred) -> float:
    yt, yp = _clean_pair(y_true, y_pred)
    if yt.size == 0:
        return float("nan")
    denom = np.abs(yt) + np.abs(yp)
    usable = denom > 1e-12
    if not usable.any():
        return float("nan")
    return float(np.mean(2.0 * np.abs(yt[usable] - yp[usable]) / denom[usable]) * 100.0)


def skill_score(y_true, y_pred, y_reference) -> float:
    """Fractional RMSE improvement over a reference forecast."""
    model_rmse = rmse(y_true, y_pred)
    ref_rmse = rmse(y_true, y_reference)
    if not np.isfinite(ref_rmse) or ref_rmse <= 0:
        return float("nan")
    return float(1.0 - model_rmse / ref_rmse)


def pinball_loss(y_true, quantile_predictions: dict[float, np.ndarray]) -> dict[str, float]:
    """Average pinball loss per quantile level and overall. [P3, eq. 28]."""
    out: dict[str, float] = {}
    per_level = []
    for tau, preds in sorted(quantile_predictions.items()):
        yt, yp = _clean_pair(y_true, preds)
        if yt.size == 0:
            continue
        diff = yt - yp
        loss = float(np.mean(np.where(diff >= 0, diff * tau, -diff * (1.0 - tau))))
        out[f"pinball_q{tau:g}"] = loss
        per_level.append(loss)
    out["pinball_mean"] = float(np.mean(per_level)) if per_level else float("nan")
    return out


def interval_metrics(
    y_true, lower, upper, *, nominal_coverage: float
) -> dict[str, float]:
    """Coverage and sharpness of a prediction interval."""
    yt = np.asarray(y_true, dtype=np.float64).ravel()
    lo = np.asarray(lower, dtype=np.float64).ravel()
    hi = np.asarray(upper, dtype=np.float64).ravel()
    mask = np.isfinite(yt) & np.isfinite(lo) & np.isfinite(hi)
    yt, lo, hi = yt[mask], lo[mask], hi[mask]
    if yt.size == 0:
        return {"picp": float("nan"), "pinaw": float("nan"), "coverage_error": float("nan")}

    inside = (yt >= lo) & (yt <= hi)
    picp = float(np.mean(inside))
    spread = float(np.max(yt) - np.min(yt))
    pinaw = float(np.mean(hi - lo) / spread) if spread > 0 else float("nan")
    return {
        "picp": picp,
        "pinaw": pinaw,
        "nominal_coverage": nominal_coverage,
        "coverage_error": picp - nominal_coverage,
        "mean_width": float(np.mean(hi - lo)),
    }


def crps_from_quantiles(y_true, quantile_predictions: dict[float, np.ndarray]) -> float:
    """Empirical CRPS approximated from a discrete quantile set.

    For an equally spaced quantile grid, CRPS ≈ 2 × mean pinball loss. With few quantile
    levels this is an approximation, which is why the metric definition says so.
    """
    losses = pinball_loss(y_true, quantile_predictions)
    mean_pinball = losses.get("pinball_mean", float("nan"))
    return float(2.0 * mean_pinball) if np.isfinite(mean_pinball) else float("nan")


def evaluate(
    y_true,
    y_pred,
    *,
    y_reference: np.ndarray | None = None,
    target_unit: str = "",
    mape_guard: float = 1e-6,
) -> dict[str, Any]:
    """Full deterministic metric set with definitions attached."""
    yt, yp = _clean_pair(y_true, y_pred)
    n = int(yt.size)
    if n == 0:
        return {"n": 0, "error": "No finite observation/prediction pairs to evaluate."}

    mean_obs = float(np.mean(yt))
    mape_value, mape_excluded = mape(yt, yp, guard=mape_guard)
    r2_value = r2(yt, yp)

    values: dict[str, Any] = {
        "n": n,
        "mae": mae(yt, yp),
        "rmse": rmse(yt, yp),
        "mbe": mbe(yt, yp),
        "r2": r2_value,
        "nse": r2_value,  # identical by construction; see module docstring
        "mape": mape_value,
        "smape": smape(yt, yp),
        "observed_mean": mean_obs,
        "observed_std": float(np.std(yt)),
        "observed_min": float(np.min(yt)),
        "observed_max": float(np.max(yt)),
    }

    if abs(mean_obs) > 1e-9:
        values["rrmse"] = values["rmse"] / mean_obs * 100.0
        values["rmae"] = values["mae"] / mean_obs * 100.0
    else:
        values["rrmse"] = float("nan")
        values["rmae"] = float("nan")

    if y_reference is not None:
        values["skill_score"] = skill_score(yt, yp, y_reference)
        values["reference_rmse"] = rmse(yt, y_reference)

    values["notes"] = []
    if mape_excluded:
        values["notes"].append(
            f"MAPE excludes {mape_excluded:,} observations at or near zero "
            f"({mape_excluded / n * 100:.1f}% of the evaluation set) where the relative "
            f"error is undefined."
        )
    if values["rmse"] > 0 and values["mae"] > 0 and values["rmse"] / values["mae"] > 1.8:
        values["notes"].append(
            "RMSE is more than 1.8× MAE, indicating error is concentrated in a minority "
            "of large misses rather than spread evenly."
        )
    values["target_unit"] = target_unit
    return values


def evaluate_by_group(
    y_true, y_pred, groups, *, target_unit: str = ""
) -> dict[str, dict[str, Any]]:
    """Metrics computed separately within each group (regime, hour, month, season)."""
    yt = np.asarray(y_true, dtype=np.float64).ravel()
    yp = np.asarray(y_pred, dtype=np.float64).ravel()
    g = np.asarray(groups).ravel()
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(set(g.tolist()), key=str):
        mask = g == key
        if mask.sum() < 3:
            continue
        out[str(key)] = evaluate(yt[mask], yp[mask], target_unit=target_unit)
    return out


def significant_figures(value: float, reference_error: float) -> str:
    """Format a value to a precision its own error can support.

    Reporting 16.79 kWh when the validation RMSE is 3 kWh implies four significant figures
    of accuracy that the model does not have.

    The rule is the standard scientific convention: round the value to the same decimal
    place as its uncertainty. An energy figure of 54.1637 with an error of 3 is reported as
    "54", because "54.16 +/- 3" claims precision the error term contradicts.
    """
    if not np.isfinite(value):
        return "—"
    if not np.isfinite(reference_error) or reference_error <= 0:
        return f"{value:.2f}"

    magnitude = int(np.floor(np.log10(abs(reference_error))))
    decimals = int(np.clip(-magnitude, 0, 3))
    return f"{value:.{decimals}f}"
