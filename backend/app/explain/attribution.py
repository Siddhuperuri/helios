"""Explainability.

Answers three different questions, which are often conflated:

1. *Which inputs does this model rely on overall?* — permutation importance.
2. *How does the prediction change as one input varies?* — partial dependence.
3. *Why did the model produce this particular number?* — local sensitivity.

Permutation importance is computed on **held-out data**, never on the training set.
Importance measured on training data reports what the model memorised; importance measured
on held-out data reports what actually carries predictive signal. Mabodi & Hammujuddy [P2]
and Vijay Babu et al. [P5] both use permutation importance, and [P5] found solar-geometry
features dominant — a result this platform can reproduce or contradict on the user's own
data rather than assert.

A caveat that is reported, not hidden
-------------------------------------
Permutation importance is unreliable when features are correlated, and several of ours are
strongly correlated by construction: zenith angle, cos(zenith), air mass, clear-sky GHI and
extraterrestrial irradiance are all deterministic functions of the same solar position.
Permuting one while its collinear partners stay intact lets the model recover the lost
information, so each individually looks less important than the group really is. The
platform therefore reports **grouped importance** alongside per-feature importance, and
states the correlation caveat next to the chart.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.inspection import partial_dependence, permutation_importance

# Features that are deterministic functions of the same underlying quantity. Permuting any
# one of them in isolation understates the group's true contribution.
FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "Solar geometry": (
        "cos_zenith",
        "solar_zenith_deg",
        "solar_elevation_deg",
        "cos_aoi",
        "aoi_deg",
        "air_mass",
        "clear_sky_ghi_wm2",
        "extraterrestrial_horizontal_wm2",
    ),
    "Cloud & precipitation": ("cloud_cover_pct", "precipitation_mm"),
    "Temperature & moisture": ("temperature_c", "relative_humidity_pct", "dew_point_c"),
    "Wind": ("wind_speed_ms", "wind_dir_sin", "wind_dir_cos"),
    "Pressure": ("surface_pressure_hpa",),
    "Time of year / day": ("hour_sin", "hour_cos", "doy_sin", "doy_cos"),
}


@dataclass
class ImportanceResult:
    per_feature: list[dict[str, Any]]
    grouped: list[dict[str, Any]]
    method: str
    n_repeats: int
    evaluated_on: str
    scoring: str
    caveat: str
    baseline_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "per_feature": self.per_feature,
            "grouped": self.grouped,
            "method": self.method,
            "n_repeats": self.n_repeats,
            "evaluated_on": self.evaluated_on,
            "scoring": self.scoring,
            "caveat": self.caveat,
            "baseline_score": self.baseline_score,
        }


def permutation_feature_importance(
    estimator: Any,
    X_test: pd.DataFrame,
    y_test: np.ndarray,
    *,
    n_repeats: int = 10,
    seed: int = 0,
    scoring: str = "neg_root_mean_squared_error",
) -> ImportanceResult:
    """Permutation importance on held-out data, with grouped importance alongside."""
    feature_names = list(X_test.columns)
    X = X_test.to_numpy(dtype=np.float64)

    result = permutation_importance(
        estimator,
        X,
        y_test,
        n_repeats=n_repeats,
        random_state=seed,
        scoring=scoring,
        n_jobs=-1,
    )

    baseline = float(estimator.score(X, y_test)) if hasattr(estimator, "score") else float("nan")

    total = float(np.sum(np.clip(result.importances_mean, 0.0, None))) or 1.0
    per_feature = [
        {
            "feature": name,
            "importance_mean": float(result.importances_mean[i]),
            "importance_std": float(result.importances_std[i]),
            "importance_share": float(max(result.importances_mean[i], 0.0) / total),
            "rank": 0,
        }
        for i, name in enumerate(feature_names)
    ]
    per_feature.sort(key=lambda d: d["importance_mean"], reverse=True)
    for rank, item in enumerate(per_feature, start=1):
        item["rank"] = rank

    grouped = _grouped_importance(estimator, X_test, y_test, seed=seed, scoring=scoring)

    return ImportanceResult(
        per_feature=per_feature,
        grouped=grouped,
        method="permutation importance",
        n_repeats=n_repeats,
        evaluated_on="held-out test set",
        scoring=scoring,
        caveat=(
            "Several solar-geometry features are deterministic functions of one another. "
            "Permuting one in isolation lets the model recover the information from its "
            "correlated partners, so individual importances understate the group. Read the "
            "grouped figures for the size of each effect."
        ),
        baseline_score=baseline,
    )


def _grouped_importance(
    estimator: Any,
    X_test: pd.DataFrame,
    y_test: np.ndarray,
    *,
    seed: int = 0,
    scoring: str = "neg_root_mean_squared_error",
    n_repeats: int = 5,
) -> list[dict[str, Any]]:
    """Permute whole groups of collinear features together.

    This is the honest measurement when features are correlated: the entire group is
    destroyed at once, so the model cannot reconstruct the signal from a partner feature.
    """
    from sklearn.metrics import mean_squared_error

    rng = np.random.default_rng(seed)
    X = X_test.to_numpy(dtype=np.float64)
    columns = list(X_test.columns)

    base_pred = estimator.predict(X)
    base_rmse = float(np.sqrt(mean_squared_error(y_test, base_pred)))

    results: list[dict[str, Any]] = []
    for group_name, members in FEATURE_GROUPS.items():
        indices = [columns.index(m) for m in members if m in columns]
        if not indices:
            continue

        deltas = []
        for _ in range(n_repeats):
            X_perm = X.copy()
            order = rng.permutation(len(X_perm))
            for idx in indices:
                X_perm[:, idx] = X_perm[order, idx]
            perm_rmse = float(np.sqrt(mean_squared_error(y_test, estimator.predict(X_perm))))
            deltas.append(perm_rmse - base_rmse)

        results.append(
            {
                "group": group_name,
                "features": [m for m in members if m in columns],
                "rmse_increase_mean": float(np.mean(deltas)),
                "rmse_increase_std": float(np.std(deltas)),
                "relative_increase": float(np.mean(deltas) / base_rmse) if base_rmse > 0 else float("nan"),
            }
        )

    results.sort(key=lambda d: d["rmse_increase_mean"], reverse=True)
    total = sum(max(r["rmse_increase_mean"], 0.0) for r in results) or 1.0
    for r in results:
        r["share"] = float(max(r["rmse_increase_mean"], 0.0) / total)
    return results


def partial_dependence_curves(
    estimator: Any,
    X_train: pd.DataFrame,
    features: Sequence[str],
    *,
    grid_resolution: int = 30,
) -> list[dict[str, Any]]:
    """Partial dependence: average prediction as one feature is swept across its range.

    Interpretation caveat, reported with the chart: partial dependence marginalises over
    the other features while holding the target feature at a fixed value, which can
    construct physically impossible combinations — 40 °C at midnight, for example. The
    curve is a description of model behaviour, not of the physical world.
    """
    columns = list(X_train.columns)
    curves: list[dict[str, Any]] = []

    for feature in features:
        if feature not in columns:
            continue
        try:
            pd_result = partial_dependence(
                estimator,
                X_train.to_numpy(dtype=np.float64),
                features=[columns.index(feature)],
                grid_resolution=grid_resolution,
                kind="average",
            )
        except Exception as exc:  # noqa: BLE001 - one failed curve must not abort the rest
            curves.append({"feature": feature, "error": str(exc)})
            continue

        grid = np.asarray(pd_result["grid_values"][0], dtype=float)
        values = np.asarray(pd_result["average"][0], dtype=float)
        curves.append(
            {
                "feature": feature,
                "grid": grid.tolist(),
                "values": values.tolist(),
                "range": [float(values.min()), float(values.max())],
                "effect_size": float(values.max() - values.min()),
            }
        )

    curves.sort(key=lambda c: c.get("effect_size", 0.0), reverse=True)
    return curves


def local_sensitivity(
    estimator: Any,
    x_row: pd.Series,
    X_reference: pd.DataFrame,
    *,
    perturbation_std: float = 1.0,
) -> dict[str, Any]:
    """Explain one prediction by perturbing each input in turn.

    For a single forecast this answers "what is driving *this* number?" without requiring
    an additive-attribution library. Each feature is moved by ±1 standard deviation of its
    training distribution and the change in prediction is recorded, giving a local
    derivative in interpretable units.

    This is a **sensitivity**, not a Shapley value: contributions do not sum to the
    prediction, and the method makes no additivity claim. Stated plainly in the UI.
    """
    columns = list(X_reference.columns)
    base_x = x_row[columns].to_numpy(dtype=np.float64).reshape(1, -1)
    base_pred = float(estimator.predict(base_x)[0])

    stds = X_reference.std(numeric_only=True)
    means = X_reference.mean(numeric_only=True)

    contributions: list[dict[str, Any]] = []
    for i, name in enumerate(columns):
        sigma = float(stds.get(name, 0.0))
        if sigma <= 0:
            continue

        up = base_x.copy()
        up[0, i] += perturbation_std * sigma
        down = base_x.copy()
        down[0, i] -= perturbation_std * sigma

        pred_up = float(estimator.predict(up)[0])
        pred_down = float(estimator.predict(down)[0])

        value = float(base_x[0, i])
        mean = float(means.get(name, 0.0))
        contributions.append(
            {
                "feature": name,
                "value": value,
                "training_mean": mean,
                "z_score": (value - mean) / sigma,
                "effect_up": pred_up - base_pred,
                "effect_down": pred_down - base_pred,
                "sensitivity": (abs(pred_up - base_pred) + abs(pred_down - base_pred)) / 2.0,
                "direction": "increases" if pred_up > base_pred else "decreases",
            }
        )

    contributions.sort(key=lambda c: c["sensitivity"], reverse=True)
    return {
        "base_prediction": base_pred,
        "contributions": contributions,
        "method": "local one-at-a-time sensitivity (±1 training standard deviation)",
        "caveat": (
            "These are sensitivities, not additive attributions. They do not sum to the "
            "prediction and no additivity is claimed. Because features are perturbed one "
            "at a time, interactions between them are not captured."
        ),
    }


def narrate(
    importance: ImportanceResult,
    by_regime: dict[str, Any],
    *,
    target_label: str = "irradiance",
) -> list[str]:
    """Plain-language findings derived from the computed numbers.

    Every sentence is generated from a measured value. Nothing here is a template
    assertion about how solar forecasting generally works.
    """
    lines: list[str] = []

    if importance.grouped:
        top = importance.grouped[0]
        lines.append(
            f"{top['group']} is the strongest driver: removing it raises prediction error "
            f"by {top['rmse_increase_mean']:.4f} in target units "
            f"({top['relative_increase'] * 100:.0f}% of the model's current error), "
            f"accounting for {top['share'] * 100:.0f}% of the total measured effect."
        )
        if len(importance.grouped) > 1:
            second = importance.grouped[1]
            lines.append(
                f"{second['group']} is next, contributing {second['share'] * 100:.0f}%."
            )
        negligible = [g["group"] for g in importance.grouped if g["share"] < 0.02]
        if negligible:
            lines.append(
                f"{', '.join(negligible)} contributed under 2% each on this dataset — the "
                f"model is barely using them here."
            )

    if by_regime:
        entries = [(k, v) for k, v in by_regime.items() if "rmse" in v]
        if len(entries) >= 2:
            best = min(entries, key=lambda kv: kv[1]["rmse"])
            worst = max(entries, key=lambda kv: kv[1]["rmse"])
            ratio = worst[1]["rmse"] / best[1]["rmse"] if best[1]["rmse"] > 0 else float("nan")
            lines.append(
                f"Accuracy depends strongly on conditions: error under '{worst[0]}' skies "
                f"({worst[1]['rmse']:.1f} W/m²) is {ratio:.1f}× that under '{best[0]}' skies "
                f"({best[1]['rmse']:.1f} W/m²). Aggregate accuracy alone would hide this."
            )

    return lines
