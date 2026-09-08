"""Seed a development database.

Creates a handful of accounts and estimates so that the dashboard, the ownership rules, the
verification banner and the result page can all be looked at without clicking through
signup and a four-minute interview each time.

Two safeguards, because a seeding script that runs against the wrong database is a bad
afternoon:

* It refuses outright when ``SOLAR_ENV=production``.
* It refuses when the database already holds accounts, unless ``--force`` is passed.

Why the estimates are real
--------------------------
The first version of this script wrote payloads by hand — a label, a capacity, a headline
figure — on the reasoning that the dashboard reads only the projected summary columns
anyway. That was true of the dashboard and false of everything else. The result page reads
``system.panels.count``, the assumptions ledger, the monthly ranges and a dozen other
nested fields, and the live forecast rebuilds a ``Location`` and a ``PVSystem`` from the
stored payload. A hand-built fixture produced a dashboard that looked correct and a result
page that died with a client-side exception.

So the engine runs for real. It costs a few seconds per estimate the first time and is
near-instant afterwards, because the weather for each location is cached and shared. In
exchange every seeded estimate is a genuine one: every screen works, and the numbers are
the numbers the platform would actually produce.

That does mean seeding needs network access to the weather service. If it is unavailable
the script says so and stops, rather than writing fixtures that break on the first click.

Usage::

    python -m scripts.seed
    python -m scripts.seed --force
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from app.auth import service
from app.config import get_settings
from app.db.base import create_all, session_scope
from app.db.models import Estimate
from app.estimate import store as estimate_store

PASSWORD = "helios-dev-password"

ACCOUNTS = [
    # (email, verified, description)
    ("farmer@example.com", True, "confirmed account with several estimates"),
    ("shopkeeper@example.com", False, "unconfirmed account — shows the verification banner"),
    ("empty@example.com", True, "confirmed account with nothing saved — the empty state"),
]

# (owner email or None for anonymous, label, engine input)
ESTIMATES: list[tuple[str | None, str, dict[str, Any]]] = [
    (
        "farmer@example.com",
        "Pump shed — Vijayawada",
        {
            "user_type": "farm",
            "latitude": 16.5062,
            "longitude": 80.6480,
            "consumption_method": "bill",
            "monthly_bill": 4200.0,
            "installation_type": "ground",
        },
    ),
    (
        "farmer@example.com",
        "North field — Guntur",
        {
            "user_type": "farm",
            "latitude": 16.3067,
            "longitude": 80.4365,
            "consumption_method": "bill",
            "monthly_bill": 7800.0,
            "installation_type": "ground",
        },
    ),
    (
        "shopkeeper@example.com",
        "Shop roof — Hyderabad",
        {
            "user_type": "business",
            "latitude": 17.3850,
            "longitude": 78.4867,
            "consumption_method": "bill",
            "monthly_bill": 3100.0,
            "installation_type": "rooftop",
        },
    ),
    (
        # No owner. The anonymous case: reachable only by its link, and the estimate the
        # "save to my account" prompt appears on.
        None,
        "Anonymous estimate — Chennai",
        {
            "user_type": "home",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "consumption_method": "bill",
            "monthly_bill": 1900.0,
            "installation_type": "rooftop",
        },
    ),
]

# Backdated past the retention window so ``store.prune()`` has something to find — and so
# the rule that *owned* estimates are spared can be seen rather than taken on trust.
STALE_ESTIMATE: dict[str, Any] = {
    "user_type": "home",
    "latitude": 9.9312,
    "longitude": 76.2673,
    "consumption_method": "bill",
    "monthly_bill": 1200.0,
    "installation_type": "rooftop",
}


def _build(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run the real pipeline for one seeded estimate."""
    from app.estimate import engine

    return engine.run(engine.EstimateInput(mode="quick", goal="install", **inputs))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="seed even if accounts already exist"
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.is_production:
        print("Refusing to seed: SOLAR_ENV=production.", file=sys.stderr)
        return 1

    print(f"Database: {settings.database.safe_url}")
    create_all()

    with session_scope() as session:
        existing = service.count_users(session)
        if existing and not args.force:
            print(
                f"Refusing to seed: the database already holds {existing} account(s). "
                f"Pass --force to add to it anyway.",
                file=sys.stderr,
            )
            return 1

    owners: dict[str, str] = {}
    with session_scope() as session:
        for email, verified, description in ACCOUNTS:
            user = service.get_user_by_email(session, email)
            if user is None:
                outcome = service.register(session, email, PASSWORD)
                user = outcome.user
                assert user is not None
                if verified:
                    service.mark_verified(session, user)
                print(f"  account  {email:26} {description}")
            else:
                print(f"  account  {email:26} (already present)")
            owners[email] = str(user.id)

    print()
    print("  Running the engine for each estimate.")
    print("  The first run per location downloads its weather; later ones reuse the cache.")

    for owner_email, label, inputs in ESTIMATES:
        owner_id = owners.get(owner_email) if owner_email else None
        try:
            payload = _build(inputs)
        except Exception as exc:  # noqa: BLE001 - any upstream failure is the same story
            print(
                f"\n  Could not build '{label}': {exc}\n"
                f"  Seeding estimates needs network access to the weather service. The "
                f"accounts above were created; re-run this script once you are online.",
                file=sys.stderr,
            )
            return 1

        record = estimate_store.save(payload, label=label, owner_id=owner_id)
        annual = (payload.get("generation") or {}).get("annual_kwh")
        ownership = f"owned by {owner_email}" if owner_email else "anonymous"
        print(f"  estimate {record.estimate_id:24} {annual!s:>10} kWh/yr  {ownership}")

    try:
        stale_payload = _build(STALE_ESTIMATE)
    except Exception as exc:  # noqa: BLE001
        print(f"\n  Could not build the backdated estimate: {exc}", file=sys.stderr)
        return 1

    with session_scope() as session:
        stale = estimate_store.save(stale_payload, label="Stale anonymous estimate")
        row = session.get(Estimate, stale.estimate_id)
        if row is not None:
            row.created_at = datetime.now(timezone.utc) - timedelta(days=400)
        print(
            f"  estimate {stale.estimate_id:24} {'':>10}         "
            f"anonymous, backdated 400 days"
        )

    print()
    print(f"Every account uses the password: {PASSWORD}")
    print("Sign in at http://localhost:3000/login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
