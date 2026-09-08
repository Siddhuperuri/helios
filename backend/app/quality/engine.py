"""Data quality assessment with a fully transparent score.

Why the arithmetic is exposed
-----------------------------
A bare "DATA QUALITY: 94%" is an assertion, not evidence. Every check here declares its
own weight, its own pass/warn/fail thresholds, and the exact count that produced its
sub-score, and the API returns all of it. A reviewer can recompute the headline number by
hand from the returned payload. If they disagree with a weight, they can see precisely
which weight to argue with.

Checks are ordered from structural (does the time axis make sense?) through physical
(are these values possible?) to statistical (are these values plausible?). Structural
failures are weighted hardest because they invalidate everything downstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from app.features.parameters import PARAMETERS
from app.features.solar_geometry import (
    clear_sky_ghi_haurwitz,
    representative_times,
    solar_position,
)


class Severity(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"


@dataclass
class QualityCheck:
    """A single quality check, carrying its own evidence."""

    key: str
    title: str
    severity: Severity
    score: float               # 0.0 - 1.0, contribution before weighting
    weight: float              # relative importance in the headline score
    message: str               # human-readable, always contains the actual numbers
    affected_rows: int = 0
    total_rows: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
    remedy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "severity": self.severity.value,
            "score": round(self.score, 4),
            "weight": self.weight,
            "weighted_contribution": round(self.score * self.weight, 4),
            "message": self.message,
            "affected_rows": self.affected_rows,
            "total_rows": self.total_rows,
            "affected_fraction": (
                round(self.affected_rows / self.total_rows, 5) if self.total_rows else 0.0
            ),
            "detail": self.detail,
            "remedy": self.remedy,
        }


@dataclass
class QualityReport:
    checks: list[QualityCheck]
    overall_score: float
    grade: str
    blocking_issues: list[str]
    row_count: int
    period_start: str | None
    period_end: str | None
    worst_severity: str = "pass"

    def to_dict(self) -> dict[str, Any]:
        total_weight = sum(c.weight for c in self.checks) or 1.0
        # Floor rather than round the displayed score. Rounding 99.96 up to "100.0%" reads
        # as a perfect result while a warning is still outstanding, which is exactly the
        # kind of small dishonesty this engine exists to avoid. Only a genuinely perfect
        # score displays as 100.
        displayed = (
            100.0
            if self.overall_score >= 1.0
            else math.floor(self.overall_score * 1000) / 10.0
        )
        return {
            "overall_score": displayed,
            "grade": self.grade,
            "row_count": self.row_count,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "blocking_issues": list(self.blocking_issues),
            "worst_severity": self.worst_severity,
            "counts": {
                "pass": sum(1 for c in self.checks if c.severity is Severity.PASS),
                "warn": sum(1 for c in self.checks if c.severity is Severity.WARN),
                "fail": sum(1 for c in self.checks if c.severity is Severity.FAIL),
            },
            "checks": [c.to_dict() for c in self.checks],
            "methodology": {
                "formula": "score = Σ(check_score × check_weight) / Σ(check_weight)",
                "total_weight": round(total_weight, 3),
                "weighted_sum": round(
                    sum(c.score * c.weight for c in self.checks), 4
                ),
                "note": (
                    "Every check publishes its own score, weight and row counts, so the "
                    "headline figure can be recomputed from this payload."
                ),
                "grade_capping": (
                    "The grade label is capped by the worst individual severity: any "
                    "failed check caps it at 'Poor', any warning at 'Good'. This prevents "
                    "a high mean from masking a defect that invalidates the dataset."
                ),
            },
        }

    @property
    def is_usable(self) -> bool:
        return not self.blocking_issues


def _grade(score: float, *, has_fail: bool = False, has_warn: bool = False) -> str:
    """Map the weighted score to a grade, capped by the worst individual severity.

    The weighted mean alone is misleading. With ~26 checks running, two hard failures
    that invalidate the whole dataset - a six-hour timezone error, say - are diluted by
    two dozen passes into a mean above 0.90, which would read as "Good". A grade is a
    summary a reviewer will act on, so a single failed check caps it at "Poor" regardless
    of how many other checks passed. The numeric score is still reported unchanged; only
    the label is constrained.
    """
    if score >= 0.95:
        label = "Excellent"
    elif score >= 0.85:
        label = "Good"
    elif score >= 0.70:
        label = "Acceptable"
    elif score >= 0.50:
        label = "Poor"
    else:
        label = "Unusable"

    order = ["Unusable", "Poor", "Acceptable", "Good", "Excellent"]
    if has_fail:
        cap = "Poor"
    elif has_warn:
        cap = "Good"
    else:
        return label
    return label if order.index(label) <= order.index(cap) else cap


def _pct(n: int, total: int) -> str:
    return f"{(100.0 * n / total):.1f}%" if total else "0.0%"


# --------------------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------------------

def _check_row_count(frame: pd.DataFrame, min_rows: int) -> QualityCheck:
    n = len(frame)
    if n >= min_rows:
        return QualityCheck(
            key="row_count",
            title="Sample size",
            severity=Severity.PASS,
            score=1.0,
            weight=3.0,
            message=f"{n:,} hourly observations retrieved, above the minimum of {min_rows:,}.",
            total_rows=n,
        )
    ratio = n / min_rows if min_rows else 0.0
    return QualityCheck(
        key="row_count",
        title="Sample size",
        severity=Severity.FAIL if ratio < 0.5 else Severity.WARN,
        score=max(0.0, ratio),
        weight=3.0,
        message=(
            f"Only {n:,} hourly observations are available, below the minimum of "
            f"{min_rows:,} needed for time-aware cross-validation."
        ),
        total_rows=n,
        remedy="Extend the training window, or reduce the number of cross-validation folds.",
    )


def _check_duplicate_timestamps(frame: pd.DataFrame) -> QualityCheck:
    n = len(frame)
    dupes = int(frame.index.duplicated().sum())
    if dupes == 0:
        return QualityCheck(
            key="duplicate_timestamps",
            title="Timestamp uniqueness",
            severity=Severity.PASS,
            score=1.0,
            weight=3.0,
            message="No duplicate timestamps.",
            total_rows=n,
        )
    return QualityCheck(
        key="duplicate_timestamps",
        title="Timestamp uniqueness",
        severity=Severity.FAIL,
        score=max(0.0, 1.0 - dupes / max(n, 1)),
        weight=3.0,
        message=(
            f"{dupes:,} duplicate timestamps ({_pct(dupes, n)}). Duplicates break the "
            f"chronological ordering that time-aware validation depends on."
        ),
        affected_rows=dupes,
        total_rows=n,
        remedy="Deduplicate by timestamp, keeping the last observation for each hour.",
    )


def _check_monotonic(frame: pd.DataFrame) -> QualityCheck:
    n = len(frame)
    ok = bool(frame.index.is_monotonic_increasing)
    return QualityCheck(
        key="chronological_order",
        title="Chronological ordering",
        severity=Severity.PASS if ok else Severity.FAIL,
        score=1.0 if ok else 0.0,
        weight=2.0,
        message=(
            "Observations are in strictly increasing time order."
            if ok
            else "Observations are not in chronological order, which invalidates any "
            "time-ordered split."
        ),
        total_rows=n,
        remedy=None if ok else "Sort the dataset by timestamp before use.",
    )


def _check_sampling_regularity(frame: pd.DataFrame) -> QualityCheck:
    n = len(frame)
    if n < 3:
        return QualityCheck(
            key="sampling_regularity",
            title="Sampling regularity",
            severity=Severity.WARN,
            score=0.5,
            weight=2.0,
            message="Too few observations to assess sampling regularity.",
            total_rows=n,
        )

    deltas = pd.Series(frame.index).diff().dropna()
    modal = deltas.mode()
    expected = modal.iloc[0] if len(modal) else pd.Timedelta(hours=1)
    irregular = int((deltas != expected).sum())
    ratio = irregular / max(len(deltas), 1)

    if ratio == 0:
        return QualityCheck(
            key="sampling_regularity",
            title="Sampling regularity",
            severity=Severity.PASS,
            score=1.0,
            weight=2.0,
            message=f"Uniform {expected} sampling interval throughout.",
            total_rows=n,
            detail={"modal_interval": str(expected)},
        )

    severity = Severity.FAIL if ratio > 0.10 else Severity.WARN
    return QualityCheck(
        key="sampling_regularity",
        title="Sampling regularity",
        severity=severity,
        score=max(0.0, 1.0 - ratio * 2.0),
        weight=2.0,
        message=(
            f"{irregular:,} of {len(deltas):,} intervals ({_pct(irregular, len(deltas))}) "
            f"differ from the modal interval of {expected}."
        ),
        affected_rows=irregular,
        total_rows=n,
        detail={
            "modal_interval": str(expected),
            "largest_gap": str(deltas.max()),
        },
        remedy="Reindex onto a regular hourly grid, leaving genuine gaps as missing.",
    )


def _check_coverage(frame: pd.DataFrame) -> QualityCheck:
    """Actual rows versus the number the period should contain."""
    n = len(frame)
    if n < 2:
        return QualityCheck(
            key="temporal_coverage",
            title="Temporal coverage",
            severity=Severity.WARN,
            score=0.0,
            weight=2.0,
            message="Insufficient observations to assess coverage.",
            total_rows=n,
        )
    span_hours = int((frame.index.max() - frame.index.min()).total_seconds() // 3600) + 1
    coverage = n / span_hours if span_hours else 0.0
    missing_hours = max(0, span_hours - n)

    if coverage >= 0.99:
        sev, score = Severity.PASS, 1.0
    elif coverage >= 0.95:
        sev, score = Severity.WARN, coverage
    else:
        sev, score = Severity.FAIL, coverage

    return QualityCheck(
        key="temporal_coverage",
        title="Temporal coverage",
        severity=sev,
        score=float(np.clip(score, 0.0, 1.0)),
        weight=2.0,
        message=(
            f"{n:,} observations cover a {span_hours:,}-hour period "
            f"({coverage * 100:.1f}% complete; {missing_hours:,} hours absent)."
        ),
        affected_rows=missing_hours,
        total_rows=span_hours,
        remedy=(
            None
            if coverage >= 0.99
            else "Gaps are preserved as missing rather than filled; models train on "
            "complete records only."
        ),
    )


def _check_missing_values(frame: pd.DataFrame) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    n = len(frame)
    for column in frame.columns:
        if column not in PARAMETERS:
            continue
        series = frame[column]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        missing = int(series.isna().sum())
        param = PARAMETERS[column]
        frac = missing / n if n else 0.0

        if missing == 0:
            severity, score = Severity.PASS, 1.0
            message = f"{param.display_name}: complete, no missing values."
        elif frac <= 0.02:
            severity, score = Severity.WARN, 1.0 - frac
            message = (
                f"{param.display_name}: {missing:,} values missing ({_pct(missing, n)})."
            )
        else:
            severity, score = Severity.FAIL, max(0.0, 1.0 - frac * 2.0)
            message = (
                f"{param.display_name}: {missing:,} values missing ({_pct(missing, n)}), "
                f"above the 2% tolerance."
            )

        checks.append(
            QualityCheck(
                key=f"missing__{column}",
                title=f"Completeness — {param.display_name}",
                severity=severity,
                score=score,
                weight=1.5 if param.required else 0.8,
                message=message,
                affected_rows=missing,
                total_rows=n,
                remedy=(
                    None
                    if missing == 0
                    else "Rows with missing predictors are excluded from training; no "
                    "value is imputed."
                ),
            )
        )
    return checks


def _check_physical_ranges(frame: pd.DataFrame) -> list[QualityCheck]:
    """Values outside physically possible bounds.

    Note this checks *physical possibility*, never statistical unusualness. A midday
    clear-sky GHI of 1000 W/m² is a large number and a perfectly valid one.
    """
    checks: list[QualityCheck] = []
    n = len(frame)
    for column in frame.columns:
        param = PARAMETERS.get(column)
        if param is None or not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        if param.valid_min is None and param.valid_max is None:
            continue

        values = frame[column].to_numpy(dtype=np.float64)
        finite = np.isfinite(values)
        below = int(np.sum(finite & (values < param.valid_min))) if param.valid_min is not None else 0
        above = int(np.sum(finite & (values > param.valid_max))) if param.valid_max is not None else 0
        nonfinite = int(np.sum(~finite & ~np.isnan(values)))  # inf, -inf
        violations = below + above + nonfinite

        if violations == 0:
            checks.append(
                QualityCheck(
                    key=f"range__{column}",
                    title=f"Physical range — {param.display_name}",
                    severity=Severity.PASS,
                    score=1.0,
                    weight=1.2,
                    message=(
                        f"{param.display_name}: all values within the physical range "
                        f"[{param.valid_min}, {param.valid_max}] {param.unit or ''}".strip()
                    ),
                    total_rows=n,
                )
            )
            continue

        frac = violations / n if n else 0.0
        parts = []
        if below:
            parts.append(f"{below:,} below {param.valid_min}")
        if above:
            parts.append(f"{above:,} above {param.valid_max}")
        if nonfinite:
            parts.append(f"{nonfinite:,} non-finite")

        checks.append(
            QualityCheck(
                key=f"range__{column}",
                title=f"Physical range — {param.display_name}",
                severity=Severity.FAIL if frac > 0.01 else Severity.WARN,
                score=max(0.0, 1.0 - frac * 3.0),
                weight=1.2,
                message=(
                    f"{param.display_name}: {violations:,} values outside the physical "
                    f"range ({', '.join(parts)})."
                ),
                affected_rows=violations,
                total_rows=n,
                detail={
                    "valid_min": param.valid_min,
                    "valid_max": param.valid_max,
                    "observed_min": float(np.nanmin(values)) if finite.any() else None,
                    "observed_max": float(np.nanmax(values)) if finite.any() else None,
                },
                remedy=(
                    "Physically impossible values are flagged, not silently corrected. "
                    "Inspect the source before training."
                ),
            )
        )
    return checks


def _check_night_irradiance(
    frame: pd.DataFrame, latitude: float, longitude: float
) -> QualityCheck | None:
    """Irradiance reported when the sun is below the horizon.

    A genuinely diagnostic check: non-zero GHI at night indicates a sensor offset, a
    timezone misalignment, or a timestamp convention mismatch. It is one of the few
    ways to detect a shifted time axis without external reference.
    """
    if "ghi_wm2" not in frame.columns or frame.empty:
        return None

    pos = solar_position(representative_times(frame.index), latitude, longitude)

    # Test *deep* night only (sun more than 5 deg below the horizon), not the whole
    # sub-horizon range. An hourly mean that straddles sunrise legitimately carries a
    # small positive value while its midpoint is already below the 87 deg day threshold,
    # so including twilight hours here would flag correct data as an error.
    deep_night = pos.apparent_zenith > 95.0
    n_night = int(deep_night.sum())
    if n_night == 0:
        return None

    ghi = frame["ghi_wm2"].to_numpy(dtype=np.float64)
    # 5 W/m^2 tolerance absorbs reanalysis rounding.
    offenders = int(np.sum(deep_night & np.isfinite(ghi) & (ghi > 5.0)))
    frac = offenders / n_night
    night = deep_night

    if offenders == 0:
        return QualityCheck(
            key="night_irradiance",
            title="Night-time irradiance consistency",
            severity=Severity.PASS,
            score=1.0,
            weight=2.0,
            message=(
                f"All {n_night:,} full-darkness hours (sun below -5 deg) report zero "
                f"irradiance, consistent with the computed solar position."
            ),
            total_rows=n_night,
        )

    max_night = float(np.nanmax(np.where(night, ghi, np.nan)))
    return QualityCheck(
        key="night_irradiance",
        title="Night-time irradiance consistency",
        severity=Severity.FAIL if frac > 0.02 else Severity.WARN,
        score=max(0.0, 1.0 - frac * 4.0),
        weight=2.0,
        message=(
            f"{offenders:,} of {n_night:,} full-darkness hours ({_pct(offenders, n_night)}) "
            f"report irradiance above 5 W/m2, peaking at {max_night:.0f} W/m2. With the sun "
            f"more than 5 deg below the horizon this cannot be twilight, and indicates a "
            f"timezone offset or a timestamp convention mismatch."
        ),
        affected_rows=offenders,
        total_rows=n_night,
        remedy="Verify that timestamps are UTC and that they label the start of each interval.",
    )


def _check_clear_sky_exceedance(
    frame: pd.DataFrame, latitude: float, longitude: float
) -> QualityCheck | None:
    """Irradiance materially above the clear-sky ceiling.

    Brief excursions above clear-sky are real (cloud-enhancement). Sustained exceedance
    is not, and points at a calibration or units problem.
    """
    if "ghi_wm2" not in frame.columns or frame.empty:
        return None

    pos = solar_position(representative_times(frame.index), latitude, longitude)
    cs = clear_sky_ghi_haurwitz(pos.apparent_zenith)

    ghi = frame["ghi_wm2"].to_numpy(dtype=np.float64)
    lit = (cs > 50.0) & np.isfinite(ghi)
    n_lit = int(lit.sum())
    if n_lit == 0:
        return None

    # 1.15 allows genuine cloud-enhancement; beyond that is not physical for hourly means.
    offenders = int(np.sum(lit & (ghi > cs * 1.15)))
    frac = offenders / n_lit

    if frac <= 0.005:
        return QualityCheck(
            key="clear_sky_exceedance",
            title="Clear-sky ceiling consistency",
            severity=Severity.PASS,
            score=1.0,
            weight=1.5,
            message=(
                f"{offenders:,} of {n_lit:,} daylight hours ({_pct(offenders, n_lit)}) "
                f"exceed 115% of modelled clear-sky irradiance, consistent with normal "
                f"cloud-enhancement."
            ),
            affected_rows=offenders,
            total_rows=n_lit,
        )

    return QualityCheck(
        key="clear_sky_exceedance",
        title="Clear-sky ceiling consistency",
        severity=Severity.FAIL if frac > 0.05 else Severity.WARN,
        score=max(0.0, 1.0 - frac * 5.0),
        weight=1.5,
        message=(
            f"{offenders:,} of {n_lit:,} daylight hours ({_pct(offenders, n_lit)}) exceed "
            f"115% of modelled clear-sky irradiance. Sustained exceedance suggests a "
            f"units or calibration problem rather than cloud-enhancement."
        ),
        affected_rows=offenders,
        total_rows=n_lit,
        remedy="Confirm irradiance is in W/m² and that the coordinates match the data.",
    )


def _check_variance(frame: pd.DataFrame) -> list[QualityCheck]:
    """Constant columns carry no information and can destabilise scaling."""
    checks: list[QualityCheck] = []
    n = len(frame)
    for column in frame.columns:
        param = PARAMETERS.get(column)
        if param is None or not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        values = frame[column].to_numpy(dtype=np.float64)
        finite = values[np.isfinite(values)]
        if finite.size < 2:
            continue
        if float(np.nanstd(finite)) > 1e-9:
            continue
        checks.append(
            QualityCheck(
                key=f"variance__{column}",
                title=f"Variability — {param.display_name}",
                severity=Severity.WARN,
                score=0.0,
                weight=1.0,
                message=(
                    f"{param.display_name} is constant at {finite[0]:.4g} across all "
                    f"{n:,} observations and carries no predictive information."
                ),
                total_rows=n,
                remedy="Remove the variable, or check whether the sensor is reporting.",
            )
        )
    return checks


def _check_discontinuities(frame: pd.DataFrame) -> list[QualityCheck]:
    """Step changes far larger than the variable's own hour-to-hour behaviour.

    Uses a robust scale (median absolute deviation of the first difference) so that the
    threshold is not itself dragged upward by the jumps it is trying to find.
    """
    checks: list[QualityCheck] = []
    n = len(frame)
    if n < 24:
        return checks

    for column in ("temperature_c", "surface_pressure_hpa", "relative_humidity_pct"):
        if column not in frame.columns:
            continue
        param = PARAMETERS.get(column)
        if param is None:
            continue
        diffs = frame[column].diff().to_numpy(dtype=np.float64)
        finite = diffs[np.isfinite(diffs)]
        if finite.size < 24:
            continue

        mad = float(np.median(np.abs(finite - np.median(finite))))
        if mad < 1e-9:
            continue
        threshold = 10.0 * mad * 1.4826  # scale MAD to a std-equivalent
        jumps = int(np.sum(np.abs(finite) > threshold))
        frac = jumps / finite.size

        if jumps == 0:
            continue

        checks.append(
            QualityCheck(
                key=f"discontinuity__{column}",
                title=f"Continuity — {param.display_name}",
                severity=Severity.WARN if frac < 0.01 else Severity.FAIL,
                score=max(0.0, 1.0 - frac * 10.0),
                weight=0.8,
                message=(
                    f"{param.display_name}: {jumps:,} hour-to-hour steps exceed "
                    f"{threshold:.2f} {param.unit or ''} "
                    f"({_pct(jumps, finite.size)} of intervals)."
                ).strip(),
                affected_rows=jumps,
                total_rows=int(finite.size),
                detail={"robust_threshold": round(threshold, 4)},
                remedy="Inspect these timestamps for sensor resets or record splicing.",
            )
        )
    return checks


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------

def assess(
    frame: pd.DataFrame,
    *,
    latitude: float,
    longitude: float,
    min_rows: int = 24 * 60,
) -> QualityReport:
    """Run the full quality assessment over a raw hourly weather frame."""
    if frame is None or len(frame) == 0:
        return QualityReport(
            checks=[
                QualityCheck(
                    key="empty_dataset",
                    title="Dataset present",
                    severity=Severity.FAIL,
                    score=0.0,
                    weight=1.0,
                    message="The dataset is empty; no quality assessment is possible.",
                )
            ],
            overall_score=0.0,
            grade="Unusable",
            blocking_issues=["The dataset contains no observations."],
            row_count=0,
            period_start=None,
            period_end=None,
        )

    checks: list[QualityCheck] = [
        _check_row_count(frame, min_rows),
        _check_duplicate_timestamps(frame),
        _check_monotonic(frame),
        _check_sampling_regularity(frame),
        _check_coverage(frame),
    ]
    checks.extend(_check_missing_values(frame))
    checks.extend(_check_physical_ranges(frame))
    checks.extend(_check_variance(frame))
    checks.extend(_check_discontinuities(frame))

    night = _check_night_irradiance(frame, latitude, longitude)
    if night is not None:
        checks.append(night)
    ceiling = _check_clear_sky_exceedance(frame, latitude, longitude)
    if ceiling is not None:
        checks.append(ceiling)

    total_weight = sum(c.weight for c in checks) or 1.0
    overall = sum(c.score * c.weight for c in checks) / total_weight

    # A failure in any of these means the dataset is not merely imperfect but wrong in a
    # way that would silently corrupt every downstream result: the time axis is misaligned,
    # the units are off, or the ordering that time-aware validation depends on is broken.
    # Training proceeds only when the caller explicitly overrides.
    blocking_keys = {
        "row_count",
        "duplicate_timestamps",
        "chronological_order",
        "empty_dataset",
        "night_irradiance",
        "clear_sky_exceedance",
    }
    blocking = [c.message for c in checks if c.severity is Severity.FAIL and c.key in blocking_keys]

    has_fail = any(c.severity is Severity.FAIL for c in checks)
    has_warn = any(c.severity is Severity.WARN for c in checks)
    worst = "fail" if has_fail else ("warn" if has_warn else "pass")

    return QualityReport(
        checks=checks,
        overall_score=float(np.clip(overall, 0.0, 1.0)),
        grade=_grade(overall, has_fail=has_fail, has_warn=has_warn),
        blocking_issues=blocking,
        row_count=len(frame),
        period_start=frame.index.min().isoformat(),
        period_end=frame.index.max().isoformat(),
        worst_severity=worst,
    )
