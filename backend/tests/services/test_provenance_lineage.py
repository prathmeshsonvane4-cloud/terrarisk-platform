"""Tests for evidence lineage content — pure, no database, no Earth Engine.

The Earth Engine providers are instantiated without running their
initialisers (`object.__new__`), so `isinstance` selects the described
lineage path without credentials. Nothing here calls a provider method.

What these tests exist to stop:
- lineage that restates a number instead of importing it, and drifts;
- "not recorded" being written as "none";
- any input being labelled anything other than unvalidated;
- a non-Earth-Engine provider silently borrowing Earth Engine's lineage.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import EvidenceKind, EvidenceValidation
from app.services.hydrology import engine as water_balance_engine
from app.services.hydrology import gee_hydrology_provider as hydro
from app.services.hydrology.recharge_stress import RechargeStressFactor
from app.services.provenance import recharge_stress_evidence, risk_score_evidence, water_balance_evidence
from app.services.risk.models import MonthlyValue
from app.services.satellite import gee_provider as gee
from app.services.satellite.provider import IndexObservation, SatelliteIndex
from tests.fakes.fake_hydrology_provider import FakeHydrologyDataProvider
from tests.fakes.fake_satellite_provider import FakeSatelliteDataProvider

_START, _END = date(2023, 6, 1), date(2026, 6, 1)
_MONTHS = [date(2023 + (m + 5) // 12, (m + 5) % 12 + 1, 1) for m in range(36)]


def _gee_satellite():
    return object.__new__(gee.GeeProvider)


def _gee_hydrology():
    return object.__new__(hydro.GEEHydrologyProvider)


def _monthly(value, missing: set[int] = frozenset()):
    return [MonthlyValue(d, None if i in missing else value) for i, d in enumerate(_MONTHS)]


def _index_obs(missing: set[int] = frozenset()):
    return [
        IndexObservation(d, d.replace(day=28), 0.5, source_scene_dates=[d.replace(day=4), d.replace(day=19)])
        for i, d in enumerate(_MONTHS)
        if i not in missing
    ]


def _by_quantity(items):
    return {item.quantity: item for item in items}


def _water_balance(**overrides):
    kwargs = dict(
        rainfall_monthly=_monthly(47.0),
        rainfall_daily=[MonthlyValue(date(2023, 7, d), 3.0) for d in range(1, 29)],
        et_monthly=_monthly(40.0, missing={2, 3}),
        start=_START,
        end=_END,
        resolution_flags=["rainfall_sub_pixel"],
        satellite_provider=_gee_satellite(),
        hydrology_provider=_gee_hydrology(),
    )
    kwargs.update(overrides)
    return _by_quantity(water_balance_evidence(**kwargs))


class TestNumbersComeFromTheCodeThatUsesThem:
    def test_et_lineage_uses_the_providers_own_scale_threshold_and_factor(self):
        et = _water_balance()["et_monthly_mm"]
        assert et.source == hydro._MODIS_ET_COLLECTION
        assert et.requested_scale_m == hydro._ET_SCALE_METERS
        assert str(hydro._ET_VALID_MAX) in et.temporal_aggregation
        assert str(hydro._ET_SCALE_FACTOR) in et.temporal_aggregation

    def test_the_curve_number_recorded_is_the_one_the_engine_uses(self):
        cn = _water_balance()["curve_number"]
        assert cn.kind is EvidenceKind.PARAMETER
        assert cn.value == water_balance_engine._CURVE_NUMBER

    def test_product_versions_come_from_the_registry(self):
        items = _water_balance()
        assert items["et_monthly_mm"].product_version == "Collection 6.1"
        assert items["rainfall_monthly_mm"].product_version == "2.0 Final"


class TestSpatialLineage:
    def test_chirps_is_recorded_as_resampled(self):
        """Requested 5000 m on a 5566 m grid. Nothing previously said so."""
        rainfall = _water_balance()["rainfall_monthly_mm"]
        assert rainfall.native_resolution_m == 5566.0
        assert rainfall.requested_scale_m == 5000.0
        assert rainfall.resampled is True

    def test_mod16a2_is_read_at_native_resolution(self):
        assert _water_balance()["et_monthly_mm"].resampled is False

    def test_catchment_resolution_flags_become_limitations_on_its_inputs(self):
        assert any("rainfall_sub_pixel" in lim for lim in _water_balance()["rainfall_monthly_mm"].known_limitations)


class TestNotRecordedIsNotNone:
    def test_et_acquisition_dates_are_null_and_the_gap_is_stated(self):
        et = _water_balance()["et_monthly_mm"]
        assert et.acquisition_dates is None
        assert any("not recorded" in lim for lim in et.known_limitations)

    def test_sentinel2_scene_dates_are_recorded_when_the_provider_returns_them(self):
        items = _by_quantity(_risk())
        assert items["ndvi"].acquisition_dates[:2] == ["2023-06-04", "2023-06-19"]

    def test_observation_counts_reflect_missing_months(self):
        et = _water_balance()["et_monthly_mm"]
        assert (et.observations_expected, et.observations_used) == (36, 34)


class TestNothingIsLabelledValidated:
    def test_every_input_to_every_result_is_unvalidated(self):
        for item in [*_water_balance().values(), *_risk(), *_stress()]:
            assert item.validation_status is EvidenceValidation.UNVALIDATED, item.quantity

    def test_the_composite_rule_that_replaced_the_neutral_score_is_recorded(self):
        """Phase C removed the neutral-50 fallback. The lineage of a score
        records the rule that replaced it, with its values imported from the
        engine."""
        from app.services.risk import engine as risk_engine

        items = _by_quantity(_risk())
        assert "neutral_score_when_uncomputable" not in items
        rule = items["composite_min_weight_coverage"]
        assert rule.value == risk_engine._MIN_WEIGHT_COVERAGE
        assert "never scored neutral" in rule.known_limitations[0]
        assert items["confidence_level"].value == pytest.approx(0.90)

    def test_a_small_farm_is_told_its_rainfall_is_regional(self):
        items = _by_quantity(_risk(farm_area_ha=0.25))
        assert any("0.25 ha farm" in lim for lim in items["rainfall_monthly_mm"].known_limitations)
        assert "centroid" in items["rainfall_monthly_mm"].reducer


class TestUndescribedProviders:
    def test_a_non_earth_engine_provider_does_not_borrow_earth_engine_lineage(self):
        items = _water_balance(
            satellite_provider=FakeSatelliteDataProvider(), hydrology_provider=FakeHydrologyDataProvider()
        )
        et = items["et_monthly_mm"]
        assert "lineage not described" in et.source
        assert et.reducer is None and et.requested_scale_m is None
        assert "not traceable" in et.known_limitations[0]

    def test_parameters_are_still_recorded_whatever_the_provider(self):
        """Parameters belong to the engine, not the provider."""
        items = _water_balance(
            satellite_provider=FakeSatelliteDataProvider(), hydrology_provider=FakeHydrologyDataProvider()
        )
        assert items["curve_number"].value == water_balance_engine._CURVE_NUMBER


def _risk(**overrides):
    obs = _index_obs()
    kwargs = dict(
        index_observations={
            SatelliteIndex.NDVI: (obs, _monthly(0.5), "fetched"),
            SatelliteIndex.MNDWI: (obs, _monthly(0.1), "cache"),
            SatelliteIndex.NDMI: (obs, _monthly(0.2), "fetched"),
        },
        baseline_observations={SatelliteIndex.NDVI: (obs, _monthly(0.5), "fetched")},
        rainfall_observations=[],
        rainfall_monthly=_monthly(47.0),
        rainfall_retrieval="cache",
        rainfall_normals={m: 47.0 for m in range(1, 13)},
        jrc_period=(date(1984, 3, 16), date(2021, 12, 31)),
        start=_START,
        end=_END,
        baseline_start=date(2015, 6, 1),
        weights={"vegetation_stability": 0.25},
        weights_version_id="cfg-1",
        floor_threshold=85.0,
        computed_in_year=2026,
        satellite_provider=_gee_satellite(),
    )
    kwargs.update(overrides)
    return risk_score_evidence(**kwargs)


class TestServiceOneLineage:
    def test_jrc_lineage_records_the_corrected_reducer(self):
        jrc = _by_quantity(_risk())["jrc_occurrence_percent"]
        assert "unweighted" in jrc.reducer and "unmask(0)" in jrc.reducer
        assert jrc.period_end == date(2021, 12, 31)

    def test_swir_indices_disclose_their_20m_effective_resolution_and_ndvi_does_not(self):
        items = _by_quantity(_risk())
        assert any("20 m" in lim for lim in items["mndwi"].known_limitations)
        assert not any("20 m" in lim for lim in items["ndvi"].known_limitations)

    def test_cached_inputs_say_they_were_reused(self):
        items = _by_quantity(_risk())
        assert items["mndwi"].retrieval == "cache"
        assert any("previous retrieval" in lim for lim in items["mndwi"].known_limitations)

    def test_cached_provisional_rainfall_is_flagged_as_possibly_stale(self):
        rainfall = _by_quantity(_risk())["rainfall_monthly_mm"]
        assert any("not refreshed" in lim for lim in rainfall.known_limitations)

    def test_baseline_evidence_is_distinguishable_from_the_report_window(self):
        items = _by_quantity(_risk())
        assert items["ndvi_baseline"].period_start == date(2015, 6, 1)
        assert items["ndvi"].period_start == _START

    def test_climatology_window_is_the_thirty_years_before_the_computation_year(self):
        normal = _by_quantity(_risk())["rainfall_climatology_mm"]
        assert (normal.period_start, normal.period_end) == (date(1996, 1, 1), date(2025, 12, 31))


def _stress():
    return recharge_stress_evidence(
        rainfall_monthly=_monthly(47.0),
        rainfall_normals={m: 47.0 for m in range(1, 13)},
        ndvi_observations=_index_obs(),
        ndvi_monthly=_monthly(0.5),
        ndvi_baseline_observations=_index_obs(),
        ndvi_baseline=_monthly(0.5),
        surface_water_monthly=_monthly(3.0),
        surface_water_baseline=_monthly(3.0),
        start=_START,
        end=_END,
        baseline_start=date(2015, 6, 1),
        weights={factor: 1 / 3 for factor in RechargeStressFactor},
        computed_in_year=2026,
        resolution_flags=[],
        satellite_provider=_gee_satellite(),
        hydrology_provider=_gee_hydrology(),
    )


class TestRechargeStressLineage:
    def test_surface_water_lineage_states_the_sar_threshold_and_the_missing_terrain_check(self):
        sw = _by_quantity(_stress())["surface_water_percent"]
        assert str(hydro._SAR_VV_WATER_THRESHOLD_DB).rstrip("0").rstrip(".") in sw.temporal_aggregation
        assert any("no DEM is read" in lim for lim in sw.known_limitations)

    def test_weights_are_recorded_with_their_values(self):
        weights = _by_quantity(_stress())["recharge_stress_weights"]
        assert "rainfall_anomaly=0.333" in weights.known_limitations[0]

    @pytest.mark.parametrize("quantity", ["surface_water_percent", "surface_water_baseline", "ndvi", "ndvi_baseline"])
    def test_both_window_and_baseline_series_are_present(self, quantity):
        assert quantity in _by_quantity(_stress())
