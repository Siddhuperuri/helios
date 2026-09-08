"""Load profile: the analysis console.

A different workload from the consumer path in every respect that matters for sizing, which
is why it is a separate file rather than another task weight in the same one.

    typical request  10–40 s of CPU, single-threaded, in-process

Creating an analysis fetches years of hourly weather, builds features, fits a model and
cross-validates it. Comparing models does that several times over. These are not requests
that queue politely behind each other: each one occupies a worker for tens of seconds, so
concurrency here is bounded by cores, not by connections — and running this profile at the
concurrency the consumer profile tolerates will saturate the fleet immediately.

That is the finding this file exists to produce. Two conclusions usually follow from it:

* the console needs its own capacity, or its own instances, so that a researcher comparing
  six models does not make the calculator unusable for everyone else, and
* the work belongs on a queue. The API is already shaped for that move — see
  docs/PRODUCTION_ARCHITECTURE.md — and a load test is how you decide when it stops being
  optional.

Run with a *small* user count. Fifty concurrent users here is not a stress test, it is a
denial of service against your own fleet::

    locust -f console.py --host http://localhost \\
           --headless --users 6 --spawn-rate 1 --run-time 10m --csv results/console
"""

from __future__ import annotations

import random

from locust import HttpUser, between, events, task

LOCATIONS = [
    (16.5062, 80.6480),
    (17.3850, 78.4867),
    (28.6139, 77.2090),
    (37.7749, -122.4194),
    (51.5074, -0.1278),
]

# The four single estimators. `ensemble_four` is deliberately absent: it fits all four of
# them plus a meta-learner over inner folds, so including it would make the load figures a
# measurement of one endpoint rather than of the console.
MODELS = ["random_forest", "hist_gradient_boosting", "extra_trees", "ridge"]


class Analyst(HttpUser):
    """One researcher working through an analysis, the way the console is actually used.

    An analysis is created once and then interrogated through a dozen follow-up requests.
    Modelling that sequence matters: the follow-ups are cheap only because the analysis is
    held in the instance that produced it, and a test that created a fresh analysis for
    every request would measure something nobody does.
    """

    wait_time = between(5, 20)

    def on_start(self) -> None:
        self.analysis_id: str | None = None
        self.create_analysis()

    @task(1)
    def create_analysis(self) -> None:
        latitude, longitude = random.choice(LOCATIONS)
        with self.client.post(
            "/api/analysis",
            json={
                "location": {"latitude": latitude, "longitude": longitude},
                "model_key": random.choice(MODELS),
                "target": "clear_sky_index",
                # A year rather than the two-year default: still a realistic run, and it
                # keeps a single iteration inside a few minutes.
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
                "compute_intervals": True,
                "run_cv": True,
            },
            name="/api/analysis [create]",
            timeout=600,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.analysis_id = response.json().get("analysis_id")
                response.success()
            elif response.status_code in (429, 503):
                # Shedding load is the system defending itself, not a fault.
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(6)
    def read_performance(self) -> None:
        if not self.analysis_id:
            return
        self.client.get(
            f"/api/analysis/{self.analysis_id}/performance",
            name="/api/analysis/{id}/performance",
            timeout=120,
        )

    @task(5)
    def read_predictions(self) -> None:
        if not self.analysis_id:
            return
        self.client.get(
            f"/api/analysis/{self.analysis_id}/predictions?limit=1500",
            name="/api/analysis/{id}/predictions",
            timeout=120,
        )

    @task(4)
    def read_quality(self) -> None:
        if not self.analysis_id:
            return
        self.client.get(
            f"/api/analysis/{self.analysis_id}/quality", name="/api/analysis/{id}/quality"
        )

    @task(2)
    def explain(self) -> None:
        """Permutation importance. Expensive: it refits the scorer many times over."""
        if not self.analysis_id:
            return
        self.client.get(
            f"/api/analysis/{self.analysis_id}/explain",
            name="/api/analysis/{id}/explain",
            timeout=300,
        )

    @task(2)
    def forecast(self) -> None:
        if not self.analysis_id:
            return
        self.client.post(
            f"/api/analysis/{self.analysis_id}/forecast",
            json={"horizon_hours": 72},
            name="/api/analysis/{id}/forecast",
            timeout=180,
        )

    @task(1)
    def compare_models(self) -> None:
        """The heaviest request in the product. Fits several models end to end.

        Weighted at 1 deliberately — it is rare in real use, and weighting it higher would
        produce a capacity number for a workload nobody has.
        """
        if not self.analysis_id:
            return
        self.client.post(
            f"/api/analysis/{self.analysis_id}/compare-models",
            json={"model_keys": random.sample(MODELS, 3)},
            name="/api/analysis/{id}/compare-models",
            timeout=900,
        )


@events.test_start.add_listener
def announce(environment, **_kwargs) -> None:
    print(
        "\nConsole profile. Keep the user count low — each request occupies a worker for "
        "tens of seconds, so this saturates a fleet at concurrency levels the consumer "
        "profile shrugs off. Record CPU per replica alongside the latencies; that is the "
        "number that decides whether this work needs its own instances or a queue.\n"
    )


@events.quitting.add_listener
def summarise(environment, **_kwargs) -> None:
    stats = environment.stats.total
    failure_ratio = stats.fail_ratio
    p95 = stats.get_response_time_percentile(0.95)

    # A far looser latency budget than the consumer path, because the work genuinely takes
    # this long. The error rate is the real signal here: it is what tells you the fleet ran
    # out of workers rather than merely being slow.
    if failure_ratio > 0.02:
        print(f"FAIL: error rate {failure_ratio:.2%} exceeds 2%")
        environment.process_exit_code = 1
    elif p95 and p95 > 120_000:
        print(f"FAIL: p95 {p95:.0f} ms exceeds the 120 s budget for the console path")
        environment.process_exit_code = 1
    else:
        print(f"PASS: error rate {failure_ratio:.2%}, p95 {p95 or 0:.0f} ms")
        environment.process_exit_code = 0
