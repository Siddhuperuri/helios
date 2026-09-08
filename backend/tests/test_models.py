"""The model registry, the energy target, and the folds the ensemble blends over.

Three things are pinned here.

**The registry is exactly five entries.** The set was cut from ten deliberately, and a
model quietly reappearing — through a merge, or a copied line — would change what every
comparison in the platform means. The withdrawn keys are named individually so the failure
message says which one came back.

**The energy target reports in kilowatt-hours and nothing else.** ``pv_kwh`` predicts the
quantity that is wanted, so there is no conversion step and no W/m² twin. A test that only
checked the numbers would pass while the units were wrong, so the units are asserted.

**The ensemble's inner folds partition the training rows.** ``StackingRegressor`` collects
its meta-features with ``cross_val_predict``, which rejects any splitter that leaves a row
uncovered. That constraint is the reason those folds are blocked rather than forward-only,
and it is easy to break by "improving" the splitter, so it is checked directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.sources import Location
from app.evaluation import leakage, splitters
from app.features.pipeline import build_features
from app.features.solar_geometry import PVSystem
from app.models import registry
from app.models.trainer import train_and_evaluate

LAT, LON = 17.385, 78.4867
LOCATION = Location(latitude=LAT, longitude=LON, name="Test Site")

WITHDRAWN_KEYS = (
    "gradient_boosting",
    "knn",
    "svr",
    "linear",
    "decision_tree",
    "stacking",
    "voting",
)


@pytest.fixture(scope="module")
def weather() -> pd.DataFrame:
    """A physically coherent synthetic year, generated from real solar geometry.

    Module-scoped because it is read-only and the training tests below are the slowest in
    the suite; regenerating it per test would add time and prove nothing.
    """
    from app.features.solar_geometry import (
        clear_sky_ghi_haurwitz,
        representative_times,
        solar_position,
    )

    idx = pd.date_range("2023-01-01", periods=24 * 200, freq="h", tz="UTC")
    pos = solar_position(representative_times(idx), LAT, LON)
    cs = clear_sky_ghi_haurwitz(pos.apparent_zenith)

    rng = np.random.default_rng(7)
    kt = np.clip(rng.beta(6, 2, len(idx)), 0.05, 1.0)
    ghi = np.round(cs * kt, 1)

    frame = pd.DataFrame(
        {
            "ghi_wm2": ghi,
            "dni_wm2": ghi * 0.7,
            "dhi_wm2": ghi * 0.3,
            "temperature_c": 25 + 8 * np.sin(2 * np.pi * idx.dayofyear / 365)
            + rng.normal(0, 1.5, len(idx)),
            "relative_humidity_pct": np.clip(rng.normal(55, 15, len(idx)), 5, 100),
            "dew_point_c": rng.normal(15, 4, len(idx)),
            "surface_pressure_hpa": rng.normal(950, 4, len(idx)),
            "wind_speed_ms": np.clip(rng.gamma(2, 1.4, len(idx)), 0, None),
            "wind_direction_deg": rng.uniform(0, 360, len(idx)),
            "cloud_cover_pct": np.clip((1 - kt) * 130, 0, 100),
            "precipitation_mm": np.where(
                rng.random(len(idx)) < 0.05, rng.gamma(1, 2, len(idx)), 0.0
            ),
        },
        index=idx,
    )
    frame.index.name = "time_utc"
    frame.attrs.update({"source": "synthetic", "kind": "archive"})
    return frame


@pytest.fixture(scope="module")
def energy_features(weather: pd.DataFrame):
    return build_features(
        weather, LOCATION, target="pv_kwh", system=PVSystem(dc_capacity_kwp=5.0)
    )


class TestRegistryContents:
    def test_exactly_the_five_kept_entries(self) -> None:
        assert set(registry.MODELS) == {
            "random_forest",
            "hist_gradient_boosting",
            "extra_trees",
            "ridge",
            "ensemble_four",
        }

    @pytest.mark.parametrize("key", WITHDRAWN_KEYS)
    def test_withdrawn_model_stays_withdrawn(self, key: str) -> None:
        assert key not in registry.MODELS, (
            f"'{key}' was removed from the registry and has come back. Every comparison "
            f"table, default selection and document in the project assumes five models."
        )

    def test_unknown_key_lists_the_alternatives(self) -> None:
        with pytest.raises(KeyError, match="random_forest"):
            registry.get("gradient_boosting")

    def test_default_comparison_is_all_of_them(self) -> None:
        assert set(registry.DEFAULT_COMPARISON) == set(registry.MODELS)

    def test_every_model_records_why_it_was_kept(self) -> None:
        """The pruning rationale travels with the model, not only in the module docstring."""
        for spec in registry.MODELS.values():
            assert spec.notes, f"{spec.key} has no model-card note"
            assert spec.sources, f"{spec.key} claims no source"

    def test_ensemble_declares_exactly_the_four_base_models(self) -> None:
        assert registry.ENSEMBLE_BASE_KEYS == (
            "random_forest",
            "hist_gradient_boosting",
            "extra_trees",
            "ridge",
        )
        estimator = registry.get("ensemble_four").build(0)
        assert [name for name, _ in estimator.estimators] == list(
            registry.ENSEMBLE_BASE_KEYS
        )


class TestEnsembleWeights:
    @pytest.fixture(scope="class")
    def fitted(self):
        rng = np.random.default_rng(3)
        X = rng.random((300, 4))
        y = 2.0 * X[:, 0] + np.sin(6.0 * X[:, 1]) + rng.normal(0, 0.05, 300)
        estimator = registry.get("ensemble_four").build(0)
        estimator.fit(X, y)
        return estimator, X

    def test_weights_are_learned_not_uniform(self, fitted) -> None:
        """A simple average would let Ridge drag the tree models down; this is not one."""
        estimator, _ = fitted
        weights = registry.ensemble_weights(estimator)
        assert weights is not None and len(weights) == 4
        values = [w["weight"] for w in weights]
        assert len({round(v, 6) for v in values}) > 1, "weights are uniform"
        assert not all(abs(v - 0.25) < 1e-6 for v in values)

    def test_every_base_model_reports_its_own_prediction(self, fitted) -> None:
        estimator, X = fitted
        contributions = registry.base_model_predictions(estimator, X[:1])
        assert contributions is not None
        assert [c["model"] for c in contributions] == list(registry.ENSEMBLE_BASE_KEYS)
        for entry in contributions:
            assert entry["prediction"] is not None
            assert entry["display_name"]

    def test_single_estimators_report_no_contributions(self) -> None:
        rng = np.random.default_rng(4)
        X = rng.random((60, 4))
        estimator = registry.get("random_forest").build(0)
        estimator.fit(X, X[:, 0])
        assert registry.ensemble_weights(estimator) is None
        assert registry.base_model_predictions(estimator, X[:1]) is None


class TestBlockedChronologicalCV:
    """The constraint that decides the fold shape, asserted rather than assumed."""

    def test_validation_blocks_partition_every_row(self) -> None:
        cv = splitters.BlockedChronologicalCV(n_splits=5, embargo_samples=10)
        X = np.zeros((500, 3))
        covered = np.concatenate([test for _, test in cv.split(X)])
        assert np.array_equal(np.sort(covered), np.arange(500)), (
            "cross_val_predict rejects a splitter that leaves rows uncovered, and "
            "StackingRegressor uses cross_val_predict"
        )

    def test_neighbouring_rows_are_purged_from_training(self) -> None:
        embargo = 10
        cv = splitters.BlockedChronologicalCV(n_splits=4, embargo_samples=embargo)
        X = np.zeros((400, 3))
        for train, test in cv.split(X):
            gap = np.min(np.abs(train[:, None] - test[None, :]))
            assert gap > embargo, "training rows sit inside the embargo around validation"

    def test_blocks_stay_contiguous_in_time(self) -> None:
        cv = splitters.BlockedChronologicalCV(n_splits=3, embargo_samples=0)
        for _, test in cv.split(np.zeros((300, 2))):
            assert np.array_equal(test, np.arange(test[0], test[-1] + 1))

    def test_rejects_a_single_fold(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            splitters.BlockedChronologicalCV(n_splits=1)

    def test_the_ensemble_actually_fits_with_it(self) -> None:
        """The failure this guards against is a hard error at fit time, not a bad number."""
        rng = np.random.default_rng(5)
        X = rng.random((200, 3))
        estimator = registry.get("ensemble_four").build(0)
        estimator.fit(X, X[:, 0] * 3.0)
        assert estimator.predict(X[:5]).shape == (5,)


class TestEnergyTarget:
    def test_features_carry_the_declared_system(self, energy_features) -> None:
        declaration = energy_features.provenance["pv_system"]
        assert declaration["dc_capacity_kwp"] == 5.0
        assert declaration["ac_capacity_kw"] > 0

    def test_labels_are_declared_as_modelled_not_metered(self, energy_features) -> None:
        """README §10 limitation 2 must survive the trip into the payload."""
        construction = energy_features.provenance["target_construction"]
        assert "modelled" in construction.lower()
        assert "not metered" in construction.lower()

    def test_energy_is_never_negative_and_never_exceeds_the_inverter(
        self, energy_features
    ) -> None:
        cap = energy_features.provenance["pv_system"]["ac_capacity_kw"]
        assert energy_features.y.min() >= 0.0
        assert energy_features.y.max() <= cap + 1e-9

    def test_the_energy_label_is_not_offered_as_a_feature(self, energy_features) -> None:
        for leaked in ("pv_kwh", "ac_power_kw", "dc_power_kw", "poa_wm2",
                       "cell_temperature_c", "ghi_wm2"):
            assert leaked not in energy_features.feature_names

    def test_no_target_lags(self, energy_features) -> None:
        assert energy_features.provenance["target_lags_used"] is False
        assert not any("lag" in name for name in energy_features.feature_names)

    def test_night_hours_are_excluded_as_for_irradiance(self, energy_features) -> None:
        assert bool(energy_features.frame["is_daytime"].all())
        assert energy_features.dropped_rows["night_hours"] > 0

    def test_the_five_check_leakage_audit_still_passes(self, energy_features) -> None:
        checks = leakage.audit(energy_features, "ensemble_four", gap_hours=24)
        assert len(checks) == 5
        statuses = {c["key"]: c["status"] for c in checks}
        assert statuses["target_leakage"] == "protected"
        assert statuses["future_information"] == "protected"
        assert statuses["preprocessing_leakage"] == "protected"
        assert statuses["temporal_contamination"] == "mitigated"
        assert statuses["trivial_observations"] == "protected"


class TestEnergyTraining:
    @pytest.fixture(scope="class")
    def trained(self, energy_features):
        return train_and_evaluate(
            energy_features,
            model_key="ridge",
            run_cv=False,
            compute_intervals=False,
            cv_splits=3,
        )

    def test_metrics_are_reported_in_kwh_on_both_sides(self, trained) -> None:
        """No W/m² twin is manufactured: the native unit is already the physical one."""
        assert trained.test_metrics["target_unit"] == "kWh"
        assert trained.test_metrics_physical["unit"] == "kWh"
        assert trained.target_name == "pv_kwh"

    def test_the_second_metric_block_is_a_constraint_not_a_conversion(
        self, trained, energy_features
    ) -> None:
        """Both blocks are in kWh, and the bounded one can only be the better of the two.

        Every label lies inside [0, inverter rating] by construction, so clipping a
        prediction into that interval moves it towards the truth or leaves it alone — it
        can never move it away. A bounded RMSE *above* the unbounded one would mean the
        bound is wrong, and a bounded RMSE in the hundreds would mean a W/m² conversion had
        crept in where this target needs none.
        """
        cap = energy_features.provenance["pv_system"]["ac_capacity_kw"]
        assert trained.test_metrics_physical["rmse"] <= trained.test_metrics["rmse"] + 1e-9
        assert trained.test_metrics_physical["rmse"] < cap

    def test_clipped_count_is_reported(self, trained) -> None:
        assert "n_clipped_to_physical_bounds" in trained.test_metrics_physical

    def test_predictions_are_labelled_kwh_and_carry_no_predicted_irradiance(
        self, trained
    ) -> None:
        columns = set(trained.predictions.columns)
        assert {"observed_kwh", "predicted_kwh", "residual_kwh"} <= columns
        assert "predicted_ghi_wm2" not in columns, (
            "an energy model has no irradiance prediction to report; publishing one would "
            "be a fabricated figure"
        )

    def test_predictions_respect_the_inverter_ceiling(self, trained, energy_features) -> None:
        cap = energy_features.provenance["pv_system"]["ac_capacity_kw"]
        predicted = trained.predictions["predicted_kwh"].to_numpy()
        assert predicted.min() >= 0.0
        assert predicted.max() <= cap + 1e-9

    def test_baselines_are_persistence_and_climatology_only(self, trained) -> None:
        """No physics-chain baseline: the labels are physics-derived, so it is circular."""
        names = {b["name"] for b in trained.baseline_results}
        assert names == {"persistence", "climatology"}
        for baseline in trained.baseline_results:
            assert baseline.get("unit") == "kWh"

    def test_the_manifest_records_how_the_labels_were_made(self, trained) -> None:
        features = trained.manifest["features"]
        assert features["target"] == "pv_kwh"
        assert features["target_unit"] == "kWh"
        assert "not metered" in features["target_construction"].lower()
        assert features["pv_system"]["dc_capacity_kwp"] == 5.0


class TestIrradianceTargetIsUnchanged:
    """The additive promise: the existing paths behave exactly as they did."""

    @pytest.fixture(scope="class")
    def trained(self, weather):
        features = build_features(weather, LOCATION, target="clear_sky_index")
        return train_and_evaluate(
            features, model_key="ridge", run_cv=False, compute_intervals=False
        )

    def test_reports_target_space_in_kt_and_physical_space_in_wm2(self, trained) -> None:
        assert trained.test_metrics["target_unit"] == "dimensionless"
        assert trained.test_metrics_physical["unit"] == "W/m²"

    def test_still_publishes_the_irradiance_columns(self, trained) -> None:
        columns = set(trained.predictions.columns)
        assert {"predicted_ghi_wm2", "residual_wm2", "observed_ghi_wm2"} <= columns

    def test_still_gets_all_four_irradiance_baselines(self, trained) -> None:
        names = {b["name"] for b in trained.baseline_results}
        assert names == {
            "persistence",
            "smart_persistence",
            "climatology",
            "persistence_ensemble",
        }
