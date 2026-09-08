"""Reference endpoints: capabilities, parameters, models, and literature traceability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.data.sources import DataSourceError, geocode, latest_available_archive_date
from app.evaluation.metrics import METRIC_DEFINITIONS
from app.features.parameters import parameter_catalogue
from app.models import registry
from app.scenario.engine import PRESET_SCENARIOS

router = APIRouter(prefix="/api", tags=["reference"])


# /api/health moved to app.api.routes.health, which also hosts the liveness and readiness
# probes the load balancer uses. Its payload is unchanged; see that module for why a probe
# and a status page cannot be the same endpoint.


@router.get("/meta/parameters")
def parameters() -> dict[str, Any]:
    """The scientific parameter dictionary: definitions, units, ranges and provenance."""
    return parameter_catalogue()


@router.get("/meta/models")
def models() -> dict[str, Any]:
    return {
        "models": registry.catalogue(),
        "default_comparison": list(registry.DEFAULT_COMPARISON),
        "future_work": registry.future_work(),
    }


@router.get("/meta/metrics")
def metrics() -> dict[str, Any]:
    return {
        "metrics": [
            {
                "key": d.key,
                "name": d.name,
                "formula": d.formula,
                "unit_kind": d.unit_kind,
                "lower_is_better": d.lower_is_better,
                "interpretation": d.interpretation,
                "caveat": d.caveat,
            }
            for d in METRIC_DEFINITIONS.values()
        ]
    }


@router.get("/meta/scenarios")
def scenario_presets() -> dict[str, Any]:
    return {"presets": [dict(p) for p in PRESET_SCENARIOS]}


@router.get("/meta/limits")
def limits() -> dict[str, Any]:
    lim = get_settings().limits
    mod = get_settings().modelling
    return {
        "min_training_days": lim.min_training_days,
        "max_training_days": lim.max_training_days,
        "default_training_days": lim.default_training_days,
        "earliest_date": lim.earliest_date,
        "archive_lag_days": lim.archive_lag_days,
        "latest_archive_date": latest_available_archive_date().isoformat(),
        "min_horizon_hours": lim.min_horizon_hours,
        "max_horizon_hours": lim.max_horizon_hours,
        "validated_horizon_hours": lim.validated_horizon_hours,
        "default_target": mod.default_target,
        "default_model": mod.default_model,
        "random_seed": mod.random_seed,
        "quantiles": list(mod.quantiles),
    }


@router.get("/meta/literature")
def literature() -> dict[str, Any]:
    """Traceability from implemented technique back to source paper."""
    return {
        "papers": [
            {
                "key": "hobbs2026",
                "title": (
                    "Using Open-Source Forecasts for Solar Plant Maintenance Outage "
                    "Scheduling Can Reduce Lost Energy"
                ),
                "authors": "W. B. Hobbs, D. Joshi",
                "venue": "IEEE Journal of Photovoltaics",
                "year": 2026,
            },
            {
                "key": "mabodi2024",
                "title": (
                    "Solar Irradiance Forecasting for Informed Solar Systems Design and "
                    "Financing Decisions"
                ),
                "authors": "R. Mabodi, J. Hammujuddy",
                "venue": "SAIEE Africa Research Journal, vol. 115(3)",
                "year": 2024,
            },
            {
                "key": "lyu2024",
                "title": (
                    "Probabilistic Solar Generation Forecasting for Rapidly Changing "
                    "Weather Conditions"
                ),
                "authors": "C. Lyu, S. Eftekharnejad",
                "venue": "IEEE Access, vol. 12",
                "year": 2024,
            },
            {
                "key": "rosales2025",
                "title": (
                    "Efficient Machine Learning Models for Solar Radiation Prediction Using "
                    "Ensemble Techniques: A Case Study in Low-Rainfall Arid Climates"
                ),
                "authors": "J. A. Rosales Huamani et al.",
                "venue": "IEEE Access, vol. 13",
                "year": 2025,
            },
            {
                "key": "babu2025",
                "title": (
                    "Solar Energy Forecasting Using Machine Learning Techniques for "
                    "Enhanced Grid Stability"
                ),
                "authors": "A. R. Vijay Babu et al.",
                "venue": "IEEE Access, vol. 13",
                "year": 2025,
            },
            {
                "key": "hayajneh2024",
                "title": (
                    "Intelligent Solar Forecasts: Modern Machine Learning Models and TinyML "
                    "Role for Improved Solar Energy Yield Predictions"
                ),
                "authors": "A. M. Hayajneh et al.",
                "venue": "IEEE Access, vol. 12",
                "year": 2024,
            },
        ],
        "techniques": [
            {
                "technique": "Clear-sky index as modelling target",
                "sources": ["hobbs2026"],
                "purpose": (
                    "Divides out the deterministic solar-geometry signal so the model only "
                    "has to learn atmospheric attenuation."
                ),
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Haurwitz clear-sky model",
                "sources": ["hobbs2026"],
                "purpose": "Reference irradiance for forming the clear-sky index.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Erbs diffuse/direct decomposition",
                "sources": ["hobbs2026"],
                "purpose": "Splits GHI into components for plane-of-array transposition.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Faiman cell-temperature model",
                "sources": ["hobbs2026"],
                "purpose": "Module temperature from irradiance, air temperature and wind.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "PVWatts v5 DC and inverter model",
                "sources": ["hobbs2026"],
                "purpose": "Converts plane-of-array irradiance to AC power.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Perez-Driesse transposition",
                "sources": ["hobbs2026"],
                "purpose": "Anisotropic sky model for tilted surfaces.",
                "status": "SUBSTITUTED",
                "note": "HDKR is used instead, to avoid a pvlib dependency.",
            },
            {
                "technique": "Solar-geometry features (zenith, azimuth, angle of incidence)",
                "sources": ["babu2025", "lyu2024"],
                "purpose": (
                    "[P5] found angle of incidence the highest-importance feature of any "
                    "variable."
                ),
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Daytime filtering at 87° solar zenith",
                "sources": ["lyu2024"],
                "purpose": "Removes trivially predictable night hours from training and metrics.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Weather-regime conditioning (sunny / cloudy / other)",
                "sources": ["lyu2024"],
                "purpose": "Per-regime error analysis; [P3] places the sunny threshold at 25% cloud.",
                "status": "PARTIALLY IMPLEMENTED",
                "note": (
                    "Regime labelling and per-regime evaluation are implemented; the "
                    "copula-based dynamic feature selection of [P3] is not."
                ),
            },
            {
                "technique": "Random Forest regression",
                "sources": ["abstract", "mabodi2024", "rosales2025", "babu2025"],
                "purpose": "The method named by the project abstract.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Boosted-tree regression",
                "sources": ["babu2025", "mabodi2024", "lyu2024"],
                "purpose": (
                    "Best single model in [P5] (R²=0.827); [P2] and [P3] use XGBoost. "
                    "Implemented as scikit-learn's histogram gradient boosting, the same "
                    "family without the extra binary dependency."
                ),
                "status": "SUBSTITUTED",
            },
            {
                "technique": "k-NN with [P2] hyperparameters",
                "sources": ["mabodi2024"],
                "purpose": (
                    "Best model in [P2] (rRMSE 5.77%, R² 0.89). Implemented and later "
                    "withdrawn when the model set was cut to four: it duplicated no "
                    "argument the kept models do not already make, and its distance "
                    "weighting makes its training metrics uninformative."
                ),
                "status": "NOT ADOPTED",
            },
            {
                "technique": "Stacking regressor with a learned meta-learner",
                "sources": ["rosales2025"],
                "purpose": (
                    "Best ensemble in [P4] (R²=0.92). Implemented over this platform's "
                    "four kept models — random forest, histogram gradient boosting, extra "
                    "trees and ridge — rather than [P4]'s base set, with a Ridge "
                    "meta-learner for stability under collinear base predictions. Each "
                    "base model's weight and contribution are reported."
                ),
                "status": "PARTIALLY IMPLEMENTED",
            },
            {
                "technique": "Direct energy target (weather → hourly kWh)",
                "sources": ["hobbs2026"],
                "purpose": (
                    "Predicts the declared array's AC energy end to end instead of "
                    "predicting irradiance and converting it afterwards. Labels come from "
                    "the PV chain applied to reanalysis weather, not from a meter, and the "
                    "model card says so."
                ),
                "status": "ENHANCEMENT",
            },
            {
                "technique": "Permutation feature importance",
                "sources": ["mabodi2024", "babu2025"],
                "purpose": "Identifies which inputs carry predictive signal on held-out data.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Pinball loss and CRPS for probabilistic forecasts",
                "sources": ["lyu2024"],
                "purpose": "Evaluates quantile forecasts and the full predictive distribution.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Persistence Ensemble (PeEn) benchmark",
                "sources": ["lyu2024"],
                "purpose": "Industry-standard probabilistic reference forecast.",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Time-aware validation (chronological + rolling origin)",
                "sources": ["babu2025"],
                "purpose": (
                    "[P5, Sec. V-D] identifies time-based splits as future work; this "
                    "implements it and measures the difference."
                ),
                "status": "IMPLEMENTED",
            },
            {
                "technique": "Conformalized quantile regression",
                "sources": [],
                "purpose": (
                    "Calibrates prediction intervals to their nominal coverage. Introduced "
                    "to fix a measured calibration failure; no supplied paper uses it."
                ),
                "status": "ENHANCEMENT",
            },
            {
                "technique": "Relative and absolute loss reduction for outage scheduling",
                "sources": ["hobbs2026"],
                "purpose": "Decision-relevant metric for maintenance scheduling [P1, eqs. 1-2].",
                "status": "IMPLEMENTED",
            },
            {
                "technique": "LSTM / BiGRU / BiLSTM sequence models",
                "sources": ["hayajneh2024"],
                "purpose": "Sequential forecasting from recent power trajectory.",
                "status": "FUTURE WORK",
                "note": (
                    "This platform forecasts from exogenous weather at the target hour, "
                    "where recurrent structure has no input to consume."
                ),
            },
            {
                "technique": "TinyML edge deployment",
                "sources": ["hayajneh2024"],
                "purpose": "Quantised inference on microcontrollers.",
                "status": "FUTURE WORK",
            },
            {
                "technique": "PCA dimensionality reduction",
                "sources": ["rosales2025"],
                "purpose": "[P4] reduced 11 variables to 8 across 3 components.",
                "status": "NOT ADOPTED",
                "note": (
                    "Tree ensembles exploit axis-aligned splits that PCA rotation destroys; "
                    "with ~10 informative predictors the reduction is not needed."
                ),
            },
        ],
        "status_legend": {
            "IMPLEMENTED": "Fully implemented and exercised by the platform.",
            "PARTIALLY IMPLEMENTED": "Core idea implemented; the full method is not.",
            "SUBSTITUTED": "A different method of the same family is used; recorded in the model card.",
            "ENHANCEMENT": "Not from the supplied research; added to address a measured problem.",
            "FUTURE WORK": "Present in the research, deliberately not implemented here.",
            "NOT ADOPTED": "Considered and rejected, with the reason stated.",
        },
    }


@router.get("/locations/search")
def search_locations(
    q: str = Query(min_length=2, max_length=120), limit: int = Query(default=5, ge=1, le=20)
) -> dict[str, Any]:
    try:
        results = geocode(q, limit=limit)
    except DataSourceError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"results": [loc.to_dict() for loc in results]}
