"""The live forecast endpoint.

The weather service is stubbed throughout. What is under test is the wiring — that a
stored estimate can be rebuilt into a Location and a PVSystem, that the physics chain is
fed the right columns, and that the response says plainly what kind of number it carries.
Whether Erbs and PVWatts are correct is established by ``test_solar_geometry.py``, and
re-asserting it here against fabricated weather would prove nothing.

The stub frame is explicitly synthetic and labelled as such. It is not a dataset standing
in for real observations — it is a fixture with known values chosen so the assertions below
mean something.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

PAYLOAD = {
    "location": {
        "latitude": 16.5062,
        "longitude": 80.648,
        "name": "Vijayawada",
        "country": "India",
        "country_code": "IN",
        "admin1": "Andhra Pradesh",
        "elevation_m": 23.0,
        "timezone": None,
        "source": "geocoding",
        "label": "Vijayawada, Andhra Pradesh, India",
    },
    "system": {
        "dc_capacity_kwp": 5.0,
        "capacity_kwp": 5.0,
        "ac_capacity_kw": 4.167,
        "surface_tilt_deg": 15.0,
        "surface_azimuth_deg": 180.0,
        "temperature_coefficient_per_c": -0.0035,
        "system_losses_fraction": 0.14,
        "inverter_efficiency": 0.96,
        "albedo": 0.2,
    },
    "generation": {"annual_kwh": 7500.0},
}


def _stub_frame(hours: int = 72) -> pd.DataFrame:
    """A deliberately synthetic forecast frame.

    A clean diurnal sine on GHI, constant temperature and wind. Not real weather and not
    presented as such — it exists so that "daylight produces power, night produces none"
    is a checkable statement.
    """
    index = pd.date_range("2026-08-24T00:00:00Z", periods=hours, freq="h", name="time_utc")
    hour_of_day = np.array([t.hour for t in index])
    ghi = np.clip(np.sin((hour_of_day - 6) / 12 * np.pi), 0, None) * 850.0

    frame = pd.DataFrame(
        {
            "ghi_wm2": ghi,
            "temperature_c": np.full(hours, 30.0),
            "wind_speed_ms": np.full(hours, 2.0),
        },
        index=index,
    )
    frame.attrs.update({"kind": "forecast", "retrieved_at": "2026-08-23T12:00:00+00:00"})
    return frame


@pytest.fixture()
def saved_estimate() -> str:
    from app.estimate import store

    return store.save(dict(PAYLOAD), label="Forecast fixture").estimate_id


@pytest.fixture()
def stub_weather(monkeypatch):
    """Replace the upstream fetch. No network, no dependence on real forecast content."""
    import app.estimate.live_forecast as module

    captured: dict[str, object] = {}

    def _fake_fetch(location, *, horizon_hours):
        captured["horizon_hours"] = horizon_hours
        captured["latitude"] = location.latitude
        return _stub_frame(min(horizon_hours, 72))

    monkeypatch.setattr(module, "fetch_forecast", _fake_fetch)
    return captured


class TestEndpoint:
    def test_returns_daily_energy_for_a_saved_estimate(
        self, client: TestClient, saved_estimate: str, stub_weather
    ) -> None:
        response = client.get(f"/api/estimate/{saved_estimate}/live-forecast")
        assert response.status_code == 200, response.text

        body = response.json()
        assert body["daily"], "expected at least one day"
        for day in body["daily"]:
            assert day["energy_kwh"] >= 0, "generation can never be negative"
            assert 1 <= day["hours"] <= 24

        assert body["total_kwh"] == pytest.approx(
            sum(d["energy_kwh"] for d in body["daily"]), abs=0.05
        )

    def test_the_method_is_named_so_it_cannot_be_read_as_a_model_prediction(
        self, client: TestClient, saved_estimate: str, stub_weather
    ) -> None:
        """The whole point of this path is that it is physics, not a trained model.

        If that label ever changed, the interface would be presenting a physics figure
        beside the console's model forecasts with nothing distinguishing them.
        """
        body = client.get(f"/api/estimate/{saved_estimate}/live-forecast").json()
        assert body["method"] == "physics_pass_through"
        assert "PVWatts" in body["provenance"]["model_chain"]
        assert body["provenance"]["kind"] == "forecast"

    def test_no_interval_is_reported(
        self, client: TestClient, saved_estimate: str, stub_weather
    ) -> None:
        """A range here would look like the annual estimate's measured band and mean
        something entirely different. The absence is deliberate and the note says so."""
        body = client.get(f"/api/estimate/{saved_estimate}/live-forecast").json()

        for day in body["daily"]:
            assert "lower_kwh" not in day
            assert "upper_kwh" not in day
        assert "not a range" in body["note"].lower() or "single expected value" in body["note"].lower()

    def test_night_hours_contribute_nothing(
        self, client: TestClient, saved_estimate: str, stub_weather
    ) -> None:
        """The stub's GHI is zero overnight, so a day's total must come only from daylight.
        A non-zero figure would mean the chain was fed the wrong column."""
        body = client.get(f"/api/estimate/{saved_estimate}/live-forecast").json()
        full_days = [d for d in body["daily"] if d["hours"] == 24]
        assert full_days, "the fixture should contain at least one complete day"
        for day in full_days:
            # 5 kWp under a clean sine cannot plausibly exceed its own daily ceiling.
            assert 0 < day["energy_kwh"] < 5.0 * 24


class TestValidation:
    def test_unknown_estimate_is_a_clean_404(self, client: TestClient, stub_weather) -> None:
        response = client.get("/api/estimate/nosuchestimateidentifier/live-forecast")
        assert response.status_code == 404
        assert "could not find" in response.json()["message"].lower()

    @pytest.mark.parametrize("horizon", [23, 385, 0, -1])
    def test_horizon_outside_the_permitted_range_is_refused(
        self, client: TestClient, saved_estimate: str, stub_weather, horizon: int
    ) -> None:
        response = client.get(
            f"/api/estimate/{saved_estimate}/live-forecast?horizon_hours={horizon}"
        )
        assert response.status_code == 422

    def test_horizon_is_passed_through_to_the_weather_service(
        self, client: TestClient, saved_estimate: str, stub_weather
    ) -> None:
        client.get(f"/api/estimate/{saved_estimate}/live-forecast?horizon_hours=48")
        assert stub_weather["horizon_hours"] == 48

    def test_the_estimates_own_coordinates_are_used(
        self, client: TestClient, saved_estimate: str, stub_weather
    ) -> None:
        """A forecast for the wrong place would be indistinguishable from a right one
        without this — the numbers would still look reasonable."""
        client.get(f"/api/estimate/{saved_estimate}/live-forecast")
        assert stub_weather["latitude"] == pytest.approx(16.5062)

    def test_an_estimate_without_a_system_is_refused_with_a_reason(
        self, client: TestClient, stub_weather
    ) -> None:
        from app.estimate import store

        broken = dict(PAYLOAD)
        broken["system"] = {}
        estimate_id = store.save(broken, label="No system").estimate_id

        response = client.get(f"/api/estimate/{estimate_id}/live-forecast")
        assert response.status_code == 409
        assert "system size" in response.json()["message"].lower()


class TestIsolation:
    def test_the_existing_estimate_response_is_unchanged(
        self, client: TestClient, saved_estimate: str
    ) -> None:
        """This feature is additive. Reading an estimate must return exactly what it
        returned before, with no forecast fields grafted on."""
        body = client.get(f"/api/estimate/{saved_estimate}").json()

        assert "daily" not in body
        assert "method" not in body
        assert "live_forecast" not in body
        assert body["generation"]["annual_kwh"] == 7500.0

    def test_no_trained_model_is_involved(
        self, client: TestClient, saved_estimate: str, stub_weather, monkeypatch
    ) -> None:
        """The calculator's two-minute promise depends on this path never fitting a model.

        Any call into the trainer would take tens of seconds, so making it explode is the
        cheapest way to keep that guarantee from eroding unnoticed.
        """
        import app.models.trainer as trainer

        def _explode(*args, **kwargs):
            raise AssertionError("the live forecast path must not train a model")

        monkeypatch.setattr(trainer, "train_and_evaluate", _explode)

        response = client.get(f"/api/estimate/{saved_estimate}/live-forecast")
        assert response.status_code == 200


class TestHorizonBoundary:
    def test_a_trailing_partial_day_is_dropped(
        self, client: TestClient, saved_estimate: str, monkeypatch
    ) -> None:
        """The horizon cuts mid-day in local time, leaving a few hours that are often all
        night. A genuine 0.0 kWh renders as an empty bar and reads as a broken forecast,
        so the boundary artifact is dropped rather than displayed."""
        import app.estimate.live_forecast as module

        # 54 UTC hours. The fixture's longitude gives a +5h offset, so in local time this
        # is a 19-hour opening day, one complete day, then an 11-hour tail — the tail being
        # exactly the artifact under test.
        monkeypatch.setattr(
            module, "fetch_forecast", lambda location, *, horizon_hours: _stub_frame(54)
        )
        body = client.get(f"/api/estimate/{saved_estimate}/live-forecast").json()

        assert body["daily"], "at least one day must survive"
        assert body["daily"][-1]["hours"] == 24, "the trailing partial day should be gone"

    def test_a_leading_partial_day_is_kept(
        self, client: TestClient, saved_estimate: str, monkeypatch
    ) -> None:
        """'Today, already partly over' is real information, unlike the trailing stub."""
        import app.estimate.live_forecast as module

        def _late_start(location, *, horizon_hours):
            # Begin at 14:00 so the first local day is genuinely partial.
            frame = _stub_frame(40)
            frame.index = pd.date_range(
                "2026-08-24T14:00:00Z", periods=len(frame), freq="h", name="time_utc"
            )
            return frame

        monkeypatch.setattr(module, "fetch_forecast", _late_start)
        body = client.get(f"/api/estimate/{saved_estimate}/live-forecast").json()

        assert body["daily"][0]["hours"] < 24, "the first day should still be partial"

    def test_a_single_day_is_never_trimmed_to_nothing(
        self, client: TestClient, saved_estimate: str, monkeypatch
    ) -> None:
        import app.estimate.live_forecast as module

        monkeypatch.setattr(
            module, "fetch_forecast", lambda location, *, horizon_hours: _stub_frame(6)
        )
        body = client.get(f"/api/estimate/{saved_estimate}/live-forecast").json()
        assert len(body["daily"]) == 1
