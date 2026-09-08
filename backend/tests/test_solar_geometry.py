"""Tests for the physics core.

These assert against values that are independently knowable — solar declination at the
solstices, the zenith angle at solar noon, the diffuse fraction under clear and overcast
skies — rather than against whatever the implementation happens to produce. A test that
only pins current behaviour would pass just as happily if the physics were wrong.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.features.solar_geometry import (
    DAYTIME_ZENITH_THRESHOLD_DEG,
    IRRADIANCE_INTERVAL_OFFSET_MINUTES,
    PVSystem,
    angle_of_incidence,
    cell_temperature_faiman,
    clear_sky_ghi_haurwitz,
    clear_sky_index,
    erbs_decomposition,
    extraterrestrial_normal,
    pv_power_chain,
    representative_times,
    solar_position,
)


def times(*iso: str) -> np.ndarray:
    return np.array([np.datetime64(s) for s in iso])


class TestSolarPosition:
    @pytest.mark.parametrize(
        "moment,expected",
        [
            ("2024-06-21T12:00", 23.44),   # June solstice
            ("2024-12-21T12:00", -23.44),  # December solstice
        ],
    )
    def test_declination_at_solstices(self, moment: str, expected: float) -> None:
        pos = solar_position(times(moment), 0.0, 0.0)
        assert pos.declination[0] == pytest.approx(expected, abs=0.02)

    def test_declination_near_zero_at_equinox(self) -> None:
        pos = solar_position(times("2024-03-20T03:06"), 0.0, 0.0)
        assert abs(pos.declination[0]) < 0.05

    @pytest.mark.parametrize("latitude", [0.0, 17.385, 51.48, -33.9, 64.14])
    def test_solar_noon_zenith_equals_latitude_minus_declination(self, latitude: float) -> None:
        """At solar noon the zenith angle is |latitude - declination|."""
        pos = solar_position(times("2024-03-20T12:07"), latitude, 0.0)
        expected = abs(latitude - pos.declination[0])
        assert pos.zenith[0] == pytest.approx(expected, abs=0.1)

    def test_azimuth_is_south_in_northern_midlatitudes_at_noon(self) -> None:
        pos = solar_position(times("2024-06-21T12:02"), 51.48, 0.0)
        assert pos.azimuth[0] == pytest.approx(180.0, abs=1.0)

    def test_azimuth_is_north_when_sun_is_north_of_site(self) -> None:
        """At the June solstice the subsolar point is 23.4 N, north of a 17.4 N site.

        06:48 UTC is solar noon at this longitude, where azimuth is least ambiguous.
        """
        pos = solar_position(times("2024-06-21T06:48"), 17.385, 78.4867)
        assert pos.azimuth[0] < 20.0 or pos.azimuth[0] > 340.0

    def test_southern_hemisphere_azimuth_is_north(self) -> None:
        pos = solar_position(times("2024-06-21T12:02"), -33.9, 0.0)
        assert pos.azimuth[0] < 10.0 or pos.azimuth[0] > 350.0

    def test_night_is_detected(self) -> None:
        pos = solar_position(times("2024-06-21T00:00"), 51.48, 0.0)
        assert not pos.is_daytime[0]
        assert pos.apparent_zenith[0] > DAYTIME_ZENITH_THRESHOLD_DEG

    def test_cos_zenith_never_negative(self) -> None:
        pos = solar_position(times(*[f"2024-06-21T{h:02d}:00" for h in range(24)]), 51.48, 0.0)
        assert np.all(pos.cos_zenith >= 0.0)

    def test_polar_night(self) -> None:
        """Above the Arctic Circle in December the sun does not rise."""
        hours = times(*[f"2024-12-21T{h:02d}:00" for h in range(24)])
        pos = solar_position(hours, 78.0, 15.0)
        assert not pos.is_daytime.any()

    def test_polar_day(self) -> None:
        hours = times(*[f"2024-06-21T{h:02d}:00" for h in range(24)])
        pos = solar_position(hours, 78.0, 15.0)
        assert pos.is_daytime.all()


class TestIntervalConvention:
    def test_representative_times_applies_offset(self) -> None:
        base = times("2024-06-01T12:00")
        shifted = representative_times(base)
        delta = (shifted[0] - base[0].astype("datetime64[s]")) / np.timedelta64(1, "m")
        assert delta == pytest.approx(IRRADIANCE_INTERVAL_OFFSET_MINUTES)

    def test_offset_is_negative_thirty_minutes(self) -> None:
        """The archive labels hourly radiation with the end of the preceding hour."""
        assert IRRADIANCE_INTERVAL_OFFSET_MINUTES == -30.0


class TestClearSky:
    def test_peak_clear_sky_is_physically_plausible(self) -> None:
        assert 900.0 < clear_sky_ghi_haurwitz(np.array([0.0]))[0] < 1100.0

    def test_zero_below_horizon(self) -> None:
        assert clear_sky_ghi_haurwitz(np.array([95.0, 120.0, 180.0])).tolist() == [0.0, 0.0, 0.0]

    def test_decreases_monotonically_with_zenith(self) -> None:
        zeniths = np.array([0.0, 20.0, 40.0, 60.0, 80.0])
        values = clear_sky_ghi_haurwitz(zeniths)
        assert np.all(np.diff(values) < 0)

    def test_clear_sky_index_is_nan_at_night(self) -> None:
        kt = clear_sky_index(np.array([0.0]), np.array([0.0]))
        assert np.isnan(kt[0])

    def test_clear_sky_index_ratio(self) -> None:
        kt = clear_sky_index(np.array([500.0]), np.array([1000.0]))
        assert kt[0] == pytest.approx(0.5)

    def test_clear_sky_index_capped(self) -> None:
        kt = clear_sky_index(np.array([5000.0]), np.array([1000.0]), cap=1.5)
        assert kt[0] == pytest.approx(1.5)


class TestExtraterrestrial:
    def test_perihelion_exceeds_aphelion(self) -> None:
        jan = extraterrestrial_normal(times("2024-01-03T12:00"))[0]
        jul = extraterrestrial_normal(times("2024-07-04T12:00"))[0]
        assert jan > jul
        # Orbital eccentricity gives about a 6.6 % annual swing.
        assert (jan - jul) / jul == pytest.approx(0.068, abs=0.01)


class TestErbs:
    def test_reconstructs_ghi(self) -> None:
        ghi = np.array([900.0, 400.0, 120.0])
        zen = np.array([20.0, 20.0, 20.0])
        e0n = np.array([1361.0, 1361.0, 1361.0])
        dhi, dni = erbs_decomposition(ghi, zen, e0n)
        reconstructed = dni * np.cos(np.radians(zen)) + dhi
        assert np.allclose(reconstructed, ghi, atol=1e-6)

    def test_overcast_is_almost_entirely_diffuse(self) -> None:
        dhi, dni = erbs_decomposition(np.array([120.0]), np.array([20.0]), np.array([1361.0]))
        assert dhi[0] / 120.0 > 0.9
        assert dni[0] < 20.0

    def test_clear_sky_has_substantial_beam(self) -> None:
        dhi, dni = erbs_decomposition(np.array([900.0]), np.array([20.0]), np.array([1361.0]))
        assert dni[0] > 500.0
        assert dhi[0] / 900.0 < 0.35

    def test_components_never_negative(self) -> None:
        dhi, dni = erbs_decomposition(
            np.array([0.0, 1.0, 1200.0]), np.array([89.0, 45.0, 5.0]), np.full(3, 1361.0)
        )
        assert np.all(dhi >= 0) and np.all(dni >= 0)


class TestAngleOfIncidence:
    def test_zero_when_sun_normal_to_panel(self) -> None:
        """A panel tilted 30 deg facing south, sun at 30 deg zenith due south."""
        aoi = angle_of_incidence(30.0, 180.0, np.array([30.0]), np.array([180.0]))
        assert aoi[0] == pytest.approx(0.0, abs=1e-6)

    def test_equals_zenith_for_horizontal_panel(self) -> None:
        aoi = angle_of_incidence(0.0, 180.0, np.array([42.0]), np.array([137.0]))
        assert aoi[0] == pytest.approx(42.0, abs=1e-6)


class TestCellTemperature:
    def test_equals_air_temperature_without_irradiance(self) -> None:
        t = cell_temperature_faiman(np.array([0.0]), np.array([25.0]), np.array([2.0]))
        assert t[0] == pytest.approx(25.0)

    def test_wind_cools_the_module(self) -> None:
        """The mechanism the project abstract calls the wind-cooling effect."""
        calm = cell_temperature_faiman(np.array([800.0]), np.array([30.0]), np.array([0.0]))
        windy = cell_temperature_faiman(np.array([800.0]), np.array([30.0]), np.array([8.0]))
        assert windy[0] < calm[0]

    def test_module_runs_hotter_than_air_under_sun(self) -> None:
        t = cell_temperature_faiman(np.array([900.0]), np.array([25.0]), np.array([1.0]))
        assert t[0] > 25.0


class TestPVChain:
    def _hours(self) -> np.ndarray:
        return times(*[f"2024-06-01T{h:02d}:30" for h in range(24)])

    def test_zero_output_at_night(self) -> None:
        hours = self._hours()
        # Deliberately feed non-zero irradiance at every hour, including night.
        out = pv_power_chain(
            ghi=np.full(24, 500.0),
            air_temp_c=np.full(24, 25.0),
            wind_speed_ms=np.full(24, 2.0),
            times_utc=hours,
            latitude=17.385,
            longitude=78.4867,
            system=PVSystem(dc_capacity_kwp=5.0),
        )
        pos = solar_position(representative_times(hours), 17.385, 78.4867)
        night = ~pos.is_daytime
        assert night.any(), "test needs some night hours"
        assert np.all(out.ac_power_kw[night] == 0.0), (
            "PV output must be zero when the sun is below the horizon, regardless of "
            "what the irradiance input claims"
        )

    def test_output_never_negative(self) -> None:
        out = pv_power_chain(
            ghi=np.full(24, 400.0),
            air_temp_c=np.full(24, 45.0),
            wind_speed_ms=np.full(24, 0.0),
            times_utc=self._hours(),
            latitude=17.385,
            longitude=78.4867,
            system=PVSystem(),
        )
        assert np.all(out.ac_power_kw >= 0.0)

    def test_inverter_clipping_respected(self) -> None:
        system = PVSystem(dc_capacity_kwp=10.0, inverter_ac_capacity_kw=3.0)
        out = pv_power_chain(
            ghi=np.full(24, 1000.0),
            air_temp_c=np.full(24, 20.0),
            wind_speed_ms=np.full(24, 3.0),
            times_utc=self._hours(),
            latitude=17.385,
            longitude=78.4867,
            system=system,
        )
        assert out.ac_power_kw.max() <= 3.0 + 1e-9
        assert out.clipped_fraction > 0.0

    def test_output_scales_with_capacity(self) -> None:
        kwargs = dict(
            ghi=np.full(24, 600.0),
            air_temp_c=np.full(24, 25.0),
            wind_speed_ms=np.full(24, 2.0),
            times_utc=self._hours(),
            latitude=17.385,
            longitude=78.4867,
        )
        small = pv_power_chain(system=PVSystem(dc_capacity_kwp=5.0), **kwargs)
        large = pv_power_chain(system=PVSystem(dc_capacity_kwp=10.0), **kwargs)
        assert large.ac_power_kw.sum() == pytest.approx(2.0 * small.ac_power_kw.sum(), rel=1e-6)

    def test_hot_modules_produce_less(self) -> None:
        kwargs = dict(
            ghi=np.full(24, 800.0),
            wind_speed_ms=np.full(24, 1.0),
            times_utc=self._hours(),
            latitude=17.385,
            longitude=78.4867,
            system=PVSystem(),
        )
        cool = pv_power_chain(air_temp_c=np.full(24, 10.0), **kwargs)
        hot = pv_power_chain(air_temp_c=np.full(24, 45.0), **kwargs)
        assert hot.ac_power_kw.sum() < cool.ac_power_kw.sum()


class TestPVSystemValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"dc_capacity_kwp": 0.0},
            {"dc_capacity_kwp": -5.0},
            {"surface_tilt_deg": 95.0},
            {"surface_tilt_deg": -1.0},
            {"surface_azimuth_deg": 360.0},
            {"system_losses_fraction": 1.0},
            {"inverter_efficiency": 0.0},
            {"inverter_efficiency": 1.5},
        ],
    )
    def test_rejects_invalid_configuration(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            PVSystem(**kwargs)

    def test_default_dc_ac_ratio(self) -> None:
        assert PVSystem(dc_capacity_kwp=6.0).ac_capacity_kw == pytest.approx(5.0)
