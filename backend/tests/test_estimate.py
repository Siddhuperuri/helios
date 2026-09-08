"""Tests for the consumer estimation domain.

Weighted toward the things that would be *silently* wrong rather than loudly broken: an
energy ledger that does not balance, losses added instead of compounded, a bill converted
without removing the fixed charge, a battery that returns more than it stored. Each of
those produces a plausible number, which is what makes them worth a test.

Nothing here touches the network. The weather-dependent paths run against a synthetic
hourly record so they are deterministic and fast.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.data.sources import Location
from app.estimate import assumptions as A
from app.estimate import (
    balance,
    climatology,
    demand,
    economics,
    farm,
    sizing,
    space,
    uncertainty,
)
from app.estimate import store as estimate_store
from app.features.solar_geometry import PVSystem

# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def location() -> Location:
    return Location(
        latitude=16.51, longitude=80.63, name="Vijayawada",
        country="India", admin1="Andhra Pradesh", timezone="Asia/Kolkata",
    )


@pytest.fixture(scope="module")
def synthetic_weather(location: Location) -> pd.DataFrame:
    """Three years of hourly weather with a physically shaped diurnal and seasonal cycle."""
    index = pd.date_range("2021-01-01", "2023-12-31 23:00", freq="h", tz="UTC")
    day_of_year = index.dayofyear.to_numpy(dtype=float)
    # Solar time at this longitude, so the peak lands near local noon.
    hour = (index.hour.to_numpy(dtype=float) + location.longitude / 15.0) % 24

    seasonal = 1.0 - 0.18 * np.cos(2 * np.pi * (day_of_year - 15) / 365.25)
    diurnal = np.clip(np.sin(np.pi * (hour - 6.0) / 12.0), 0.0, None)
    ghi = 950.0 * seasonal * diurnal

    frame = pd.DataFrame(
        {
            "ghi_wm2": ghi,
            "temperature_c": 28.0 + 6.0 * diurnal,
            "wind_speed_ms": np.full(len(index), 2.5),
        },
        index=index,
    )
    frame.attrs["source"] = "synthetic"
    return frame


@pytest.fixture(scope="module")
def climate(location: Location, synthetic_weather: pd.DataFrame) -> climatology.ClimatologyResult:
    return climatology.compute(
        location,
        PVSystem(dc_capacity_kwp=5.0, surface_tilt_deg=16.0, surface_azimuth_deg=180.0),
        raw=synthetic_weather,
        period=(date(2021, 1, 1), date(2023, 12, 31)),
    )


# --------------------------------------------------------------------------------------
# Losses
# --------------------------------------------------------------------------------------

def test_losses_compound_rather_than_add():
    """Two 10 % losses leave 81 %, not 80 %. Adding them overstates the penalty."""
    items = [A.LossItem("a", "A", 0.10, ""), A.LossItem("b", "B", 0.10, "")]
    assert A.combine_losses(items) == pytest.approx(0.19)


def test_default_loss_stack_is_below_the_naive_sum():
    naive = sum(item.fraction for item in A.DEFAULT_LOSS_STACK)
    assert A.DEFAULT_SYSTEM_LOSS_FRACTION < naive
    assert 0.12 < A.DEFAULT_SYSTEM_LOSS_FRACTION < 0.15


def test_loss_stack_excludes_temperature_and_inverter():
    """Both are modelled explicitly by the physical chain; counting them twice is the bug."""
    keys = {item.key for item in A.DEFAULT_LOSS_STACK}
    assert "temperature" not in keys
    assert "inverter" not in keys


def test_shading_answer_changes_the_loss_stack():
    assert A.shading_fraction("heavy") > A.shading_fraction("none")
    assert A.shading_fraction(None) == A.shading_fraction("unknown")


# --------------------------------------------------------------------------------------
# Area
# --------------------------------------------------------------------------------------

def test_polygon_area_matches_a_known_square():
    """A square 0.01° of latitude on a side, at the equator, is about 1.113 km."""
    side_deg = 0.01
    coords = [(0.0, 0.0), (0.0, side_deg), (side_deg, side_deg), (side_deg, 0.0)]
    expected = (side_deg * 111_320.0) ** 2
    assert sizing.polygon_area_m2(coords) == pytest.approx(expected, rel=0.01)


def test_polygon_area_is_orientation_independent():
    coords = [(16.5, 80.6), (16.5, 80.61), (16.51, 80.61), (16.51, 80.6)]
    assert sizing.polygon_area_m2(coords) == pytest.approx(
        sizing.polygon_area_m2(list(reversed(coords)))
    )


def test_polygon_needs_three_points():
    with pytest.raises(ValueError, match="three points"):
        sizing.polygon_area_m2([(0.0, 0.0), (0.0, 1.0)])


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        (1.0, "sqm", 1.0),
        (10.7639, "sqft", 1.0),
        (1.0, "acre", 4046.86),
        (1.0, "hectare", 10_000.0),
        (100.0, "cent", 4046.86),
    ],
)
def test_area_unit_conversions(value, unit, expected):
    assert sizing.to_square_metres(value, unit) == pytest.approx(expected, rel=1e-3)


def test_unknown_area_unit_is_rejected():
    with pytest.raises(ValueError, match="Unrecognised area unit"):
        sizing.to_square_metres(1.0, "bigha")


def test_stated_area_round_trips_through_capacity():
    """The inverse of `capacity_from_area` is *stated* area, not footprint.

    These are different quantities and must not round-trip into each other: footprint is
    what the array occupies, stated area is the whole roof it sits on, and the usable
    fraction separates them. An earlier version of this test asserted they were inverses,
    which is precisely the assumption §6 forbids — that a roof is 100 % buildable.
    """
    stated = space.available_area_for_capacity(10.0, "rooftop")
    assert sizing.capacity_from_area(stated, "rooftop") == pytest.approx(10.0)


def test_footprint_is_smaller_than_the_roof_it_needs():
    footprint = space.area_for_capacity(10.0, "rooftop")
    stated = space.available_area_for_capacity(10.0, "rooftop")
    assert footprint < stated
    assert footprint / stated == pytest.approx(space.usable_fraction("rooftop"))


# --------------------------------------------------------------------------------------
# Space: four areas that are not the same area (§6)
# --------------------------------------------------------------------------------------

def test_panel_area_is_derived_from_rating_and_efficiency():
    """Checked against four real datasheets; the relation is definitional at STC."""
    # A 550 W panel at 20.5 % efficiency: 550 / (0.205 x 1000).
    assert space.panel_area_m2(550, "mono_perc") == pytest.approx(2.683, rel=1e-3)
    # A more efficient panel of the same rating is physically smaller.
    assert space.panel_area_m2(550, "mono_topcon") < space.panel_area_m2(550, "mono_perc")


def test_datasheet_dimensions_override_the_derivation():
    derived = space.panel_area_m2(550, "mono_perc")
    measured = space.panel_area_m2(550, "mono_perc", length_m=2.279, width_m=1.134)
    assert measured == pytest.approx(2.584, rel=1e-3)
    assert measured != pytest.approx(derived, rel=1e-4)


def test_the_four_areas_are_ordered_and_distinct():
    """module < footprint, and usable < available. Collapsing any pair is the §6 error."""
    a = space.assess(
        count=20, watts=550, installation_type="rooftop", available_area_m2=200
    )
    assert a.module_area_m2 < a.footprint_m2          # spacing adds to the glass
    assert a.usable_area_m2 < a.available_area_m2     # not all of a roof is buildable
    assert a.usable_area_m2 == pytest.approx(200 * space.usable_fraction("rooftop"))


def test_a_roof_is_not_treated_as_fully_coverable():
    """20 panels do not fit on 100 m² of roof, though their glass is only 54 m²."""
    a = space.assess(
        count=20, watts=550, installation_type="rooftop", available_area_m2=100
    )
    assert a.module_area_m2 < 100          # the glass alone would "fit"
    assert a.fits is False                 # the installation does not
    assert a.max_panels_in_space < 20


def test_a_space_too_small_for_one_panel_says_so():
    """"Around 0 panels would fit" is true and tells the reader nothing actionable."""
    a = space.assess(count=10, watts=550, installation_type="rooftop", available_area_m2=1)
    assert a.fits is False
    assert a.max_panels_in_space == 0
    joined = " ".join(a.notes)
    assert "not enough for even one panel" in joined
    assert "Around 0 panels" not in joined


def test_single_panel_fit_is_not_pluralised():
    a = space.assess(count=10, watts=550, installation_type="rooftop", available_area_m2=5)
    if a.max_panels_in_space == 1:
        assert "1 panel would fit" in " ".join(a.notes)


def test_feasibility_is_reported_when_there_is_room():
    a = space.assess(
        count=10, watts=550, installation_type="rooftop", available_area_m2=400
    )
    assert a.fits is True
    assert a.utilisation < 1.0
    assert a.max_panels_in_space > 10


def test_space_is_assessed_without_an_area_but_declines_to_judge_fit():
    a = space.assess(count=20, watts=550, installation_type="rooftop")
    assert a.footprint_m2 > 0
    assert a.fits is None                  # nothing to compare against; not False
    assert a.usable_area_m2 is None


def test_ground_mounting_needs_more_room_than_a_roof():
    roof = space.assess(count=20, watts=550, installation_type="rooftop", available_area_m2=500)
    ground = space.assess(count=20, watts=550, installation_type="ground_mounted",
                          available_area_m2=500)
    assert ground.footprint_m2 > roof.footprint_m2      # row spacing
    assert ground.usable_fraction > roof.usable_fraction  # but less is wasted


def test_more_panels_means_more_footprint():
    small = space.assess(count=10, watts=550, installation_type="rooftop")
    large = space.assess(count=30, watts=550, installation_type="rooftop")
    assert large.footprint_m2 == pytest.approx(small.footprint_m2 * 3)


# --------------------------------------------------------------------------------------
# Inverter
# --------------------------------------------------------------------------------------

def test_inverter_is_sized_to_a_real_product_step():
    assert sizing.recommend_inverter_kw(11.0) in {8, 10, 12}
    # Never below the target, so the ratio cannot drift above what was asked for.
    assert sizing.recommend_inverter_kw(11.0) >= 11.0 / sizing.DEFAULT_DC_AC_RATIO


def test_dc_ac_ratio_follows_the_array():
    small = sizing.describe_inverter(5.0, 5.0)
    oversized = sizing.describe_inverter(10.0, 5.0)
    assert small["dc_ac_ratio"] == pytest.approx(1.0)
    assert oversized["dc_ac_ratio"] == pytest.approx(2.0)
    assert "clipped" in oversized["verdict"]


def test_an_undersized_array_is_called_out_as_wasteful_not_clipped():
    result = sizing.describe_inverter(4.0, 5.0)
    assert "nothing is clipped" in result["verdict"].lower()
    assert result["severity"] == "caution"


def test_an_unusual_ratio_is_warned_about_but_never_rejected():
    """§11: a 1.6 ratio is unusual, and it is somebody's deliberate design."""
    result = sizing.describe_inverter(16.0, 10.0)
    assert result["severity"] == "caution"
    assert result["dc_ac_ratio"] == pytest.approx(1.6)
    # Modelled, not refused — no exception, and a usable number comes back.
    assert "modelled as given rather than refused" in result["verdict"]


def test_a_normal_ratio_is_not_flagged():
    assert sizing.describe_inverter(12.0, 10.0)["severity"] == "ok"


def test_every_inverter_verdict_has_a_plain_language_twin():
    """§13: the beginner surface must be able to say this without the vocabulary."""
    for dc, ac in [(4.0, 5.0), (9.0, 10.0), (12.0, 10.0), (14.5, 10.0), (18.0, 10.0)]:
        result = sizing.describe_inverter(dc, ac)
        assert result["plain"]
        for jargon in ("DC/AC", "dc_ac", "ratio of"):
            assert jargon not in result["plain"]





def test_ground_mount_needs_more_area_than_rooftop():
    """Row spacing to avoid self-shading is real and materially changes what fits."""
    assert sizing.area_per_kwp("ground_mounted") > sizing.area_per_kwp("rooftop")


# --------------------------------------------------------------------------------------
# Demand
# --------------------------------------------------------------------------------------

def test_bill_conversion_removes_the_fixed_charge():
    """Treating the whole bill as energy inflates consumption, size and claimed savings."""
    from app.estimate.tariffs import consumption_from_bill

    kwh, notes = consumption_from_bill(
        monthly_bill=1_000.0, rate_per_kwh=8.0, fixed_monthly_charge=100.0
    )
    assert kwh == pytest.approx(112.5)
    assert notes


def test_bill_below_the_fixed_charge_is_reported_not_negative():
    from app.estimate.tariffs import consumption_from_bill

    kwh, notes = consumption_from_bill(
        monthly_bill=50.0, rate_per_kwh=8.0, fixed_monthly_charge=100.0
    )
    assert kwh == 0.0
    assert any("fixed monthly service charge" in n for n in notes)


def test_refrigerator_duty_cycle_is_applied():
    """A fridge at 24 h nameplate would be four times its real consumption."""
    spec = demand.APPLIANCES["refrigerator"]
    daily = spec.daily_kwh(count=1, hours_per_day=24)
    assert daily == pytest.approx(150 * 24 * 0.35 / 1000.0)
    assert daily < 24 * 0.150  # strictly below the nameplate-times-hours figure


def test_pump_draws_more_than_its_horsepower_rating():
    """Horsepower is shaft output; the motor draws more than that from the wire."""
    result = demand.from_equipment(
        [], user_type="farm",
        pumps=[{"horsepower": 5, "count": 1, "hours_per_day": 6, "days_per_month": 30}],
    )
    nameplate_kw = 5 * demand.WATTS_PER_HP / 1000.0
    drawn_kw = result.breakdown[0]["watts_each"] / 1000.0
    assert drawn_kw > nameplate_kw
    assert drawn_kw == pytest.approx(nameplate_kw / demand.DEFAULT_MOTOR_EFFICIENCY, rel=1e-3)


def test_equipment_estimate_requires_at_least_one_item():
    with pytest.raises(ValueError, match="No equipment was entered"):
        demand.from_equipment([], user_type="home")


def test_impossible_hours_are_rejected():
    with pytest.raises(ValueError, match="between 0 and 24"):
        demand.from_equipment(
            [demand.EquipmentItem(key="ceiling_fan", hours_per_day=30)], user_type="home"
        )


def test_load_profiles_are_normalised():
    for key in ("home", "farm", "shop", "commercial", "institution"):
        assert demand.hourly_profile(key).sum() == pytest.approx(1.0)


def test_farm_profile_is_daytime_weighted_and_home_is_not():
    """The whole self-consumption story depends on these shapes differing."""
    daylight = slice(8, 17)
    farm_day = demand.hourly_profile("farm")[daylight].sum()
    home_day = demand.hourly_profile("home")[daylight].sum()
    assert farm_day > home_day


def test_metered_units_beat_a_bill_for_confidence():
    units = demand.from_metered_units(300, user_type="home")
    billed = demand.from_bill(monthly_bill=2_400, rate_per_kwh=8.0, user_type="home")
    assert units.confidence == "high"
    assert billed.confidence == "medium"


# --------------------------------------------------------------------------------------
# Climatology
# --------------------------------------------------------------------------------------

def test_climatology_produces_physically_plausible_yield(climate):
    assert 800 < climate.specific_yield_kwh_per_kwp < 2200
    assert 0.6 < climate.performance_ratio < 0.95
    assert 0 < climate.capacity_factor < 0.35
    assert len(climate.monthly_kwh) == 12


def test_annual_total_equals_the_sum_of_months(climate):
    assert climate.annual_kwh == pytest.approx(sum(climate.monthly_kwh), rel=1e-6)


def test_daily_profile_is_zero_at_night_and_peaks_near_noon(climate):
    profile = np.asarray(climate.daily_profile_kwh)
    assert profile[0] == pytest.approx(0.0, abs=1e-6)
    assert profile[23] == pytest.approx(0.0, abs=1e-6)
    assert 10 <= int(np.argmax(profile)) <= 14


def test_yield_scales_linearly_with_capacity(location, synthetic_weather):
    """Specific yield must be capacity-invariant, or sizing from it would be circular."""
    period = (date(2021, 1, 1), date(2023, 12, 31))
    small = climatology.compute(
        location, PVSystem(dc_capacity_kwp=1.0, inverter_ac_capacity_kw=10.0),
        raw=synthetic_weather, period=period,
    )
    large = climatology.compute(
        location, PVSystem(dc_capacity_kwp=10.0, inverter_ac_capacity_kw=100.0),
        raw=synthetic_weather, period=period,
    )
    assert large.annual_kwh == pytest.approx(small.annual_kwh * 10.0, rel=1e-6)


def test_partial_months_are_excluded(location, synthetic_weather):
    """A half-month at the edge of the window must not depress that month's average."""
    trimmed = synthetic_weather.loc["2021-01-01":"2023-12-15"]
    result = climatology.compute(
        location, PVSystem(dc_capacity_kwp=5.0),
        raw=trimmed, period=(date(2021, 1, 1), date(2023, 12, 15)),
    )
    full = climatology.compute(
        location, PVSystem(dc_capacity_kwp=5.0),
        raw=synthetic_weather, period=(date(2021, 1, 1), date(2023, 12, 31)),
    )
    # December is averaged over the two complete Decembers in both cases.
    assert result.monthly_kwh[11] == pytest.approx(full.monthly_kwh[11], rel=0.02)


def test_missing_weather_is_dropped_never_imputed(location, synthetic_weather):
    holed = synthetic_weather.copy()
    holed.iloc[100:200, holed.columns.get_loc("ghi_wm2")] = np.nan
    frame, dropped = climatology.usable_hours(holed)
    assert dropped == 100
    assert not frame["ghi_wm2"].isna().any()


def test_too_little_data_is_refused(location):
    index = pd.date_range("2023-01-01", periods=24 * 30, freq="h", tz="UTC")
    thin = pd.DataFrame(
        {"ghi_wm2": 500.0, "temperature_c": 25.0, "wind_speed_ms": 2.0}, index=index
    )
    with pytest.raises(ValueError, match="under a year"):
        climatology.compute(location, PVSystem(), raw=thin)


# --------------------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------------------

def test_optimal_tilt_is_near_latitude(location, synthetic_weather):
    frame, _ = climatology.usable_hours(synthetic_weather)
    best = sizing.optimal_orientation(frame, location, PVSystem(dc_capacity_kwp=1.0))
    assert abs(best.tilt_deg - abs(location.latitude)) <= 15
    assert best.annual_kwh_per_kwp > 0


def test_optimal_orientation_faces_the_equator(location, synthetic_weather):
    frame, _ = climatology.usable_hours(synthetic_weather)
    best = sizing.optimal_orientation(frame, location, PVSystem(dc_capacity_kwp=1.0))
    assert best.azimuth_deg == pytest.approx(180.0, abs=30)  # northern hemisphere


def test_southern_hemisphere_faces_north(synthetic_weather):
    south = Location(latitude=-33.9, longitude=18.4, name="Cape Town", country="South Africa")
    frame, _ = climatology.usable_hours(synthetic_weather)
    best = sizing.optimal_orientation(frame, south, PVSystem(dc_capacity_kwp=1.0))
    assert min(best.azimuth_deg, 360 - best.azimuth_deg) <= 30


def test_search_sample_keeps_hour_of_day_coverage(synthetic_weather):
    """A stride sharing a factor with 24 would sample the same clock hours forever."""
    sampled = sizing._search_sample(synthetic_weather, max_rows=2_000)
    assert len(set(sampled.index.hour)) == 24


def test_compass_labels_are_plain_language():
    assert sizing.compass_label(180) == "south"
    assert sizing.compass_label(0) == "north"
    assert sizing.compass_label(270) == "west"


# --------------------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------------------

def test_sizing_is_limited_by_the_smallest_constraint():
    result = sizing.recommend_capacity(
        annual_demand_kwh=20_000,          # would want ~13 kWp
        specific_yield_kwh_per_kwp=1_500,
        available_area_m2=30,              # only fits ~4.5 kWp
        installation_type="rooftop",
    )
    assert result.binding_constraint == "space"
    assert result.capacity_kwp < 6


def test_sizing_reports_demand_when_space_is_ample():
    result = sizing.recommend_capacity(
        annual_demand_kwh=6_000,
        specific_yield_kwh_per_kwp=1_500,
        available_area_m2=10_000,
        installation_type="rooftop",
    )
    assert result.binding_constraint == "demand"
    assert result.capacity_kwp == pytest.approx(4.0, abs=0.5)


def test_sizing_without_any_input_still_answers_and_says_why():
    result = sizing.recommend_capacity(
        annual_demand_kwh=None,
        specific_yield_kwh_per_kwp=1_500,
        available_area_m2=None,
        installation_type="not_sure",
    )
    assert result.binding_constraint == "default"
    assert "nothing to size against" in result.reason


def test_user_requested_capacity_wins_but_warns_when_it_will_not_fit():
    result = sizing.recommend_capacity(
        annual_demand_kwh=5_000,
        specific_yield_kwh_per_kwp=1_500,
        available_area_m2=20,
        installation_type="rooftop",
        requested_kwp=50.0,
    )
    assert result.binding_constraint == "user_specified"
    assert result.capacity_kwp == 50.0
    assert any("may not physically fit" in n for n in result.notes)


# --------------------------------------------------------------------------------------
# Energy balance
# --------------------------------------------------------------------------------------

def _balance_inputs(climate):
    return climate.hourly_ac_kw, demand.from_metered_units(400, user_type="home")


def test_energy_ledgers_balance_without_storage(climate):
    generation, load = _balance_inputs(climate)
    result = balance.energy_balance(generation, load)
    assert result.self_consumed_kwh + result.exported_kwh == pytest.approx(
        result.generation_kwh, rel=1e-6
    )
    assert result.self_consumed_kwh + result.imported_kwh == pytest.approx(
        result.consumption_kwh, rel=1e-6
    )


def test_energy_ledgers_balance_with_storage(climate):
    """Both ledgers must close, and the battery must not appear on both sides at once.

    Generation splits into what was used as it arrived, what went into the battery, and
    what was exported. Consumption splits into what solar covered directly, what came back
    out of the battery, and what was still bought. Energy released from storage belongs to
    the consumption ledger only — adding it to the generation ledger as well counts it
    twice, which is exactly the arithmetic that lets a calculator claim a battery creates
    energy.
    """
    generation, load = _balance_inputs(climate)
    result = balance.energy_balance(generation, load, battery_kwh=10.0)

    charged = result.battery["annual_charged_kwh"]
    discharged = result.battery["annual_discharged_kwh"]
    used_directly = result.self_consumed_kwh - discharged

    assert used_directly + charged + result.exported_kwh == pytest.approx(
        result.generation_kwh, rel=0.02
    )
    assert result.self_consumed_kwh + result.imported_kwh == pytest.approx(
        result.consumption_kwh, rel=1e-6
    )


def test_battery_cannot_return_more_than_it_stored(climate):
    generation, load = _balance_inputs(climate)
    result = balance.energy_balance(generation, load, battery_kwh=10.0)
    assert result.battery["annual_discharged_kwh"] <= result.battery["annual_charged_kwh"]
    assert result.battery["annual_round_trip_loss_kwh"] > 0


def test_battery_raises_self_consumption(climate):
    generation, load = _balance_inputs(climate)
    without = balance.energy_balance(generation, load)
    with_battery = balance.energy_balance(generation, load, battery_kwh=10.0)
    assert with_battery.self_consumption_fraction > without.self_consumption_fraction
    assert with_battery.imported_kwh < without.imported_kwh


def test_offset_never_exceeds_one(climate):
    """A vast array against a tiny load must not report a 400 % offset."""
    generation, _ = _balance_inputs(climate)
    tiny = demand.from_metered_units(20, user_type="home")
    result = balance.energy_balance(generation, tiny)
    assert result.solar_offset_fraction <= 1.0


def test_battery_recommendation_from_backup_need():
    load = demand.from_metered_units(300, user_type="home")
    rec = balance.recommend_battery(
        demand=load, desired_backup_hours=4, critical_load_kw=0.5
    )
    assert rec.usable_kwh == pytest.approx(2.0)
    assert rec.capacity_kwh > rec.usable_kwh  # depth of discharge is respected


def test_offgrid_battery_is_sized_larger():
    load = demand.from_metered_units(300, user_type="home")
    on = balance.recommend_battery(demand=load, grid_connected=True)
    off = balance.recommend_battery(demand=load, grid_connected=False)
    assert off.capacity_kwh > on.capacity_kwh


# --------------------------------------------------------------------------------------
# Economics
# --------------------------------------------------------------------------------------

def _economics(**kwargs):
    result = balance.EnergyBalance(
        generation_kwh=10_000, consumption_kwh=12_000, self_consumed_kwh=7_000,
        exported_kwh=3_000, imported_kwh=5_000, solar_offset_fraction=7 / 12,
        self_consumption_fraction=0.7, grid_dependence_fraction=5 / 12,
    )
    params = dict(
        balance=result, capacity_kwp=8.0, currency_code="INR", currency_symbol="₹",
        import_rate_per_kwh=8.0, export_rate_per_kwh=3.0, country_code="IN",
    )
    params.update(kwargs)
    return economics.compute(**params)


def test_savings_split_between_self_use_and_export():
    money = _economics()
    assert money.annual_import_savings == pytest.approx(7_000 * 8.0)
    assert money.annual_export_income == pytest.approx(3_000 * 3.0)
    assert money.annual_savings_year1 == pytest.approx(
        money.annual_import_savings + money.annual_export_income
    )


def test_degradation_reduces_generation_year_on_year():
    money = _economics()
    assert money.yearly[0]["generation_kwh"] > money.yearly[-1]["generation_kwh"]
    assert len(money.yearly) == 25


def test_payback_is_interpolated_not_a_whole_year():
    money = _economics()
    assert money.payback_years is not None
    assert money.payback_years != round(money.payback_years)


def test_no_payback_is_reported_honestly_not_as_zero():
    money = _economics(import_rate_per_kwh=0.01, export_rate_per_kwh=0.0)
    assert money.payback_years is None
    assert any("does not pay for itself" in c for c in money.caveats)


def test_subsidised_tariff_is_called_out():
    money = _economics(tariff_is_subsidised=True)
    assert any("subsidised" in c for c in money.caveats)


def test_market_cost_default_is_flagged_as_not_a_quote():
    money = _economics()
    assert any("not a quotation" in c or "not a quote" in c for c in money.caveats)


def test_supplied_cost_is_used_verbatim():
    money = _economics(system_cost_override=250_000)
    assert money.system_cost == 250_000


def test_currency_changes_the_cost_scale():
    inr = A.indicative_cost_per_kwp(5.0, "INR")
    usd = A.indicative_cost_per_kwp(5.0, "USD")
    assert inr > usd * 10  # a rupee figure must never be served as dollars


def test_emissions_follow_the_degrading_output():
    money = _economics()
    naive = money.co2_avoided_kg_per_year * money.lifetime_years / 1000.0
    assert money.co2_avoided_tonnes_lifetime < naive


# --------------------------------------------------------------------------------------
# Uncertainty
# --------------------------------------------------------------------------------------

def _assess(**kwargs):
    params = dict(
        expected_annual_kwh=10_000, measured_annual_std_kwh=400,
        variability_basis="test", complete_calendar_years=3, data_completeness=1.0,
        shading_known=True, orientation_known=True, system_specified=True,
        demand_confidence="high",
    )
    params.update(kwargs)
    return uncertainty.assess(**params)


def test_range_brackets_the_expected_value():
    band = _assess()
    assert band.lower < band.expected < band.upper


def test_unknown_inputs_widen_the_range():
    """This is what makes 'I don't know' honest rather than free."""
    known = _assess()
    unknown = _assess(shading_known=False, orientation_known=False, system_specified=False)
    assert unknown.relative > known.relative
    assert (unknown.upper - unknown.lower) > (known.upper - known.lower)


def test_unknown_inputs_produce_actionable_improvements():
    band = _assess(shading_known=False)
    assert band.improvements
    assert any("shade" in i.lower() for i in band.improvements)


def test_weather_variability_is_always_present_and_irreducible():
    band = _assess()
    weather = next(f for f in band.factors if f.key == "weather_variability")
    assert weather.kind == "irreducible"
    assert weather.reducible_by is None


def test_incomplete_data_forces_low_confidence():
    band = _assess(data_completeness=0.5)
    assert band.confidence == "low"


def test_rough_consumption_downgrades_confidence():
    band = _assess(demand_confidence="low")
    assert band.confidence in {"medium", "low"}


def test_lower_bound_never_goes_negative():
    band = _assess(expected_annual_kwh=100, measured_annual_std_kwh=500)
    assert band.lower >= 0.0


# --------------------------------------------------------------------------------------
# Farm
# --------------------------------------------------------------------------------------

def test_pumping_refuses_without_a_pump_rating():
    """§24: do not invent agricultural performance without sufficient inputs."""
    result = farm.capability(daily_generation_kwh=30.0)
    assert result.sufficient_inputs is False
    assert result.typical_daily_hours is None
    assert result.missing


def test_pumping_hours_from_horsepower_alone():
    result = farm.capability(daily_generation_kwh=30.0, horsepower=5)
    assert result.sufficient_inputs is True
    assert result.typical_daily_hours == pytest.approx(30.0 / result.pump_input_kw)
    assert result.daily_water_m3 is None  # no head given, so no water claim
    assert "depth or head" in " ".join(result.missing).lower()


def test_water_volume_needs_a_head_and_then_appears():
    result = farm.capability(daily_generation_kwh=30.0, horsepower=5, head_metres=50)
    assert result.daily_water_m3 is not None
    assert result.daily_water_m3 > 0


def test_deeper_water_means_less_of_it():
    shallow = farm.capability(daily_generation_kwh=30.0, horsepower=5, head_metres=20)
    deep = farm.capability(daily_generation_kwh=30.0, horsepower=5, head_metres=80)
    assert shallow.daily_water_m3 > deep.daily_water_m3


def test_irrigable_area_requires_a_crop_requirement():
    without = farm.capability(daily_generation_kwh=30.0, horsepower=5, head_metres=50)
    with_crop = farm.capability(
        daily_generation_kwh=30.0, horsepower=5, head_metres=50,
        crop_water_requirement_mm_per_day=5,
    )
    assert without.irrigable_area_hectares is None
    assert with_crop.irrigable_area_hectares > 0


def test_shortfall_against_a_stated_requirement_is_reported():
    result = farm.capability(
        daily_generation_kwh=5.0, horsepower=5, head_metres=50,
        required_daily_water_m3=500,
    )
    assert result.meets_requirement is False
    assert any("short" in n for n in result.notes)


# --------------------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------------------

def test_save_read_rename_delete_round_trip():
    record = estimate_store.save({"location": {"label": "Test"}, "system": {"capacity_kwp": 5}})
    assert record.estimate_id

    fetched = estimate_store.get(record.estimate_id)
    assert fetched is not None and fetched.label == "Test — 5 kW"

    renamed = estimate_store.rename(record.estimate_id, "My farm")
    assert renamed is not None and renamed.label == "My farm"
    assert renamed.created_at == record.created_at  # identity survives a rename

    assert estimate_store.delete(record.estimate_id) is True
    assert estimate_store.get(record.estimate_id) is None


def test_an_estimate_saved_without_an_owner_is_anonymous():
    """The default, and the one the signed-out calculator relies on."""
    record = estimate_store.save({"location": {"label": "Test"}})
    assert record.owner_id is None
    assert estimate_store.owner_of(record.estimate_id) is None


def test_identifiers_are_not_guessable():
    ids = {estimate_store.new_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(len(i) >= 20 for i in ids)


@pytest.mark.parametrize("bad", ["../secrets", "a/b", "..", "x" * 5 + "/../y", "x" * 200])
def test_a_malformed_identifier_resolves_to_nothing(bad):
    """Identifiers are still validated before they are used to look anything up.

    This used to defend a filesystem path join. There is no path any more — the identifier
    is a primary key — but the check earns its place twice over: it turns a malformed link
    into a clean miss without a database round-trip, and it means no caller can pass an
    arbitrary string of arbitrary length into a query.
    """
    assert estimate_store.get(bad) is None
    assert estimate_store.delete(bad) is False
    assert estimate_store.rename(bad, "anything") is None


def test_missing_estimate_reads_as_none():
    assert estimate_store.get("doesnotexist") is None


# --------------------------------------------------------------------------------------
# Country, currency and labelling
# --------------------------------------------------------------------------------------

def test_monthly_bands_use_each_month_own_variability():
    """A monsoon July is genuinely less predictable than a dry February.

    Applying one annual figure to all twelve months is wrong in both directions: it
    overstates the settled months and understates the volatile ones, which are exactly the
    months somebody planning irrigation needs to see clearly.
    """
    band = _assess()
    assert band.non_weather_relative > 0
    assert band.non_weather_relative < band.relative  # weather is a real share of the total

    steady_lo, steady_hi = band.band_for(1000.0, 0.02)
    volatile_lo, volatile_hi = band.band_for(1000.0, 0.20)
    assert (volatile_hi - volatile_lo) > (steady_hi - steady_lo) * 2


def test_a_month_band_never_goes_negative():
    band = _assess()
    lower, _ = band.band_for(10.0, 5.0)
    assert lower >= 0.0


def test_non_weather_uncertainty_excludes_the_weather_term():
    band = _assess()
    weather = next(f for f in band.factors if f.key == "weather_variability")
    # Removing the weather term must actually change the figure.
    assert band.non_weather_relative < band.relative
    assert weather.relative > 0


def test_demand_returns_the_hourly_profile_it_used():
    """The chart overlays this curve on generation; reconstructing it client-side invites
    drift between what is drawn and what was calculated."""
    estimate = demand.from_metered_units(300, user_type="farm")
    payload = estimate.to_dict()
    hourly = payload["hourly_kwh"]
    assert len(hourly) == 24
    assert sum(hourly) == pytest.approx(estimate.daily_kwh, rel=1e-3)
    # And it is the farm shape, not a flat line.
    assert max(hourly) > min(hourly) * 3


def test_iso_code_is_preferred_over_the_country_name():
    """A translated country name must not decide the currency.

    Nominatim answers in the local language unless asked otherwise, so matching "India"
    against a table of English names is one config change away from serving an Indian farm
    its savings in dollars. The ISO code is unambiguous, and this pins that preference.
    """
    from app.estimate.engine import _country_code

    translated = Location(
        latitude=16.5, longitude=80.6, name="Vijayawada",
        country="भारत", country_code="IN",
    )
    assert _country_code(translated) == "IN"


def test_country_name_still_works_when_no_code_is_supplied():
    from app.estimate.engine import _country_code

    assert _country_code(Location(latitude=1, longitude=1, name="x", country="India")) == "IN"
    assert _country_code(Location(latitude=1, longitude=1, name="x")) is None


def test_currency_follows_the_country():
    from app.estimate.tariffs import currency_for_country

    assert currency_for_country("IN").code == "INR"
    assert currency_for_country("US").code == "USD"
    # An unknown country must fall back rather than raise mid-estimate.
    assert currency_for_country("ZZ").code == "USD"
    assert currency_for_country(None).code == "USD"


def test_indian_farm_tariff_is_flagged_subsidised():
    """Billing displaced farm units at a commercial rate overstates savings severalfold."""
    from app.estimate.tariffs import default_tariff

    assert default_tariff("IN", "farm").subsidised is True
    assert default_tariff("IN", "home").subsidised is False


def test_currency_and_tariff_are_always_on_the_same_scale():
    """A symbol beside a number from a different currency is not an approximation.

    The generic fallback rate is denominated in dollars. Handing it to a Kenyan user under
    a shilling symbol would read as authoritative while being wrong by a factor of 130.
    """
    from app.estimate import assumptions as A
    from app.estimate.tariffs import currency_for_country, default_tariff

    for country in ("IN", "US", "ES", "KE", "SE", "ZA", "JP"):
        currency = currency_for_country(country)
        tariff = default_tariff(country, "home")
        cost = A.indicative_cost_per_kwp(5.0, currency.code)

        # A domestic unit costs somewhere between a hundredth and a hundred of a currency
        # unit in every real tariff; anything outside that is a scale error.
        assert 0.01 <= tariff.rate_per_kwh <= 100, f"{country}: {tariff.rate_per_kwh}"
        # And an installed kW costs between a hundred and ten million currency units.
        assert 100 <= cost <= 10_000_000, f"{country}: {cost}"


def test_unknown_currency_falls_back_rather_than_mixing_scales():
    from app.estimate.tariffs import currency_for_country

    # Iceland has a currency we hold no rate for; the dollar is safer than a wrong krona.
    assert currency_for_country("IS").code == "USD"


def test_eurozone_countries_share_one_currency():
    from app.estimate.tariffs import currency_for_country

    codes = {currency_for_country(c).code for c in ("DE", "ES", "FR", "IT", "NL")}
    assert codes == {"EUR"}


def test_location_label_prefers_a_name_over_coordinates():
    named = Location(
        latitude=16.5074, longitude=80.6466, name="Vijayawada",
        admin1="Andhra Pradesh", country="India", country_code="IN",
    )
    assert named.label == "Vijayawada, Andhra Pradesh, India"
    assert "16.5" not in named.label


# --------------------------------------------------------------------------------------
# Interview
# --------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------
# Panel quantity
# --------------------------------------------------------------------------------------

def test_summary_capitalisation_preserves_units():
    """`str.capitalize()` would render "550 W" as "550 w" and "kW" as "kw"."""
    from app.estimate.engine import build_narrative

    payload = {
        "generation": {
            "annual_kwh": 17_000, "daily_average_kwh": 46.8,
            "specific_yield_kwh_per_kwp": 1550, "best_month_name": "March",
            "worst_month_name": "July", "clipped_fraction": 0.0,
        },
        "location": {"label": "Hyderabad"},
        "system": {
            "capacity_kwp": 11, "panels": {"count": 20, "watts": 550},
            "orientation": {"tilt_deg": 20, "azimuth_compass": "south"},
            "inverter": {},
        },
        "uncertainty": {"relative_pct": 11.0, "confidence": "medium",
                        "confidence_reason": "", "improvements": []},
    }
    summary = build_narrative(payload)["summary"]
    assert "550 W panels" in summary
    assert "kW in total" in summary
    assert " w panels" not in summary
    assert " kw " not in summary


def test_summary_names_the_array_not_just_the_capacity():
    """§15: the result must connect panel quantity to generation."""
    from app.estimate.engine import build_narrative

    payload = {
        "generation": {
            "annual_kwh": 17_000, "daily_average_kwh": 46.8,
            "specific_yield_kwh_per_kwp": 1550, "best_month_name": "March",
            "worst_month_name": "July", "clipped_fraction": 0.0,
        },
        "location": {"label": "Hyderabad"},
        "system": {
            "capacity_kwp": 11, "panels": {"count": 20, "watts": 550},
            "orientation": {"tilt_deg": 20, "azimuth_compass": "south"},
            "inverter": {},
        },
        "uncertainty": {"relative_pct": 11.0, "confidence": "medium",
                        "confidence_reason": "", "improvements": []},
    }
    narrative = build_narrative(payload)
    assert "20 × 550 W panels" in narrative["summary"]
    # §16: and it must say output is not proportional to panel count.
    reasons = {a["key"] for a in narrative["what_affects_this"]}
    assert "panel_count" in reasons


def test_capacity_from_panels_matches_the_specified_example():
    """20 panels of 550 W are 11 kW. The arithmetic everything else rests on."""
    assert sizing.capacity_from_panels(20, 550) == pytest.approx(11.0)


def test_panels_for_capacity_rounds_to_whole_panels():
    # There is no such thing as most of a panel.
    assert sizing.panels_for_capacity(15.37, 550) == 28
    assert sizing.panels_for_capacity(0.2, 550) == 1   # never zero panels
    assert sizing.panels_for_capacity(11.0, 550) == 20


def test_configured_capacity_is_recomputed_from_the_rounded_count():
    """The reported capacity must describe the array shown, not the sizing target.

    A target of 15.37 kW becomes 28 panels, and 28 × 550 W is 15.40 kW. Carrying the target
    through would put a capacity on the page that no whole number of panels produces.
    """
    config = sizing.configure_panels(target_kwp=15.37, watts=550)
    assert config.count == 28
    assert config.capacity_kwp == pytest.approx(15.4)
    assert config.capacity_kwp != pytest.approx(15.37)


def test_unknown_wattage_falls_back_and_says_so():
    """§5: never block a beginner — but never let the assumption pass unrecorded."""
    config = sizing.configure_panels(target_kwp=10.0, watts=None, panel_key="mono_perc")
    assert config.watts_known is False
    assert config.watts == A.typical_panel_watts("mono_perc")
    assert "not given" in config.note


def test_panel_count_override_wins_over_the_recommendation():
    config = sizing.configure_panels(target_kwp=15.37, watts=550, count_override=34)
    assert config.count == 34
    assert config.capacity_kwp == pytest.approx(18.7)
    assert config.source == "recommended"  # source is the caller's to declare


def test_zero_or_negative_panels_are_refused():
    with pytest.raises(ValueError, match="at least 1"):
        sizing.capacity_from_panels(0, 550)
    with pytest.raises(ValueError, match="greater than zero"):
        sizing.capacity_from_panels(10, 0)


def test_typical_wattage_is_known_for_every_panel_technology():
    for key in A.PANEL_TECHNOLOGIES:
        watts = A.typical_panel_watts(key)
        assert A.MIN_PANEL_WATTS <= watts <= A.MAX_PANEL_WATTS


def test_offered_wattages_are_physically_plausible():
    for entry in A.PANEL_WATTAGE_OPTIONS:
        assert A.MIN_PANEL_WATTS <= entry["watts"] <= A.MAX_PANEL_WATTS
        assert entry["label"] and entry["note"]


def test_goal_reshapes_the_interview():
    """Panel count is asked of an owner and withheld from a planner (§1, §3)."""
    from app.estimate import personas

    existing = personas.flow_for("home", "quick", "existing")
    install = personas.flow_for("home", "quick", "install")

    existing_fields = {q.field for step in existing for q in step.questions}
    install_fields = {q.field for step in install for q in step.questions}

    assert "panel_count" in existing_fields
    # A quick install flow must not ask for panel count — it is the answer, not the input.
    assert "panel_count" not in install_fields


def test_existing_flow_asks_about_panels_before_anything_optional():
    from app.estimate import personas

    steps = personas.flow_for("home", "quick", "existing")
    ids = [s.id for s in steps]
    assert ids.index("existing") < ids.index("consumption")


def test_existing_flow_does_not_ask_for_available_space():
    """The array is already installed; its space is a decision already taken."""
    from app.estimate import personas

    fields = {
        q.field
        for step in personas.flow_for("home", "quick", "existing")
        for q in step.questions
    }
    assert "available_area" not in fields


def test_panel_wattage_question_offers_an_escape():
    from app.estimate import personas

    assert personas.PANEL_WATTS.unknown_label
    assert personas.PANEL_WATTS.unknown_effect
    offered = {int(o.value) for o in personas.PANEL_WATTS.options}
    assert {330, 400, 450, 540, 550, 600} <= offered


def test_catalogue_enumerates_every_goal_branch():
    from app.estimate import personas

    catalogue = personas.catalogue()
    assert [g["key"] for g in catalogue["goals"]] == ["existing", "install", "compare"]
    for user in catalogue["flows"].values():
        for mode in user.values():
            assert set(mode) == {"existing", "install", "compare"}


def test_every_user_type_has_a_flow_in_both_modes():
    from app.estimate import personas

    for user in personas.USER_TYPES:
        for mode in ("quick", "detailed"):
            steps = personas.flow_for(user.key, mode)
            assert steps
            assert steps[0].id == "location"


def test_detailed_mode_asks_more_than_quick_mode():
    from app.estimate import personas

    quick = personas.flow_for("commercial", "quick")
    detailed = personas.flow_for("commercial", "detailed")
    assert len(detailed) > len(quick)


def test_farm_flow_asks_about_the_pump():
    from app.estimate import personas

    steps = personas.flow_for("farm", "quick")
    assert any(step.id == "farm" for step in steps)


def test_home_flow_does_not_ask_about_pumps():
    from app.estimate import personas

    steps = personas.flow_for("home", "quick")
    assert not any(step.id == "farm" for step in steps)


def test_technical_questions_offer_a_way_out():
    """§12: every question a beginner cannot answer needs an explicit escape."""
    from app.estimate import personas

    technical = {"tilt", "azimuth", "inverter_efficiency", "dc_ac_ratio", "system_cost"}
    seen = set()
    for user in personas.USER_TYPES:
        for step in personas.flow_for(user.key, "detailed"):
            for question in step.questions:
                if question.id in technical:
                    seen.add(question.id)
                    assert question.unknown_label, f"{question.id} has no escape route"
                    assert question.unknown_effect, f"{question.id} does not say what happens"
    assert seen == technical


def test_catalogue_is_serialisable():
    import json

    from app.estimate import personas

    payload = personas.catalogue()
    json.dumps(payload)  # must survive the wire
    assert payload["user_types"] and payload["appliances"] and payload["flows"]
