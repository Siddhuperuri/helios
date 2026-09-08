"""The forward-looking path: what this system will produce over the next few days.

The annual estimate in :mod:`app.estimate.climatology` answers *"what will this produce in
a typical year?"* by running the physical chain over three years of observed weather. That
is the right answer to the sizing question, and it is deliberately not a forecast — a
twenty-year average has no opinion about Thursday.

This module answers the other question. It runs **the same physical chain** over
*forward-looking* numerical weather prediction instead of historical reanalysis, so the
result is specific to the days ahead rather than typical of the season.

What this is, precisely
-----------------------
Physics applied to a weather forecast. Nothing is trained, nothing is fitted, and no model
from :mod:`app.models` is involved. The chain is identical to the one behind the annual
figure — Erbs decomposition, HDKR transposition, Faiman cell temperature, PVWatts v5 DC and
the inverter model — and the only thing that changes is which weather goes in.

That is a deliberate choice rather than a shortcut. Two reasons:

1. **It costs nothing to be consistent.** A trained model on this path would mean the
   short-term number and the annual number came from different machinery, and any
   disagreement between them would be unattributable. Sharing the chain means a difference
   between the two can only come from the weather, which is the thing the user is
   actually being told about.
2. **The calculator has a two-minute promise.** Fitting a model per request costs tens of
   seconds. Whether a trained model beats pure physics for a given site is a real and
   testable question — and it is answered on the analysis console, where the comparison can
   be made properly against held-out data, rather than guessed at here.

Why no interval
---------------
The annual estimate's range is a measured quantity: the spread between what 2019 actually
produced at these coordinates and what 2021 produced. There is no equivalent here. The
honest uncertainty on a seven-day forecast is dominated by error in the *weather
prediction*, which this platform does not model and cannot observe from a single forecast
run. Rather than manufacture a band that would look like the annual one but mean something
entirely different, this returns a single figure and says so in the payload.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.data.sources import Location, fetch_forecast
from app.estimate.climatology import _local_index
from app.features.solar_geometry import PVSystem, pv_power_chain

logger = logging.getLogger(__name__)

# Seven days. Open-Meteo publishes sixteen, and the extra nine are available through the
# horizon argument, but a week is the span over which an operational forecast is worth
# acting on — and it is the window the console's validated-horizon warning is built around.
DEFAULT_HORIZON_HOURS = 168

# Stated in the payload rather than left for the reader to infer. The frontend renders this
# verbatim beneath the chart.
METHOD_NOTE = (
    "Physics applied to a live weather forecast — the same Erbs, HDKR, Faiman and "
    "PVWatts chain behind your yearly figure, run on the days ahead instead of on years "
    "of history. It is a single expected value, not a range: the real uncertainty here "
    "comes from the weather forecast itself, which this figure does not attempt to measure."
)


def physics_forecast(
    location: Location,
    system: PVSystem,
    horizon_hours: int = DEFAULT_HORIZON_HOURS,
) -> dict[str, Any]:
    """Expected daily generation over the coming days, from forecast weather.

    Raises :class:`app.data.sources.DataSourceError` if the forecast service cannot be
    reached, exactly as the climatology path does — the caller translates it into the
    platform's standard error envelope.
    """
    raw = fetch_forecast(location, horizon_hours=horizon_hours)

    if raw.empty:
        raise ValueError(
            "The weather service returned no forecast hours for this location."
        )

    pv = pv_power_chain(
        ghi=raw["ghi_wm2"].to_numpy(dtype=np.float64),
        air_temp_c=raw["temperature_c"].to_numpy(dtype=np.float64),
        wind_speed_ms=raw["wind_speed_ms"].to_numpy(dtype=np.float64),
        times_utc=raw.index.to_numpy(),
        latitude=location.latitude,
        longitude=location.longitude,
        system=system,
    )

    # Local clock time, because "Thursday" means the user's Thursday. The same helper the
    # annual path uses, imported rather than reimplemented: two copies of timezone
    # resolution would eventually disagree, and the day boundary is exactly where that
    # would show up.
    local_index = _local_index(raw, location)

    # Hourly AC power in kW over a one-hour interval is kWh, which is what the sum below
    # accumulates — the same identity the climatology aggregation relies on.
    energy = pd.Series(pv.ac_power_kw, index=local_index, name="kwh")
    grouped = energy.groupby(energy.index.date)

    daily: list[dict[str, Any]] = []
    for day, values in grouped:
        daily.append(
            {
                "date": day.isoformat(),
                "energy_kwh": round(float(values.sum()), 2),
                # An operational forecast begins at the current day's first hour, so the
                # first entry usually covers a day that is already partly over. Reporting
                # the hour count makes that visible instead of leaving a low first bar
                # looking like a bad forecast.
                "hours": int(len(values)),
            }
        )

    # The horizon cuts mid-day in local time, so the final entry is usually a handful of
    # hours that are often entirely night — a genuine zero that renders as an empty bar and
    # reads as a broken forecast. It is an artifact of where the window ends, not a
    # prediction, so it is dropped. The *leading* partial day is kept: "today, already
    # partly over" is real information.
    while len(daily) > 1 and daily[-1]["hours"] < 24:
        daily.pop()

    total = round(sum(entry["energy_kwh"] for entry in daily), 2)
    complete = [entry for entry in daily if entry["hours"] >= 24]

    return {
        # Named so it can never be mistaken for the console's trained-model forecast.
        "method": "physics_pass_through",
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "horizon_hours": int(horizon_hours),
        "daily": daily,
        "total_kwh": total,
        "daily_average_kwh": (
            round(sum(e["energy_kwh"] for e in complete) / len(complete), 2)
            if complete
            else None
        ),
        "note": METHOD_NOTE,
        "provenance": {
            "source": "Open-Meteo operational forecast",
            "kind": str(raw.attrs.get("kind", "forecast")),
            "model_chain": "Erbs → HDKR → Faiman → PVWatts v5",
            "retrieved_at": str(raw.attrs.get("retrieved_at", "")),
            "system_dc_capacity_kwp": system.dc_capacity_kwp,
        },
    }
