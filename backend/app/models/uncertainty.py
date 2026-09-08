"""Prediction intervals.

A point forecast without an interval is an incomplete answer: it tells a grid operator
what to expect but nothing about how much to hedge. Lyu & Eftekharnejad [P3] make this
the centre of their contribution, and their critique of conventional probabilistic
methods is specific — the intervals are so wide they are "overly wide to be a credible
reference for power system planning". Width is therefore reported alongside coverage
everywhere in this platform; neither number means anything alone.

Two estimators are provided.

``quantile_gradient_boosting``
    Separate gradient-boosting models fitted with the pinball loss at each quantile
    level. This is genuine quantile regression: it estimates conditional quantiles
    directly and lets the interval width vary with the inputs, so overcast hours can
    carry wider intervals than clear ones. Costs one model fit per quantile.

``forest_spread``
    Empirical quantiles across the individual trees of an already-fitted forest. Free if
    a forest has been trained, but it measures *model* disagreement, not total predictive
    uncertainty, so it systematically under-covers. The platform says so rather than
    presenting the two as equivalent.

Terminology
-----------
These are **prediction intervals**, not confidence intervals: they describe where a future
observation is expected to fall, not where a parameter lies. The distinction is stated in
the UI because conflating them overstates what the model knows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.ensemble import (
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)


@dataclass
class IntervalForecast:
    """Quantile predictions plus the interval derived from them."""

    quantiles: dict[float, np.ndarray]
    method: str
    method_description: str
    nominal_coverage: float
    lower: np.ndarray = field(repr=False)
    upper: np.ndarray = field(repr=False)
    median: np.ndarray = field(repr=False)
    caveat: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "method_description": self.method_description,
            "nominal_coverage": self.nominal_coverage,
            "quantile_levels": sorted(self.quantiles),
            "caveat": self.caveat,
        }


def _enforce_monotonic(quantiles: dict[float, np.ndarray]) -> dict[float, np.ndarray]:
    """Repair quantile crossing.

    Independently fitted quantile models can cross — the 0.9 estimate falling below the
    0.5 — which is impossible for a real distribution. Sorting the estimates at each point
    restores monotonicity. This is a real limitation of fitting quantiles independently,
    so it is recorded rather than hidden.
    """
    levels = sorted(quantiles)
    stacked = np.vstack([quantiles[q] for q in levels])
    stacked = np.sort(stacked, axis=0)
    return {q: stacked[i] for i, q in enumerate(levels)}


def quantile_gradient_boosting(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_predict: np.ndarray,
    *,
    quantile_levels: tuple[float, ...] = (0.025, 0.1, 0.5, 0.9, 0.975),
    nominal_coverage: float = 0.8,
    seed: int = 0,
    n_estimators: int = 200,
    max_depth: int = 4,
    learning_rate: float = 0.06,
) -> IntervalForecast:
    """Fit one quantile-loss GBM per level and assemble an interval."""
    preds: dict[float, np.ndarray] = {}
    for tau in quantile_levels:
        model = GradientBoostingRegressor(
            loss="quantile",
            alpha=float(tau),
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=0.9,
            random_state=seed,
        )
        model.fit(X_train, y_train)
        preds[float(tau)] = model.predict(X_predict)

    preds = _enforce_monotonic(preds)
    lo_level = (1.0 - nominal_coverage) / 2.0
    hi_level = 1.0 - lo_level
    lower = preds[_nearest(preds, lo_level)]
    upper = preds[_nearest(preds, hi_level)]
    median = preds[_nearest(preds, 0.5)]

    return IntervalForecast(
        quantiles=preds,
        method="quantile_gradient_boosting",
        method_description=(
            "Independent gradient-boosting models fitted with the pinball (quantile) loss "
            "at each level. Interval width adapts to the input conditions."
        ),
        nominal_coverage=nominal_coverage,
        lower=lower,
        upper=upper,
        median=median,
        caveat=(
            "Quantile levels are fitted independently and can cross; estimates are sorted "
            "per observation to restore monotonicity."
        ),
    )


def forest_spread(
    forest: RandomForestRegressor,
    X_predict: np.ndarray,
    *,
    quantile_levels: tuple[float, ...] = (0.025, 0.1, 0.5, 0.9, 0.975),
    nominal_coverage: float = 0.8,
) -> IntervalForecast:
    """Empirical quantiles over the individual trees of a fitted forest."""
    if not hasattr(forest, "estimators_"):
        raise ValueError("forest_spread requires an already-fitted forest.")

    tree_preds = np.vstack([tree.predict(X_predict) for tree in forest.estimators_])
    preds = {float(q): np.quantile(tree_preds, q, axis=0) for q in quantile_levels}

    lo_level = (1.0 - nominal_coverage) / 2.0
    hi_level = 1.0 - lo_level
    return IntervalForecast(
        quantiles=preds,
        method="forest_spread",
        method_description=(
            "Spread of predictions across the individual trees of the fitted forest."
        ),
        nominal_coverage=nominal_coverage,
        lower=preds[_nearest(preds, lo_level)],
        upper=preds[_nearest(preds, hi_level)],
        median=preds[_nearest(preds, 0.5)],
        caveat=(
            "Measures disagreement between trees, which is model uncertainty only. It "
            "excludes irreducible observation noise and will under-cover — typically "
            "well below its nominal level. Use quantile regression for calibrated intervals."
        ),
    )


def _nearest(quantiles: dict[float, np.ndarray], target: float) -> float:
    return min(quantiles, key=lambda q: abs(q - target))


def _seasonal_calibration_split(
    n: int, *, calibration_fraction: float = 0.25, n_blocks: int = 16, embargo: int = 24
) -> tuple[np.ndarray, np.ndarray]:
    """Choose a calibration set that is seasonally representative but not adjacent.

    Split conformal prediction assumes calibration and test points are exchangeable. On a
    strongly seasonal series that assumption fails badly if calibration is simply the most
    recent contiguous block of training data: at Hyderabad that block is the monsoon
    (mean clear-sky index 0.63) while the test period is not (0.72), so a correction
    calibrated on one regime is applied to another and coverage falls short.

    Taking calibration points at random across the training window fixes the seasonal
    representativeness but introduces a different error: a calibration hour sitting
    directly beside a training hour shares its weather, so the model appears more accurate
    on calibration than it is, the conformity scores come out too small, and the interval
    is again too narrow.

    This splitter takes the middle path. The training window is cut into contiguous blocks,
    whole blocks are assigned to calibration at even intervals so every season is
    represented, and an embargo of ``embargo`` observations on each side of a calibration
    block is withheld from proper training so no calibration point neighbours a training
    point.

    Everything here stays strictly inside the training window; no test information is used.
    """
    n_blocks = max(4, min(n_blocks, n // 20))
    edges = np.linspace(0, n, n_blocks + 1).astype(int)
    blocks = [np.arange(edges[i], edges[i + 1]) for i in range(n_blocks)]

    n_cal_blocks = max(1, int(round(n_blocks * calibration_fraction)))
    # Evenly spaced block indices, offset so calibration is not all at one end.
    stride = n_blocks / n_cal_blocks
    cal_block_ids = sorted({int(min(n_blocks - 1, round(i * stride + stride / 2))) for i in range(n_cal_blocks)})

    cal_idx = np.concatenate([blocks[b] for b in cal_block_ids]) if cal_block_ids else np.array([], dtype=int)

    embargoed = set()
    for b in cal_block_ids:
        lo, hi = blocks[b][0], blocks[b][-1]
        embargoed.update(range(max(0, lo - embargo), min(n, hi + embargo + 1)))

    proper_idx = np.array([i for i in range(n) if i not in embargoed], dtype=int)
    return proper_idx, np.asarray(cal_idx, dtype=int)


def conformalized_quantile_regression(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_predict: np.ndarray,
    *,
    quantile_levels: tuple[float, ...] = (0.025, 0.1, 0.5, 0.9, 0.975),
    nominal_coverage: float = 0.8,
    seed: int = 0,
    calibration_fraction: float = 0.25,
    embargo: int = 24,
    n_estimators: int = 200,
    max_depth: int = 5,
    learning_rate: float = 0.08,
) -> IntervalForecast:
    """Conformalized Quantile Regression (Romano, Patterson & Candes, 2019).

    Plain quantile regression estimates conditional quantiles but offers no guarantee that
    they are *calibrated*: on our own data an uncalibrated 80 % interval covered only 66 %
    of observations, which would mislead anyone sizing a reserve margin against it.

    CQR fixes this with a held-out calibration step. The quantile models are fitted on a
    proper training subset; on a disjoint calibration subset the conformity score

        E_i = max(lower(x_i) - y_i,  y_i - upper(x_i))

    measures how far outside the interval each observation fell (negative when inside).
    The (1-alpha) empirical quantile of those scores, with a finite-sample correction, is
    added symmetrically to the interval. This yields *marginal* coverage of at least the
    nominal level under exchangeability, whatever the underlying model does.

    Two honest caveats, both surfaced in the UI:

    * The guarantee is marginal, not conditional. Coverage holds on average across all
      hours, not necessarily within every weather regime, which is why per-regime coverage
      is reported separately.
    * Exchangeability is violated by time series. The calibration split here is
      chronological, so the guarantee is approximate rather than exact. It is nonetheless
      dramatically better calibrated than the uncorrected interval.

    Status: **enhancement**, class D. No supplied paper uses CQR; it is introduced to fix
    a measured calibration failure in the method [P3] motivates.
    """
    n = len(X_train)
    if n < 40:
        raise ValueError(
            f"Conformal calibration needs at least 40 training observations; got {n}."
        )

    # Contiguous-tail calibration: the most recent block of the training window.
    #
    # A seasonally-stratified alternative was implemented and measured (see
    # _seasonal_calibration_split). It did not robustly improve coverage: at Hyderabad it
    # scored 0.700 / 0.725 / 0.706 / 0.790 as the embargo widened, and 0.767 vs 0.834 for
    # six vs eight blocks. That non-monotonicity is instability rather than signal, and
    # selecting the best-scoring configuration would be tuning on the test set. The simpler
    # design is therefore kept, with the residual shortfall measured and reported rather
    # than engineered away.
    n_cal = max(20, int(n * calibration_fraction))
    n_proper = n - n_cal
    proper_idx = np.arange(0, n_proper)
    cal_idx = np.arange(n_proper, n)
    if proper_idx.size < 20 or cal_idx.size < 20:
        raise ValueError("Training set too small to split for conformal calibration.")

    X_proper, y_proper = X_train[proper_idx], y_train[proper_idx]
    X_cal, y_cal = X_train[cal_idx], y_train[cal_idx]
    n_cal = int(cal_idx.size)

    lo_level = (1.0 - nominal_coverage) / 2.0
    hi_level = 1.0 - lo_level

    # HistGradientBoostingRegressor optimises the same pinball objective as the exact
    # implementation but bins features first, which measured ~3.4x faster here (10.9s ->
    # 3.2s per quantile at this sample size). Interval fitting is otherwise the dominant
    # cost of an analysis.
    fitted: dict[float, HistGradientBoostingRegressor] = {}
    for tau in sorted({*quantile_levels, lo_level, hi_level}):
        model = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=float(tau),
            max_iter=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            min_samples_leaf=20,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=seed,
        )
        model.fit(X_proper, y_proper)
        fitted[float(tau)] = model

    # Conformity scores on the calibration set.
    cal_lo = fitted[lo_level].predict(X_cal)
    cal_hi = fitted[hi_level].predict(X_cal)
    scores = np.maximum(cal_lo - y_cal, y_cal - cal_hi)

    # Finite-sample corrected quantile level.
    level = min(1.0, np.ceil((n_cal + 1) * nominal_coverage) / n_cal)
    correction = float(np.quantile(scores, level, method="higher"))

    preds = {tau: model.predict(X_predict) for tau, model in fitted.items()}
    preds = _enforce_monotonic(preds)

    lower = preds[_nearest(preds, lo_level)] - correction
    upper = preds[_nearest(preds, hi_level)] + correction
    median = preds[_nearest(preds, 0.5)]

    # Widen the outer quantile estimates by the same correction so that pinball loss and
    # CRPS are computed on the calibrated distribution rather than the raw one.
    calibrated = dict(preds)
    for tau in calibrated:
        if tau < 0.5:
            calibrated[tau] = calibrated[tau] - correction * (1.0 - 2.0 * tau)
        elif tau > 0.5:
            calibrated[tau] = calibrated[tau] + correction * (2.0 * tau - 1.0)
    calibrated = _enforce_monotonic(calibrated)
    calibrated[_nearest(calibrated, lo_level)] = lower
    calibrated[_nearest(calibrated, hi_level)] = upper

    return IntervalForecast(
        quantiles=calibrated,
        method="conformalized_quantile_regression",
        method_description=(
            f"Quantile gradient boosting calibrated by split conformal prediction on the "
            f"most recent {n_cal:,} training observations (correction {correction:+.4f})."
        ),
        nominal_coverage=nominal_coverage,
        lower=lower,
        upper=upper,
        median=median,
        caveat=(
            "Coverage is marginal, not conditional: the guarantee holds on average across "
            "all hours, not within each weather regime, so per-regime coverage is reported "
            "separately. Conformal prediction also assumes calibration and test points are "
            "exchangeable, which a seasonal series satisfies only approximately. Always read "
            "the reported PICP rather than assuming the nominal level was achieved."
        ),
    )


def decompose_uncertainty(
    interval: IntervalForecast,
    residual_std: float,
) -> dict[str, Any]:
    """Separate the sources of uncertainty, insofar as the method permits.

    Honest accounting: quantile regression gives *total* predictive uncertainty and does
    not decompose it. What can legitimately be said is how the fitted interval width
    compares with the width implied by homoscedastic residual noise alone — if the model's
    intervals are no wider than a constant-variance assumption, it has learned nothing
    about *when* it is uncertain, which is most of the value of a probabilistic forecast.
    """
    mean_width = float(np.mean(interval.upper - interval.lower))
    z = 1.2816 if abs(interval.nominal_coverage - 0.8) < 1e-6 else 1.96
    homoscedastic_width = 2.0 * z * residual_std
    width_variation = float(np.std(interval.upper - interval.lower))

    return {
        "mean_interval_width": mean_width,
        "homoscedastic_reference_width": homoscedastic_width,
        "width_ratio": (
            mean_width / homoscedastic_width if homoscedastic_width > 0 else float("nan")
        ),
        "width_std": width_variation,
        "adapts_to_conditions": bool(width_variation > 0.05 * mean_width),
        "interpretation": (
            "Interval width varies materially across conditions, so the model has learned "
            "when it is uncertain."
            if width_variation > 0.05 * mean_width
            else "Interval width is nearly constant, so this forecast conveys little "
            "condition-specific uncertainty beyond an average error bar."
        ),
        "sources_covered": (
            "Quantile regression estimates total predictive uncertainty: model error and "
            "irreducible observation noise combined. It cannot separate them, and no "
            "such separation is claimed here."
        ),
        "not_covered": (
            "Uncertainty in the input weather forecast itself is not represented. These "
            "intervals are conditional on the supplied weather being correct — a "
            "materially optimistic assumption at long horizons."
        ),
    }
