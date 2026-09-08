"""Experiment tracking endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.experiments import store
from app.schemas.models import ExperimentCompareRequest

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.get("")
def list_experiments(
    limit: int = Query(default=50, ge=1, le=200),
    model_key: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    records = store.list_experiments(limit=limit, model_key=model_key)
    return {
        "experiments": [
            {
                "experiment_id": r["experiment_id"],
                "created_at": r["created_at"],
                "label": r["label"],
                "model_key": r["model_key"],
                "model_display_name": r["model_display_name"],
                "target": r["target"],
                "location_label": r["location_label"],
                "period_start": r["period_start"],
                "period_end": r["period_end"],
                "n_train": r["n_train"],
                "n_test": r["n_test"],
                "rmse_wm2": (r.get("metrics", {}).get("physical") or {}).get("rmse"),
                "mae_wm2": (r.get("metrics", {}).get("physical") or {}).get("mae"),
                "r2": (r.get("metrics", {}).get("physical") or {}).get("r2"),
                "skill_scores": r.get("skill_scores", {}),
                "n_warnings": len(r.get("warnings", [])),
            }
            for r in records
        ],
        "count": len(records),
    }


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str) -> dict[str, Any]:
    record = store.get_experiment(experiment_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment '{experiment_id}' was not found in the experiment store.",
        )
    return record


@router.post("/compare")
def compare(request: ExperimentCompareRequest) -> dict[str, Any]:
    """Compare stored experiments, refusing to rank runs that are not comparable."""
    return store.compare(request.experiment_ids)
