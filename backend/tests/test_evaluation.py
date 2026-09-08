"""Tests for metrics, splitting and baselines.

The splitter tests are the important ones: they assert the properties that make a
reported number trustworthy — that no validation observation ever precedes a training
observation, and that the embargo gap is actually enforced.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.evaluation import baselines, metrics, splitters


@pytest.fixture
def hourly_index() -> pd.DatetimeIndex:
    return pd.date_range("2023-01-01", periods=2000, freq="h", tz="UTC")


class TestMetrics:
    def test_perfect_prediction(self) -> None:
        y = np.array([1.0, 2.0, 3.0, 4.0])
        assert metrics.mae(y, y) == 0.0
        assert metrics.rmse(y, y) == 0.0
        assert metrics.r2(y, y) == pytest.approx(1.0)
        assert metrics.mbe(y, y) == 0.0

    def test_rmse_at_least_mae(self) -> None:
        rng = np.random.default_rng(0)
        y = rng.normal(500, 200, 500)
        p = y + rng.normal(0, 60, 500)
        assert metrics.rmse(y, p) >= metrics.mae(y, p)

    def test_bias_sign_convention(self) -> None:
        """Positive MBE means over-forecasting."""
        y = np.array([100.0, 100.0])
        assert metrics.mbe(y, np.array([110.0, 110.0])) > 0
        assert metrics.mbe(y, np.array([90.0, 90.0])) < 0

    def test_r2_undefined_for_constant_observations(self) -> None:
        y = np.full(10, 5.0)
        assert np.isnan(metrics.r2(y, y + 0.1))

    def test_nse_equals_r2(self) -> None:
        """They are the same quantity; the platform states this rather than implying two."""
        rng = np.random.default_rng(1)
        y = rng.normal(400, 150, 300)
        p = y + rng.normal(0, 50, 300)
        result = metrics.evaluate(y, p)
        assert result["nse"] == result["r2"]

    def test_mape_guards_zero_denominators(self) -> None:
        y = np.array([0.0, 0.0, 100.0, 200.0])
        p = np.array([5.0, 5.0, 110.0, 190.0])
        value, excluded = metrics.mape(y, p)
        assert excluded == 2
        assert np.isfinite(value)

    def test_handles_nan_pairs(self) -> None:
        y = np.array([1.0, np.nan, 3.0])
        p = np.array([1.0, 2.0, np.nan])
        assert metrics.mae(y, p) == pytest.approx(0.0)

    def test_empty_input(self) -> None:
        result = metrics.evaluate(np.array([]), np.array([]))
        assert result["n"] == 0
        assert "error" in result

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            metrics.mae(np.array([1.0, 2.0]), np.array([1.0]))

    def test_skill_score_semantics(self) -> None:
        y = np.array([10.0, 20.0, 30.0, 40.0])
        perfect = y.copy()
        poor = np.full(4, 25.0)
        assert metrics.skill_score(y, perfect, poor) == pytest.approx(1.0)
        assert metrics.skill_score(y, poor, poor) == pytest.approx(0.0)
        # Worse than the reference gives a negative score.
        assert metrics.skill_score(y, np.full(4, 100.0), poor) < 0

    def test_interval_metrics_coverage(self) -> None:
        y = np.arange(100, dtype=float)
        lower = y - 10
        upper = y + 10
        result = metrics.interval_metrics(y, lower, upper, nominal_coverage=0.8)
        assert result["picp"] == pytest.approx(1.0)
        assert result["coverage_error"] == pytest.approx(0.2)

    def test_pinball_loss_zero_for_perfect_median(self) -> None:
        y = np.array([1.0, 2.0, 3.0])
        losses = metrics.pinball_loss(y, {0.5: y})
        assert losses["pinball_q0.5"] == pytest.approx(0.0)

    def test_significant_figures_respects_error(self) -> None:
        # Round to the same decimal place as the uncertainty: 54 +/- 3, not 54.16 +/- 3.
        assert metrics.significant_figures(54.1637, 3.0) == "54"
        assert metrics.significant_figures(54.1637, 0.02) == "54.16"
        assert metrics.significant_figures(54.1637, 75.0) == "54"


class TestChronologicalSplit:
    def test_test_set_is_strictly_later(self, hourly_index: pd.DatetimeIndex) -> None:
        train, test = splitters.chronological_split(hourly_index, test_fraction=0.2)
        assert hourly_index[train].max() < hourly_index[test].min()

    def test_embargo_gap_enforced(self, hourly_index: pd.DatetimeIndex) -> None:
        gap = 48
        train, test = splitters.chronological_split(hourly_index, gap_hours=gap)
        separation = (hourly_index[test].min() - hourly_index[train].max()).total_seconds() / 3600
        assert separation >= gap

    def test_no_index_appears_in_both(self, hourly_index: pd.DatetimeIndex) -> None:
        train, test = splitters.chronological_split(hourly_index)
        assert len(set(train.tolist()) & set(test.tolist())) == 0

    def test_rejects_unsorted_index(self) -> None:
        idx = pd.DatetimeIndex(
            pd.date_range("2023-01-01", periods=100, freq="h", tz="UTC")[::-1]
        )
        with pytest.raises(ValueError, match="chronological order"):
            splitters.chronological_split(idx)

    def test_rejects_tiny_dataset(self) -> None:
        idx = pd.date_range("2023-01-01", periods=5, freq="h", tz="UTC")
        with pytest.raises(ValueError):
            splitters.chronological_split(idx)

    @pytest.mark.parametrize("fraction", [0.0, 0.04, 0.6, 1.0])
    def test_rejects_invalid_fraction(self, hourly_index, fraction: float) -> None:
        with pytest.raises(ValueError):
            splitters.chronological_split(hourly_index, test_fraction=fraction)


class TestRollingOrigin:
    def test_every_fold_trains_only_on_the_past(self, hourly_index: pd.DatetimeIndex) -> None:
        for split in splitters.rolling_origin_splits(hourly_index, n_splits=5):
            assert hourly_index[split.train_idx].max() < hourly_index[split.test_idx].min(), (
                f"fold {split.fold} trains on data that postdates its validation set"
            )

    def test_embargo_enforced_in_every_fold(self, hourly_index: pd.DatetimeIndex) -> None:
        gap = 24
        for split in splitters.rolling_origin_splits(hourly_index, n_splits=4, gap_hours=gap):
            sep = (
                hourly_index[split.test_idx].min() - hourly_index[split.train_idx].max()
            ).total_seconds() / 3600
            assert sep >= gap

    def test_expanding_window_grows(self, hourly_index: pd.DatetimeIndex) -> None:
        sizes = [s.train_idx.size for s in splitters.rolling_origin_splits(hourly_index, n_splits=4)]
        assert sizes == sorted(sizes)

    def test_folds_do_not_overlap_themselves(self, hourly_index: pd.DatetimeIndex) -> None:
        for split in splitters.rolling_origin_splits(hourly_index, n_splits=4):
            assert len(set(split.train_idx.tolist()) & set(split.test_idx.tolist())) == 0

    def test_rejects_too_few_splits(self, hourly_index: pd.DatetimeIndex) -> None:
        with pytest.raises(ValueError):
            list(splitters.rolling_origin_splits(hourly_index, n_splits=1))

    def test_raises_when_data_cannot_support_folds(self) -> None:
        idx = pd.date_range("2023-01-01", periods=20, freq="h", tz="UTC")
        with pytest.raises(ValueError, match="Reduce the number of folds|observations"):
            list(splitters.rolling_origin_splits(idx, n_splits=8))


class TestBlockedSplit:
    def test_keeps_whole_days_together(self) -> None:
        idx = pd.date_range("2023-01-01", periods=24 * 40, freq="h", tz="UTC")
        train, test = splitters.blocked_random_split(idx, block="D", seed=3)
        train_days = set(idx[train].date)
        test_days = set(idx[test].date)
        assert not (train_days & test_days), "a day must not straddle the split"


class TestBaselines:
    @pytest.fixture
    def series(self) -> pd.Series:
        idx = pd.date_range("2023-01-01", periods=24 * 40, freq="h", tz="UTC")
        # A clean diurnal cycle so persistence is exactly right at a 24 h lag.
        values = 500 * np.clip(np.sin(np.pi * (idx.hour - 6) / 12), 0, None)
        return pd.Series(values, index=idx)

    def test_persistence_uses_the_stated_lag(self, series: pd.Series) -> None:
        test_index = series.index[-48:]
        result = baselines.persistence(series, test_index, horizon_hours=24)
        expected = series.reindex(test_index - pd.Timedelta(hours=24)).to_numpy()
        assert np.allclose(result.predictions, expected, equal_nan=True)

    def test_persistence_reports_missing_history_rather_than_filling(self) -> None:
        idx = pd.date_range("2023-01-01", periods=30, freq="h", tz="UTC")
        s = pd.Series(np.arange(30, dtype=float), index=idx)
        result = baselines.persistence(s, idx[:10], horizon_hours=24)
        # The first ten hours have no observation 24 h earlier.
        assert result.coverage < 1.0
        assert np.isnan(result.predictions).any()

    def test_climatology_uses_only_training_data(self, series: pd.Series) -> None:
        train = series.iloc[: 24 * 30]
        test_index = series.index[24 * 30 :]
        result = baselines.climatology(train, test_index)
        assert np.isfinite(result.predictions).all()
        assert result.predictions.max() <= train.max() + 1e-9

    def test_persistence_ensemble_is_probabilistic(self, series: pd.Series) -> None:
        test_index = series.index[-24:]
        result = baselines.persistence_ensemble(series, test_index, n_members=10)
        assert result.quantiles is not None
        lower = result.quantiles[0.1]
        upper = result.quantiles[0.9]
        assert np.all(upper[np.isfinite(upper)] >= lower[np.isfinite(lower)])

    def test_smart_persistence_differs_from_naive_in_physical_space(self) -> None:
        """The two coincide in clear-sky-index space; they must differ in W/m^2."""
        idx = pd.date_range("2023-06-01", periods=24 * 5, freq="h", tz="UTC")
        rng = np.random.default_rng(0)
        kt = pd.Series(rng.uniform(0.3, 0.95, len(idx)), index=idx)
        # Clear-sky irradiance that changes between the two days.
        cs = pd.Series(np.linspace(600, 900, len(idx)), index=idx)
        ghi = pd.Series(kt.to_numpy() * cs.to_numpy(), index=idx)
        test_index = idx[-24:]

        naive = baselines.persistence(ghi, test_index, horizon_hours=6)
        smart = baselines.smart_persistence(kt, cs, test_index, horizon_hours=6)
        assert not np.allclose(naive.predictions, smart.predictions)
