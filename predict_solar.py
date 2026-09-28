# -*- coding: utf-8 -*-
"""
End-to-end solar output prediction for ANY location on Earth and ANY date/time
(recent past or near-future), matching the abstract's described pipeline:

  location (city name or GPS) -> geocode to lat/lon -> fetch irradiance,
  air temperature, wind speed for that place/time -> derive module temperature
  (NOCT model) -> feed into the trained XGBoost model -> predicted energy
  output in kWh.

No dataset download needed - weather is fetched on demand from Open-Meteo,
which is free, keyless, and covers the whole globe.

Usage:
  python predict_solar.py --location "Paris, France" --date 2026-08-20 --hour 13
  python predict_solar.py --lat 35.6762 --lon 139.6503 --date 2026-08-20 --hour 13
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import joblib
import pandas as pd

MODEL_PATHS = {
    "xgboost": str(Path(__file__).resolve().parent / "backend" / "app" / "models" / "artifacts" / "solar_xgboost_model_plants.joblib"),
    "plants": r"C:\Projects_AI\college_project\solar_stacking_model_plants.joblib",
    "synthetic": r"C:\Projects_AI\college_project\solar_stacking_model.joblib",
}

# NOCT cell-temperature model, used to derive module temperature from the
# fetched air temperature, irradiance and wind speed. The "xgboost" and "plants"
# models were trained against measured module temperature, so wind still enters
# the pipeline through this step.
NOCT = 45.0


def module_temperature(air_temp, irradiance, wind_speed):
    return air_temp + (NOCT - 20) / 800.0 * irradiance / (1 + 0.05 * wind_speed)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def geocode(location_name):
    resp = requests.get(GEOCODE_URL, params={"name": location_name, "count": 1}, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        raise ValueError(f"Could not find a location matching '{location_name}'")
    r = results[0]
    label = f"{r['name']}, {r.get('admin1', '')}, {r['country']}".replace(" ,", ",")
    return r["latitude"], r["longitude"], label


def fetch_weather(lat, lon, target_date):
    today = date.today()
    hourly_vars = "shortwave_radiation,temperature_2m,wind_speed_10m"

    if target_date <= today - timedelta(days=6):
        url, params = ARCHIVE_URL, {
            "latitude": lat, "longitude": lon,
            "start_date": target_date.isoformat(), "end_date": target_date.isoformat(),
            "hourly": hourly_vars, "wind_speed_unit": "ms", "timezone": "auto",
        }
        source = "archive (ERA5 reanalysis)"
    else:
        url, params = FORECAST_URL, {
            "latitude": lat, "longitude": lon,
            "start_date": target_date.isoformat(), "end_date": target_date.isoformat(),
            "hourly": hourly_vars, "wind_speed_unit": "ms", "timezone": "auto",
        }
        source = "forecast model"

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "hourly" not in data:
        raise ValueError(f"No weather data available for that date: {data}")
    return data["hourly"], source


def main():
    ap = argparse.ArgumentParser(description="Predict solar energy output for any location on Earth.")
    ap.add_argument("--location", help="City name, e.g. 'Paris, France'")
    ap.add_argument("--lat", type=float, help="Latitude (skips geocoding)")
    ap.add_argument("--lon", type=float, help="Longitude (skips geocoding)")
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    ap.add_argument("--hour", type=int, default=datetime.now().hour, help="0-23 local hour (default: current hour)")
    ap.add_argument("--model", choices=("xgboost", "plants", "synthetic"), default="xgboost",
                    help="'xgboost' = the project's model, trained on measured plant output (default); "
                         "'plants' = baseline stacking ensemble on the same data; "
                         "'synthetic' = trained on PV-model output from hourly weather history")
    args = ap.parse_args()

    if args.lat is not None and args.lon is not None:
        lat, lon, label = args.lat, args.lon, f"({args.lat}, {args.lon})"
    elif args.location:
        lat, lon, label = geocode(args.location)
    else:
        print("Provide either --location or --lat/--lon", file=sys.stderr)
        sys.exit(1)

    target_date = date.fromisoformat(args.date)
    hourly, source = fetch_weather(lat, lon, target_date)

    times = hourly["time"]
    want = f"{args.date}T{args.hour:02d}:00"
    if want not in times:
        print(f"Hour {args.hour:02d}:00 not available for {args.date} at this location.", file=sys.stderr)
        sys.exit(1)
    idx = times.index(want)

    irradiance = hourly["shortwave_radiation"][idx]
    air_temp = hourly["temperature_2m"][idx]
    wind_speed = hourly["wind_speed_10m"][idx]

    if irradiance is None or air_temp is None or wind_speed is None:
        print("Weather data incomplete for that hour (may be too far in the future).", file=sys.stderr)
        sys.exit(1)

    model = joblib.load(MODEL_PATHS[args.model])
    if args.model in ("xgboost", "plants"):
        mod_temp = module_temperature(air_temp, irradiance, wind_speed)
        features = pd.DataFrame(
            [[irradiance, air_temp, mod_temp]],
            columns=["irradiance_w_m2", "air_temp_c", "module_temp_c"],
        )
        # The plant model predicts kWh per 15-minute interval; report hourly.
        predicted_kwh = model.predict(features)[0] * 4
    else:
        mod_temp = None
        features = pd.DataFrame(
            [[irradiance, air_temp, wind_speed]],
            columns=["irradiance_w_m2", "air_temp_c", "wind_speed_ms"],
        )
        predicted_kwh = model.predict(features)[0]

    print(f"Location:        {label}  (lat {lat:.4f}, lon {lon:.4f})")
    print(f"Date / time:     {args.date} {args.hour:02d}:00 local")
    print(f"Weather source:  {source}")
    print(f"Irradiance:      {irradiance:.1f} W/m^2")
    print(f"Air temperature: {air_temp:.1f} C")
    print(f"Wind speed:      {wind_speed:.1f} m/s")
    if mod_temp is not None:
        print(f"Module temp:     {mod_temp:.1f} C  (derived, NOCT model)")
    print(f"Model:           {args.model}")
    print(f"Predicted output: {predicted_kwh:.3f} kWh  (5 kW reference system)")


if __name__ == "__main__":
    main()
