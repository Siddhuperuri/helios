"""Data-leakage audit and the random-vs-chronological experiment.

Two capabilities live here.

**The audit** inspects the configured pipeline for the four leakage routes that matter in
time-series forecasting and reports, for each, what the platform does about it.

**The experiment** is the one that changes minds. It fits the identical model twice on the
identical data, differing only in how the data was split, and reports both numbers side by
side. Random splitting is standard practice in several of the supplied papers; Vijay Babu
et al. [P5, Sec. V-D] name time-based splits as future work. Rather than assert that random
splitting inflates results, this measures the inflation on whatever dataset the user has
loaded.

The result is an argument a reviewer can check, not a claim they have to accept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.evaluation import metrics as metric_mod
from app.evaluation import splitters
from app.features.pipeline import LEAKAGE_EXCLUDED, FeatureSet
from app.models import registry


@dataclass
class LeakageCheck:
    key: str
    title: str
    question: str
    status: str            # "protected" | "mitigated" | "at_risk" | "not_applicable"
    finding: str
    mechanism: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "question": self.question,
            "status": self.status,
            "finding": self.finding,
            "mechanism": self.mechanism,
        }


def audit(fs: FeatureSet, model_key: str, *, gap_hours: int = 24) -> list[dict[str, Any]]:
    """Audit the configured pipeline against known leakage routes."""
    spec = registry.get(model_key)
    checks: list[LeakageCheck] = []

    # 1. Target leakage --------------------------------------------------------------
    leaked = [f for f in fs.feature_names if f in LEAKAGE_EXCLUDED]
    checks.append(
        LeakageCheck(
            key="target_leakage",
            title="Target leakage",
            question="Does any feature contain the answer?",
            status="at_risk" if leaked else "protected",
            finding=(
                f"Features derived from the target are present: {', '.join(leaked)}."
                if leaked
                else (
                    "No feature is a component or transform of the target. Direct normal "
                    "and diffuse irradiance are excluded from the predictor set because "
                    "GHI is their sum; they are retained as diagnostics only. Every "
                    "intermediate of the PV conversion chain — plane-of-array irradiance, "
                    "cell temperature, DC and AC power — is excluded on the same grounds, "
                    "since each is a monotone transform of the energy label."
                    if fs.target_name == "pv_kwh"
                    else (
                        "No feature is a component or transform of the target. Direct "
                        "normal and diffuse irradiance are excluded from the predictor set "
                        "because GHI is their sum; they are retained as diagnostics only."
                    )
                )
            ),
            mechanism=(
                "A deny-list is enforced at feature-build time and raises rather than "
                "silently dropping, so a leaking feature cannot be requested by accident."
            ),
        )
    )

    # 2. Temporal / future information ------------------------------------------------
    uses_lags = bool(fs.provenance.get("target_lags_used", False))
    checks.append(
        LeakageCheck(
            key="future_information",
            title="Future information",
            question="Could the model see data unavailable at forecast time?",
            status="at_risk" if uses_lags else "protected",
            finding=(
                "Lagged target values are in use; at a day-ahead horizon these would not "
                "exist when the forecast is issued."
                if uses_lags
                else (
                    "No lagged target values are used. Every predictor is a weather or "
                    "geometry variable available for the target hour from a numerical "
                    "weather prediction, which is the information a real day-ahead "
                    "forecast actually has."
                )
            ),
            mechanism=(
                "The feature builder constructs no autoregressive terms. Persistence "
                "baselines do use past observations, and are held to the same horizon "
                "accounting so the comparison stays fair."
            ),
        )
    )

    # 3. Preprocessing leakage --------------------------------------------------------
    checks.append(
        LeakageCheck(
            key="preprocessing_leakage",
            title="Preprocessing leakage",
            question="Were any statistics computed over the whole dataset before splitting?",
            status="protected",
            finding=(
                "Standardisation is a pipeline step inside the estimator, so the scaler is "
                "refitted on the training partition of every fold."
                if spec.requires_scaling
                else "This estimator needs no scaling, so no fitted preprocessing exists."
            ),
            mechanism=(
                "Scalers are wrapped in sklearn Pipelines rather than applied as a "
                "preparation pass. No imputation is performed at all: incomplete rows are "
                "dropped, so no fill value can carry information across the split."
            ),
        )
    )

    # 4. Temporal contamination across the split boundary -----------------------------
    checks.append(
        LeakageCheck(
            key="temporal_contamination",
            title="Boundary contamination",
            question="Are train and test observations adjacent enough to share weather?",
            status="mitigated" if gap_hours > 0 else "at_risk",
            finding=(
                f"An embargo of {gap_hours} hours is removed from the end of each training "
                f"partition, so the nearest training and validation observations are at "
                f"least {gap_hours} hours apart."
                if gap_hours > 0
                else "No embargo gap is applied; the last training hour directly abuts the "
                "first validation hour."
            ),
            mechanism=(
                "Both the chronological hold-out and every rolling-origin fold apply the "
                "embargo. It reduces but does not eliminate contamination, since synoptic "
                "weather systems persist for several days."
            ),
        )
    )

    # 5. Evaluation-set composition ---------------------------------------------------
    daytime_only = bool(fs.provenance.get("daytime_only", False))
    checks.append(
        LeakageCheck(
            key="trivial_observations",
            title="Trivial observations in the evaluation set",
            question="Do easy night-time zeros inflate goodness-of-fit?",
            status="protected" if daytime_only else "at_risk",
            finding=(
                f"Night hours are excluded using a solar-zenith threshold of "
                f"{fs.provenance.get('day_mask_threshold_deg')}°, so every evaluated hour "
                f"is one where a forecast is actually needed."
                if daytime_only
                else "Night hours are included. Predicting zero at night is trivial and "
                "inflates R² because day/night contrast dominates the total sum of squares."
            ),
            mechanism="Threshold follows Lyu & Eftekharnejad [P3, Sec. II-A].",
        )
    )

    return [c.to_dict() for c in checks]


def compare_split_strategies(
    fs: FeatureSet,
    *,
    model_key: str = "random_forest",
    seed: int = 0,
    test_fraction: float = 0.2,
    gap_hours: int = 24,
) -> dict[str, Any]:
    """Fit the same model under different split strategies and compare.

    Everything is held constant except the split. Any difference in reported accuracy is
    therefore attributable to the split alone.
    """
    from app.models.trainer import ENERGY_TARGET, _to_physical

    spec = registry.get(model_key)
    X = fs.X.to_numpy(dtype=np.float64)
    y = fs.y.to_numpy(dtype=np.float64)
    index = fs.frame.index
    clear_sky = fs.frame["clear_sky_ghi_wm2"].to_numpy(dtype=np.float64)

    # Scored in the unit the model is reported in, using the same bounding rule the trainer
    # applies. The experiment is about the split and nothing else, so the scoring path has
    # to be the ordinary one rather than a second implementation that could drift from it.
    is_energy = fs.target_name == ENERGY_TARGET
    unit = "kWh" if is_energy else "W/m²"
    observed = fs.frame[fs.target_name if is_energy else "ghi_wm2"].to_numpy(dtype=np.float64)
    ac_capacity_kw = (
        float((fs.provenance.get("pv_system") or {}).get("ac_capacity_kw", 0.0))
        if is_energy
        else None
    )

    def _fit_score(train_idx: np.ndarray, test_idx: np.ndarray) -> dict[str, Any]:
        est = spec.build(seed)
        est.fit(X[train_idx], y[train_idx])
        pred = est.predict(X[test_idx])
        bounded, _ = _to_physical(
            pred, clear_sky[test_idx], fs.target_name, ac_capacity_kw=ac_capacity_kw
        )
        m = metric_mod.evaluate(observed[test_idx], bounded, target_unit=unit)
        return {
            "rmse": m["rmse"],
            "mae": m["mae"],
            "r2": m["r2"],
            "rrmse": m.get("rrmse"),
            "n_train": int(train_idx.size),
            "n_test": int(test_idx.size),
        }

    strategies: dict[str, Any] = {}

    tr, te = splitters.chronological_split(index, test_fraction=test_fraction, gap_hours=gap_hours)
    strategies["chronological"] = {
        **_fit_score(tr, te),
        **splitters.describe_strategy("chronological"),
    }

    tr, te = splitters.blocked_random_split(index, test_fraction=test_fraction, seed=seed)
    strategies["blocked_random"] = {
        **_fit_score(tr, te),
        **splitters.describe_strategy("blocked_random"),
    }

    tr, te = splitters.random_split(index, test_fraction=test_fraction, seed=seed)
    strategies["random"] = {
        **_fit_score(tr, te),
        **splitters.describe_strategy("random"),
    }

    honest = strategies["chronological"]["rmse"]
    optimistic = strategies["random"]["rmse"]
    inflation = (honest - optimistic) / honest * 100.0 if honest > 0 else float("nan")

    r2_honest = strategies["chronological"]["r2"]
    r2_optimistic = strategies["random"]["r2"]

    return {
        "strategies": strategies,
        "model": model_key,
        "model_display_name": spec.display_name,
        "target": fs.target_name,
        "unit": unit,
        "comparison": {
            "chronological_rmse": honest,
            "random_rmse": optimistic,
            "rmse_understatement_pct": inflation,
            "chronological_r2": r2_honest,
            "random_r2": r2_optimistic,
            "r2_overstatement": r2_optimistic - r2_honest,
        },
        "conclusion": _conclusion(inflation, r2_optimistic - r2_honest),
        "method_note": (
            "The same estimator, the same hyperparameters, the same random seed and the "
            "same dataset are used in every row. Only the assignment of observations to "
            "train and test differs, so any difference in the reported figures is caused "
            "by the split alone."
        ),
        "why_it_matters": (
            "Random splitting places observations from the same afternoon on both sides of "
            "the boundary. Hourly irradiance is strongly autocorrelated, so the model is "
            "scored on conditions it has effectively already seen. The resulting figure "
            "describes interpolation between known hours, not forecasting of unknown ones."
        ),
        "provenance": (
            "Mabodi & Hammujuddy [P2, Sec. III-B] use a random train/test split. Vijay Babu "
            "et al. [P5, Sec. V-D] also use random sampling and explicitly identify "
            "time-based splits as future work. This experiment implements that comparison."
        ),
    }


def _conclusion(rmse_understatement_pct: float, r2_overstatement: float) -> str:
    if not np.isfinite(rmse_understatement_pct):
        return "The comparison could not be completed on this dataset."

    if rmse_understatement_pct < 2.0:
        return (
            f"On this dataset the two strategies agree closely (random splitting "
            f"understates RMSE by only {rmse_understatement_pct:.1f}%). That is itself "
            f"informative: with purely exogenous weather features and no autoregressive "
            f"terms, there is little temporal structure left for a random split to exploit."
        )
    if rmse_understatement_pct < 15.0:
        return (
            f"Random splitting understates RMSE by {rmse_understatement_pct:.1f}% and "
            f"overstates R² by {r2_overstatement:+.3f}. A moderate but real optimism: "
            f"published figures obtained this way are not directly comparable to "
            f"forward-in-time evaluation."
        )
    return (
        f"Random splitting understates RMSE by {rmse_understatement_pct:.1f}% and overstates "
        f"R² by {r2_overstatement:+.3f}. Substantial optimism — accuracy reported this way "
        f"would not be attainable in deployment."
    )
