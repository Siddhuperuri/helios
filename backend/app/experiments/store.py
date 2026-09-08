"""Experiment tracking.

A research platform has to answer "which run produced this number, and what changed since
the last one?" without the user keeping their own notes. Every training run is persisted
with its full manifest, so results can be compared and reproduced later.

Storage was newline-delimited JSON on local disk. The original note in this file said that
choice was "not appropriate for concurrent multi-user writes, which is stated rather than
discovered later" — which is exactly the condition the platform is now in. Runs are rows in
PostgreSQL. The record shape, the trimming behaviour and the comparability rules are
unchanged; only the medium moved.

Experiments carry an optional owner for the same reason estimates do, and with the same
ON DELETE SET NULL behaviour: a run's scientific record outlives the account that produced
it. Unlike estimates, the console's listing is not filtered by owner — a shared research
workbench is the point of it — but ownership is recorded so that it can be.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import Experiment as ExperimentRow

logger = logging.getLogger(__name__)


@dataclass
class Experiment:
    experiment_id: str
    created_at: str
    label: str
    model_key: str
    model_display_name: str
    target: str
    location_label: str
    latitude: float
    longitude: float
    period_start: str
    period_end: str
    n_train: int
    n_test: int
    metrics: dict[str, Any] = field(default_factory=dict)
    cv_summary: dict[str, Any] = field(default_factory=dict)
    skill_scores: dict[str, float] = field(default_factory=dict)
    interval_metrics: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    notes: str | None = None
    owner_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
            "label": self.label,
            "model_key": self.model_key,
            "model_display_name": self.model_display_name,
            "target": self.target,
            "location_label": self.location_label,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "metrics": self.metrics,
            "cv_summary": self.cv_summary,
            "skill_scores": self.skill_scores,
            "interval_metrics": self.interval_metrics,
            "manifest": self.manifest,
            "warnings": self.warnings,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Experiment:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})


def _json_safe(value: Any) -> Any:
    """Coerce numpy scalars and the like into something a JSON column will accept.

    The file store got this for free from ``json.dumps(..., default=str)``. A JSON column
    binds the object directly, so the same normalisation has to happen here — otherwise a
    ``numpy.float64`` in a metrics dict fails at insert time rather than at write time,
    which is a much less obvious place to debug it.
    """
    return json.loads(json.dumps(value, default=str))


def _row_to_dict(row: ExperimentRow) -> dict[str, Any]:
    created = row.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "experiment_id": row.experiment_id,
        "created_at": created.isoformat() if created else "",
        "label": row.label,
        "model_key": row.model_key,
        "model_display_name": row.model_display_name,
        "target": row.target,
        "location_label": row.location_label,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "n_train": row.n_train,
        "n_test": row.n_test,
        "metrics": row.metrics or {},
        "cv_summary": row.cv_summary or {},
        "skill_scores": row.skill_scores or {},
        "interval_metrics": row.interval_metrics or {},
        "manifest": row.manifest or {},
        "warnings": row.warnings or [],
        "notes": row.notes,
    }


def record(
    result: Any,
    *,
    location_label: str,
    latitude: float,
    longitude: float,
    label: str | None = None,
    notes: str | None = None,
    owner_id: str | uuid.UUID | None = None,
) -> Experiment:
    """Persist a training run and return the stored record."""
    manifest = result.manifest or {}
    dataset = manifest.get("dataset", {})
    validation = manifest.get("validation", {})

    experiment_id = uuid.uuid4().hex[:12]
    created_at = datetime.now(timezone.utc)

    experiment = Experiment(
        experiment_id=experiment_id,
        created_at=created_at.isoformat(),
        label=label or f"{result.model_display_name} @ {location_label}",
        model_key=result.model_key,
        model_display_name=result.model_display_name,
        target=result.target_name,
        location_label=location_label,
        latitude=latitude,
        longitude=longitude,
        period_start=dataset.get("period_start", ""),
        period_end=dataset.get("period_end", ""),
        n_train=int(validation.get("n_train", 0)),
        n_test=int(validation.get("n_test", 0)),
        metrics={
            "physical": result.test_metrics_physical,
            "target_space": result.test_metrics,
            "train": result.train_metrics,
        },
        cv_summary=result.cv_summary,
        skill_scores=result.skill_scores,
        interval_metrics=result.interval_metrics,
        manifest=manifest,
        warnings=list(result.warnings),
        notes=notes,
        owner_id=str(owner_id) if owner_id else None,
    )

    with session_scope() as session:
        session.add(
            ExperimentRow(
                experiment_id=experiment_id,
                owner_id=_as_uuid(owner_id),
                created_at=created_at,
                label=experiment.label[:255],
                model_key=experiment.model_key[:64],
                model_display_name=(experiment.model_display_name or "")[:128],
                target=(experiment.target or "")[:64],
                location_label=(experiment.location_label or "")[:255],
                latitude=float(experiment.latitude),
                longitude=float(experiment.longitude),
                period_start=str(experiment.period_start)[:32],
                period_end=str(experiment.period_end)[:32],
                n_train=experiment.n_train,
                n_test=experiment.n_test,
                metrics=_json_safe(experiment.metrics),
                cv_summary=_json_safe(experiment.cv_summary),
                skill_scores=_json_safe(experiment.skill_scores),
                interval_metrics=_json_safe(experiment.interval_metrics),
                manifest=_json_safe(experiment.manifest),
                warnings=_json_safe(experiment.warnings),
                notes=experiment.notes,
            )
        )
        session.flush()
        _trim_if_needed(session)

    logger.info("Recorded experiment %s (%s)", experiment_id, experiment.model_key)
    return experiment


def _trim_if_needed(session) -> None:  # noqa: ANN001
    """Keep the store bounded, discarding the oldest records first.

    Same policy as the file store's line trimming, expressed as a delete of everything
    beyond the newest N. Cheap because it only runs when the count is over the limit.
    """
    limit = get_settings().store.max_experiments
    total = int(session.execute(select(func.count()).select_from(ExperimentRow)).scalar_one())
    if total <= limit:
        return

    keep_ids = (
        session.execute(
            select(ExperimentRow.experiment_id)
            .order_by(ExperimentRow.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    session.query(ExperimentRow).filter(
        ExperimentRow.experiment_id.notin_(keep_ids)
    ).delete(synchronize_session=False)
    logger.info("Trimmed experiment store to the newest %d records", limit)


def list_experiments(*, limit: int = 50, model_key: str | None = None) -> list[dict[str, Any]]:
    """Most recent experiments first."""
    with session_scope() as session:
        statement = select(ExperimentRow).order_by(ExperimentRow.created_at.desc())
        if model_key:
            statement = statement.where(ExperimentRow.model_key == model_key)
        rows = session.execute(statement.limit(max(1, min(int(limit), 200)))).scalars().all()
        return [_row_to_dict(row) for row in rows]


def get_experiment(experiment_id: str) -> dict[str, Any] | None:
    if not experiment_id or len(experiment_id) > 64:
        return None
    with session_scope() as session:
        row = session.get(ExperimentRow, experiment_id)
        return _row_to_dict(row) if row is not None else None


def compare(experiment_ids: list[str]) -> dict[str, Any]:
    """Side-by-side comparison of stored experiments.

    Comparability is checked rather than assumed: two runs on different locations or
    different periods are not directly comparable, and the response says so instead of
    quietly ranking them.
    """
    records = [get_experiment(eid) for eid in experiment_ids]
    found = [r for r in records if r is not None]
    missing = [
        eid for eid, r in zip(experiment_ids, records, strict=True) if r is None
    ]

    if not found:
        return {"experiments": [], "missing": missing, "comparable": False,
                "warning": "None of the requested experiments were found."}

    locations = {r["location_label"] for r in found}
    periods = {(r["period_start"], r["period_end"]) for r in found}
    targets = {r["target"] for r in found}

    incomparable: list[str] = []
    if len(locations) > 1:
        incomparable.append(
            f"Different locations ({', '.join(sorted(locations))}) — irradiance regimes "
            f"differ, so error magnitudes are not directly comparable."
        )
    if len(periods) > 1:
        incomparable.append(
            "Different date ranges — models were evaluated on different weather, so the "
            "comparison confounds model quality with period difficulty."
        )
    if len(targets) > 1:
        incomparable.append(
            f"Different modelling targets ({', '.join(sorted(targets))}) — metrics are in "
            f"different units."
        )

    rows = [
        {
            "experiment_id": r["experiment_id"],
            "label": r["label"],
            "created_at": r["created_at"],
            "model": r["model_display_name"],
            "location": r["location_label"],
            "period": f"{r['period_start'][:10]} → {r['period_end'][:10]}",
            "n_train": r["n_train"],
            "n_test": r["n_test"],
            "rmse_wm2": (r.get("metrics", {}).get("physical") or {}).get("rmse"),
            "mae_wm2": (r.get("metrics", {}).get("physical") or {}).get("mae"),
            "r2": (r.get("metrics", {}).get("physical") or {}).get("r2"),
            "cv_rmse_mean": r.get("cv_summary", {}).get("rmse_mean"),
            "cv_rmse_std": r.get("cv_summary", {}).get("rmse_std"),
            "skill_vs_smart_persistence": r.get("skill_scores", {}).get("smart_persistence"),
            "picp": r.get("interval_metrics", {}).get("picp"),
            "n_warnings": len(r.get("warnings", [])),
        }
        for r in found
    ]

    ranked = sorted(
        (row for row in rows if isinstance(row.get("rmse_wm2"), (int, float))),
        key=lambda row: row["rmse_wm2"],
    )

    return {
        "experiments": rows,
        "missing": missing,
        "comparable": not incomparable,
        "comparability_warnings": incomparable,
        "best_by_rmse": ranked[0]["experiment_id"] if ranked and not incomparable else None,
        "ranking_note": (
            "Ranking is withheld because the runs are not directly comparable."
            if incomparable
            else "Ranked by hold-out RMSE in W/m² on the same location and period."
        ),
    }


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
