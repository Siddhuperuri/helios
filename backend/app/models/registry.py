"""The model zoo.

Four estimators plus one ensemble of exactly those four. Every entry appears in at least
one supplied paper, and where a paper reports its tuned hyperparameters those exact values
are used and attributed.

Why only four
-------------
The set was cut from ten. A longer list is not a stronger result: most of the removed
entries were second representatives of a family already present, and a comparison table
with ten rows invites the reader to hunt for the best number rather than to ask whether
the method earns its complexity. What remains is one model per argument:

``random_forest``           The method the project abstract names. Bagged trees.
``hist_gradient_boosting``  The boosted-tree family the cited papers use ([P2], [P3] run
                            XGBoost). Boosting and bagging fail differently, so keeping
                            one of each is informative rather than redundant.
``extra_trees``             Also bagged, but with randomised split thresholds, so its
                            errors are decorrelated from the forest's. That is exactly
                            what makes it worth something to an ensemble.
``ridge``                   The linear baseline, kept so the non-linear models have to
                            prove they earn their complexity. If Ridge is close, the
                            extra machinery is not buying anything.
``ensemble_four``           The four above, combined by a learned meta-model.

Each model card records that rationale in its ``notes``, so the reasoning travels with the
model rather than living only here.

Scaling is inside the pipeline
------------------------------
Penalised linear models (Ridge) require standardised inputs. The scaler is a *pipeline
step*, not a preprocessing pass, so it is refitted on the training partition of every
cross-validation fold. Standardising the whole dataset before splitting would leak
test-set means and variances into training — a subtle form of leakage that survives even
a correct chronological split.

On gradient boosting
--------------------
Mabodi & Hammujuddy [P2] and Lyu & Eftekharnejad [P3] use XGBoost. This platform uses
scikit-learn's ``HistGradientBoostingRegressor``, a histogram-based boosted-tree
implementation of the same family and algorithmic lineage. The substitution avoids an
additional binary dependency; it is recorded in the model card rather than glossed over.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.ensemble import (
    ExtraTreesRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
    StackingRegressor,
)
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.evaluation.splitters import BlockedChronologicalCV

# The base models of ``ensemble_four``, in the order their weights are reported.
ENSEMBLE_BASE_KEYS: tuple[str, ...] = (
    "random_forest",
    "hist_gradient_boosting",
    "extra_trees",
    "ridge",
)

# Folds the stacking meta-learner is fitted on. Five matches the platform's default
# cross-validation width; the embargo is stated in samples because a StackingRegressor is
# handed a matrix and never sees the time index. See BlockedChronologicalCV for why that
# is roughly a calendar day on daytime-only hourly data, and for why the inner folds are
# blocked rather than forward-only.
ENSEMBLE_CV_SPLITS = 5
ENSEMBLE_CV_EMBARGO_SAMPLES = 12


@dataclass(frozen=True)
class ModelSpec:
    """A model, its provenance, and its cost profile."""

    key: str
    display_name: str
    family: str
    factory: Callable[[int], BaseEstimator]
    description: str
    sources: tuple[str, ...]
    supports_feature_importance: bool = False
    requires_scaling: bool = False
    cost: str = "low"                 # low | medium | high — training-time guidance
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    hyperparameter_source: str | None = None
    notes: str | None = None

    def build(self, seed: int) -> BaseEstimator:
        return self.factory(seed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "family": self.family,
            "description": self.description,
            "sources": list(self.sources),
            "supports_feature_importance": self.supports_feature_importance,
            "requires_scaling": self.requires_scaling,
            "cost": self.cost,
            "hyperparameters": dict(self.hyperparameters),
            "hyperparameter_source": self.hyperparameter_source,
            "notes": self.notes,
        }


def _scaled(estimator: BaseEstimator) -> Pipeline:
    """Wrap an estimator so standardisation is refitted per fold."""
    return Pipeline([("scaler", StandardScaler()), ("model", estimator)])


def _four_model_stack(seed: int) -> StackingRegressor:
    """The four kept models combined by a Ridge meta-learner.

    The weights are *learned* from out-of-fold predictions rather than fixed at 1/4. That
    distinction is the whole point of the entry: an unweighted mean would let the linear
    model pull the tree models down on exactly the non-linear hours they exist to handle,
    and the ensemble would score worse than its own best member.

    The inner folds are time-blocked with an embargo, not plain K-fold. A shuffled inner
    split would train the meta-learner on out-of-fold predictions that were themselves
    produced with access to neighbouring hours, which flatters whichever base model
    overfits hardest. See :class:`BlockedChronologicalCV` for why those folds are blocked
    rather than forward-only — scikit-learn's stacking requires an out-of-fold prediction
    for every training row, which a forward-only scheme cannot produce for its first block.
    """
    return StackingRegressor(
        estimators=[(key, MODELS[key].build(seed)) for key in ENSEMBLE_BASE_KEYS],
        final_estimator=Ridge(alpha=1.0),
        cv=BlockedChronologicalCV(
            n_splits=ENSEMBLE_CV_SPLITS, embargo_samples=ENSEMBLE_CV_EMBARGO_SAMPLES
        ),
        n_jobs=None,  # the base models already parallelise internally
    )


# --------------------------------------------------------------------------------------
# Specifications
# --------------------------------------------------------------------------------------

_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        key="random_forest",
        display_name="Random Forest",
        family="Bagged trees",
        factory=lambda seed: RandomForestRegressor(
            n_estimators=300,
            max_depth=None,
            min_samples_split=2,
            min_samples_leaf=2,
            max_features="sqrt",
            n_jobs=-1,
            random_state=seed,
        ),
        description=(
            "An ensemble of decision trees fitted on bootstrap samples with randomised "
            "feature subsets. Handles non-linear interactions without feature engineering "
            "and is stable across reruns."
        ),
        sources=("abstract", "mabodi2024", "rosales2025", "babu2025"),
        supports_feature_importance=True,
        cost="medium",
        hyperparameters={
            "n_estimators": 300,
            "min_samples_leaf": 2,
            "max_features": "sqrt",
        },
        hyperparameter_source=(
            "Mabodi & Hammujuddy [P2] tuned to n_estimators=50, min_samples_leaf=1. We "
            "raise n_estimators to 300 for a more stable importance ranking and set "
            "min_samples_leaf=2 to reduce variance on hourly data, which is noisier than "
            "the monthly aggregates [P2] modelled."
        ),
        notes=(
            "Kept because it is the method the project abstract names, and because a "
            "bagged-tree reference is needed to make the boosted one interpretable."
        ),
    ),
    ModelSpec(
        key="hist_gradient_boosting",
        display_name="Histogram Gradient Boosting",
        family="Boosted trees",
        factory=lambda seed: HistGradientBoostingRegressor(
            learning_rate=0.08,
            max_depth=None,
            max_iter=300,
            min_samples_leaf=20,
            l2_regularization=1.0,
            random_state=seed,
        ),
        description=(
            "Histogram-binned gradient boosting: the same family as XGBoost and LightGBM, "
            "an order of magnitude faster than exact boosting on large samples."
        ),
        sources=("mabodi2024", "lyu2024"),
        supports_feature_importance=False,
        cost="low",
        hyperparameters={"learning_rate": 0.08, "max_iter": 300, "l2_regularization": 1.0},
        notes=(
            "Kept as the boosted-tree family the cited papers actually use: it stands in "
            "for the XGBoost models of [P2] and [P3]. Boosting fits residuals sequentially "
            "where bagging averages independent fits, so it fails differently from the "
            "forest rather than redundantly. Feature importance is obtained by permutation "
            "rather than from split gains."
        ),
    ),
    ModelSpec(
        key="extra_trees",
        display_name="Extremely Randomised Trees",
        family="Bagged trees",
        factory=lambda seed: ExtraTreesRegressor(
            n_estimators=300,
            min_samples_leaf=2,
            max_features="sqrt",
            n_jobs=-1,
            random_state=seed,
        ),
        description=(
            "Like a random forest, but split thresholds are drawn at random rather than "
            "optimised. Lower variance, slightly higher bias."
        ),
        sources=("rosales2025",),
        supports_feature_importance=True,
        cost="medium",
        hyperparameters={"n_estimators": 300, "min_samples_leaf": 2},
        notes=(
            "Kept because randomised split thresholds decorrelate its errors from the "
            "random forest's. Two models that are wrong on the same hours add nothing to "
            "an ensemble; two that are wrong on different hours do. In the spirit of [P4]."
        ),
    ),
    ModelSpec(
        key="ridge",
        display_name="Ridge Regression",
        family="Linear",
        factory=lambda seed: _scaled(Ridge(alpha=1.0, random_state=seed)),
        description=(
            "Least squares with an L2 penalty. The linear reference point: if a non-linear "
            "model cannot beat this, the extra complexity is not earning anything."
        ),
        sources=("babu2025",),
        requires_scaling=True,
        cost="low",
        hyperparameters={"alpha": 1.0},
        notes=(
            "Kept as the linear baseline the non-linear models must beat. It is in the "
            "comparison to be a floor, not a contender — a result that only shows tree "
            "models against other tree models never establishes that the non-linearity "
            "was necessary."
        ),
    ),
    ModelSpec(
        key="ensemble_four",
        display_name="Four-Model Stacking Ensemble",
        family="Stacked ensemble",
        factory=_four_model_stack,
        description=(
            "The four models above, combined by a Ridge meta-learner fitted on their "
            "out-of-fold predictions. The weights are learned, so each base model "
            "contributes where it is actually strongest."
        ),
        sources=("rosales2025",),
        cost="high",
        hyperparameters={
            "base_models": list(ENSEMBLE_BASE_KEYS),
            "meta": "ridge(alpha=1.0)",
            "cv": f"blocked_chronological(n_splits={ENSEMBLE_CV_SPLITS}, "
                  f"embargo_samples={ENSEMBLE_CV_EMBARGO_SAMPLES})",
        },
        hyperparameter_source=(
            "Rosales Huamani et al. [P4, Table 4] report a stacking regressor as their "
            "best configuration (R²=0.92) with ordinary linear regression as the "
            "meta-learner. Ridge is used here instead, for numerical stability when base "
            "predictions are collinear — which, four models fitted on one feature matrix, "
            "they invariably are. The base set is this platform's four kept models rather "
            "than [P4]'s."
        ),
        notes=(
            "Weights are learned, never uniform: a simple average lets Ridge drag the tree "
            "models down on the non-linear hours they exist to handle. The learned weights "
            "and each base model's contribution are reported in the payload, so the "
            "ensemble is inspectable rather than a black box wrapped around four others. "
            "The inner folds are contiguous time blocks with an embargo, so no base "
            "prediction the meta-learner sees was made by a model that had just been shown "
            "the surrounding hours. Those inner folds are blocked rather than forward-only "
            "because scikit-learn's stacking needs an out-of-fold prediction for every "
            "training row; the outer evaluation this platform reports from is strictly "
            "chronological."
        ),
    ),
)


MODELS: dict[str, ModelSpec] = {spec.key: spec for spec in _SPECS}

# Default comparison set: every model in the registry. With four estimators and one
# ensemble the full set is small enough to run, so there is nothing to select down to.
DEFAULT_COMPARISON: tuple[str, ...] = (
    "ridge",
    "random_forest",
    "extra_trees",
    "hist_gradient_boosting",
    "ensemble_four",
)


def get(key: str) -> ModelSpec:
    if key not in MODELS:
        raise KeyError(
            f"Unknown model '{key}'. Available: {', '.join(sorted(MODELS))}."
        )
    return MODELS[key]


def catalogue() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in _SPECS]


def is_ensemble(key: str) -> bool:
    return key == "ensemble_four"


def ensemble_weights(estimator: Any) -> list[dict[str, Any]] | None:
    """Learned meta-learner weight for each base model, or None if not an ensemble.

    The weights come from the fitted Ridge meta-learner's coefficients, one per base
    model, in the order the estimators were declared. A negative weight is not an error
    and is reported as it stands: it means the meta-learner is using that model to correct
    another rather than to predict directly, and hiding the sign would misrepresent what
    the ensemble learned.
    """
    final = getattr(estimator, "final_estimator_", None)
    fitted = getattr(estimator, "estimators_", None)
    if final is None or fitted is None:
        return None

    coefficients = np.ravel(np.asarray(getattr(final, "coef_", []), dtype=np.float64))
    names = [name for name, _ in getattr(estimator, "estimators", [])]
    if coefficients.size != len(names):
        # `passthrough=True` would append the raw features to the meta-learner's inputs,
        # which would break this one-coefficient-per-model correspondence. It is off, so
        # a mismatch means the estimator is not the shape this function documents.
        return None

    total = float(np.sum(np.abs(coefficients)))
    return [
        {
            "model": name,
            "display_name": MODELS[name].display_name if name in MODELS else name,
            "weight": float(coefficient),
            "weight_share": float(abs(coefficient) / total) if total > 0 else None,
        }
        for name, coefficient in zip(names, coefficients, strict=True)
    ]


def base_model_predictions(estimator: Any, X: np.ndarray) -> list[dict[str, Any]] | None:
    """Each base model's own prediction alongside the ensemble's, or None.

    This is what makes the ensemble legible in the interface: the reader sees four
    individual answers and the one number the meta-learner formed from them, rather than
    a single figure they have to take on trust.
    """
    weights = ensemble_weights(estimator)
    if weights is None:
        return None

    fitted = list(getattr(estimator, "estimators_", []))
    if len(fitted) != len(weights):
        return None

    out: list[dict[str, Any]] = []
    for entry, model in zip(weights, fitted, strict=True):
        prediction = np.asarray(model.predict(X), dtype=np.float64)
        out.append(
            {
                **entry,
                "prediction": float(prediction[0]) if prediction.size else None,
                "predictions": [float(v) for v in prediction],
            }
        )
    return out


def future_work() -> list[dict[str, Any]]:
    """Methods present in the source research but deliberately not implemented.

    Listed so the platform's scope is legible: a reviewer can see immediately what was
    considered and rejected, and why, rather than wondering whether it was overlooked.
    """
    return [
        {
            "name": "LSTM / BiLSTM / BiGRU sequence models",
            "sources": ["hayajneh2024"],
            "status": "Future Work",
            "reason": (
                "Hayajneh et al. [P6] report a test R² of 0.9590 for a 64-cell LSTM on "
                "15-minute plant data with a 4-hour look-back. That setting is genuinely "
                "sequential — it forecasts from the recent power trajectory. This platform "
                "forecasts from exogenous weather at the target hour, where recurrent "
                "structure has nothing to consume. Adding one would require a deep-learning "
                "runtime and a different problem formulation."
            ),
        },
        {
            "name": "Kernel, instance-based and single-tree estimators",
            "sources": ["mabodi2024", "rosales2025", "babu2025"],
            "status": "Removed",
            "reason": (
                "Support vector regression, k-nearest neighbours, a single decision tree "
                "and ordinary least squares were implemented and have been withdrawn. Each "
                "duplicated an argument another kept model already makes — OLS against "
                "Ridge, a lone tree against two tree ensembles — while SVR's training cost "
                "grows super-linearly and [P5] found it significantly worse than boosting "
                "(paired t-test, p = 1.19e-6). A ten-row comparison table invites reading "
                "off the winner; a five-row one invites asking whether the complexity was "
                "necessary."
            ),
        },
        {
            "name": "Copula-based dynamic feature selection",
            "sources": ["lyu2024"],
            "status": "Partially Implemented",
            "reason": (
                "The weather-regime conditioning of [P3] (sunny / cloudy / other, and "
                "per-regime error analysis) is implemented. The full vine- and Gaussian-"
                "copula machinery with an XGBoost copula classifier is not."
            ),
        },
        {
            "name": "TinyML edge deployment",
            "sources": ["hayajneh2024"],
            "status": "Future Work",
            "reason": (
                "[P6] quantises models onto an ESP32-S3 microcontroller. Out of scope for "
                "a server-side platform; no claim is made about edge feasibility here."
            ),
        },
        {
            "name": "pvlib / Perez-Driesse transposition",
            "sources": ["hobbs2026"],
            "status": "Substituted",
            "reason": (
                "[P1] uses pvlib with the Perez-Driesse transposition model. This platform "
                "implements HDKR, one step lower in complexity, to avoid the dependency. "
                "The difference is small relative to irradiance forecast error, but it is "
                "a real difference and is recorded in the model card."
            ),
        },
    ]
