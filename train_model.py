# -*- coding: utf-8 -*-
"""
Trains the 4-model stacking ensemble described in the abstract:
Random Forest, Histogram Gradient Boosting, Extremely Randomised Trees and
Ridge Regression, combined via a stacking ensemble, on real hourly weather
(Andhra Pradesh towns, 2023) with energy output computed from a standard
PV performance model (NOCT cell-temperature model + linear power/temperature
coefficient). Evaluated on data held out in date order (Nov-Dec vs Jan-Oct).
"""
import time
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    RandomForestRegressor,
    HistGradientBoostingRegressor,
    ExtraTreesRegressor,
    StackingRegressor,
)
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score, mean_absolute_error
import joblib

DATA_PATH = r"C:\Users\siddh\Downloads\andhra_pradesh_towns_weather_2023.csv"
MODEL_OUT = r"C:\Projects_AI\college_project\solar_stacking_model.joblib"

# --- standard PV performance model (same as used for the earlier synthetic dataset) ---
NOCT = 45.0
GAMMA = -0.0045
CAPACITY_KW = 5.0
SYSTEM_DERATE = 0.94


def compute_energy_kwh(irradiance, air_temp, wind_speed):
    cell_temp = air_temp + (NOCT - 20) / 800.0 * irradiance / (1 + 0.05 * wind_speed)
    dc_kw = CAPACITY_KW * (irradiance / 1000.0) * (1 + GAMMA * (cell_temp - 25))
    dc_kw = np.clip(dc_kw, 0, None) * SYSTEM_DERATE
    return dc_kw


print("Loading data...")
t0 = time.time()
df = pd.read_csv(DATA_PATH, usecols=["datetime", "irradiance_w_m2", "air_temp_c", "wind_speed_ms"])
print(f"  {len(df):,} rows loaded in {time.time() - t0:.1f}s")

df["month"] = df["datetime"].str.slice(5, 7).astype(int)
df["energy_output_kwh"] = compute_energy_kwh(
    df["irradiance_w_m2"].values, df["air_temp_c"].values, df["wind_speed_ms"].values
)

FEATURES = ["irradiance_w_m2", "air_temp_c", "wind_speed_ms"]
TARGET = "energy_output_kwh"

train_df = df[df["month"] <= 10]
test_df = df[df["month"] >= 11]

rng = np.random.default_rng(42)
TRAIN_SAMPLE = 300_000
if len(train_df) > TRAIN_SAMPLE:
    train_df = train_df.iloc[rng.choice(len(train_df), TRAIN_SAMPLE, replace=False)]

TEST_SAMPLE = 60_000
if len(test_df) > TEST_SAMPLE:
    test_df = test_df.iloc[rng.choice(len(test_df), TEST_SAMPLE, replace=False)]

X_train, y_train = train_df[FEATURES], train_df[TARGET]
X_test, y_test = test_df[FEATURES], test_df[TARGET]
print(f"Train: {len(X_train):,} rows (Jan-Oct)  |  Test: {len(X_test):,} rows (Nov-Dec, held out in date order)")

base_learners = [
    ("random_forest", RandomForestRegressor(n_estimators=150, max_depth=14, n_jobs=-1, random_state=42)),
    ("hist_gb", HistGradientBoostingRegressor(max_iter=200, random_state=42)),
    ("extra_trees", ExtraTreesRegressor(n_estimators=150, max_depth=14, n_jobs=-1, random_state=42)),
    ("ridge", Ridge(alpha=1.0)),
]

stack = StackingRegressor(
    estimators=base_learners,
    final_estimator=Ridge(alpha=1.0),
    n_jobs=-1,
    passthrough=False,
)

print("Training stacking ensemble...")
t0 = time.time()
stack.fit(X_train, y_train)
print(f"  trained in {time.time() - t0:.1f}s")

print("\nHold-out evaluation (Nov-Dec, unseen in date order):")
preds = stack.predict(X_test)
print(f"  R^2  = {r2_score(y_test, preds):.4f}")
print(f"  MAE  = {mean_absolute_error(y_test, preds):.4f} kWh")

print("\nPer-model comparison on the same holdout:")
for name, model in base_learners:
    model.fit(X_train, y_train)
    p = model.predict(X_test)
    print(f"  {name:12s} R^2={r2_score(y_test, p):.4f}  MAE={mean_absolute_error(y_test, p):.4f}")

joblib.dump(stack, MODEL_OUT)
print(f"\nSaved trained model to {MODEL_OUT}")
