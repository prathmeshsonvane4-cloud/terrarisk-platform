"""FAO-56 checks against FAO's own worked examples (Allen et al. 1998,
Irrigation and Drainage Paper 56). If these drift, every ET0 and every
water balance built on it is wrong, so they are pinned to the published
numbers rather than to values this code once produced."""

from __future__ import annotations

import pytest

from farm_context import (
    et0_fao56,
    extraterrestrial_radiation,
    rolling_sum,
    saturation_vapour_pressure,
    wind_10m_to_2m,
)


def test_extraterrestrial_radiation_matches_fao56_example_8():
    """20 °S on 3 September (day 246): Ra = 32.2 MJ m-2 day-1."""
    assert extraterrestrial_radiation(-20.0, 246) == pytest.approx(32.2, abs=0.1)


def test_saturation_vapour_pressure_matches_the_fao56_table():
    """Annex 2, Table 2.3: e°(25 °C) = 3.168 kPa."""
    assert saturation_vapour_pressure(25.0) == pytest.approx(3.168, abs=0.002)


def test_wind_is_brought_down_from_10_m_to_2_m():
    """FAO-56 eq. 47 multiplies a 10 m wind by about 0.748."""
    assert wind_10m_to_2m(1.0) == pytest.approx(0.748, abs=0.001)


def test_daily_et0_matches_fao56_example_18():
    """Brussels, 6 July (day 187), 50°48' N, 100 m: Tmax 21.5, Tmin 12.3,
    ea 1.409 kPa, u2 2.078 m/s, Rs 22.07 MJ m-2, P 100.1 kPa.
    FAO-56 gives ET0 = 3.9 mm/day."""
    et0 = et0_fao56(tmax=21.5, tmin=12.3, ea=1.409, rs=22.07, u2=2.078, pressure_kpa=100.1,
                    latitude_deg=50.8, day_of_year=187, elevation_m=100)
    assert et0 == pytest.approx(3.9, abs=0.05)


def test_et0_is_never_negative():
    """A cold, dark, humid day can drive the formula below zero; ET0 cannot be."""
    assert et0_fao56(tmax=2.0, tmin=-3.0, ea=0.7, rs=1.0, u2=0.5, pressure_kpa=95.0,
                     latitude_deg=60.0, day_of_year=355, elevation_m=500) >= 0.0


def test_a_thirty_day_balance_with_a_gap_is_not_reported():
    values = [1.0] * 40
    values[35] = None
    sums = rolling_sum(values, 30)
    assert sums[29] == 30.0
    assert sums[35] is None and sums[39] is None
