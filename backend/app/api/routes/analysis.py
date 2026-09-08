"""Analysis endpoints: create an analysis and query everything derived from it."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.anomaly import detector
from app.api.service import CACHE, Analysis, create_analysis, to_pv_system
from app.data.sources import DataSourceError
from app.evaluation import leakage as leakage_mod
from app.experiments import store
from app.explain import attribution
from app.models import registry
from app.models.forecast import generate_forecast, operating_conditions
from app.models.trainer import train_and_evaluate
from app.reports import generator
from app.scenario import engine as scenario_engine
from app.schemas.models import (
    AnalysisRequest,
    ForecastRequest,
    ModelComparisonRequest,
    ScenarioRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["analysis"])


def _require(analysis_id: str) -> Analysis:
    analysis = CACHE.get(analysis_id)
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Analysis '{analysis_id}' was not found. Cached analyses are held in "
                f"memory and are cleared when the server restarts or when capacity is "
                f"exceeded. Re-run the analysis to continue."
            ),
        )
    return analysis


def _records(frame: pd.DataFrame, index_name: str = "timestamp") -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.reset_index()
    out = out.rename(columns={out.columns[0]: index_name})
    out[index_name] = out[index_name].astype(str)
    return out.replace({np.nan: None}).to_dict(orient="records")


@router.post("/analysis")
def create(request: AnalysisRequest) -> dict[str, Any]:
    """Run the full pipeline: fetch, quality-assess, build features, train, evaluate."""
    system = to_pv_system(request.system)
    try:
        analysis, notes = create_analysis(
            location_query=request.location.query,
            latitude=request.location.latitude,
            longitude=request.location.longitude,
            start=request.start_date,
            end=request.end_date,
            model_key=request.model_key,
            target=request.target,
            system=system,
            horizon_hours=request.horizon_hours,
            test_fraction=request.test_fraction,
            cv_splits=request.cv_splits,
            nominal_coverage=request.nominal_coverage,
            compute_intervals=request.compute_intervals,
            run_cv=request.run_cv,
        )
    except DataSourceError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if analysis.experiment_id is None:
        experiment = store.record(
            analysis.training,
            location_label=analysis.location.label,
            latitude=analysis.location.latitude,
            longitude=analysis.location.longitude,
            label=request.label,
        )
        analysis.experiment_id = experiment.experiment_id

    payload = analysis.summary()
    payload["notes"] = notes
    return payload


@router.get("/analysis/{analysis_id}")
def get_analysis(analysis_id: str) -> dict[str, Any]:
    return _require(analysis_id).summary()


@router.get("/analysis/{analysis_id}/quality")
def get_quality(analysis_id: str) -> dict[str, Any]:
    return _require(analysis_id).quality


@router.get("/analysis/{analysis_id}/performance")
def get_performance(analysis_id: str) -> dict[str, Any]:
    """Full evaluation payload: metrics, folds, baselines and error decompositions."""
    t = _require(analysis_id).training
    return {
        "test_metrics_physical": t.test_metrics_physical,
        "test_metrics_target_space": t.test_metrics,
        "train_metrics": t.train_metrics,
        "cv_summary": t.cv_summary,
        "cv_folds": [
            {
                "fold": f.fold,
                "metrics": f.metrics,
                "n_train": f.n_train,
                "n_test": f.n_test,
                "test_start": f.test_start,
                "test_end": f.test_end,
            }
            for f in t.cv_folds
        ],
        "baselines": t.baseline_results,
        "skill_scores": t.skill_scores,
        "by_regime": t.by_regime,
        "by_hour": t.by_hour,
        "by_month": t.by_month,
        "interval_metrics": t.interval_metrics,
        "uncertainty_decomposition": t.uncertainty_decomposition,
        "interval": t.interval.to_dict() if t.interval else None,
        "warnings": t.warnings,
    }


@router.get("/analysis/{analysis_id}/predictions")
def get_predictions(
    analysis_id: str,
    limit: int = Query(default=1500, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Actual-versus-predicted series for the hold-out test set."""
    t = _require(analysis_id).training
    frame = t.predictions
    total = len(frame)
    window = frame.iloc[offset : offset + limit]

    # Trim the wire payload. The target-space columns are a deterministic rescaling of the
    # GHI pair, so sending both doubles the size for no additional information, and full
    # float64 precision is meaningless against a ~75 W/m^2 RMSE.
    drop = [c for c in ("observed_target", "predicted_target") if c in window.columns]
    window = window.drop(columns=drop)
    window = window.round(
        {
            # Energy columns are fractions of a kilowatt-hour, so one decimal would round
            # most of a day's profile to the same number.
            c: (3 if c.endswith("_kwh") else 1)
            for c in window.columns
            if window[c].dtype.kind == "f"
        }
    )

    # Energy runs publish `residual_kwh` and irradiance runs `residual_wm2`; the payload
    # names its unit rather than assuming the reader knows which target was used.
    residual_column = "residual_kwh" if "residual_kwh" in frame.columns else "residual_wm2"
    unit = "kWh" if residual_column == "residual_kwh" else "W/m²"

    residuals = frame[residual_column].to_numpy(dtype=np.float64)
    finite = residuals[np.isfinite(residuals)]
    hist_counts, hist_edges = (
        np.histogram(finite, bins=40) if finite.size else (np.array([]), np.array([]))
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "series": _records(window),
        "residual_summary": {
            "mean": float(np.mean(finite)) if finite.size else None,
            "std": float(np.std(finite)) if finite.size else None,
            "median": float(np.median(finite)) if finite.size else None,
            "q05": float(np.quantile(finite, 0.05)) if finite.size else None,
            "q95": float(np.quantile(finite, 0.95)) if finite.size else None,
            "skew": float(pd.Series(finite).skew()) if finite.size > 2 else None,
            "kurtosis": float(pd.Series(finite).kurtosis()) if finite.size > 3 else None,
        },
        "residual_histogram": {
            "counts": hist_counts.tolist(),
            "edges": hist_edges.tolist(),
        },
        "unit": unit,
    }


@router.get("/analysis/{analysis_id}/explain")
def get_explanation(
    analysis_id: str, n_repeats: int = Query(default=8, ge=3, le=30)
) -> dict[str, Any]:
    """Permutation importance, grouped importance, and partial dependence."""
    analysis = _require(analysis_id)
    cache_key = f"explain_{n_repeats}"
    if cache_key in analysis.derived:
        return analysis.derived[cache_key]

    t = analysis.training
    test_index = t.predictions.index
    X_test = analysis.features.frame.loc[test_index, t.feature_names]
    y_test = analysis.features.frame.loc[test_index, t.target_name].to_numpy(dtype=np.float64)

    importance = attribution.permutation_feature_importance(
        t.estimator, X_test, y_test, n_repeats=n_repeats, seed=7
    )
    top_features = [f["feature"] for f in importance.per_feature[:6]]
    curves = attribution.partial_dependence_curves(
        t.estimator, analysis.features.X, top_features
    )
    narrative = attribution.narrate(importance, t.by_regime)

    payload = {
        "importance": importance.to_dict(),
        "partial_dependence": curves,
        "partial_dependence_caveat": (
            "Partial dependence marginalises over the other features while holding the "
            "target feature fixed, which can construct physically impossible combinations "
            "such as high temperature at midnight. These curves describe model behaviour, "
            "not the physical world."
        ),
        "narrative": narrative,
        "target": t.target_name,
    }
    analysis.derived[cache_key] = payload
    return payload


@router.get("/analysis/{analysis_id}/leakage")
def get_leakage(analysis_id: str, run_experiment: bool = Query(default=True)) -> dict[str, Any]:
    """Leakage audit, and optionally the split-strategy comparison experiment."""
    analysis = _require(analysis_id)
    key = f"leakage_{run_experiment}"
    if key in analysis.derived:
        return analysis.derived[key]

    payload: dict[str, Any] = {
        "audit": leakage_mod.audit(analysis.features, analysis.training.model_key),
    }
    if run_experiment:
        try:
            payload["experiment"] = leakage_mod.compare_split_strategies(
                analysis.features, model_key=analysis.training.model_key, seed=20240617
            )
        except Exception as exc:  # noqa: BLE001 - the audit is still useful without it
            payload["experiment"] = None
            payload["experiment_error"] = (
                f"The split-strategy comparison could not be completed: {exc}"
            )

    analysis.derived[key] = payload
    return payload


@router.get("/analysis/{analysis_id}/anomalies")
def get_anomalies(
    analysis_id: str,
    sigma: float = Query(default=4.0, ge=2.0, le=10.0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Statistical and physical irregularities in the data and in model residuals."""
    analysis = _require(analysis_id)
    frame = analysis.features.frame
    training = analysis.training

    anomalies = []
    anomalies.extend(detector.detect_physical(analysis.raw, limit=limit))
    anomalies.extend(detector.detect_clear_sky_violations(frame, limit=limit))
    anomalies.extend(detector.detect_residual_anomalies(
        training.predictions, sigma_threshold=sigma, limit=limit
    ))
    anomalies.extend(detector.detect_ramps(frame, sigma_threshold=sigma, limit=limit))
    anomalies.extend(detector.detect_gaps(analysis.raw, limit=50))

    test_index = training.predictions.index
    train_frame = frame[~frame.index.isin(test_index)]
    shift = detector.detect_distribution_shift(train_frame, frame.loc[test_index])

    ordered = sorted(
        anomalies,
        key=lambda a: (
            {"high": 0, "medium": 1, "low": 2}.get(a.severity, 3),
            -(abs(a.deviation_sigma) if a.deviation_sigma else 0.0),
        ),
    )

    return {
        "summary": detector.summarise(anomalies),
        "anomalies": [a.to_dict() for a in ordered[:limit]],
        "distribution_shift": shift,
        "distribution_shift_note": (
            "Compares the training period against the evaluation period. Meaningful shift "
            "means a model validated on one period may not transfer to the other."
        ),
        "threshold_sigma": sigma,
    }


@router.post("/analysis/{analysis_id}/forecast")
def post_forecast(analysis_id: str, request: ForecastRequest) -> dict[str, Any]:
    """Generate a forward-looking forecast from the trained model."""
    analysis = _require(analysis_id)
    system = to_pv_system(request.system) if request.system else analysis.system
    try:
        result = generate_forecast(
            trained=analysis.training,
            location=analysis.location,
            horizon_hours=request.horizon_hours,
            system=system,
            nominal_coverage=request.nominal_coverage,
        )
    except DataSourceError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = result.to_dict()
    payload["operating_conditions"] = operating_conditions(result.frame, system)
    return payload


@router.post("/analysis/{analysis_id}/scenario")
def post_scenario(analysis_id: str, request: ScenarioRequest) -> dict[str, Any]:
    """Run a modelled counterfactual. Always labelled as a simulation."""
    analysis = _require(analysis_id)
    training = analysis.training

    # Scenarios run over the hold-out period, so the comparison uses data the model
    # was not fitted on.
    base_frame = analysis.features.frame.loc[training.predictions.index]
    train_frame = analysis.features.frame[
        ~analysis.features.frame.index.isin(training.predictions.index)
    ]

    try:
        if request.kind == "system":
            scenario_system = to_pv_system(request.scenario_system)
            result = scenario_engine.run_system_scenario(
                base_frame=base_frame,
                baseline_system=analysis.system,
                scenario_system=scenario_system,
                name=request.name,
                location_lat=analysis.location.latitude,
                location_lon=analysis.location.longitude,
            )
        else:
            perturbations = list(request.perturbations)
            name = request.name
            if request.preset_key:
                preset = next(
                    (p for p in scenario_engine.PRESET_SCENARIOS if p["key"] == request.preset_key),
                    None,
                )
                if preset is None:
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"Unknown preset '{request.preset_key}'. Available presets are "
                            f"listed at /api/meta/scenarios."
                        ),
                    )
                perturbations = [
                    scenario_engine.Perturbation(**p) for p in preset["perturbations"]
                ]
                name = preset["name"]
            else:
                perturbations = [
                    scenario_engine.Perturbation(
                        variable=p.variable, mode=p.mode, value=p.value
                    )
                    for p in perturbations
                ]

            result = scenario_engine.run_meteorological_scenario(
                trained=training,
                base_frame=base_frame,
                training_frame=train_frame,
                perturbations=perturbations,
                name=name,
                system=analysis.system,
                location_lat=analysis.location.latitude,
                location_lon=analysis.location.longitude,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return result.to_dict()


@router.post("/analysis/{analysis_id}/compare-models")
def compare_models(analysis_id: str, request: ModelComparisonRequest) -> dict[str, Any]:
    """Train several models on the identical data and compare them fairly."""
    analysis = _require(analysis_id)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    # Metric keys carry their unit, the same way the analysis summary's headline does: an
    # energy analysis is compared in kWh and must not publish those figures under a name
    # that says W/m².
    is_energy = analysis.training.target_name == "pv_kwh"
    unit_suffix = "kwh" if is_energy else "wm2"
    unit = "kWh" if is_energy else "W/m²"

    for key in request.model_keys:
        if key == analysis.training.model_key:
            result = analysis.training
        else:
            try:
                result = train_and_evaluate(
                    analysis.features,
                    model_key=key,
                    horizon_hours=analysis.horizon_hours,
                    compute_intervals=False,
                    run_cv=True,
                )
            except Exception as exc:  # noqa: BLE001 - one failure must not lose the rest
                logger.exception("Model %s failed during comparison", key)
                errors.append({"model": key, "error": str(exc)})
                continue

        phys = result.test_metrics_physical
        rows.append(
            {
                "model": key,
                "display_name": result.model_display_name,
                "family": result.manifest.get("model", {}).get("family"),
                f"rmse_{unit_suffix}": phys.get("rmse"),
                f"mae_{unit_suffix}": phys.get("mae"),
                f"mbe_{unit_suffix}": phys.get("mbe"),
                "r2": phys.get("r2"),
                "rrmse_pct": phys.get("rrmse"),
                "cv_rmse_mean": result.cv_summary.get("rmse_mean"),
                "cv_rmse_std": result.cv_summary.get("rmse_std"),
                # Smart persistence is an irradiance baseline; an energy run is scored
                # against persistence instead, so the key that is populated follows the
                # baselines that were actually built.
                "skill_vs_smart_persistence": result.skill_scores.get("smart_persistence"),
                "skill_vs_persistence": result.skill_scores.get("persistence"),
                "fit_seconds": result.timings.get("fit_seconds"),
                "sources": result.manifest.get("model", {}).get("sources", []),
                "warnings": result.warnings,
            }
        )

    rmse_key = f"rmse_{unit_suffix}"
    rows.sort(key=lambda r: (r[rmse_key] if r[rmse_key] is not None else float("inf")))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    return {
        "results": rows,
        "errors": errors,
        "evaluation_protocol": {
            "note": (
                "Every model is fitted on the identical feature matrix with the identical "
                "chronological split, embargo gap and random seed. Differences reflect the "
                "estimator alone."
            ),
            "split": analysis.training.manifest.get("validation", {}),
            "n_features": len(analysis.training.feature_names),
        },
        "unit": unit,
    }


@router.get("/analysis/{analysis_id}/model-card")
def get_model_card(analysis_id: str) -> dict[str, Any]:
    """Structured model documentation."""
    analysis = _require(analysis_id)
    t = analysis.training
    manifest = t.manifest
    phys = t.test_metrics_physical
    spec = manifest.get("model", {})
    is_energy = t.target_name == "pv_kwh"

    return {
        "model_name": spec.get("display_name"),
        "version": f"{manifest.get('platform_version')}-{manifest.get('dataset', {}).get('fingerprint')}",
        "objective": (
            "Predict hourly AC energy for a declared photovoltaic system at a fixed "
            "location, directly from weather and solar-geometry inputs."
            if is_energy
            else (
                "Predict hourly global horizontal irradiance at a fixed location from "
                "numerical weather prediction inputs, and convert that to photovoltaic "
                "energy for a declared system."
            )
        ),
        "target_variable": {
            "modelling_target": t.target_name,
            "reported_as": (
                "AC energy (kWh) for the declared PV system"
                if is_energy
                else "Global Horizontal Irradiance (W/m²)"
            ),
            "derived_output": (
                "None — the model predicts the reported quantity directly"
                if is_energy
                else "AC energy (kWh) for the declared PV system"
            ),
            "label_provenance": manifest.get("features", {}).get("target_construction"),
            "declared_system": manifest.get("features", {}).get("pv_system"),
        },
        "input_variables": t.feature_names,
        "training_data": manifest.get("dataset", {}),
        "preprocessing": manifest.get("preprocessing", {}),
        "validation_strategy": manifest.get("validation", {}),
        "performance": {
            "hold_out": phys,
            "cross_validation": t.cv_summary,
            "skill_scores": t.skill_scores,
            "by_regime": t.by_regime,
        },
        "uncertainty": {
            "method": t.interval.method if t.interval else None,
            "metrics": t.interval_metrics,
            "decomposition": t.uncertainty_decomposition,
        },
        "hyperparameters": spec.get("hyperparameters"),
        "hyperparameter_provenance": spec.get("hyperparameter_source"),
        # Present only for the stacking ensemble, and load-bearing when it is: without the
        # weights, "an ensemble of four models" is a claim rather than something a reader
        # can check. None for a single estimator.
        "ensemble_weights": registry.ensemble_weights(t.estimator),
        "reproducibility": manifest.get("reproducibility", {}),
        "plain_language": {
            "what_it_does": (
                "The model estimates how much of the maximum possible sunlight actually "
                "reaches the ground in a given hour. The maximum possible amount is "
                "calculated exactly from the position of the sun, which is known in "
                "advance for any date, time and place. What cannot be known in advance is "
                "how much the atmosphere will block, so that is the only part the model is "
                "asked to predict — from forecast cloud cover, humidity, temperature and "
                "related conditions."
            ),
            "why_this_design": (
                "Separating the two makes the problem easier and the result easier to "
                "check. The sun's position contributes no error because it is computed "
                "rather than learned, and any error that remains is attributable to the "
                "weather prediction."
            ),
            "how_to_read_the_numbers": (
                "RMSE is the typical size of an error in watts per square metre. Compare it "
                "with the average irradiance to judge whether it is large. The skill score "
                "shows the improvement over simply assuming today repeats yesterday: zero "
                "means no improvement at all."
            ),
        },
        "technical_summary": {
            "approach": (
                f"{spec.get('display_name')} regression onto hourly AC energy for the "
                f"declared array, with deterministic solar geometry supplied as features. "
                f"Predictions are already in kilowatt-hours, so nothing is converted back; "
                f"they are bounded below at zero and above at the inverter's AC rating."
                if is_energy
                else (
                    f"{spec.get('display_name')} regression onto the clear-sky index, with "
                    f"deterministic solar geometry supplied as features and the Haurwitz "
                    f"clear-sky model as the normalising reference. Predictions are "
                    f"transformed back to W/m² and bounded by physical limits."
                )
            ),
            "pv_chain": (
                "Erbs decomposition → HDKR transposition → Faiman cell temperature → "
                "PVWatts v5 DC model → inverter efficiency with AC clipping."
            ),
        },
        "limitations": [
            *(
                [
                    "The training labels are modelled, not metered. Hourly energy was "
                    "produced by running the deterministic PV chain (Erbs, HDKR, Faiman, "
                    "PVWatts v5) over reanalysis weather for the declared array; no "
                    "measured generation was available to fit against. Every kilowatt-hour "
                    "reported here therefore inherits the chain's assumptions as well as "
                    "the model's error. This mirrors README section 10, limitation 2.",
                    "The labels depend on the declared array. A model fitted for one tilt, "
                    "azimuth and capacity does not describe a different system.",
                ]
                if is_energy
                else []
            ),
            "Trained and validated at a single location; no cross-location generalisation "
            "is claimed. [P3] notes explicitly that models may not transfer between climates.",
            "Irradiance is ERA5 reanalysis, a modelled gridded product, not a ground "
            "pyranometer measurement.",
            "PV output is physically modelled and has not been validated against metered "
            "generation, because no metered data was available.",
            "Prediction intervals exclude uncertainty in the input weather forecast.",
            f"Accuracy measured only to a "
            f"{manifest.get('validation', {}).get('forecast_horizon_hours', 24)}-hour horizon.",
            "Aerosol optical depth and sunshine duration are not available from this source "
            "and are not represented.",
        ],
        "known_failure_modes": [
            {
                "condition": "Rapidly changing broken cloud",
                "evidence": (
                    f"Error under '{max(t.by_regime, key=lambda k: t.by_regime[k].get('rmse', 0))}' "
                    f"conditions is materially higher than under clear skies."
                    if t.by_regime
                    else "Per-regime breakdown unavailable."
                ),
            },
            {
                "condition": "Conditions outside the training range",
                "evidence": (
                    "Tree ensembles saturate rather than extrapolate; predictions flatten "
                    "at the boundary of the training distribution."
                ),
            },
            {
                "condition": "Horizons beyond the validated range",
                "evidence": (
                    "Weather-forecast error grows with lead time and is not represented in "
                    "the intervals."
                ),
            },
        ],
        "warnings": t.warnings,
    }


@router.get("/analysis/{analysis_id}/report", response_class=PlainTextResponse)
def get_report(analysis_id: str) -> str:
    """Full scientific report as Markdown."""
    analysis = _require(analysis_id)
    t = analysis.training

    explanation = analysis.derived.get("explain_8")
    if explanation is None:
        try:
            explanation = get_explanation(analysis_id, n_repeats=8)
        except Exception:  # noqa: BLE001 - report must render without it
            explanation = None

    leak = analysis.derived.get("leakage_True")

    anomalies = detector.detect_residual_anomalies(t.predictions, sigma_threshold=4.0, limit=50)
    anomalies.extend(detector.detect_clear_sky_violations(analysis.features.frame, limit=50))

    return generator.build_markdown_report(
        result=t,
        location_label=analysis.location.label,
        quality=analysis.quality,
        importance=(explanation or {}).get("importance"),
        leakage_audit=(leak or {}).get("audit"),
        leakage_experiment=(leak or {}).get("experiment"),
        anomaly_summary=detector.summarise(anomalies),
        narrative=(explanation or {}).get("narrative"),
        experiment_id=analysis.experiment_id,
    )
