"""Determine the archive's hourly interval-labelling convention empirically.

Irradiance in the source archive is an average over an interval, but solar position is an
instantaneous quantity. If the position is evaluated at the interval's label rather than at
its representative instant, a systematic phase error appears — irradiance seems to arrive
before sunrise, and the clear-sky ceiling is apparently exceeded.

Rather than assume the convention, this script measures it: it sweeps candidate offsets and
scores each by three independent criteria. The offset that wins on all three is the correct
representative instant.

    python scripts/calibrate_interval.py --location Hyderabad --year 2023

The result of this procedure is recorded as IRRADIANCE_INTERVAL_OFFSET_MINUTES in
app/features/solar_geometry.py.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.sources import fetch_archive, resolve_location  # noqa: E402
from app.features.solar_geometry import (  # noqa: E402
    clear_sky_ghi_haurwitz,
    solar_position,
)

CANDIDATE_OFFSETS = (-60, -45, -30, -15, 0, 15, 30, 45, 60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", default="Hyderabad")
    parser.add_argument("--year", type=int, default=2023)
    args = parser.parse_args()

    location = resolve_location(query=args.location)
    frame = fetch_archive(location, date(args.year, 1, 1), date(args.year, 12, 31))

    ghi = frame["ghi_wm2"].to_numpy(dtype=float)
    labels = frame.index.to_numpy().astype("datetime64[s]")

    print(f"Location : {location.label} ({location.latitude:.4f}, {location.longitude:.4f})")
    print(f"Period   : {frame.index.min()} -> {frame.index.max()}  ({len(frame):,} hours)\n")
    print(f"{'offset':>8} {'night viol.':>12} {'exceed>115%':>12} {'corr':>9} {'RMSE clear':>11}")
    print("-" * 56)

    best = None
    for offset in CANDIDATE_OFFSETS:
        shifted = labels + np.timedelta64(offset * 60, "s")
        pos = solar_position(shifted, location.latitude, location.longitude)
        clear = clear_sky_ghi_haurwitz(pos.apparent_zenith)

        night_violations = int(np.sum((~pos.is_daytime) & (ghi > 5.0)))
        lit = clear > 50.0
        exceedances = int(np.sum(lit & (ghi > clear * 1.15)))
        correlation = float(np.corrcoef(ghi, clear)[0, 1])

        with np.errstate(divide="ignore", invalid="ignore"):
            kt = np.where(lit, ghi / clear, np.nan)
        clear_hours = lit & (kt > 0.9) & np.isfinite(kt)
        rmse = (
            float(np.sqrt(np.nanmean((ghi[clear_hours] - clear[clear_hours]) ** 2)))
            if clear_hours.any()
            else float("nan")
        )

        print(f"{offset:+7d}m {night_violations:12d} {exceedances:12d} {correlation:9.5f} {rmse:11.2f}")

        score = (exceedances, -correlation, night_violations)
        if best is None or score < best[0]:
            best = (score, offset)

    print(
        f"\nBest offset: {best[1]:+d} minutes "
        f"(fewest clear-sky exceedances, then highest correlation)."
    )
    print("Record this as IRRADIANCE_INTERVAL_OFFSET_MINUTES in app/features/solar_geometry.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
