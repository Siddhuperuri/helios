# -*- coding: utf-8 -*-
"""
Trains the 4-model stacking ensemble described in the abstract -- Random Forest,
Histogram Gradient Boosting, Extremely Randomised Trees and Ridge Regression --
on REAL measured inverter output from all four plant files:

    Plant_1_Generation_Data.csv   + Plant_1_Weather_Sensor_Data.csv
    Plant_2_Generation_Data.csv   + Plant_2_Weather_Sensor_Data.csv

Each plant's generation log is joined to its weather log on DATE_TIME, the two
plants are pooled, and the target is measured AC output normalised to a 5 kW
reference system (kWh per 15-minute interval) so both plants share one scale.

Evaluated on data held out in date order (last 7 days vs the rest), and also
plant-against-plant to show cross-site generalisation.
"""
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
    StackingRegressor,
)
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score

DATA_DIR = r"C:\Users\siddh\Downloads\archive"
MODEL_OUT = r"C:\Projects_AI\college_project\solar_stacking_model_plants.joblib"

REFERENCE_KW = 5.0          # abstract's reference system size
INTERVAL_HOURS = 0.25       # records are 15 minutes apart
HOLDOUT_DAYS = 7

FEATURES = ["irradiance_w_m2", "air_temp_c", "module_temp_c"]
TARGET = "energy_output_kwh"


def load_plant(plant_no, dayfirst_generation):
    """Join one plant's generation log to its weather log."""
    gen = pd.read_csv(rf"{DATA_DIR}\Plant_{plant_no}_Generation_Data.csv")
    wx = pd.read_csv(rf"{DATA_DIR}\Plant_{plant_no}_Weather_Sensor_Data.csv")

    # Plant 1 stores DD-MM-YYYY HH:MM, Plant 2 stores YYYY-MM-DD HH:MM:SS.
    gen["DATE_TIME"] = pd.to_datetime(gen["DATE_TIME"], dayfirst=dayfirst_generation)
    wx["DATE_TIME"] = pd.to_datetime(wx["DATE_TIME"])

    wx = wx[["DATE_TIME", "AMBIENT_TEMPERATURE", "MODULE_TEMPERATURE", "IRRADIATION"]]
    df = gen.merge(wx, on="DATE_TIME", how="inner")

    # Inverter nameplate differs per unit and is not published; use the 99.5th
    # percentile of observed AC output as that inverter's rated capacity, then
    # rescale to the 5 kW reference system so both plants live on one scale.
    rated = df.groupby("SOURCE_KEY")["AC_POWER"].transform(lambda s: s.quantile(0.995))
    df = df[rated > 0].copy()
    df["energy_output_kwh"] = (
        (df["AC_POWER"] / rated).clip(0, 1.2) * REFERENCE_KW * INTERVAL_HOURS
    )

    df["irradiance_w_m2"] = df["IRRADIATION"] * 1000.0   # file stores kW/m^2
    df["air_temp_c"] = df["AMBIENT_TEMPERATURE"]
    df["module_temp_c"] = df["MODULE_TEMPERATURE"]
    df["plant"] = plant_no
    return df[["DATE_TIME", "plant", "SOURCE_KEY", *FEATURES, TARGET]]


def evaluate(name, model, X_tr, y_tr, X_te, y_te, fit=True):
    if fit:
        model.fit(X_tr, y_tr)
    p = model.predict(X_te)
    return r2_score(y_te, p), mean_absolute_error(y_te, p)


print("Loading all four plant files...")
t0 = time.time()
p1 = load_plant(1, dayfirst_generation=True)
p2 = load_plant(2, dayfirst_generation=False)
df = pd.concat([p1, p2], ignore_index=True).sort_values("DATE_TIME")
print(f"  Plant 1: {len(p1):,} rows   Plant 2: {len(p2):,} rows   pooled: {len(df):,}")
print(f"  {df.DATE_TIME.min().date()} to {df.DATE_TIME.max().date()}  ({time.time() - t0:.1f}s)")

cutoff = df["DATE_TIME"].max().normalize() - pd.Timedelta(days=HOLDOUT_DAYS - 1)
train_df = df[df["DATE_TIME"] < cutoff]
test_df = df[df["DATE_TIME"] >= cutoff]

X_train, y_train = train_df[FEATURES], train_df[TARGET]
X_test, y_test = test_df[FEATURES], test_df[TARGET]
print(f"\nTrain: {len(X_train):,} rows (before {cutoff.date()})")
print(f"Test:  {len(X_test):,} rows (from {cutoff.date()}, held out in date order)")

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

print("\nTraining stacking ensemble...")
t0 = time.time()
stack.fit(X_train, y_train)
print(f"  trained in {time.time() - t0:.1f}s")

r2, mae = evaluate("stack", stack, None, None, X_test, y_test, fit=False)
print(f"\nHold-out evaluation (last {HOLDOUT_DAYS} days, unseen in date order):")
print(f"  stacking     R^2={r2:.4f}  MAE={mae:.4f} kWh")

print("\nPer-model comparison on the same holdout:")
for name, model in base_learners:
    r, m = evaluate(name, model, X_train, y_train, X_test, y_test)
    print(f"  {name:12s} R^2={r:.4f}  MAE={m:.4f}")

print("\nCross-plant generalisation (train on one site, test on the other):")
for tr, te in ((1, 2), (2, 1)):
    a, b = df[df.plant == tr], df[df.plant == te]
    s = StackingRegressor(
        estimators=[(n, type(m)(**m.get_params())) for n, m in base_learners],
        final_estimator=Ridge(alpha=1.0), n_jobs=-1,
    )
    s.fit(a[FEATURES], a[TARGET])
    p = s.predict(b[FEATURES])
    print(f"  train Plant {tr} -> test Plant {te}: "
          f"R^2={r2_score(b[TARGET], p):.4f}  MAE={mean_absolute_error(b[TARGET], p):.4f}")

joblib.dump(stack, MODEL_OUT, compress=3)
print(f"\nSaved trained model to {MODEL_OUT}")
