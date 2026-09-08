"""Analysis orchestration and in-process caching.

A full analysis — fetch, quality-assess, feature-build, train, cross-validate, calibrate
intervals — takes tens of seconds. Repeating that for every panel of the interface would
be unusable, so an analysis is created once, assigned an id, and its artefacts are held in
memory for follow-up requests.

The cache is bounded and evicts least-recently-used entries. It is per-process and
deliberately not shared: a restart loses cached analyses but loses nothing durable, since
every experiment is persisted to the experiment store as it completes.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.config import get_settings
from app.data.sources import (
    InsufficientDataError,
    Location,
    fetch_archive,
    latest_available_archive_date,
    resolve_location,
)
from app.features.pipeline import FeatureSet, build_features
from app.features.solar_geometry import PVSystem
from app.models.trainer import TrainingResult, train_and_evaluate
from app.quality import engine as quality_engine

logger = logging.getLogger(__name__)

MAX_CACHED_ANALYSES = 12


@dataclass
class Analysis:
    """One completed analysis and everything derived from it."""

    analysis_id: str
    location: Location
    raw: pd.DataFrame = field(repr=False)
    features: FeatureSet = field(repr=False)
    training: TrainingResult = field(repr=False)
    quality: dict[str, Any]
    system: PVSystem
    request_signature: str
    created_at: float
    horizon_hours: int
    experiment_id: str | None = None
    derived: dict[str, Any] = field(default_factory=dict, repr=False)

    def summary(self) -> dict[str, Any]:
        t = self.training
        phys = t.test_metrics_physical

        # Headline keys carry their unit in the name, so a reader cannot mistake an energy
        # figure for an irradiance one. The irradiance suffix is unchanged from before the
        # energy target existed; an energy run publishes the kWh variants instead.
        unit_suffix = "kwh" if t.target_name == "pv_kwh" else "wm2"
        return {
            "analysis_id": self.analysis_id,
            "experiment_id": self.experiment_id,
            "location": self.location.to_dict(),
            "system": self.system.describe(),
            "model": {
                "key": t.model_key,
                "display_name": t.model_display_name,
                "target": t.target_name,
            },
            "data_quality": {
                "overall_score": self.quality.get("overall_score"),
                "grade": self.quality.get("grade"),
                "worst_severity": self.quality.get("worst_severity"),
                "counts": self.quality.get("counts"),
                "blocking_issues": self.quality.get("blocking_issues", []),
            },
            "dataset": t.manifest.get("dataset", {}),
            "validation": t.manifest.get("validation", {}),
            "headline": {
                f"rmse_{unit_suffix}": phys.get("rmse"),
                f"mae_{unit_suffix}": phys.get("mae"),
                "r2": phys.get("r2"),
                "rrmse_pct": phys.get("rrmse"),
                f"mbe_{unit_suffix}": phys.get("mbe"),
                "n_test": phys.get("n"),
                f"observed_mean_{unit_suffix}": phys.get("observed_mean"),
                "unit": phys.get("unit", "W/m²"),
            },
            "cv_summary": t.cv_summary,
            "skill_scores": t.skill_scores,
            "interval_metrics": t.interval_metrics,
            "warnings": t.warnings,
            "timings": t.timings,
        }


class AnalysisCache:
    """Thread-safe, bounded, LRU cache of completed analyses."""

    def __init__(self, max_entries: int = MAX_CACHED_ANALYSES) -> None:
        self._entries: OrderedDict[str, Analysis] = OrderedDict()
        self._by_signature: dict[str, str] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    def get(self, analysis_id: str) -> Analysis | None:
        with self._lock:
            entry = self._entries.get(analysis_id)
            if entry is not None:
                self._entries.move_to_end(analysis_id)
            return entry

    def find_by_signature(self, signature: str) -> Analysis | None:
        with self._lock:
            analysis_id = self._by_signature.get(signature)
            if analysis_id is None:
                return None
            entry = self._entries.get(analysis_id)
            if entry is not None:
                self._entries.move_to_end(analysis_id)
            return entry

    def put(self, analysis: Analysis) -> None:
        with self._lock:
            self._entries[analysis.analysis_id] = analysis
            self._by_signature[analysis.request_signature] = analysis.analysis_id
            self._entries.move_to_end(analysis.analysis_id)
            while len(self._entries) > self._max:
                evicted_id, evicted = self._entries.popitem(last=False)
                self._by_signature.pop(evicted.request_signature, None)
                logger.info("Evicted cached analysis %s", evicted_id)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"cached_analyses": len(self._entries), "capacity": self._max}


CACHE = AnalysisCache()


def _signature(**kwargs: Any) -> str:
    payload = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def resolve_period(
    start: date | None, end: date | None
) -> tuple[date, date, list[str]]:
    """Resolve the analysis period, clamping to what the archive actually covers."""
    settings = get_settings()
    notes: list[str] = []

    latest = latest_available_archive_date()
    resolved_end = end or latest
    if resolved_end > latest:
        notes.append(
            f"The requested end date {resolved_end.isoformat()} is beyond the reanalysis "
            f"archive, which currently extends to {latest.isoformat()}. The period was "
            f"clamped; reanalysis is published on a delay of about "
            f"{settings.limits.archive_lag_days} days."
        )
        resolved_end = latest

    resolved_start = start or (resolved_end - timedelta(days=settings.limits.default_training_days))

    earliest = date.fromisoformat(settings.limits.earliest_date)
    if resolved_start < earliest:
        notes.append(
            f"The start date was moved forward to {earliest.isoformat()}, the earliest date "
            f"available from this source."
        )
        resolved_start = earliest

    return resolved_start, resolved_end, notes


def create_analysis(
    *,
    location_query: str | None,
    latitude: float | None,
    longitude: float | None,
    start: date | None,
    end: date | None,
    model_key: str,
    target: str,
    system: PVSystem,
    horizon_hours: int,
    test_fraction: float,
    cv_splits: int,
    nominal_coverage: float,
    compute_intervals: bool,
    run_cv: bool,
    force: bool = False,
) -> tuple[Analysis, list[str]]:
    """Run the full analysis pipeline, or return a cached equivalent."""
    settings = get_settings()
    location = resolve_location(query=location_query, latitude=latitude, longitude=longitude)
    resolved_start, resolved_end, notes = resolve_period(start, end)

    signature = _signature(
        lat=round(location.latitude, 4),
        lon=round(location.longitude, 4),
        start=resolved_start,
        end=resolved_end,
        model=model_key,
        target=target,
        test_fraction=test_fraction,
        cv=cv_splits,
        coverage=nominal_coverage,
        intervals=compute_intervals,
        run_cv=run_cv,
        tilt=system.surface_tilt_deg,
        azimuth=system.surface_azimuth_deg,
        kwp=system.dc_capacity_kwp,
    )

    if not force:
        cached = CACHE.find_by_signature(signature)
        if cached is not None:
            logger.info("Reusing cached analysis %s", cached.analysis_id)
            return cached, notes + ["Reused a cached analysis with identical parameters."]

    raw = fetch_archive(location, resolved_start, resolved_end)

    quality = quality_engine.assess(
        raw,
        latitude=location.latitude,
        longitude=location.longitude,
        min_rows=24 * settings.limits.min_training_days,
    )
    quality_payload = quality.to_dict()

    if quality.blocking_issues:
        raise InsufficientDataError(
            "The retrieved data cannot support a reliable analysis.",
            detail=" ".join(quality.blocking_issues),
        )

    features = build_features(raw, location, target=target, system=system, daytime_only=True)

    if len(features.frame) < 200:
        raise InsufficientDataError(
            f"Only {len(features.frame):,} usable daylight observations remain after "
            f"removing night hours and incomplete records — too few to train and validate "
            f"a model.",
            detail=f"Dropped rows: {features.dropped_rows}",
        )

    training = train_and_evaluate(
        features,
        model_key=model_key,
        test_fraction=test_fraction,
        cv_splits=cv_splits,
        seed=settings.modelling.random_seed,
        horizon_hours=horizon_hours,
        compute_intervals=compute_intervals,
        nominal_coverage=nominal_coverage,
        run_cv=run_cv,
    )

    analysis = Analysis(
        analysis_id=hashlib.sha256(f"{signature}{time.time()}".encode()).hexdigest()[:16],
        location=location,
        raw=raw,
        features=features,
        training=training,
        quality=quality_payload,
        system=system,
        request_signature=signature,
        created_at=time.time(),
        horizon_hours=horizon_hours,
    )
    CACHE.put(analysis)
    return analysis, notes


def to_pv_system(payload: Any) -> PVSystem:
    """Build a validated PVSystem from a request payload."""
    if payload is None:
        return PVSystem()
    return PVSystem(
        dc_capacity_kwp=payload.dc_capacity_kwp,
        surface_tilt_deg=payload.surface_tilt_deg,
        surface_azimuth_deg=payload.surface_azimuth_deg,
        temperature_coefficient_per_c=payload.temperature_coefficient_per_c,
        system_losses_fraction=payload.system_losses_fraction,
        inverter_efficiency=payload.inverter_efficiency,
        inverter_ac_capacity_kw=payload.inverter_ac_capacity_kw,
        albedo=payload.albedo,
    )
