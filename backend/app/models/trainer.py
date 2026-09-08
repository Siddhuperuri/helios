"""Training and evaluation orchestration.

This module holds the sequence that produces a defensible result: split chronologically,
fit only on the past, predict the future, express the result in units somebody can check,
and score against baselines that had access to the same information.

Two conversions matter and are handled explicitly.

**Target space vs reported space.** When the modelling target is the clear-sky index, the
model's native errors are in dimensionless kt units, which nobody can interpret. Such a
result is therefore reported twice: in the modelling target's own units, and in W/m² after
multiplying back by clear-sky irradiance. The physical figure is the headline, because that
is the one a reviewer can sanity-check against known irradiance magnitudes.

The ``pv_kwh`` target is the case where that machinery must *not* fire. Its native unit is
already kilowatt-hours, the unit the answer is wanted in, so there is nothing to convert
back to and no W/m² twin is manufactured for it. Both metric blocks carry the same units,
and the second differs from the first only in that physical bounds have been applied.

**Physical constraints applied after prediction.** A statistical model has no notion that
irradiance cannot be negative or exceed the clear-sky ceiling by more than a small margin,
nor that an inverter cannot deliver more than its AC rating. Those constraints are imposed
after inference, and the number of clipped predictions is reported — a model needing
frequent clipping is telling you something.
"""

from __future__ import annotations

import hashlib
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import sklearn

from app.config import get_settings
from app.evaluation import baselines as baseline_mod
from app.evaluation import metrics as metric_mod
from app.evaluation import splitters
from app.features.pipeline import HOURS_PER_INTERVAL, TARGET_UNITS, FeatureSet
from app.models import registry, uncertainty

# Predictions above this multiple of clear-sky irradiance are not physical for hourly means.
CLEAR_SKY_CEILING_FACTOR = 1.25

# The target whose native unit is already the physical one.
ENERGY_TARGET = "pv_kwh"


@dataclass
class FoldResult:
    fold: int
    metrics: dict[str, Any]
    n_train: int
    n_test: int
    test_start: str | None
    test_end: str | None


@dataclass
class TrainingResult:
    """Everything produced by one training run."""

    model_key: str
    model_display_name: str
    estimator: Any = field(repr=False)
    feature_names: list[str] = field(default_factory=list)
    target_name: str = "clear_sky_index"

    test_metrics: dict[str, Any] = field(default_factory=dict)
    test_metrics_physical: dict[str, Any] = field(default_factory=dict)
    train_metrics: dict[str, Any] = field(default_factory=dict)

    cv_folds: list[FoldResult] = field(default_factory=list)
    cv_summary: dict[str, Any] = field(default_factory=dict)

    baseline_results: list[dict[str, Any]] = field(default_factory=list)
    skill_scores: dict[str, float] = field(default_factory=dict)

    by_regime: dict[str, Any] = field(default_factory=dict)
    by_hour: dict[str, Any] = field(default_factory=dict)
    by_month: dict[str, Any] = field(default_factory=dict)

    interval: uncertainty.IntervalForecast | None = field(default=None, repr=False)
    interval_metrics: dict[str, Any] = field(default_factory=dict)
    uncertainty_decomposition: dict[str, Any] = field(default_factory=dict)

    predictions: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "model": self.model_key,
            "model_display_name": self.model_display_name,
            "target": self.target_name,
            "test_metrics": self.test_metrics,
            "test_metrics_physical": self.test_metrics_physical,
            "train_metrics": self.train_metrics,
            "cv_summary": self.cv_summary,
            "cv_folds": [
                {
                    "fold": f.fold,
                    "metrics": f.metrics,
                    "n_train": f.n_train,
                    "n_test": f.n_test,
                    "test_start": f.test_start,
                    "test_end": f.test_end,
                }
                for f in self.cv_folds
            ],
            "baselines": self.baseline_results,
            "skill_scores": self.skill_scores,
            "by_regime": self.by_regime,
            "by_hour": self.by_hour,
            "by_month": self.by_month,
            "interval": self.interval.to_dict() if self.interval else None,
            "interval_metrics": self.interval_metrics,
            "uncertainty_decomposition": self.uncertainty_decomposition,
            "manifest": self.manifest,
            "warnings": self.warnings,
            "timings": self.timings,
        }


def _dataset_fingerprint(fs: FeatureSet) -> str:
    """Stable hash of the exact data used, for reproducibility."""
    hasher = hashlib.sha256()
    hasher.update(str(fs.frame.index.min()).encode())
    hasher.update(str(fs.frame.index.max()).encode())
    hasher.update(str(len(fs.frame)).encode())
    hasher.update(",".join(sorted(fs.feature_names)).encode())
    hasher.update(fs.target_name.encode())
    values = np.ascontiguousarray(fs.frame[fs.feature_names].to_numpy(dtype=np.float64))
    hasher.update(np.round(values, 6).tobytes())
    hasher.update(np.round(fs.y.to_numpy(dtype=np.float64), 6).tobytes())
    return hasher.hexdigest()[:16]


def _to_physical(
    predictions: np.ndarray,
    clear_sky: np.ndarray,
    target: str,
    *,
    ac_capacity_kw: float | None = None,
) -> tuple[np.ndarray, int]:
    """Express model output in its reported unit and apply physical bounds.

    For the irradiance targets that means W/m², bounded below by zero and above by a small
    multiple of the clear-sky ceiling. For ``pv_kwh`` the model already predicts the
    reported quantity, so nothing is converted; the bounds become the ones that constrain
    an array — no negative energy, and nothing above what the inverter can deliver in an
    hour.

    Returns (values, n_clipped).
    """
    if target == "clear_sky_index":
        values = predictions * clear_sky
    else:
        values = predictions.copy()

    if target == ENERGY_TARGET:
        if ac_capacity_kw is None:
            raise ValueError(
                "Bounding an energy prediction needs the declared inverter AC capacity, "
                "which was not supplied."
            )
        ceiling = np.full_like(values, float(ac_capacity_kw) * HOURS_PER_INTERVAL)
    else:
        ceiling = clear_sky * CLEAR_SKY_CEILING_FACTOR

    below = values < 0.0
    above = values > ceiling
    n_clipped = int(np.sum(below | above))

    values = np.clip(values, 0.0, ceiling)
    return values, n_clipped


def train_and_evaluate(
    fs: FeatureSet,
    *,
    model_key: str = "random_forest",
    test_fraction: float | None = None,
    cv_splits: int | None = None,
    gap_hours: int | None = None,
    seed: int | None = None,
    horizon_hours: int = 24,
    compute_intervals: bool = True,
    nominal_coverage: float = 0.8,
    run_cv: bool = True,
) -> TrainingResult:
    """Fit one model and evaluate it thoroughly against baselines."""
    settings = get_settings()
    seed = settings.modelling.random_seed if seed is None else seed
    test_fraction = settings.modelling.test_fraction if test_fraction is None else test_fraction
    cv_splits = settings.modelling.cv_splits if cv_splits is None else cv_splits
    gap_hours = settings.modelling.cv_gap_hours if gap_hours is None else gap_hours

    spec = registry.get(model_key)
    warnings: list[str] = []
    timings: dict[str, float] = {}

    X = fs.X.to_numpy(dtype=np.float64)
    y = fs.y.to_numpy(dtype=np.float64)
    index = fs.frame.index
    clear_sky_all = fs.frame["clear_sky_ghi_wm2"].to_numpy(dtype=np.float64)
    ghi_all = fs.frame["ghi_wm2"].to_numpy(dtype=np.float64)

    # What "the reported number" means for this run. For the irradiance targets it is GHI
    # in W/m^2 and the model output has to be converted into it; for pv_kwh it is the
    # target itself, and the only thing applied afterwards is the physical bound.
    is_energy = fs.target_name == ENERGY_TARGET
    reported_unit = TARGET_UNITS[ENERGY_TARGET] if is_energy else "W/m²"

    ac_capacity_kw: float | None = None
    if is_energy:
        declared = fs.provenance.get("pv_system") or {}
        capacity = declared.get("ac_capacity_kw")
        if not isinstance(capacity, (int, float)) or capacity <= 0:
            raise ValueError(
                "Training on the pv_kwh target requires the feature set to declare the PV "
                "system it was built for, and this one does not. Rebuild the features with "
                "build_features(..., target='pv_kwh', system=...)."
            )
        ac_capacity_kw = float(capacity)
        observed_reported = fs.frame[ENERGY_TARGET].to_numpy(dtype=np.float64)
    else:
        observed_reported = ghi_all

    def to_reported(values: np.ndarray, positions: np.ndarray) -> tuple[np.ndarray, int]:
        """Bound a block of predictions, in the unit this run reports in."""
        return _to_physical(
            values,
            clear_sky_all[positions],
            fs.target_name,
            ac_capacity_kw=ac_capacity_kw,
        )

    # ---------------------------------------------------------------- split
    train_idx, test_idx = splitters.chronological_split(
        index, test_fraction=test_fraction, gap_hours=gap_hours
    )

    t0 = time.perf_counter()
    estimator = spec.build(seed)
    estimator.fit(X[train_idx], y[train_idx])
    timings["fit_seconds"] = round(time.perf_counter() - t0, 3)

    t0 = time.perf_counter()
    pred_test = estimator.predict(X[test_idx])
    pred_train = estimator.predict(X[train_idx])
    timings["predict_seconds"] = round(time.perf_counter() - t0, 3)

    # ------------------------------------------------- metrics in target space
    target_unit = TARGET_UNITS.get(fs.target_name, "W/m²")
    test_metrics = metric_mod.evaluate(y[test_idx], pred_test, target_unit=target_unit)
    train_metrics = metric_mod.evaluate(y[train_idx], pred_train, target_unit=target_unit)

    if np.isfinite(train_metrics.get("rmse", np.nan)) and train_metrics["rmse"] > 0:
        ratio = test_metrics["rmse"] / train_metrics["rmse"]
        if ratio > 2.0:
            warnings.append(
                f"Test RMSE is {ratio:.1f}× the training RMSE, which indicates the model "
                f"has fitted training-set detail that does not generalise."
            )

    # ------------------------------------------------ metrics in physical space
    pred_test_bounded, n_clipped = to_reported(pred_test, test_idx)
    regimes = fs.frame["weather_regime"].to_numpy()[test_idx]
    observed_test = observed_reported[test_idx]
    test_metrics_physical = metric_mod.evaluate(
        observed_test, pred_test_bounded, target_unit=reported_unit
    )
    test_metrics_physical["unit"] = reported_unit
    test_metrics_physical["n_clipped_to_physical_bounds"] = n_clipped
    if n_clipped:
        frac = n_clipped / max(len(test_idx), 1)
        test_metrics_physical["clipped_fraction"] = round(frac, 4)
        bound = (
            f"[0, {ac_capacity_kw:.2f} kWh] — the inverter's AC rating over one hour"
            if is_energy
            else f"[0, {CLEAR_SKY_CEILING_FACTOR}× clear-sky]"
        )
        if frac > 0.02:
            warnings.append(
                f"{n_clipped:,} predictions ({frac * 100:.1f}%) fell outside physical "
                f"bounds and were clipped to {bound}."
            )

    # ------------------------------------------------------------- baselines
    ghi_series = pd.Series(ghi_all, index=index)
    kt_series = (
        fs.frame["clear_sky_index"]
        if "clear_sky_index" in fs.frame.columns
        else pd.Series(np.full(len(index), np.nan), index=index)
    )
    cs_series = pd.Series(clear_sky_all, index=index)

    # Baselines are formed and scored in the unit the model is reported in, never in the
    # modelling target's space. Two reasons: the figures stay directly comparable to the
    # model's headline metric, and naive vs smart persistence are the same function in
    # clear-sky index space, so the comparison would be vacuous there.
    if is_energy:
        # Persistence and climatology only. A physics-chain baseline is deliberately absent:
        # the pv_kwh labels are produced *by* that chain, so a baseline running the same
        # chain over the same weather would score near-zero error by construction. It would
        # be a tautology dressed as a reference, and it would make every model look useless
        # against it.
        energy_series = pd.Series(observed_reported, index=index)
        baseline_forecasts = baseline_mod.build_for_energy(
            energy_full=energy_series,
            energy_train=energy_series.iloc[train_idx],
            test_index=index[test_idx],
            horizon_hours=horizon_hours,
        )
    else:
        baseline_forecasts = baseline_mod.build_all(
            ghi_full=ghi_series,
            ghi_train=ghi_series.iloc[train_idx],
            test_index=index[test_idx],
            clear_sky_ghi=cs_series,
            clear_sky_index_series=kt_series,
            horizon_hours=horizon_hours,
        )

    baseline_results: list[dict[str, Any]] = []
    skill_scores: dict[str, float] = {}
    ghi_test_obs = observed_test
    for bf in baseline_forecasts:
        finite = np.isfinite(bf.predictions)
        if finite.sum() < 10:
            baseline_results.append(
                {
                    **bf.to_dict(),
                    "metrics": None,
                    "note": (
                        f"Insufficient history to evaluate: only {int(finite.sum())} of "
                        f"{len(bf.predictions)} test points could be predicted at a "
                        f"{horizon_hours}-hour horizon."
                    ),
                }
            )
            continue

        b_metrics = metric_mod.evaluate(
            ghi_test_obs[finite], bf.predictions[finite], target_unit=reported_unit
        )
        # Skill is computed on exactly the subset the baseline could cover, so a baseline
        # with gaps is not credited or penalised for the points it could not predict.
        model_rmse_on_subset = metric_mod.rmse(
            ghi_test_obs[finite], pred_test_bounded[finite]
        )
        skill = (
            1.0 - model_rmse_on_subset / b_metrics["rmse"]
            if b_metrics["rmse"] > 0
            else float("nan")
        )
        skill_scores[bf.name] = float(skill)
        baseline_results.append(
            {
                **bf.to_dict(),
                "metrics": b_metrics,
                "skill_score": float(skill),
                "model_rmse_on_same_subset": float(model_rmse_on_subset),
                "unit": reported_unit,
            }
        )

    if skill_scores:
        weakest = min(
            (k for k in skill_scores if np.isfinite(skill_scores[k])),
            key=lambda k: skill_scores[k],
            default=None,
        )
        if weakest is not None and skill_scores[weakest] <= 0:
            warnings.append(
                f"The model does not improve on the '{weakest}' baseline "
                f"(skill score {skill_scores[weakest]:+.3f}). A negative or zero skill "
                f"score means the simpler reference is at least as good."
            )

    # ------------------------------------------------- error decompositions
    by_regime = metric_mod.evaluate_by_group(
        observed_test, pred_test_bounded, regimes, target_unit=reported_unit
    )
    by_hour = metric_mod.evaluate_by_group(
        observed_test,
        pred_test_bounded,
        index[test_idx].hour.to_numpy(),
        target_unit=reported_unit,
    )
    by_month = metric_mod.evaluate_by_group(
        observed_test,
        pred_test_bounded,
        index[test_idx].month.to_numpy(),
        target_unit=reported_unit,
    )

    # ----------------------------------------------------- cross-validation
    cv_folds: list[FoldResult] = []
    cv_summary: dict[str, Any] = {}
    if run_cv:
        t0 = time.perf_counter()
        fold_metrics: list[dict[str, Any]] = []
        try:
            for split in splitters.rolling_origin_splits(
                index, n_splits=cv_splits, gap_hours=gap_hours
            ):
                fold_est = spec.build(seed)
                fold_est.fit(X[split.train_idx], y[split.train_idx])
                fold_pred = fold_est.predict(X[split.test_idx])
                fold_bounded, _ = to_reported(fold_pred, split.test_idx)
                m = metric_mod.evaluate(
                    observed_reported[split.test_idx],
                    fold_bounded,
                    target_unit=reported_unit,
                )
                fold_metrics.append(m)
                cv_folds.append(
                    FoldResult(
                        fold=split.fold,
                        metrics=m,
                        n_train=int(split.train_idx.size),
                        n_test=int(split.test_idx.size),
                        test_start=split.test_start.isoformat() if split.test_start else None,
                        test_end=split.test_end.isoformat() if split.test_end else None,
                    )
                )
        except ValueError as exc:
            warnings.append(f"Cross-validation could not run: {exc}")

        timings["cv_seconds"] = round(time.perf_counter() - t0, 3)

        if fold_metrics:
            for key in ("mae", "rmse", "r2", "mbe"):
                vals = [m[key] for m in fold_metrics if np.isfinite(m.get(key, np.nan))]
                if vals:
                    cv_summary[f"{key}_mean"] = float(np.mean(vals))
                    cv_summary[f"{key}_std"] = float(np.std(vals))
                    cv_summary[f"{key}_min"] = float(np.min(vals))
                    cv_summary[f"{key}_max"] = float(np.max(vals))
            cv_summary["n_folds"] = len(fold_metrics)
            cv_summary["strategy"] = "rolling_origin"
            cv_summary["gap_hours"] = gap_hours
            cv_summary["unit"] = reported_unit

            rmse_std = cv_summary.get("rmse_std", 0.0)
            rmse_mean = cv_summary.get("rmse_mean", 0.0)
            if rmse_mean > 0 and rmse_std / rmse_mean > 0.25:
                warnings.append(
                    f"Cross-validation RMSE varies substantially across folds "
                    f"({rmse_mean:.3g} ± {rmse_std:.3g} {reported_unit}). Performance is "
                    f"period-dependent, so a single hold-out figure would be misleading."
                )

    # -------------------------------------------------------------- intervals
    interval: uncertainty.IntervalForecast | None = None
    interval_metrics: dict[str, Any] = {}
    uncertainty_decomposition: dict[str, Any] = {}
    if compute_intervals:
        t0 = time.perf_counter()
        try:
            interval = uncertainty.conformalized_quantile_regression(
                X[train_idx],
                y[train_idx],
                X[test_idx],
                quantile_levels=settings.modelling.quantiles,
                nominal_coverage=nominal_coverage,
                seed=seed,
            )
            # Evaluate intervals in the reported unit so widths are interpretable.
            lo_phys, _ = to_reported(interval.lower, test_idx)
            hi_phys, _ = to_reported(interval.upper, test_idx)
            interval_metrics = metric_mod.interval_metrics(
                observed_test, lo_phys, hi_phys, nominal_coverage=nominal_coverage
            )
            q_phys = {
                q: to_reported(v, test_idx)[0] for q, v in interval.quantiles.items()
            }
            interval_metrics.update(metric_mod.pinball_loss(observed_test, q_phys))
            interval_metrics["crps"] = metric_mod.crps_from_quantiles(observed_test, q_phys)
            interval_metrics["unit"] = reported_unit

            residual_std = float(np.std(observed_test - pred_test_bounded))
            uncertainty_decomposition = uncertainty.decompose_uncertainty(
                uncertainty.IntervalForecast(
                    quantiles=q_phys,
                    method=interval.method,
                    method_description=interval.method_description,
                    nominal_coverage=nominal_coverage,
                    lower=lo_phys,
                    upper=hi_phys,
                    median=to_reported(interval.median, test_idx)[0],
                ),
                residual_std,
            )

            # Conformal coverage is marginal. Report it per regime as well, because a
            # model can hit 80% overall while badly under-covering the cloudy hours that
            # matter most operationally.
            per_regime_coverage: dict[str, Any] = {}
            for regime_name in sorted(set(regimes.tolist())):
                m = regimes == regime_name
                if m.sum() < 20:
                    continue
                inside = (ghi_test_obs[m] >= lo_phys[m]) & (ghi_test_obs[m] <= hi_phys[m])
                per_regime_coverage[str(regime_name)] = {
                    "picp": float(np.mean(inside)),
                    "n": int(m.sum()),
                    "mean_width": float(np.mean(hi_phys[m] - lo_phys[m])),
                }
            interval_metrics["by_regime"] = per_regime_coverage

            cov_err = interval_metrics.get("coverage_error", 0.0)
            if abs(cov_err) > 0.10:
                direction = "over" if cov_err > 0 else "under"
                warnings.append(
                    f"Prediction intervals are mis-calibrated: nominal coverage "
                    f"{nominal_coverage:.0%}, empirical {interval_metrics['picp']:.1%} "
                    f"({direction}-covering by {abs(cov_err):.1%})."
                )
        except Exception as exc:  # noqa: BLE001 - interval failure must not lose the point forecast
            warnings.append(f"Prediction intervals could not be computed: {exc}")
        timings["interval_seconds"] = round(time.perf_counter() - t0, 3)

    # ------------------------------------------------------------ predictions
    #
    # The column names carry their unit, because a consumer reading `residual_wm2` off an
    # energy run would be reading kilowatt-hours labelled as irradiance. An energy run
    # therefore publishes `*_kwh` columns and no W/m² prediction at all: the observed
    # irradiance is real data and stays, but there is no predicted irradiance to report,
    # and inventing one would be the fabrication this target exists to avoid.
    columns: dict[str, Any] = {
        "observed_target": y[test_idx],
        "predicted_target": pred_test,
        "observed_ghi_wm2": ghi_all[test_idx],
        "clear_sky_ghi_wm2": clear_sky_all[test_idx],
        "weather_regime": regimes,
    }
    if is_energy:
        columns["observed_kwh"] = observed_test
        columns["predicted_kwh"] = pred_test_bounded
        columns["residual_kwh"] = observed_test - pred_test_bounded
        bound_names = ("lower_kwh", "upper_kwh")
    else:
        columns["predicted_ghi_wm2"] = pred_test_bounded
        columns["residual_wm2"] = observed_test - pred_test_bounded
        bound_names = ("lower_wm2", "upper_wm2")

    predictions = pd.DataFrame(columns, index=index[test_idx])
    if interval is not None:
        lower_name, upper_name = bound_names
        predictions[lower_name] = to_reported(interval.lower, test_idx)[0]
        predictions[upper_name] = to_reported(interval.upper, test_idx)[0]

    manifest = build_manifest(
        fs=fs,
        spec=spec,
        seed=seed,
        test_fraction=test_fraction,
        cv_splits=cv_splits,
        gap_hours=gap_hours,
        horizon_hours=horizon_hours,
        n_train=int(train_idx.size),
        n_test=int(test_idx.size),
        train_period=(index[train_idx[0]], index[train_idx[-1]]) if train_idx.size else None,
        test_period=(index[test_idx[0]], index[test_idx[-1]]) if test_idx.size else None,
    )

    return TrainingResult(
        model_key=model_key,
        model_display_name=spec.display_name,
        estimator=estimator,
        feature_names=list(fs.feature_names),
        target_name=fs.target_name,
        test_metrics=test_metrics,
        test_metrics_physical=test_metrics_physical,
        train_metrics=train_metrics,
        cv_folds=cv_folds,
        cv_summary=cv_summary,
        baseline_results=baseline_results,
        skill_scores=skill_scores,
        by_regime=by_regime,
        by_hour=by_hour,
        by_month=by_month,
        interval=interval,
        interval_metrics=interval_metrics,
        uncertainty_decomposition=uncertainty_decomposition,
        predictions=predictions,
        manifest=manifest,
        warnings=warnings,
        timings=timings,
    )


def build_manifest(
    *,
    fs: FeatureSet,
    spec: registry.ModelSpec,
    seed: int,
    test_fraction: float,
    cv_splits: int,
    gap_hours: int,
    horizon_hours: int,
    n_train: int,
    n_test: int,
    train_period: tuple[pd.Timestamp, pd.Timestamp] | None,
    test_period: tuple[pd.Timestamp, pd.Timestamp] | None,
) -> dict[str, Any]:
    """Everything needed to reproduce this run.

    A reviewer asking "which dataset produced this number?" should be able to answer it
    from this object alone, without reading the code.
    """
    settings = get_settings()
    return {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform_version": settings.version,
        "dataset": {
            "fingerprint": _dataset_fingerprint(fs),
            "source": fs.provenance.get("source"),
            "attribution": fs.provenance.get("attribution"),
            "retrieved_at": fs.provenance.get("retrieved_at"),
            "kind": fs.provenance.get("kind"),
            "location": fs.location.to_dict(),
            "grid_latitude": fs.provenance.get("grid_latitude"),
            "grid_longitude": fs.provenance.get("grid_longitude"),
            "elevation_m": fs.provenance.get("elevation_m"),
            "rows_retrieved": fs.provenance.get("rows_retrieved"),
            "rows_used": int(len(fs.frame)),
            "rows_dropped": fs.dropped_rows,
            "period_start": fs.frame.index.min().isoformat(),
            "period_end": fs.frame.index.max().isoformat(),
            "temporal_resolution": "1 hour",
        },
        "preprocessing": {
            "daytime_only": fs.provenance.get("daytime_only"),
            "day_mask_threshold_deg": fs.provenance.get("day_mask_threshold_deg"),
            "interval_offset_minutes": fs.provenance.get("interval_offset_minutes"),
            "imputation": "none — incomplete rows are excluded, never filled",
            "outlier_treatment": (
                "physical-range validation only; no statistical truncation of the target"
            ),
            "scaling": (
                "StandardScaler inside the model pipeline, refitted per fold"
                if spec.requires_scaling
                else "not required by this estimator"
            ),
        },
        "features": {
            "names": list(fs.feature_names),
            "count": len(fs.feature_names),
            "target": fs.target_name,
            "target_unit": TARGET_UNITS.get(fs.target_name),
            "target_lags_used": fs.provenance.get("target_lags_used", False),
            "leakage_note": fs.provenance.get("target_lag_rationale"),
            # Present only for pv_kwh, and load-bearing when it is: it records that the
            # labels came out of the physical chain rather than off a meter.
            "target_construction": fs.provenance.get("target_construction"),
            "pv_system": (
                fs.provenance.get("pv_system") if fs.target_name == ENERGY_TARGET else None
            ),
        },
        "model": {
            "key": spec.key,
            "display_name": spec.display_name,
            "family": spec.family,
            "hyperparameters": spec.hyperparameters,
            "hyperparameter_source": spec.hyperparameter_source,
            "sources": list(spec.sources),
        },
        "validation": {
            "strategy": "chronological hold-out + rolling-origin cross-validation",
            "test_fraction": test_fraction,
            "cv_splits": cv_splits,
            "embargo_gap_hours": gap_hours,
            "forecast_horizon_hours": horizon_hours,
            "n_train": n_train,
            "n_test": n_test,
            "train_period": [t.isoformat() for t in train_period] if train_period else None,
            "test_period": [t.isoformat() for t in test_period] if test_period else None,
        },
        "reproducibility": {
            "random_seed": seed,
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
            "scikit_learn_version": sklearn.__version__,
            "platform": platform.platform(),
        },
    }
