"""The date-and-time prediction endpoint.

The weather archive is stubbed throughout, so nothing here touches the network and nothing
depends on what a real reanalysis happens to contain. What is under test is the wiring and
the promises: that the requested hour is read in the location's time zone and actually
changes the answer, that the model is never shown data from the target hour or later, that
the four base models are reported individually alongside the blended figure, and that a
date the archive cannot cover is refused with a message naming what it can.

The stub frame is explicitly synthetic and labelled as such. Irradiance is derived from
real solar geometry so that night is genuinely dark and the clear-sky ceiling holds — those
are the properties the assertions below lean on. It is a fixture, not a dataset standing in
for observations.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

LAT, LON = 17.385, 78.4867

# The archive is pretended to end here, so the tests do not drift as the calendar moves.
LATEST_ARCHIVE_DATE = date(2024, 6, 30)
TARGET_DATE = date(2024, 6, 20)

# The stub serves at most this many days. The endpoint asks for two years; training four
# models on two years of hourly data inside a unit test would cost minutes and prove
# nothing that ninety days does not.
MAX_STUB_DAYS = 90


def _synthetic_archive(start: date, end: date) -> pd.DataFrame:
    """Hourly weather for a date range, physically coherent and deterministic."""
    from app.features.solar_geometry import (
        clear_sky_ghi_haurwitz,
        representative_times,
        solar_position,
    )

    start = max(start, end - timedelta(days=MAX_STUB_DAYS))
    index = pd.date_range(
        f"{start.isoformat()}T00:00:00Z", f"{end.isoformat()}T23:00:00Z", freq="h"
    )
    position = solar_position(representative_times(index), LAT, LON)
    clear_sky = clear_sky_ghi_haurwitz(position.apparent_zenith)

    rng = np.random.default_rng(11)
    kt = np.clip(rng.beta(6, 2, len(index)), 0.05, 1.0)
    ghi = np.round(clear_sky * kt, 1)

    frame = pd.DataFrame(
        {
            "ghi_wm2": ghi,
            "dni_wm2": ghi * 0.7,
            "dhi_wm2": ghi * 0.3,
            "temperature_c": 30 + 4 * np.sin(2 * np.pi * index.dayofyear / 365)
            + rng.normal(0, 1.0, len(index)),
            "relative_humidity_pct": np.clip(rng.normal(55, 12, len(index)), 5, 100),
            "dew_point_c": rng.normal(18, 3, len(index)),
            "surface_pressure_hpa": rng.normal(950, 3, len(index)),
            "wind_speed_ms": np.clip(rng.gamma(2, 1.2, len(index)), 0, None),
            "wind_direction_deg": rng.uniform(0, 360, len(index)),
            "cloud_cover_pct": np.clip((1 - kt) * 130, 0, 100),
            "precipitation_mm": np.where(
                rng.random(len(index)) < 0.04, rng.gamma(1, 2, len(index)), 0.0
            ),
        },
        index=index,
    )
    frame.index.name = "time_utc"
    frame.attrs.update(
        {
            "source": "synthetic fixture",
            "kind": "archive",
            "retrieved_at": "2024-07-01T00:00:00+00:00",
            "latitude": LAT,
            "longitude": LON,
            "elevation_m": 505.0,
        }
    )
    return frame


@pytest.fixture()
def stub_archive(client: TestClient, monkeypatch):
    """Replace every upstream call the endpoint makes.

    ``client`` is requested first so the application — and therefore the module objects the
    routers close over — exists before anything is patched onto them.
    """
    from app.api import service
    from app.api.routes import point_forecast as route
    from app.data.sources import Location

    calls: dict[str, object] = {"windows": []}

    def _fetch(location, start, end, *, variables=None):
        calls["windows"].append((start, end))
        return _synthetic_archive(start, end)

    def _resolve(*, query=None, latitude=None, longitude=None):
        return Location(
            latitude=float(latitude) if latitude is not None else LAT,
            longitude=float(longitude) if longitude is not None else LON,
            name=query or "Hyderabad",
            country="India",
            country_code="IN",
            admin1="Telangana",
            elevation_m=505.0,
            timezone="Asia/Kolkata",
            source="stub",
        )

    for module in (service, route):
        monkeypatch.setattr(module, "fetch_archive", _fetch)
        monkeypatch.setattr(module, "resolve_location", _resolve)
        monkeypatch.setattr(
            module, "latest_available_archive_date", lambda: LATEST_ARCHIVE_DATE
        )

    return calls


def _request(**overrides) -> dict:
    body = {
        "location": {"query": "Hyderabad"},
        "target_datetime": f"{TARGET_DATE.isoformat()}T13:00:00",
        "model_key": "ridge",
    }
    body.update(overrides)
    return body


class TestPrediction:
    def test_returns_energy_for_the_requested_hour(
        self, client: TestClient, stub_archive
    ) -> None:
        response = client.post("/api/point-forecast", json=_request())
        assert response.status_code == 200, response.text

        body = response.json()
        assert body["kwh_hour"] >= 0.0
        assert body["kwh_day"] >= body["kwh_hour"]
        assert body["resolved_place_name"]
        assert body["latitude"] == pytest.approx(LAT)
        assert body["longitude"] == pytest.approx(LON)

    def test_reports_the_three_driving_parameters(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post("/api/point-forecast", json=_request()).json()
        assert body["ghi_wm2"] >= 0.0
        assert -60.0 < body["air_temperature_c"] < 60.0
        assert body["wind_speed_ms"] >= 0.0

    def test_the_hour_is_read_in_the_location_time_zone(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post("/api/point-forecast", json=_request()).json()
        target = body["target"]
        # Asia/Kolkata is UTC+5:30 and the archive is hourly on UTC hours, so 13:00 local
        # resolves to 07:00 UTC — 12:30 local. Both frames are echoed back precisely so the
        # half-hour is visible rather than silently absorbed.
        assert target["resolved_utc"].startswith(f"{TARGET_DATE.isoformat()}T07:00")
        assert target["resolved_local"].startswith(f"{TARGET_DATE.isoformat()}T12:30")
        assert "Asia/Kolkata" in target["timezone_source"]

    def test_the_requested_hour_changes_the_answer(
        self, client: TestClient, stub_archive
    ) -> None:
        """The defect this endpoint exists to fix: a time control that did nothing."""
        noon = client.post(
            "/api/point-forecast",
            json=_request(target_datetime=f"{TARGET_DATE.isoformat()}T12:00:00"),
        ).json()
        evening = client.post(
            "/api/point-forecast",
            json=_request(target_datetime=f"{TARGET_DATE.isoformat()}T17:00:00"),
        ).json()
        assert noon["kwh_hour"] != evening["kwh_hour"]
        assert noon["kwh_day"] == pytest.approx(evening["kwh_day"], rel=1e-6)

    def test_night_produces_nothing_and_says_why(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post(
            "/api/point-forecast",
            json=_request(target_datetime=f"{TARGET_DATE.isoformat()}T02:00:00"),
        ).json()
        assert body["kwh_hour"] == 0.0
        assert body["target"]["is_daytime"] is False
        assert any("below the horizon" in w for w in body["warnings"])

    def test_energy_never_exceeds_the_inverter_rating(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post(
            "/api/point-forecast",
            json=_request(system={"dc_capacity_kwp": 5.0, "inverter_ac_capacity_kw": 3.0}),
        ).json()
        assert 0.0 <= body["kwh_hour"] <= 3.0
        assert body["n_clipped_to_physical_bounds"] >= 0

    def test_interval_brackets_the_point_prediction(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post("/api/point-forecast", json=_request()).json()
        interval = body["interval"]
        assert interval["nominal_coverage"] == 0.8
        if interval["lower_kwh"] is not None:
            assert interval["lower_kwh"] <= body["kwh_hour"] <= interval["upper_kwh"]

    def test_operating_conditions_state_their_thresholds(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post("/api/point-forecast", json=_request()).json()
        assert body["operating_conditions"], "expected at least the wind-cooling note"
        keys = {note["key"] for note in body["operating_conditions"]}
        assert "wind_cooling" in keys
        for note in body["operating_conditions"]:
            assert note["threshold"], f"{note['key']} states no threshold"
            assert note["message"]

    def test_label_provenance_is_not_hidden(
        self, client: TestClient, stub_archive
    ) -> None:
        """README §10 limitation 2, carried in the payload rather than left to the docs."""
        body = client.post("/api/point-forecast", json=_request()).json()
        provenance = body["label_provenance"].lower()
        assert "modelled" in provenance
        assert "not metered" in provenance


class TestNoLeakage:
    def test_training_ends_strictly_before_the_target_hour(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post("/api/point-forecast", json=_request()).json()
        period_end = pd.Timestamp(body["training"]["period_end"])
        target = pd.Timestamp(body["target"]["resolved_utc"])
        assert period_end < target, (
            "the model was fitted on data at or after the hour it is predicting"
        )

    def test_no_archive_window_used_for_training_reaches_the_target_date(
        self, client: TestClient, stub_archive
    ) -> None:
        client.post("/api/point-forecast", json=_request())
        training_windows = [w for w in stub_archive["windows"] if (w[1] - w[0]).days > 3]
        assert training_windows, "expected one long fetch for the training window"
        for _start, end in training_windows:
            assert end < TARGET_DATE

    def test_the_leakage_rule_is_stated_in_the_payload(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post("/api/point-forecast", json=_request()).json()
        rule = body["training"]["leakage_rule"]
        assert "strictly before" in rule
        assert "embargo" in rule


class TestEnsembleVisibility:
    def test_four_base_models_are_reported_beside_the_ensemble(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post(
            "/api/point-forecast", json=_request(model_key="ensemble_four")
        ).json()

        assert body["model_key"] == "ensemble_four"
        assert len(body["per_model"]) == 4
        assert [entry["model"] for entry in body["per_model"]] == [
            "random_forest",
            "hist_gradient_boosting",
            "extra_trees",
            "ridge",
        ]
        for entry in body["per_model"]:
            assert entry["display_name"]
            assert entry["kwh_hour"] >= 0.0
            assert isinstance(entry["weight"], float)

    def test_weights_are_not_a_uniform_average(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post(
            "/api/point-forecast", json=_request(model_key="ensemble_four")
        ).json()
        weights = [entry["weight"] for entry in body["per_model"]]
        assert len(set(weights)) > 1

    def test_a_single_estimator_says_it_has_no_breakdown(
        self, client: TestClient, stub_archive
    ) -> None:
        body = client.post(
            "/api/point-forecast", json=_request(model_key="random_forest")
        ).json()
        assert body["per_model"] == []
        assert "ensemble_four" in body["per_model_note"]


class TestRejections:
    def test_a_date_beyond_the_archive_names_the_window(
        self, client: TestClient, stub_archive
    ) -> None:
        response = client.post(
            "/api/point-forecast", json=_request(target_datetime="2030-01-01T12:00:00")
        )
        assert response.status_code == 422
        message = response.json()["message"]
        assert LATEST_ARCHIVE_DATE.isoformat() in message
        assert "reanalysis" in message.lower()

    def test_a_date_before_the_record_is_refused(
        self, client: TestClient, stub_archive
    ) -> None:
        response = client.post(
            "/api/point-forecast", json=_request(target_datetime="1995-05-05T12:00:00")
        )
        assert response.status_code == 422

    def test_an_impossible_year_is_refused_at_the_boundary(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/point-forecast", json=_request(target_datetime="1830-05-05T12:00:00")
        )
        assert response.status_code == 422

    def test_unknown_model_lists_the_alternatives(self, client: TestClient) -> None:
        response = client.post("/api/point-forecast", json=_request(model_key="knn"))
        assert response.status_code == 422
        assert "ensemble_four" in response.json()["message"]

    def test_unknown_field_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/point-forecast", json=_request(targt_datetime="2024-06-20T13:00")
        )
        assert response.status_code == 422

    def test_missing_location_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/point-forecast",
            json={"location": {}, "target_datetime": "2024-06-20T13:00"},
        )
        assert response.status_code == 422


class TestReuse:
    def test_a_second_request_for_the_same_hour_reuses_the_trained_model(
        self, client: TestClient, stub_archive
    ) -> None:
        """Training costs tens of seconds; the same question must not pay twice."""
        first = client.post("/api/point-forecast", json=_request()).json()
        second = client.post("/api/point-forecast", json=_request()).json()

        assert first["training"]["analysis_id"] == second["training"]["analysis_id"]
        assert any("cached" in note.lower() for note in second["warnings"])

    def test_a_different_hour_on_the_same_day_reuses_it_too(
        self, client: TestClient, stub_archive
    ) -> None:
        morning = client.post(
            "/api/point-forecast",
            json=_request(target_datetime=f"{TARGET_DATE.isoformat()}T09:00:00"),
        ).json()
        afternoon = client.post(
            "/api/point-forecast",
            json=_request(target_datetime=f"{TARGET_DATE.isoformat()}T15:00:00"),
        ).json()
        assert morning["training"]["analysis_id"] == afternoon["training"]["analysis_id"]
        assert morning["kwh_hour"] != afternoon["kwh_hour"]
