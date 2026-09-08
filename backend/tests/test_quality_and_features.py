"""Tests for the data quality engine and the feature pipeline.

The quality tests deliberately corrupt clean data in specific ways and assert the engine
notices. A quality engine that never fires is worthless, so every check that exists here
is proven to catch the fault it claims to catch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.sources import Location
from app.features.pipeline import LEAKAGE_EXCLUDED, build_features, label_weather_regime
from app.quality import engine

LAT, LON = 17.385, 78.4867
LOCATION = Location(latitude=LAT, longitude=LON, name="Test Site")


@pytest.fixture
def clean_frame() -> pd.DataFrame:
    """A physically coherent synthetic year at hourly resolution.

    Synthetic rather than fetched so the tests are deterministic and run without network.
    Irradiance is derived from real solar geometry, so night hours are genuinely dark and
    the clear-sky ceiling is respected.
    """
    from app.features.solar_geometry import (
        clear_sky_ghi_haurwitz,
        representative_times,
        solar_position,
    )

    idx = pd.date_range("2023-01-01", periods=24 * 365, freq="h", tz="UTC")
    pos = solar_position(representative_times(idx), LAT, LON)
    cs = clear_sky_ghi_haurwitz(pos.apparent_zenith)

    rng = np.random.default_rng(42)
    kt = np.clip(rng.beta(6, 2, len(idx)), 0.05, 1.0)
    ghi = np.round(cs * kt, 1)

    frame = pd.DataFrame(
        {
            "ghi_wm2": ghi,
            "dni_wm2": ghi * 0.7,
            "dhi_wm2": ghi * 0.3,
            "temperature_c": 25 + 8 * np.sin(2 * np.pi * idx.dayofyear / 365) + rng.normal(0, 1.5, len(idx)),
            "relative_humidity_pct": np.clip(rng.normal(55, 15, len(idx)), 5, 100),
            "dew_point_c": rng.normal(15, 4, len(idx)),
            "surface_pressure_hpa": rng.normal(950, 4, len(idx)),
            "wind_speed_ms": np.clip(rng.gamma(2, 1.4, len(idx)), 0, None),
            "wind_direction_deg": rng.uniform(0, 360, len(idx)),
            "cloud_cover_pct": np.clip((1 - kt) * 130, 0, 100),
            "precipitation_mm": np.where(rng.random(len(idx)) < 0.05, rng.gamma(1, 2, len(idx)), 0.0),
        },
        index=idx,
    )
    frame.index.name = "time_utc"
    frame.attrs.update({"source": "synthetic", "kind": "archive", "retrieved_at": "2024-01-01T00:00:00Z"})
    return frame


class TestQualityOnCleanData:
    def test_clean_data_passes(self, clean_frame: pd.DataFrame) -> None:
        report = engine.assess(clean_frame, latitude=LAT, longitude=LON)
        assert report.is_usable
        assert report.overall_score > 0.95
        assert report.worst_severity in {"pass", "warn"}

    def test_score_is_recomputable_from_the_payload(self, clean_frame: pd.DataFrame) -> None:
        """A reviewer must be able to verify the headline figure by hand."""
        payload = engine.assess(clean_frame, latitude=LAT, longitude=LON).to_dict()
        recomputed = (
            payload["methodology"]["weighted_sum"] / payload["methodology"]["total_weight"]
        ) * 100
        assert recomputed == pytest.approx(payload["overall_score"], abs=0.15)

    def test_score_never_displays_100_with_outstanding_issues(self, clean_frame: pd.DataFrame) -> None:
        d = clean_frame.copy()
        d["wind_speed_ms"] = 3.0  # constant sensor -> one warning
        payload = engine.assess(d, latitude=LAT, longitude=LON).to_dict()
        assert payload["counts"]["warn"] >= 1
        assert payload["overall_score"] < 100.0
        assert payload["grade"] != "Excellent"


class TestQualityDetectsCorruption:
    def test_detects_timezone_shift(self, clean_frame: pd.DataFrame) -> None:
        shifted = clean_frame.set_index(clean_frame.index + pd.Timedelta(hours=6))
        report = engine.assess(shifted, latitude=LAT, longitude=LON)
        night = next(c for c in report.checks if c.key == "night_irradiance")
        assert night.severity is engine.Severity.FAIL
        assert not report.is_usable

    def test_detects_unit_error(self, clean_frame: pd.DataFrame) -> None:
        d = clean_frame.copy()
        d["ghi_wm2"] = d["ghi_wm2"] * 2.0
        report = engine.assess(d, latitude=LAT, longitude=LON)
        ceiling = next(c for c in report.checks if c.key == "clear_sky_exceedance")
        assert ceiling.severity is engine.Severity.FAIL

    def test_detects_missing_values(self, clean_frame: pd.DataFrame) -> None:
        d = clean_frame.copy()
        idx = np.random.default_rng(0).choice(len(d), int(0.2 * len(d)), replace=False)
        d.iloc[idx, d.columns.get_loc("temperature_c")] = np.nan
        report = engine.assess(d, latitude=LAT, longitude=LON)
        check = next(c for c in report.checks if c.key == "missing__temperature_c")
        assert check.severity is engine.Severity.FAIL
        assert "20" in check.message  # the actual percentage is reported

    def test_detects_duplicate_timestamps(self, clean_frame: pd.DataFrame) -> None:
        d = pd.concat([clean_frame, clean_frame.iloc[:100]]).sort_index()
        report = engine.assess(d, latitude=LAT, longitude=LON)
        check = next(c for c in report.checks if c.key == "duplicate_timestamps")
        assert check.severity is engine.Severity.FAIL
        assert not report.is_usable

    def test_detects_impossible_values(self, clean_frame: pd.DataFrame) -> None:
        d = clean_frame.copy()
        d.iloc[:50, d.columns.get_loc("relative_humidity_pct")] = 150.0
        report = engine.assess(d, latitude=LAT, longitude=LON)
        check = next(c for c in report.checks if c.key == "range__relative_humidity_pct")
        assert check.severity in {engine.Severity.FAIL, engine.Severity.WARN}
        assert check.affected_rows == 50

    def test_detects_stuck_sensor(self, clean_frame: pd.DataFrame) -> None:
        d = clean_frame.copy()
        d["wind_speed_ms"] = 3.0
        report = engine.assess(d, latitude=LAT, longitude=LON)
        assert any(c.key == "variance__wind_speed_ms" for c in report.checks)

    def test_detects_large_gap(self, clean_frame: pd.DataFrame) -> None:
        d = pd.concat([clean_frame.iloc[:1000], clean_frame.iloc[3000:]])
        report = engine.assess(d, latitude=LAT, longitude=LON)
        coverage = next(c for c in report.checks if c.key == "temporal_coverage")
        assert coverage.severity is engine.Severity.FAIL

    def test_empty_dataset(self) -> None:
        report = engine.assess(pd.DataFrame(), latitude=LAT, longitude=LON)
        assert not report.is_usable
        assert report.overall_score == 0.0
        assert report.grade == "Unusable"

    def test_single_row(self, clean_frame: pd.DataFrame) -> None:
        report = engine.assess(clean_frame.iloc[:1], latitude=LAT, longitude=LON)
        assert not report.is_usable


class TestFeaturePipeline:
    def test_builds_expected_columns(self, clean_frame: pd.DataFrame) -> None:
        fs = build_features(clean_frame, LOCATION, target="clear_sky_index")
        for col in ("solar_zenith_deg", "clear_sky_ghi_wm2", "cos_aoi", "air_mass", "weather_regime"):
            assert col in fs.frame.columns

    def test_excludes_night_hours(self, clean_frame: pd.DataFrame) -> None:
        fs = build_features(clean_frame, LOCATION, daytime_only=True)
        assert bool(fs.frame["is_daytime"].all())
        assert fs.dropped_rows["night_hours"] > 0

    def test_no_leaking_feature_reaches_the_model(self, clean_frame: pd.DataFrame) -> None:
        fs = build_features(clean_frame, LOCATION)
        assert not set(fs.feature_names) & LEAKAGE_EXCLUDED

    def test_rejects_explicitly_requested_leaking_feature(self, clean_frame: pd.DataFrame) -> None:
        """A leaking feature must raise, not be silently dropped."""
        with pytest.raises(ValueError, match="components of the target"):
            build_features(clean_frame, LOCATION, feature_names=("temperature_c", "dni_wm2"))

    def test_no_target_lags_are_created(self, clean_frame: pd.DataFrame) -> None:
        fs = build_features(clean_frame, LOCATION)
        assert fs.provenance["target_lags_used"] is False
        assert not any("lag" in f for f in fs.feature_names)

    def test_target_is_within_physical_bounds(self, clean_frame: pd.DataFrame) -> None:
        fs = build_features(clean_frame, LOCATION, target="clear_sky_index")
        assert fs.y.min() >= 0.0
        assert fs.y.max() <= 1.5

    def test_no_missing_values_survive(self, clean_frame: pd.DataFrame) -> None:
        d = clean_frame.copy()
        d.iloc[100:200, d.columns.get_loc("temperature_c")] = np.nan
        fs = build_features(d, LOCATION)
        assert not fs.X.isna().any().any()
        assert fs.dropped_rows["incomplete_rows"] > 0

    def test_rejects_unknown_target(self, clean_frame: pd.DataFrame) -> None:
        with pytest.raises(ValueError, match="Unsupported target"):
            build_features(clean_frame, LOCATION, target="not_a_target")

    def test_rejects_empty_frame(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            build_features(pd.DataFrame(), LOCATION)

    def test_raises_when_nothing_survives_filtering(self, clean_frame: pd.DataFrame) -> None:
        d = clean_frame.copy()
        d["temperature_c"] = np.nan
        with pytest.raises(ValueError, match="No complete observations"):
            build_features(d, LOCATION)

    def test_index_remains_sorted(self, clean_frame: pd.DataFrame) -> None:
        fs = build_features(clean_frame, LOCATION)
        assert fs.frame.index.is_monotonic_increasing


class TestWeatherRegime:
    def test_thresholds_follow_the_source_paper(self) -> None:
        frame = pd.DataFrame(
            {
                "cloud_cover_pct": [10.0, 50.0, 80.0, 15.0],
                "precipitation_mm": [0.0, 0.0, 0.5, 2.0],
            },
            index=pd.date_range("2023-01-01", periods=4, freq="h", tz="UTC"),
        )
        regimes = label_weather_regime(frame).tolist()
        assert regimes[0] == "sunny"   # <25 % cloud, dry
        assert regimes[1] == "cloudy"  # >=25 % cloud, dry
        assert regimes[2] == "other"   # precipitation dominates
        assert regimes[3] == "other"   # precipitation overrides low cloud
