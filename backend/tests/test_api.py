"""API contract tests.

These exercise the request-validation boundary and the reference endpoints, which need no
network access. They assert that rejections carry an actionable message — the platform
treats "Something went wrong" as a defect, and a test that only checked the status code
would let that regression through.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# `client` comes from conftest, which builds the application against a database and shared
# store belonging to this test alone. Importing `app.main.app` at module scope, as this
# file used to, binds one application object for the whole session and quietly opts every
# test in the file out of that isolation.


class TestReferenceEndpoints:
    def test_health(self, client: TestClient) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.parametrize(
        "path,key",
        [
            ("/api/meta/parameters", "parameters"),
            ("/api/meta/models", "models"),
            ("/api/meta/metrics", "metrics"),
            ("/api/meta/literature", "papers"),
            ("/api/meta/scenarios", "presets"),
        ],
    )
    def test_metadata_endpoints(self, client: TestClient, path: str, key: str) -> None:
        r = client.get(path)
        assert r.status_code == 200
        assert key in r.json()

    def test_parameter_dictionary_is_complete(self, client: TestClient) -> None:
        params = client.get("/api/meta/parameters").json()["parameters"]
        for p in params:
            assert p["definition"], f"{p['key']} has no definition"
            assert p["role"], f"{p['key']} has no role"
        keys = {p["key"] for p in params}
        assert {"ghi_wm2", "temperature_c", "solar_zenith_deg"} <= keys

    def test_unavailable_parameters_are_declared(self, client: TestClient) -> None:
        """Variables the research used but this source lacks must be surfaced, not hidden."""
        payload = client.get("/api/meta/parameters").json()
        assert payload["unavailable"]
        for u in payload["unavailable"]:
            assert u["reason"]

    def test_every_model_declares_provenance(self, client: TestClient) -> None:
        for m in client.get("/api/meta/models").json()["models"]:
            assert m["sources"], f"{m['key']} claims no source"
            assert m["description"]

    def test_literature_statuses_are_from_the_legend(self, client: TestClient) -> None:
        payload = client.get("/api/meta/literature").json()
        legend = set(payload["status_legend"])
        for t in payload["techniques"]:
            assert t["status"] in legend, f"{t['technique']} has an undeclared status"

    def test_security_headers(self, client: TestClient) -> None:
        r = client.get("/api/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert "X-Request-ID" in r.headers


class TestRequestValidation:
    """Every rejection must name the field and say what is acceptable."""

    def _post(self, client: TestClient, body: dict):
        return client.post("/api/analysis", json=body)

    def test_missing_location(self, client: TestClient) -> None:
        r = self._post(client, {"location": {}})
        assert r.status_code == 422
        assert "latitude" in r.json()["message"].lower()

    def test_latitude_without_longitude(self, client: TestClient) -> None:
        r = self._post(client, {"location": {"latitude": 17.4}})
        assert r.status_code == 422

    @pytest.mark.parametrize("lat", [91, -91, 1000])
    def test_out_of_range_latitude(self, client: TestClient, lat: float) -> None:
        r = self._post(client, {"location": {"latitude": lat, "longitude": 0}})
        assert r.status_code == 422

    def test_unknown_model_lists_the_alternatives(self, client: TestClient) -> None:
        r = self._post(client, {"location": {"query": "Hyderabad"}, "model_key": "does_not_exist"})
        assert r.status_code == 422
        message = r.json()["message"]
        assert "random_forest" in message, "the error should list valid models"

    def test_period_too_short_states_the_minimum(self, client: TestClient) -> None:
        r = self._post(
            client,
            {
                "location": {"query": "Hyderabad"},
                "start_date": "2024-01-01",
                "end_date": "2024-01-10",
            },
        )
        assert r.status_code == 422
        assert "60 days" in r.json()["message"]

    def test_reversed_dates(self, client: TestClient) -> None:
        r = self._post(
            client,
            {
                "location": {"query": "Hyderabad"},
                "start_date": "2024-06-01",
                "end_date": "2024-01-01",
            },
        )
        assert r.status_code == 422
        assert "earlier" in r.json()["message"].lower()

    def test_horizon_out_of_range(self, client: TestClient) -> None:
        r = self._post(client, {"location": {"query": "Hyderabad"}, "horizon_hours": 99999})
        assert r.status_code == 422

    def test_unknown_field_rejected(self, client: TestClient) -> None:
        """extra='forbid' stops silent typos from being ignored."""
        r = self._post(client, {"location": {"query": "Hyderabad"}, "modle_key": "random_forest"})
        assert r.status_code == 422

    def test_invalid_pv_system(self, client: TestClient) -> None:
        r = self._post(
            client,
            {"location": {"query": "Hyderabad"}, "system": {"dc_capacity_kwp": -5}},
        )
        assert r.status_code == 422

    def test_tilt_beyond_vertical(self, client: TestClient) -> None:
        r = self._post(
            client, {"location": {"query": "Hyderabad"}, "system": {"surface_tilt_deg": 120}}
        )
        assert r.status_code == 422

    def test_error_payload_shape(self, client: TestClient) -> None:
        body = self._post(client, {"location": {}}).json()
        assert body["error"] == "validation_error"
        assert body["message"]
        assert body["remedy"]
        assert isinstance(body["field_errors"], list)

    def test_pydantic_prefix_is_stripped(self, client: TestClient) -> None:
        """'Value error, ' is an implementation detail users should never see."""
        body = self._post(client, {"location": {}}).json()
        assert "Value error" not in body["message"]
        for fe in body["field_errors"]:
            assert not fe["message"].startswith("Value error")


class TestMissingResources:
    def test_unknown_analysis_explains_itself(self, client: TestClient) -> None:
        r = client.get("/api/analysis/nonexistent123")
        assert r.status_code == 404
        assert "Re-run" in r.json()["message"]

    def test_unknown_experiment(self, client: TestClient) -> None:
        r = client.get("/api/experiments/nonexistent123")
        assert r.status_code == 404

    def test_short_location_query_rejected(self, client: TestClient) -> None:
        r = client.get("/api/locations/search?q=a")
        assert r.status_code == 422
