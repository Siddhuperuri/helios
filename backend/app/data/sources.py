"""Upstream data acquisition: geocoding, historical reanalysis, and forecast weather.

Design notes
------------
* Every response is cached, keyed by a hash of the request URL and parameters. This is
  what makes a recorded experiment reproducible later: the exact bytes that produced a
  result are kept, so a re-run does not silently pick up a revised reanalysis. The cache
  now lives in Redis and is therefore shared by every backend replica — one fetch, not one
  per container. The key scheme is unchanged; see :mod:`app.infra.cache`.
* Errors are translated into domain exceptions carrying a message a user can act on.
  "Something went wrong" is never an acceptable outcome here.
* Nothing in this module fabricates or interpolates a value. If the upstream service has
  a gap, the gap survives into the DataFrame as NaN and is reported by the quality engine.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.config import get_settings
from app.infra import cache as shared_cache

logger = logging.getLogger(__name__)

USER_AGENT = "Helios-Solar-Intelligence/1.0 (research platform; contact: local deployment)"


# --------------------------------------------------------------------------------------
# Domain exceptions
# --------------------------------------------------------------------------------------

class DataSourceError(RuntimeError):
    """Base class for upstream data problems, carrying a user-facing message."""

    def __init__(self, message: str, *, detail: str | None = None, status: int = 502):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.status = status


class LocationNotFoundError(DataSourceError):
    def __init__(self, query: str):
        super().__init__(
            f"No location matched '{query}'. Try a larger nearby city, add a country "
            f"(for example 'Springfield, United States'), or switch to coordinate entry.",
            status=404,
        )
        self.query = query


class UpstreamUnavailableError(DataSourceError):
    pass


class InsufficientDataError(DataSourceError):
    def __init__(self, message: str, *, detail: str | None = None):
        super().__init__(message, detail=detail, status=422)


# --------------------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Location:
    """A resolved geographic location."""

    latitude: float
    longitude: float
    name: str
    country: str | None = None
    # ISO 3166-1 alpha-2, when the upstream service supplies one. Kept separate from the
    # display name because it is what selects currency, tariff defaults and the grid
    # emission factor — matching those on a translated country name is fragile.
    country_code: str | None = None
    admin1: str | None = None
    elevation_m: float | None = None
    timezone: str | None = None
    source: str = "user"

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.admin1 and self.admin1 != self.name:
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = self.label
        return d


# Canonical internal column names mapped to Open-Meteo's variable names.
# Keeping our own vocabulary means a change of provider touches only this table.
HOURLY_VARIABLES: dict[str, str] = {
    "ghi_wm2": "shortwave_radiation",
    "dni_wm2": "direct_normal_irradiance",
    "dhi_wm2": "diffuse_radiation",
    "temperature_c": "temperature_2m",
    "relative_humidity_pct": "relative_humidity_2m",
    "dew_point_c": "dew_point_2m",
    "surface_pressure_hpa": "surface_pressure",
    "wind_speed_ms": "wind_speed_10m",
    "wind_direction_deg": "wind_direction_10m",
    "cloud_cover_pct": "cloud_cover",
    "precipitation_mm": "precipitation",
}


# --------------------------------------------------------------------------------------
# HTTP with caching and retry
# --------------------------------------------------------------------------------------

def _cache_key(url: str, params: dict[str, Any]) -> str:
    payload = json.dumps({"url": url, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _read_cache(key: str) -> dict[str, Any] | None:
    """Read from the shared cache.

    The key is computed exactly as before, so entries written by the previous release
    still resolve. Only the storage moved: see :mod:`app.infra.cache` for why one copy
    shared between replicas replaced one copy per container.
    """
    return shared_cache.read(key)


def _write_cache(key: str, payload: dict[str, Any]) -> None:
    shared_cache.write(key, payload)


def _http_get_json(url: str, params: dict[str, Any], *, use_cache: bool = True) -> dict[str, Any]:
    """GET a JSON document with retry, backoff, and shared caching."""
    settings = get_settings()
    key = _cache_key(url, params)

    if use_cache:
        cached = _read_cache(key)
        if cached is not None:
            logger.debug("Cache hit for %s", key)
            return cached

    query = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}"
    request = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})

    last_error: Exception | None = None
    for attempt in range(1, settings.data.max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=settings.data.request_timeout_s) as response:
                body = response.read().decode("utf-8")
            payload = json.loads(body)

            # Open-Meteo signals errors with HTTP 400 plus {"error": true, "reason": ...}
            if isinstance(payload, dict) and payload.get("error"):
                raise DataSourceError(
                    "The weather data service rejected the request.",
                    detail=str(payload.get("reason", "unspecified")),
                    status=502,
                )

            if use_cache:
                _write_cache(key, payload)
            return payload

        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:400]
            except Exception:  # noqa: BLE001 - diagnostic best-effort only
                pass
            if exc.code == 400:
                raise DataSourceError(
                    "The weather data service rejected the request parameters.",
                    detail=detail or str(exc),
                    status=502,
                ) from exc
            if exc.code == 429:
                # Rate limited upstream: back off harder before retrying.
                last_error = exc
                time.sleep(settings.data.retry_backoff_s * attempt * 3)
                continue
            last_error = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc

        if attempt < settings.data.max_retries:
            time.sleep(settings.data.retry_backoff_s * attempt)

    raise UpstreamUnavailableError(
        "Could not reach the weather data service after "
        f"{settings.data.max_retries} attempts. Check the network connection and retry.",
        detail=str(last_error),
    )


# --------------------------------------------------------------------------------------
# Geocoding
# --------------------------------------------------------------------------------------

def geocode(query: str, *, limit: int = 5) -> list[Location]:
    """Resolve a place name to candidate locations."""
    settings = get_settings()
    cleaned = (query or "").strip()
    if len(cleaned) < 2:
        raise DataSourceError(
            "Enter at least two characters to search for a location.", status=400
        )
    if len(cleaned) > 120:
        raise DataSourceError("Location query is too long (limit 120 characters).", status=400)

    payload = _http_get_json(
        settings.data.geocoding_url,
        {"name": cleaned, "count": max(1, min(limit, 20)), "format": "json", "language": "en"},
    )
    results = payload.get("results") or []
    if not results:
        raise LocationNotFoundError(cleaned)

    return [
        Location(
            latitude=float(r["latitude"]),
            longitude=float(r["longitude"]),
            name=str(r.get("name", cleaned)),
            country=r.get("country"),
            country_code=(str(r["country_code"]).upper() if r.get("country_code") else None),
            admin1=r.get("admin1"),
            elevation_m=r.get("elevation"),
            timezone=r.get("timezone"),
            source="geocoding",
        )
        for r in results
        if "latitude" in r and "longitude" in r
    ]


def resolve_location(
    *, query: str | None = None, latitude: float | None = None, longitude: float | None = None
) -> Location:
    """Resolve either a place name or an explicit coordinate pair to a Location."""
    settings = get_settings()

    if latitude is not None and longitude is not None:
        lim = settings.limits
        if not lim.min_latitude <= latitude <= lim.max_latitude:
            raise DataSourceError(
                f"Latitude {latitude} is outside the valid range "
                f"[{lim.min_latitude}, {lim.max_latitude}].",
                status=400,
            )
        if not lim.min_longitude <= longitude <= lim.max_longitude:
            raise DataSourceError(
                f"Longitude {longitude} is outside the valid range "
                f"[{lim.min_longitude}, {lim.max_longitude}].",
                status=400,
            )
        # Name the point rather than echoing its coordinates back.
        #
        # A GPS fix or a dropped map pin arrives here as bare numbers, and every downstream
        # consumer inherits whatever this returns: the label in the result, the report
        # heading, the plain-language summary. Returning "16.5074, 80.6466" makes all of
        # them read as coordinates, which §9 rules out as a primary experience.
        #
        # The country matters just as much and less visibly — it selects the currency, the
        # tariff defaults and the grid emission factor. Without it a rupee estimate is
        # quietly served in dollars.
        #
        # Best-effort by construction: reverse_geocode never raises, falling back to a
        # coordinate label, so an unreachable geocoder costs a nice name and nothing else.
        return reverse_geocode(float(latitude), float(longitude))

    if query:
        return geocode(query, limit=1)[0]

    raise DataSourceError(
        "Provide either a place name or a latitude/longitude pair.", status=400
    )


def elevation(latitude: float, longitude: float) -> float | None:
    """Ground elevation at a point, in metres.

    Best-effort: a missing elevation degrades one line of the location card, so a failure
    here must never take the estimate down with it.
    """
    settings = get_settings()
    try:
        payload = _http_get_json(
            settings.data.elevation_url,
            {"latitude": round(latitude, 4), "longitude": round(longitude, 4)},
        )
    except DataSourceError as exc:
        logger.info("Elevation lookup failed: %s", exc.message)
        return None
    values = payload.get("elevation")
    if isinstance(values, list) and values:
        try:
            return float(values[0])
        except (TypeError, ValueError):
            return None
    return None


def reverse_geocode(latitude: float, longitude: float) -> Location:
    """Turn coordinates into a place a person recognises (§9).

    Used when the browser supplies a GPS fix or the user drops a pin on the map. Showing
    "16.5062, 80.6480" back to somebody who just pressed *Use my location* is a failure of
    the interface, not a result.

    If the lookup fails the coordinates still resolve — to a Location labelled by its
    coordinates — because a name is a convenience and the estimate does not depend on it.
    """
    settings = get_settings()
    lim = settings.limits
    if not lim.min_latitude <= latitude <= lim.max_latitude:
        raise DataSourceError(
            f"Latitude {latitude} is outside the valid range.", status=400
        )
    if not lim.min_longitude <= longitude <= lim.max_longitude:
        raise DataSourceError(
            f"Longitude {longitude} is outside the valid range.", status=400
        )

    precision = settings.data.reverse_geocoding_precision
    lat_r = round(latitude, precision)
    lon_r = round(longitude, precision)

    name = f"{latitude:.4f}, {longitude:.4f}"
    country: str | None = None
    country_code: str | None = None
    admin1: str | None = None

    try:
        payload = _http_get_json(
            settings.data.reverse_geocoding_url,
            {
                "lat": lat_r,
                "lon": lon_r,
                "format": "jsonv2",
                "zoom": 12,          # settlement level: a town or suburb, not a house number
                "addressdetails": 1,
                # Without this the service answers in the local language, and a country
                # named in Telugu will not match anything downstream.
                "accept-language": "en",
            },
        )
        address = payload.get("address") or {}
        # Nominatim's vocabulary varies with what exists at the point, so take the first
        # populated place-like field rather than assuming one key is present.
        for key in ("village", "town", "city", "suburb", "municipality", "county", "state_district"):
            if address.get(key):
                name = str(address[key])
                break
        admin1 = address.get("state") or address.get("region")
        country = address.get("country")
        raw_code = address.get("country_code")
        country_code = str(raw_code).upper() if raw_code else None
    except DataSourceError as exc:
        logger.info("Reverse geocoding failed, falling back to coordinates: %s", exc.message)
    except Exception as exc:  # noqa: BLE001 - a name is a nicety; never fail on one
        logger.info("Reverse geocoding error, falling back to coordinates: %s", exc)

    return Location(
        latitude=float(latitude),
        longitude=float(longitude),
        name=name,
        country=country,
        country_code=country_code,
        admin1=admin1,
        elevation_m=elevation(latitude, longitude),
        timezone=None,
        source="reverse_geocoding",
    )


# --------------------------------------------------------------------------------------
# Historical archive
# --------------------------------------------------------------------------------------

def latest_available_archive_date() -> date:
    """Most recent date the reanalysis archive can be expected to cover.

    ERA5 is published on a lag. Requesting right up to today returns trailing NaNs that
    look like data quality failures but are really just publication latency, so we stop
    short of the boundary and say so.
    """
    settings = get_settings()
    return datetime.now(timezone.utc).date() - timedelta(days=settings.limits.archive_lag_days)


def fetch_archive(
    location: Location,
    start: date,
    end: date,
    *,
    variables: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fetch hourly historical weather and irradiance for a location.

    Returns a DataFrame indexed by timezone-aware UTC timestamps, with the canonical
    column names of :data:`HOURLY_VARIABLES`. Missing values are preserved as NaN.
    """
    settings = get_settings()
    variables = variables or HOURLY_VARIABLES

    if start > end:
        raise DataSourceError("The start date must not be after the end date.", status=400)

    earliest = date.fromisoformat(settings.limits.earliest_date)
    if start < earliest:
        raise DataSourceError(
            f"Historical data before {earliest.isoformat()} is not available from this "
            f"source. Choose a later start date.",
            status=400,
        )

    latest = latest_available_archive_date()
    if end > latest:
        # Clamp rather than fail: the user's intent is clear and the shortfall is reported.
        logger.info("Clamping requested end date %s to %s (archive lag)", end, latest)
        end = latest
    if start > end:
        raise DataSourceError(
            f"The reanalysis archive currently extends only to {latest.isoformat()}. "
            f"The requested window starts after that date.",
            status=400,
        )

    span_days = (end - start).days + 1
    if span_days > settings.limits.max_training_days:
        raise DataSourceError(
            f"Requested window of {span_days} days exceeds the maximum of "
            f"{settings.limits.max_training_days} days.",
            status=400,
        )

    payload = _http_get_json(
        settings.data.archive_url,
        {
            "latitude": round(location.latitude, 4),
            "longitude": round(location.longitude, 4),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(variables.values()),
            "timezone": "UTC",
            "windspeed_unit": "ms",
        },
    )

    return _payload_to_frame(payload, variables, location)


def fetch_forecast(location: Location, *, horizon_hours: int) -> pd.DataFrame:
    """Fetch hourly forward-looking weather from the operational forecast endpoint.

    This is genuine numerical weather prediction output, the same class of input Hobbs &
    Joshi [P1] drive their power forecasts with. It is *not* reanalysis, and the two are
    never mixed silently: the returned frame is tagged so downstream code knows which it
    is holding.
    """
    settings = get_settings()
    horizon_hours = int(horizon_hours)
    lim = settings.limits
    if not lim.min_horizon_hours <= horizon_hours <= lim.max_horizon_hours:
        raise DataSourceError(
            f"Forecast horizon must be between {lim.min_horizon_hours} and "
            f"{lim.max_horizon_hours} hours.",
            status=400,
        )

    forecast_days = min(16, max(1, (horizon_hours + 23) // 24))
    payload = _http_get_json(
        settings.data.forecast_url,
        {
            "latitude": round(location.latitude, 4),
            "longitude": round(location.longitude, 4),
            "hourly": ",".join(HOURLY_VARIABLES.values()),
            "forecast_days": forecast_days,
            "timezone": "UTC",
            "windspeed_unit": "ms",
        },
        # Forecasts go stale quickly; never serve one from a long-lived cache.
        use_cache=False,
    )

    frame = _payload_to_frame(payload, HOURLY_VARIABLES, location)
    frame.attrs["kind"] = "forecast"
    return frame


def _payload_to_frame(
    payload: dict[str, Any], variables: dict[str, str], location: Location
) -> pd.DataFrame:
    """Convert an Open-Meteo hourly payload into a canonical DataFrame."""
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise DataSourceError(
            "The weather service returned a response without an hourly time series.",
            detail=json.dumps(payload)[:400],
        )

    times = pd.to_datetime(pd.Series(hourly["time"]), utc=True, format="ISO8601")
    if times.empty:
        raise InsufficientDataError(
            "The weather service returned an empty time series for this location and period."
        )

    data: dict[str, Any] = {}
    missing_upstream: list[str] = []
    for canonical, upstream in variables.items():
        series = hourly.get(upstream)
        if series is None:
            missing_upstream.append(upstream)
            data[canonical] = np.full(len(times), np.nan)
        else:
            data[canonical] = pd.to_numeric(pd.Series(series), errors="coerce").to_numpy()

    frame = pd.DataFrame(data)
    frame.index = pd.DatetimeIndex(times.to_numpy(), name="time_utc")
    frame = frame.sort_index()

    # Retain provenance on the frame so nothing downstream has to guess where it came from.
    frame.attrs.update(
        {
            "kind": "archive",
            "latitude": payload.get("latitude", location.latitude),
            "longitude": payload.get("longitude", location.longitude),
            "elevation_m": payload.get("elevation"),
            "utc_offset_seconds": payload.get("utc_offset_seconds", 0),
            "units": payload.get("hourly_units", {}),
            "source": get_settings().data.dataset_name,
            "attribution": get_settings().data.attribution,
            "location_label": location.label,
            "missing_upstream_variables": missing_upstream,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    if missing_upstream:
        logger.warning("Upstream omitted variables: %s", ", ".join(missing_upstream))

    return frame
