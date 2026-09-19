# -*- coding: utf-8 -*-
"""
Trains the project's model -- XGBoost -- on REAL measured inverter output from all
four plant files:

    Plant_1_Generation_Data.csv   + Plant_1_Weather_Sensor_Data.csv
    Plant_2_Generation_Data.csv   + Plant_2_Weather_Sensor_Data.csv

Each plant's generation log is joined to its weather log on DATE_TIME, the two
plants are pooled, and the target is measured AC output normalised to a 5 kW
reference system (kWh per 15-minute interval) so both plants share one scale.

The four earlier models -- Random Forest, Histogram Gradient Boosting, Extremely
Randomised Trees and Ridge Regression -- and their stacking ensemble are kept as
baselines, scored on the same holdout so XGBoost's result has a reference point.

Evaluated on data held out in date order (last 7 days vs the rest), and also
plant-against-plant to show cross-site generalisation.

Usage:
  python train_model_plants.py
  python train_model_plants.py --data-dir "D:\\datasets\\solar"
"""
import argparse
import time

import joblib
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
    StackingRegressor,
)
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from xgboost import XGBRegressor

DEFAULT_DATA_DIR = r"C:\Users\siddh\Downloads\archive"
MODEL_OUT = r"C:\Projects_AI\college_project\solar_xgboost_model_plants.joblib"

REFERENCE_KW = 5.0          # abstract's reference system size
INTERVAL_HOURS = 0.25       # records are 15 minutes apart
HOLDOUT_DAYS = 7

FEATURES = ["irradiance_w_m2", "air_temp_c", "module_temp_c"]
TARGET = "energy_output_kwh"


def make_xgboost():
    return XGBRegressor(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        reg_lambda=1.0,
        n_jobs=-1,
        random_state=42,
    )


def make_baselines():
    return [
        ("random_forest", RandomForestRegressor(n_estimators=150, max_depth=14, n_jobs=-1, random_state=42)),
        ("hist_gb", HistGradientBoostingRegressor(max_iter=200, random_state=42)),
        ("extra_trees", ExtraTreesRegressor(n_estimators=150, max_depth=14, n_jobs=-1, random_state=42)),
        ("ridge", Ridge(alpha=1.0)),
    ]


def load_plant(data_dir, plant_no, dayfirst_generation):
    """Join one plant's generation log to its weather log."""
    gen = pd.read_csv(rf"{data_dir}\Plant_{plant_no}_Generation_Data.csv")
    wx = pd.read_csv(rf"{data_dir}\Plant_{plant_no}_Weather_Sensor_Data.csv")

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


def score(model, X_te, y_te):
    p = model.predict(X_te)
    return r2_score(y_te, p), mean_absolute_error(y_te, p)


def main():
    ap = argparse.ArgumentParser(description="Train the XGBoost solar output model.")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                    help="Folder holding the four Plant_*.csv files")
    args = ap.parse_args()

    print("Loading all four plant files...")
    t0 = time.time()
    p1 = load_plant(args.data_dir, 1, dayfirst_generation=True)
    p2 = load_plant(args.data_dir, 2, dayfirst_generation=False)
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

    # ---- the project's model
    print("\nTraining XGBoost...")
    t0 = time.time()
    model = make_xgboost()
    model.fit(X_train, y_train)
    print(f"  trained in {time.time() - t0:.1f}s")

    r2, mae = score(model, X_test, y_test)
    print(f"\nHold-out evaluation (last {HOLDOUT_DAYS} days, unseen in date order):")
    print(f"  XGBoost      R^2={r2:.4f}  MAE={mae:.4f} kWh per 15 min  "
          f"(~{mae * 4:.3f} kWh per hour, 5 kW system)")

    print("\nFeature importance (XGBoost, gain):")
    for name, imp in sorted(zip(FEATURES, model.feature_importances_), key=lambda t: -t[1]):
        print(f"  {name:16s} {imp:.3f}")

    # ---- baselines on the same holdout
    print("\nBaselines on the same holdout:")
    baselines = make_baselines()
    for name, m in baselines:
        m.fit(X_train, y_train)
        r, e = score(m, X_test, y_test)
        print(f"  {name:12s} R^2={r:.4f}  MAE={e:.4f}")
    stack = StackingRegressor(estimators=make_baselines(), final_estimator=Ridge(alpha=1.0), n_jobs=-1)
    stack.fit(X_train, y_train)
    r, e = score(stack, X_test, y_test)
    print(f"  {'stacking':12s} R^2={r:.4f}  MAE={e:.4f}")

    # ---- cross-site generalisation for the project's model
    print("\nCross-plant generalisation, XGBoost (train on one site, test on the other):")
    for tr, te in ((1, 2), (2, 1)):
        a, b = df[df.plant == tr], df[df.plant == te]
        m = make_xgboost().fit(a[FEATURES], a[TARGET])
        r, e = score(m, b[FEATURES], b[TARGET])
        print(f"  train Plant {tr} -> test Plant {te}: R^2={r:.4f}  MAE={e:.4f}")

    joblib.dump(model, MODEL_OUT, compress=3)
    print(f"\nSaved XGBoost model to {MODEL_OUT}")


if __name__ == "__main__":
    main()
