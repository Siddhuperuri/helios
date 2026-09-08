"""Scientific report generation.

Produces a self-contained Markdown report of a training run: what was predicted, from what
data, by what method, how well, and with what limitations.

The report states only what was measured. It contains no generated conclusions about the
merit of the result, because that judgement belongs to the reader. Where a number needs a
caveat, the caveat is printed next to it rather than in a footnote nobody reads. Where a
capability was not exercised, the report says so explicitly instead of omitting the section
and leaving the absence ambiguous.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.config import get_settings


def _fmt(value: Any, decimals: int = 2, unit: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        if not np.isfinite(value):
            return "—"
        return f"{value:,.{decimals}f}{(' ' + unit) if unit else ''}"
    return str(value)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No data._\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def build_markdown_report(
    *,
    result: Any,
    location_label: str,
    quality: dict[str, Any] | None = None,
    importance: dict[str, Any] | None = None,
    leakage_audit: list[dict[str, Any]] | None = None,
    leakage_experiment: dict[str, Any] | None = None,
    anomaly_summary: dict[str, Any] | None = None,
    narrative: list[str] | None = None,
    experiment_id: str | None = None,
) -> str:
    """Assemble the full report."""
    settings = get_settings()
    manifest = result.manifest or {}
    dataset = manifest.get("dataset", {})
    validation = manifest.get("validation", {})
    model = manifest.get("model", {})
    repro = manifest.get("reproducibility", {})
    preprocessing = manifest.get("preprocessing", {})
    phys = result.test_metrics_physical or {}

    parts: list[str] = []

    parts.append("# Solar Irradiance Forecast — Evaluation Report\n")
    parts.append(
        f"**Location** {location_label}  \n"
        f"**Generated** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"**Platform** {settings.app_name} v{settings.version}  \n"
        + (f"**Experiment ID** `{experiment_id}`  \n" if experiment_id else "")
        + f"**Dataset fingerprint** `{dataset.get('fingerprint', 'n/a')}`\n"
    )

    # ------------------------------------------------------------------ 1
    parts.append("\n---\n\n## 1. What was predicted\n")
    parts.append(
        f"The modelling target is **{result.target_name}**"
        + (
            " (the ratio of observed to clear-sky irradiance), converted back to global "
            "horizontal irradiance in W/m² for all reported figures."
            if result.target_name == "clear_sky_index"
            else " in W/m²."
        )
        + f" Temporal resolution is {dataset.get('temporal_resolution', 'hourly')}. "
        f"Forecast horizon for baseline comparison is "
        f"{validation.get('forecast_horizon_hours', 24)} hours.\n"
    )

    # ------------------------------------------------------------------ 2
    parts.append("\n## 2. Data\n")
    parts.append(
        _table(
            ["Property", "Value"],
            [
                ["Source", dataset.get("source", "—")],
                ["Type", dataset.get("kind", "—")],
                ["Period", f"{str(dataset.get('period_start'))[:10]} → {str(dataset.get('period_end'))[:10]}"],
                ["Retrieved", str(dataset.get("retrieved_at", "—"))[:19]],
                ["Grid point", f"{_fmt(dataset.get('grid_latitude'), 4)}, {_fmt(dataset.get('grid_longitude'), 4)}"],
                ["Elevation", _fmt(dataset.get("elevation_m"), 0, "m")],
                ["Rows retrieved", f"{dataset.get('rows_retrieved', 0):,}"],
                ["Rows used", f"{dataset.get('rows_used', 0):,}"],
                ["Rows dropped", str(dataset.get("rows_dropped", {}))],
            ],
        )
    )
    parts.append(
        f"\n> {dataset.get('attribution', '')}\n\n"
        f"> **Important.** This is reanalysis output, not ground-station pyranometer "
        f"measurement. Results are therefore not directly comparable with studies using "
        f"measured irradiance, and no such comparison is made here.\n"
    )

    if quality:
        parts.append(
            f"\n**Data quality: {quality.get('overall_score')}% ({quality.get('grade')})** — "
            f"{quality.get('counts', {}).get('pass', 0)} checks passed, "
            f"{quality.get('counts', {}).get('warn', 0)} warnings, "
            f"{quality.get('counts', {}).get('fail', 0)} failures.\n"
        )
        failures = [c for c in quality.get("checks", []) if c["severity"] in ("fail", "warn")]
        if failures:
            parts.append(
                _table(
                    ["Severity", "Check", "Finding"],
                    [[c["severity"].upper(), c["title"], c["message"]] for c in failures[:12]],
                )
            )

    # ------------------------------------------------------------------ 3
    parts.append("\n## 3. Method\n")
    parts.append(
        _table(
            ["Stage", "Choice"],
            [
                ["Model", f"{model.get('display_name')} ({model.get('family')})"],
                ["Hyperparameters", f"`{model.get('hyperparameters')}`"],
                ["Night exclusion", f"zenith ≥ {preprocessing.get('day_mask_threshold_deg')}° removed"],
                ["Interval alignment", f"{preprocessing.get('interval_offset_minutes')} min offset for solar position"],
                ["Missing values", preprocessing.get("imputation", "—")],
                ["Outliers", preprocessing.get("outlier_treatment", "—")],
                ["Scaling", preprocessing.get("scaling", "—")],
                ["Validation", validation.get("strategy", "—")],
                ["Embargo gap", _fmt(validation.get("embargo_gap_hours"), 0, "hours")],
                ["Train / test", f"{validation.get('n_train', 0):,} / {validation.get('n_test', 0):,}"],
            ],
        )
    )
    if model.get("hyperparameter_source"):
        parts.append(f"\n_Hyperparameter provenance:_ {model['hyperparameter_source']}\n")

    parts.append(
        f"\n**Features ({len(result.feature_names)}):** "
        + ", ".join(f"`{f}`" for f in result.feature_names)
        + "\n"
    )
    if manifest.get("features", {}).get("leakage_note"):
        parts.append(f"\n_Leakage control:_ {manifest['features']['leakage_note']}\n")

    # ------------------------------------------------------------------ 4
    parts.append("\n## 4. Results\n")
    parts.append("### 4.1 Hold-out test set (W/m²)\n")
    parts.append(
        _table(
            ["Metric", "Value", "Note"],
            [
                ["MAE", _fmt(phys.get("mae"), 2, "W/m²"), "Mean absolute error"],
                ["RMSE", _fmt(phys.get("rmse"), 2, "W/m²"), "Penalises large errors"],
                ["MBE", _fmt(phys.get("mbe"), 2, "W/m²"), "Positive = over-forecast"],
                ["R²", _fmt(phys.get("r2"), 4), "Identical to Nash-Sutcliffe Efficiency"],
                ["rRMSE", _fmt(phys.get("rrmse"), 2, "%"), "RMSE ÷ mean observation"],
                ["rMAE", _fmt(phys.get("rmae"), 2, "%"), "MAE ÷ mean observation"],
                ["sMAPE", _fmt(phys.get("smape"), 2, "%"), "Bounded percentage error"],
                ["Observed mean", _fmt(phys.get("observed_mean"), 1, "W/m²"), "Evaluation set"],
                ["Observed range", f"{_fmt(phys.get('observed_min'), 0)} – {_fmt(phys.get('observed_max'), 0)} W/m²", ""],
                ["n", f"{phys.get('n', 0):,}", "Daylight hours evaluated"],
            ],
        )
    )
    for note in phys.get("notes", []) or []:
        parts.append(f"\n> {note}\n")

    if result.cv_summary:
        cv = result.cv_summary
        parts.append(
            f"\n### 4.2 Rolling-origin cross-validation ({cv.get('n_folds')} folds)\n\n"
            f"RMSE **{_fmt(cv.get('rmse_mean'), 2)} ± {_fmt(cv.get('rmse_std'), 2)} W/m²** "
            f"(range {_fmt(cv.get('rmse_min'), 1)}–{_fmt(cv.get('rmse_max'), 1)}), "
            f"R² **{_fmt(cv.get('r2_mean'), 4)} ± {_fmt(cv.get('r2_std'), 4)}**.\n"
        )
        parts.append(
            _table(
                ["Fold", "Test period", "n", "RMSE", "MAE", "R²"],
                [
                    [
                        str(f.fold),
                        f"{str(f.test_start)[:10]} → {str(f.test_end)[:10]}",
                        f"{f.n_test:,}",
                        _fmt(f.metrics.get("rmse"), 2),
                        _fmt(f.metrics.get("mae"), 2),
                        _fmt(f.metrics.get("r2"), 4),
                    ]
                    for f in result.cv_folds
                ],
            )
        )

    parts.append("\n### 4.3 Comparison with reference forecasts\n")
    parts.append(
        "A model is only useful if it improves on a simple rule. Skill score is "
        "`1 − RMSE_model / RMSE_reference`; zero means no better than the reference.\n\n"
    )
    rows = []
    for b in result.baseline_results:
        if b.get("metrics"):
            rows.append(
                [
                    b["display_name"],
                    _fmt(b["metrics"].get("rmse"), 2),
                    _fmt(b["metrics"].get("mae"), 2),
                    f"**{_fmt(b.get('skill_score'), 4)}**",
                    _fmt(b.get("coverage", 0) * 100, 0, "%"),
                ]
            )
        else:
            rows.append([b["display_name"], "—", "—", "—", b.get("note", "")[:40]])
    parts.append(_table(["Reference", "RMSE (W/m²)", "MAE (W/m²)", "Skill", "Coverage"], rows))

    if result.by_regime:
        parts.append("\n### 4.4 Error by weather regime\n")
        parts.append(
            "Regimes follow Lyu & Eftekharnejad [P3]: *sunny* is cloud cover below 25 %, "
            "*other* denotes precipitation, *cloudy* is the remainder.\n\n"
        )
        parts.append(
            _table(
                ["Regime", "n", "RMSE (W/m²)", "MAE (W/m²)", "R²", "Mean observed"],
                [
                    [
                        k,
                        f"{v['n']:,}",
                        _fmt(v.get("rmse"), 2),
                        _fmt(v.get("mae"), 2),
                        _fmt(v.get("r2"), 4),
                        _fmt(v.get("observed_mean"), 1),
                    ]
                    for k, v in result.by_regime.items()
                ],
            )
        )

    # ------------------------------------------------------------------ 5
    if result.interval_metrics:
        im = result.interval_metrics
        parts.append("\n## 5. Uncertainty\n")
        parts.append(
            f"Intervals are produced by "
            f"`{(result.interval.method if result.interval else 'n/a')}`.\n\n"
        )
        parts.append(
            _table(
                ["Metric", "Value", "Meaning"],
                [
                    ["Nominal coverage", _fmt(im.get("nominal_coverage", 0) * 100, 0, "%"), "Target"],
                    ["PICP", _fmt(im.get("picp", 0) * 100, 1, "%"), "Observed coverage"],
                    ["Coverage error", _fmt(im.get("coverage_error", 0) * 100, 1, "pp"), "Observed − nominal"],
                    ["Mean width", _fmt(im.get("mean_width"), 1, "W/m²"), "Interval sharpness"],
                    ["PINAW", _fmt(im.get("pinaw"), 4), "Width ÷ observed range"],
                    ["Pinball loss", _fmt(im.get("pinball_mean"), 3), "Quantile accuracy [P3]"],
                    ["CRPS", _fmt(im.get("crps"), 3), "Whole-distribution score [P3]"],
                ],
            )
        )
        if im.get("by_regime"):
            parts.append("\nCoverage by regime (the conformal guarantee is marginal, not conditional):\n\n")
            parts.append(
                _table(
                    ["Regime", "PICP", "n", "Mean width (W/m²)"],
                    [
                        [k, _fmt(v["picp"] * 100, 1, "%"), f"{v['n']:,}", _fmt(v["mean_width"], 1)]
                        for k, v in im["by_regime"].items()
                    ],
                )
            )
        if result.interval and result.interval.caveat:
            parts.append(f"\n> {result.interval.caveat}\n")

    # ------------------------------------------------------------------ 6
    if importance:
        parts.append("\n## 6. What drives the prediction\n")
        grouped = importance.get("grouped", [])
        if grouped:
            parts.append(
                _table(
                    ["Feature group", "ΔRMSE when permuted", "Share"],
                    [
                        [g["group"], _fmt(g["rmse_increase_mean"], 5), _fmt(g["share"] * 100, 1, "%")]
                        for g in grouped
                    ],
                )
            )
        parts.append(f"\n> {importance.get('caveat', '')}\n")

    if narrative:
        parts.append("\n**Findings**\n\n" + "\n".join(f"- {line}" for line in narrative) + "\n")

    # ------------------------------------------------------------------ 7
    parts.append("\n## 7. Validity controls\n")
    if leakage_audit:
        parts.append(
            _table(
                ["Check", "Status", "Finding"],
                [[c["title"], c["status"].replace("_", " "), c["finding"]] for c in leakage_audit],
            )
        )
    if leakage_experiment:
        parts.append(
            "\n**Split-strategy experiment.** The identical model, seed and dataset were "
            "evaluated under three splitting strategies.\n\n"
        )
        parts.append(
            _table(
                ["Strategy", "RMSE (W/m²)", "R²", "Leakage risk"],
                [
                    [v.get("name", k), _fmt(v.get("rmse"), 2), _fmt(v.get("r2"), 4), v.get("leakage_risk", "")]
                    for k, v in leakage_experiment.get("strategies", {}).items()
                ],
            )
        )
        parts.append(f"\n{leakage_experiment.get('conclusion', '')}\n")

    # ------------------------------------------------------------------ 8
    if anomaly_summary:
        parts.append("\n## 8. Anomalies\n")
        parts.append(
            f"{anomaly_summary.get('total', 0)} irregularities detected "
            f"(by severity: {anomaly_summary.get('by_severity')}).\n\n"
            f"> {anomaly_summary.get('scope_note', '')}\n"
        )

    # ------------------------------------------------------------------ 9
    parts.append("\n## 9. Limitations\n")
    limitations = [
        "Irradiance is taken from ERA5 reanalysis, which is a modelled gridded product "
        "rather than a ground measurement. Grid-cell averages differ systematically from "
        "point observations, particularly in broken cloud and complex terrain.",
        "No metered photovoltaic output was available. PV figures are physically modelled "
        "from predicted irradiance and have **not** been validated against measured "
        "generation.",
        "Prediction intervals cover model error given the supplied weather. They exclude "
        "error in the weather forecast itself, which grows with horizon.",
        "The model is fitted to one location. Lyu & Eftekharnejad [P3] note explicitly that "
        "models trained at one site may not transfer to a different climate; no "
        "cross-location generalisation is claimed.",
        "Conformal coverage is marginal, not conditional, and assumes exchangeability that "
        "a seasonal series only approximately satisfies.",
        f"Accuracy has been measured only up to a "
        f"{validation.get('forecast_horizon_hours', 24)}-hour horizon.",
    ]
    if result.warnings:
        limitations.extend(result.warnings)
    parts.append("\n".join(f"{i}. {t}" for i, t in enumerate(limitations, start=1)) + "\n")

    # ----------------------------------------------------------------- 10
    parts.append("\n## 10. Reproducibility\n")
    parts.append(
        _table(
            ["Item", "Value"],
            [
                ["Random seed", str(repro.get("random_seed"))],
                ["Python", str(repro.get("python_version"))],
                ["NumPy", str(repro.get("numpy_version"))],
                ["pandas", str(repro.get("pandas_version"))],
                ["scikit-learn", str(repro.get("scikit_learn_version"))],
                ["Platform", str(repro.get("platform"))],
                ["Run timestamp", str(manifest.get("run_timestamp_utc"))[:19]],
                ["Dataset fingerprint", f"`{dataset.get('fingerprint')}`"],
            ],
        )
    )
    parts.append(
        "\nThe dataset fingerprint is a SHA-256 digest of the feature matrix, target "
        "vector, feature names and period. An identical fingerprint with an identical seed "
        "reproduces these numbers exactly.\n"
    )

    parts.append(
        "\n---\n\n_This report states measured results only. It contains no generated "
        "interpretation of whether the model is fit for any particular purpose._\n"
    )

    return "\n".join(parts)
