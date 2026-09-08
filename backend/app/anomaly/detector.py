"""Anomaly detection.

Scope discipline
----------------
This module detects **statistical and physical irregularities in the data and in the
model's residuals**. It does not diagnose equipment faults, and it does not claim to.

That restraint is deliberate. With reanalysis weather data and no metered plant output,
there is no observable signal that could distinguish a soiled array from a passing cloud.
Presenting a residual spike as "panel degradation detected" would be fabrication. Where a
finding has several plausible explanations, all of them are listed and none is asserted.

Detector families
-----------------
``physical``      Values outside physically possible bounds.
``clear_sky``     Irradiance inconsistent with the clear-sky ceiling.
``residual``      Hours the fitted model gets unusually wrong.
``ramp``          Abrupt hour-to-hour changes (the rapid-change events of [P3]).
``gap``           Missing or irregular records.
``distribution``  Drift between the training period and the evaluation period.

Thresholds use robust statistics — median and median absolute deviation — so that the
anomalies being searched for do not inflate the threshold meant to catch them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.features.parameters import PARAMETERS

MAD_TO_SIGMA = 1.4826


@dataclass
class Anomaly:
    timestamp: str
    detector: str
    variable: str
    severity: str            # "low" | "medium" | "high"
    observed: float | None
    expected: float | None
    expected_low: float | None
    expected_high: float | None
    deviation_sigma: float | None
    description: str
    possible_causes: list[str] = field(default_factory=list)
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "detector": self.detector,
            "variable": self.variable,
            "severity": self.severity,
            "observed": self.observed,
            "expected": self.expected,
            "expected_low": self.expected_low,
            "expected_high": self.expected_high,
            "deviation_sigma": self.deviation_sigma,
            "description": self.description,
            "possible_causes": list(self.possible_causes),
            "confidence": self.confidence,
        }


def _robust_scale(values: np.ndarray) -> tuple[float, float]:
    """Median and MAD-derived sigma, ignoring non-finite values."""
    finite = values[np.isfinite(values)]
    if finite.size < 8:
        return float("nan"), float("nan")
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    return median, mad * MAD_TO_SIGMA


def _severity(sigma: float) -> str:
    if sigma >= 6.0:
        return "high"
    if sigma >= 4.0:
        return "medium"
    return "low"


def detect_physical(frame: pd.DataFrame, *, limit: int = 200) -> list[Anomaly]:
    """Values outside the physically possible range for their parameter."""
    out: list[Anomaly] = []
    for column in frame.columns:
        param = PARAMETERS.get(column)
        if param is None or not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        if param.valid_min is None and param.valid_max is None:
            continue

        values = frame[column].to_numpy(dtype=np.float64)
        bad = np.zeros(len(values), dtype=bool)
        if param.valid_min is not None:
            bad |= np.isfinite(values) & (values < param.valid_min)
        if param.valid_max is not None:
            bad |= np.isfinite(values) & (values > param.valid_max)
        bad |= np.isinf(values)

        for pos in np.where(bad)[0][:limit]:
            out.append(
                Anomaly(
                    timestamp=str(frame.index[pos]),
                    detector="physical",
                    variable=column,
                    severity="high",
                    observed=float(values[pos]) if np.isfinite(values[pos]) else None,
                    expected=None,
                    expected_low=param.valid_min,
                    expected_high=param.valid_max,
                    deviation_sigma=None,
                    description=(
                        f"{param.display_name} of {values[pos]:.2f} {param.unit or ''} is "
                        f"outside the physically possible range "
                        f"[{param.valid_min}, {param.valid_max}]."
                    ).strip(),
                    possible_causes=[
                        "Sensor fault or calibration error",
                        "Unit mismatch in the source data",
                        "Encoding of a missing-value sentinel as a real number",
                    ],
                    confidence="high",
                )
            )
    return out


def detect_clear_sky_violations(frame: pd.DataFrame, *, limit: int = 200) -> list[Anomaly]:
    """Irradiance materially above the modelled clear-sky ceiling."""
    if "ghi_wm2" not in frame or "clear_sky_ghi_wm2" not in frame:
        return []

    ghi = frame["ghi_wm2"].to_numpy(dtype=np.float64)
    cs = frame["clear_sky_ghi_wm2"].to_numpy(dtype=np.float64)
    lit = cs > 50.0
    ratio = np.full(len(ghi), np.nan)
    ratio[lit] = ghi[lit] / cs[lit]

    offenders = np.where(np.isfinite(ratio) & (ratio > 1.15))[0]
    out: list[Anomaly] = []
    for pos in offenders[:limit]:
        out.append(
            Anomaly(
                timestamp=str(frame.index[pos]),
                detector="clear_sky",
                variable="ghi_wm2",
                severity="medium" if ratio[pos] < 1.35 else "high",
                observed=float(ghi[pos]),
                expected=float(cs[pos]),
                expected_low=0.0,
                expected_high=float(cs[pos] * 1.15),
                deviation_sigma=None,
                description=(
                    f"Observed irradiance of {ghi[pos]:.0f} W/m² is "
                    f"{ratio[pos]:.2f}× the modelled clear-sky value of {cs[pos]:.0f} W/m²."
                ),
                possible_causes=[
                    "Cloud enhancement — forward scattering off cloud edges, which is real "
                    "and brief",
                    "Clear-sky model under-estimating at this elevation, since the Haurwitz "
                    "model carries no altitude term",
                    "Sensor calibration drift",
                ],
                confidence="medium",
            )
        )
    return out


def detect_residual_anomalies(
    predictions: pd.DataFrame, *, sigma_threshold: float = 4.0, limit: int = 200
) -> list[Anomaly]:
    """Hours the model gets unusually wrong relative to its own typical error."""
    if predictions.empty or "residual_wm2" not in predictions:
        return []

    residuals = predictions["residual_wm2"].to_numpy(dtype=np.float64)
    median, sigma = _robust_scale(residuals)
    if not np.isfinite(sigma) or sigma <= 0:
        return []

    z = (residuals - median) / sigma
    flagged = np.where(np.abs(z) > sigma_threshold)[0]
    order = flagged[np.argsort(-np.abs(z[flagged]))][:limit]

    out: list[Anomaly] = []
    for pos in order:
        observed = float(predictions["observed_ghi_wm2"].iloc[pos])
        predicted = float(predictions["predicted_ghi_wm2"].iloc[pos])
        under = residuals[pos] > 0
        regime = str(predictions["weather_regime"].iloc[pos]) if "weather_regime" in predictions else "unknown"
        out.append(
            Anomaly(
                timestamp=str(predictions.index[pos]),
                detector="residual",
                variable="ghi_wm2",
                severity=_severity(abs(z[pos])),
                observed=observed,
                expected=predicted,
                expected_low=predicted - sigma_threshold * sigma,
                expected_high=predicted + sigma_threshold * sigma,
                deviation_sigma=float(z[pos]),
                description=(
                    f"Observed {observed:.0f} W/m² against a predicted {predicted:.0f} W/m² "
                    f"— the model {'under' if under else 'over'}-forecast by "
                    f"{abs(residuals[pos]):.0f} W/m² ({abs(z[pos]):.1f}σ) under "
                    f"'{regime}' conditions."
                ),
                possible_causes=(
                    [
                        "Unforecast cloud clearance",
                        "Rapid weather change the hourly inputs cannot resolve",
                        "Reanalysis grid-cell average diverging from the point location",
                    ]
                    if under
                    else [
                        "Unforecast cloud, fog, or aerosol event",
                        "Precipitation not captured at hourly resolution",
                        "Reanalysis grid-cell average diverging from the point location",
                    ]
                ),
                confidence="medium",
            )
        )
    return out


def detect_ramps(
    frame: pd.DataFrame, *, column: str = "clear_sky_index", sigma_threshold: float = 4.0, limit: int = 200
) -> list[Anomaly]:
    """Abrupt hour-to-hour changes — the rapidly changing conditions of [P3]."""
    if column not in frame:
        return []

    values = frame[column].to_numpy(dtype=np.float64)
    diffs = np.diff(values, prepend=np.nan)
    median, sigma = _robust_scale(diffs)
    if not np.isfinite(sigma) or sigma <= 0:
        return []

    z = (diffs - median) / sigma
    flagged = np.where(np.isfinite(z) & (np.abs(z) > sigma_threshold))[0]
    order = flagged[np.argsort(-np.abs(z[flagged]))][:limit]

    out: list[Anomaly] = []
    for pos in order:
        direction = "increase" if diffs[pos] > 0 else "decrease"
        out.append(
            Anomaly(
                timestamp=str(frame.index[pos]),
                detector="ramp",
                variable=column,
                severity=_severity(abs(z[pos])),
                observed=float(values[pos]),
                expected=float(values[pos] - diffs[pos]),
                expected_low=None,
                expected_high=None,
                deviation_sigma=float(z[pos]),
                description=(
                    f"Clear-sky index changed by {diffs[pos]:+.3f} in one hour, a "
                    f"{abs(z[pos]):.1f}σ {direction} against the typical hourly change."
                ),
                possible_causes=[
                    "Frontal passage or convective cloud development",
                    "Fog or low-cloud burn-off",
                    "Sunrise or sunset transition where the clear-sky reference is small",
                ],
                confidence="medium",
            )
        )
    return out


def detect_gaps(frame: pd.DataFrame, *, limit: int = 50) -> list[Anomaly]:
    """Interruptions in an otherwise regular time axis."""
    if len(frame) < 3:
        return []

    deltas = pd.Series(frame.index).diff()
    modal = deltas.mode()
    expected = modal.iloc[0] if len(modal) else pd.Timedelta(hours=1)

    out: list[Anomaly] = []
    for pos in np.where((deltas > expected * 1.5).to_numpy())[0][:limit]:
        missing = int(deltas.iloc[pos] / expected) - 1
        out.append(
            Anomaly(
                timestamp=str(frame.index[pos]),
                detector="gap",
                variable="__record__",
                severity="high" if missing > 24 else "medium",
                observed=None,
                expected=None,
                expected_low=None,
                expected_high=None,
                deviation_sigma=None,
                description=(
                    f"A gap of {deltas.iloc[pos]} precedes this record — approximately "
                    f"{missing} expected observations are absent."
                ),
                possible_causes=[
                    "Upstream service outage over this period",
                    "Records excluded by an earlier quality filter",
                    "Genuine interruption in the source archive",
                ],
                confidence="high",
            )
        )
    return out


def detect_distribution_shift(
    train_frame: pd.DataFrame, test_frame: pd.DataFrame, *, columns: list[str] | None = None
) -> list[dict[str, Any]]:
    """Compare the training and evaluation distributions, feature by feature.

    Uses standardised mean difference plus a Kolmogorov-Smirnov statistic. Meaningful
    shift means a model validated on one period may not transfer to the other, and it is
    the most common reason a model that scored well degrades after deployment.
    """
    from scipy import stats

    columns = columns or [
        c for c in train_frame.columns
        if c in PARAMETERS and pd.api.types.is_numeric_dtype(train_frame[c])
    ]

    findings: list[dict[str, Any]] = []
    for column in columns:
        a = train_frame[column].to_numpy(dtype=np.float64)
        b = test_frame[column].to_numpy(dtype=np.float64)
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if a.size < 30 or b.size < 30:
            continue

        pooled_std = np.sqrt((np.var(a) + np.var(b)) / 2.0)
        smd = float((np.mean(b) - np.mean(a)) / pooled_std) if pooled_std > 0 else 0.0
        ks_stat, ks_p = stats.ks_2samp(a, b)

        if abs(smd) >= 0.5 or ks_stat >= 0.2:
            severity = "high" if (abs(smd) >= 0.8 or ks_stat >= 0.3) else "medium"
        elif abs(smd) >= 0.2:
            severity = "low"
        else:
            continue

        param = PARAMETERS.get(column)
        findings.append(
            {
                "variable": column,
                "display_name": param.display_name if param else column,
                "unit": param.unit if param else None,
                "severity": severity,
                "train_mean": float(np.mean(a)),
                "test_mean": float(np.mean(b)),
                "standardised_mean_difference": smd,
                "ks_statistic": float(ks_stat),
                "ks_p_value": float(ks_p),
                "description": (
                    f"{param.display_name if param else column} shifts from "
                    f"{np.mean(a):.2f} in training to {np.mean(b):.2f} in evaluation "
                    f"({smd:+.2f} standardised difference, KS={ks_stat:.3f})."
                ),
            }
        )

    findings.sort(key=lambda f: abs(f["standardised_mean_difference"]), reverse=True)
    return findings


def summarise(anomalies: list[Anomaly]) -> dict[str, Any]:
    """Aggregate counts by detector and severity."""
    by_detector: dict[str, int] = {}
    by_severity: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    for a in anomalies:
        by_detector[a.detector] = by_detector.get(a.detector, 0) + 1
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
    return {
        "total": len(anomalies),
        "by_detector": by_detector,
        "by_severity": by_severity,
        "scope_note": (
            "These are statistical and physical irregularities in the data and in model "
            "residuals. They are not equipment diagnoses: with reanalysis weather and no "
            "metered plant output, this platform cannot distinguish a hardware fault from "
            "a weather event, and does not claim to."
        ),
    }
