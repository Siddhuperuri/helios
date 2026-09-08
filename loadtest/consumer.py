"""Load profile: the consumer path.

What a real visitor does. Most of them never sign in, most requests are reference data or
a cached estimate, and the expensive one — producing an estimate for a location nobody has
asked about before — is comparatively rare because the weather cache is shared across the
fleet.

    typical request  1–15 s   (a first estimate for an unseen location is the slow end)

Run::

    locust -f consumer.py --host http://localhost

Headless, which is what CI and a capacity run want::

    locust -f consumer.py --host http://localhost \\
           --headless --users 100 --spawn-rate 10 --run-time 5m \\
           --csv results/consumer

What to read afterwards is in docs/LOAD_TESTING.md. The short version: p95 and the error
rate are the numbers that decide replica count, and the mean is close to useless here
because the distribution is bimodal — a cache hit and a cache miss are three orders of
magnitude apart.
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, events, task

# Real places, spread across climates and hemispheres. Using a fixed set rather than random
# coordinates is deliberate: it keeps the shared weather cache warm the way real traffic
# does, so the test measures the application rather than Open-Meteo's rate limiter.
LOCATIONS = [
    (16.5062, 80.6480, "Vijayawada"),
    (17.3850, 78.4867, "Hyderabad"),
    (13.0827, 80.2707, "Chennai"),
    (28.6139, 77.2090, "Delhi"),
    (-33.8688, 151.2093, "Sydney"),
    (37.7749, -122.4194, "San Francisco"),
    (51.5074, -0.1278, "London"),
    (-1.2921, 36.8219, "Nairobi"),
]

SEARCH_TERMS = ["vijay", "hyder", "chen", "lond", "nairo", "sydn"]


class AnonymousVisitor(HttpUser):
    """Somebody using the calculator without an account. The majority of traffic."""

    weight = 7
    # Think time. Without it a load test measures how fast a machine can loop, which is a
    # number nobody can act on.
    wait_time = between(3, 12)

    def on_start(self) -> None:
        self.estimate_id: str | None = None

    @task(10)
    def browse_reference_data(self) -> None:
        """Cheap reads. The interview catalogue and the limits load on almost every visit."""
        self.client.get("/api/meta/interview", name="/api/meta/interview")
        self.client.get("/api/meta/limits", name="/api/meta/limits")

    @task(8)
    def search_for_a_location(self) -> None:
        term = random.choice(SEARCH_TERMS)
        self.client.get(
            f"/api/locations/search?q={term}&limit=6", name="/api/locations/search"
        )

    @task(3)
    def run_an_estimate(self) -> None:
        """The expensive one, and the reason capacity has to be measured rather than guessed."""
        latitude, longitude, _ = random.choice(LOCATIONS)
        with self.client.post(
            "/api/estimate",
            json={
                "user_type": "home",
                "mode": "quick",
                "goal": "install",
                "location": {"latitude": latitude, "longitude": longitude},
                "installation_type": "rooftop",
                "consumption_method": "bill",
                "monthly_bill": random.choice([1200, 2400, 3600, 5000]),
                "save": True,
            },
            name="/api/estimate [create]",
            timeout=120,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.estimate_id = response.json().get("estimate_id")
                response.success()
            elif response.status_code == 429:
                # Being rate limited is the system working, not a failure. Counting it as
                # an error would make the error-rate graph meaningless at exactly the load
                # where it matters most.
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(6)
    def reopen_a_saved_estimate(self) -> None:
        """Following the opaque link. Should be a cheap database read and nothing else."""
        if not self.estimate_id:
            return
        self.client.get(
            f"/api/estimate/{self.estimate_id}", name="/api/estimate/{id} [read]"
        )

    @task(1)
    def download_the_report(self) -> None:
        if not self.estimate_id:
            return
        self.client.get(
            f"/api/estimate/{self.estimate_id}/report",
            name="/api/estimate/{id}/report",
            timeout=30,
        )


class SignedInVisitor(HttpUser):
    """Somebody with an account. A minority, but they exercise the authenticated paths."""

    weight = 3
    wait_time = between(4, 15)

    def on_start(self) -> None:
        """Register and sign in.

        Two calls, because registration deliberately returns no session — see
        app/auth/routes.py::register. Doing it the same way the frontend does keeps the
        measured cost honest.
        """
        self.token: str | None = None
        self.estimate_id: str | None = None

        email = f"load-{uuid.uuid4().hex[:12]}@loadtest.invalid"
        password = "a-long-enough-load-test-password"

        self.client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
            name="/api/auth/register",
        )
        with self.client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
            name="/api/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.token = response.json()["access_token"]
                response.success()
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(8)
    def open_the_dashboard(self) -> None:
        """The listing reads projected columns, never the payloads. This is the query that
        would have been catastrophic if it deserialised a megabyte per row."""
        if not self.token:
            return
        self.client.get("/api/estimates?limit=25", headers=self.auth, name="/api/estimates")

    @task(4)
    def check_the_account(self) -> None:
        if not self.token:
            return
        self.client.get("/api/auth/me", headers=self.auth, name="/api/auth/me")

    @task(2)
    def run_an_owned_estimate(self) -> None:
        if not self.token:
            return
        latitude, longitude, _ = random.choice(LOCATIONS)
        with self.client.post(
            "/api/estimate",
            headers=self.auth,
            json={
                "user_type": "business",
                "mode": "quick",
                "goal": "install",
                "location": {"latitude": latitude, "longitude": longitude},
                "installation_type": "rooftop",
                "consumption_method": "bill",
                "monthly_bill": 8000,
                "save": True,
            },
            name="/api/estimate [create, owned]",
            timeout=120,
            catch_response=True,
        ) as response:
            if response.status_code in (200, 429):
                if response.status_code == 200:
                    self.estimate_id = response.json().get("estimate_id")
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")


@events.test_start.add_listener
def announce(environment, **_kwargs) -> None:
    print(
        "\nConsumer profile. Watch p95 rather than the mean: the distribution is bimodal "
        "(cache hit vs. cache miss) and a mean between the two describes no real request.\n"
    )


@events.quitting.add_listener
def summarise(environment, **_kwargs) -> None:
    """Fail the run on the thresholds a capacity exercise actually cares about.

    A non-zero exit is what lets this run in CI as a gate rather than as a report nobody
    reads.
    """
    stats = environment.stats.total
    failure_ratio = stats.fail_ratio
    p95 = stats.get_response_time_percentile(0.95)

    if failure_ratio > 0.01:
        print(f"FAIL: error rate {failure_ratio:.2%} exceeds 1%")
        environment.process_exit_code = 1
    elif p95 and p95 > 20_000:
        print(f"FAIL: p95 {p95:.0f} ms exceeds the 20 s budget for the consumer path")
        environment.process_exit_code = 1
    else:
        print(f"PASS: error rate {failure_ratio:.2%}, p95 {p95 or 0:.0f} ms")
        environment.process_exit_code = 0
