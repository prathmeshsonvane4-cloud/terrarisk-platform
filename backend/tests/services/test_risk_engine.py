"""Unit tests for the pure Risk Engine. No database, no network, no Earth
Engine — every test constructs an ObservationBundle by hand and asserts on
RiskEngine.compute()'s output, per the Blueprint §07 contract."""

from datetime import date

import pytest

from app.models.enums import RiskBand, RiskFactor
from app.services.risk.engine import RiskEngine
from app.services.risk.models import MonthlyValue, ObservationBundle, RiskEngineConfig

EQUAL_WEIGHTS = {
    RiskFactor.VEGETATION_STABILITY: 0.25,
    RiskFactor.WATER_AVAILABILITY: 0.25,
    RiskFactor.DROUGHT_RISK: 0.25,
    RiskFactor.FLOOD_EXPOSURE: 0.25,
}


def _months(n: int = 36) -> list[date]:
    return [date(2023 + (m // 12), (m % 12) + 1, 1) for m in range(n)]


def _config(floor_threshold: float = 80.0) -> RiskEngineConfig:
    return RiskEngineConfig(
        weights=EQUAL_WEIGHTS,
        floor_threshold=floor_threshold,
        model_version="rule-engine-v1",
        weights_version_id="test-version",
    )


def _uniform_bundle(ndvi=0.6, mndwi=0.1, ndmi=0.2, rainfall=80.0, jrc=10.0) -> ObservationBundle:
    months = _months()
    return ObservationBundle(
        ndvi_monthly=[MonthlyValue(m, ndvi) for m in months],
        mndwi_monthly=[MonthlyValue(m, mndwi) for m in months],
        ndmi_monthly=[MonthlyValue(m, ndmi) for m in months],
        rainfall_monthly=[MonthlyValue(m, rainfall) for m in months],
        rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
        jrc_water_occurrence_percent=jrc,
    )


class TestVegetationStability:
    def test_current_value_at_historical_peak_is_lowest_risk(self):
        """NDVI trending upward to a new high => current value is the max
        of its own history => 100th percentile => risk should be 0."""
        months = _months()
        rising = [MonthlyValue(m, 0.2 + (i * 0.01)) for i, m in enumerate(months)]
        bundle = ObservationBundle(
            ndvi_monthly=rising,
            mndwi_monthly=[MonthlyValue(m, 0.1) for m in months],
            ndmi_monthly=[MonthlyValue(m, 0.1) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config())
        veg = next(f for f in result.factors if f.factor == RiskFactor.VEGETATION_STABILITY)
        assert veg.score == 0.0
        assert veg.band == RiskBand.LOW

    def test_current_value_at_historical_low_is_highest_risk(self):
        """NDVI trending downward to a new low => current value is the min
        of its own 36-month history. The percentile-rank formula counts a
        value against its own history inclusively (standard convention),
        so a strict minimum among 36 points lands at the 1/36th percentile
        (~2.78%), i.e. risk ~97.22 — not exactly 100, but still the
        highest possible risk band."""
        months = _months()
        falling = [MonthlyValue(m, 0.8 - (i * 0.01)) for i, m in enumerate(months)]
        bundle = ObservationBundle(
            ndvi_monthly=falling,
            mndwi_monthly=[MonthlyValue(m, 0.1) for m in months],
            ndmi_monthly=[MonthlyValue(m, 0.1) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config())
        veg = next(f for f in result.factors if f.factor == RiskFactor.VEGETATION_STABILITY)
        assert veg.score == pytest.approx(100.0 - (1 / 36 * 100))
        assert veg.band == RiskBand.VERY_HIGH

    def test_insufficient_history_falls_back_to_neutral_score(self):
        bundle = ObservationBundle(
            ndvi_monthly=[MonthlyValue(date(2026, 1, 1), 0.5)],
            mndwi_monthly=[],
            ndmi_monthly=[],
            rainfall_monthly=[],
            rainfall_normal_by_month={},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config())
        veg = next(f for f in result.factors if f.factor == RiskFactor.VEGETATION_STABILITY)
        assert veg.score == 50.0

    def test_all_months_missing_falls_back_to_neutral_and_zero_confidence(self):
        months = _months()
        bundle = ObservationBundle(
            ndvi_monthly=[MonthlyValue(m, None) for m in months],
            mndwi_monthly=[MonthlyValue(m, None) for m in months],
            ndmi_monthly=[MonthlyValue(m, None) for m in months],
            rainfall_monthly=[MonthlyValue(m, None) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config())
        assert result.confidence == 0.0
        veg = next(f for f in result.factors if f.factor == RiskFactor.VEGETATION_STABILITY)
        assert veg.score == 50.0


class TestDroughtRisk:
    def test_vci_undefined_when_no_historical_variation(self):
        """Uniform NDVI history => ndvi_max == ndvi_min => VCI is
        mathematically undefined; the engine must not divide by zero and
        must exclude it from the drought composite rather than crash."""
        result = RiskEngine().compute(_uniform_bundle(), _config())
        drought = next(f for f in result.factors if f.factor == RiskFactor.DROUGHT_RISK)
        assert drought.raw_inputs["vci"] is None
        assert drought.raw_inputs["vci_risk"] is None
        # Falls back to rainfall-anomaly-only, not a crash or NaN.
        assert 0.0 <= drought.score <= 100.0

    def test_below_normal_rainfall_increases_drought_risk(self):
        dry = _uniform_bundle(rainfall=20.0)  # 25% of the 80.0 normal
        wet = _uniform_bundle(rainfall=80.0)
        dry_result = RiskEngine().compute(dry, _config())
        wet_result = RiskEngine().compute(wet, _config())
        dry_drought = next(f for f in dry_result.factors if f.factor == RiskFactor.DROUGHT_RISK)
        wet_drought = next(f for f in wet_result.factors if f.factor == RiskFactor.DROUGHT_RISK)
        assert dry_drought.score > wet_drought.score


class TestFloodExposure:
    def test_above_normal_rainfall_increases_flood_risk(self):
        heavy = _uniform_bundle(rainfall=160.0)  # 2x the 80.0 normal
        normal = _uniform_bundle(rainfall=80.0)
        heavy_result = RiskEngine().compute(heavy, _config())
        normal_result = RiskEngine().compute(normal, _config())
        heavy_flood = next(f for f in heavy_result.factors if f.factor == RiskFactor.FLOOD_EXPOSURE)
        normal_flood = next(f for f in normal_result.factors if f.factor == RiskFactor.FLOOD_EXPOSURE)
        assert heavy_flood.score > normal_flood.score

    def test_below_normal_rainfall_does_not_produce_negative_flood_risk(self):
        """Flood risk from rainfall must clamp at 0, not go negative when
        rainfall is far below normal (that's a drought signal, not an
        'anti-flood' signal)."""
        bone_dry = _uniform_bundle(rainfall=0.0, jrc=0.0)
        result = RiskEngine().compute(bone_dry, _config())
        flood = next(f for f in result.factors if f.factor == RiskFactor.FLOOD_EXPOSURE)
        assert flood.raw_inputs["flood_rain_risk"] == 0.0

    def test_jrc_water_history_used_directly_as_risk_contribution(self):
        high_history = _uniform_bundle(jrc=90.0, rainfall=80.0)
        low_history = _uniform_bundle(jrc=0.0, rainfall=80.0)
        high_result = RiskEngine().compute(high_history, _config())
        low_result = RiskEngine().compute(low_history, _config())
        high_flood = next(f for f in high_result.factors if f.factor == RiskFactor.FLOOD_EXPOSURE)
        low_flood = next(f for f in low_result.factors if f.factor == RiskFactor.FLOOD_EXPOSURE)
        assert high_flood.score > low_flood.score


class TestFloorRule:
    def test_severe_single_factor_forces_overall_band_to_at_least_high(self):
        """A farm with catastrophic vegetation collapse (near-zero NDVI
        after a healthy history) should never be diluted to a low overall
        score just because its other three factors look fine."""
        months = _months()
        # NDVI craters at the very end after 35 months of healthy, stable values.
        collapsing = [MonthlyValue(m, 0.7) for m in months[:-1]] + [MonthlyValue(months[-1], 0.05)]
        bundle = ObservationBundle(
            ndvi_monthly=collapsing,
            mndwi_monthly=[MonthlyValue(m, 0.1) for m in months],
            ndmi_monthly=[MonthlyValue(m, 0.2) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config(floor_threshold=80.0))
        veg = next(f for f in result.factors if f.factor == RiskFactor.VEGETATION_STABILITY)
        assert veg.score >= 80.0  # confirms the scenario actually triggers the floor
        assert result.overall_band in (RiskBand.HIGH, RiskBand.VERY_HIGH)
        assert result.overall_score > 50.0

    def test_no_factor_reaching_threshold_uses_plain_weighted_average(self):
        bundle = _uniform_bundle()
        no_floor_result = RiskEngine().compute(bundle, _config(floor_threshold=999.0))
        result = RiskEngine().compute(bundle, _config(floor_threshold=80.0))
        assert result.overall_score == no_floor_result.overall_score


class TestDeterminism:
    def test_same_inputs_produce_identical_output(self):
        bundle = _uniform_bundle()
        config = _config()
        first = RiskEngine().compute(bundle, config)
        second = RiskEngine().compute(bundle, config)
        assert first == second


class TestConfidence:
    def test_full_data_coverage_is_full_confidence(self):
        result = RiskEngine().compute(_uniform_bundle(), _config())
        assert result.confidence == 100.0

    def test_partial_data_coverage_reduces_confidence(self):
        months = _months()
        sparse_ndvi = [MonthlyValue(m, 0.5 if i % 2 == 0 else None) for i, m in enumerate(months)]
        bundle = ObservationBundle(
            ndvi_monthly=sparse_ndvi,
            mndwi_monthly=[MonthlyValue(m, 0.1) for m in months],
            ndmi_monthly=[MonthlyValue(m, 0.2) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config())
        assert result.confidence < 100.0


class TestOverallScoreWeighting:
    def test_zero_weight_factor_does_not_influence_overall_score(self):
        # Terrible drought signal, but its weight is zeroed out.
        bundle = _uniform_bundle(rainfall=0.0)
        weights = {**EQUAL_WEIGHTS, RiskFactor.DROUGHT_RISK: 0.0}
        # Redistribute the removed weight so total_weight stays sane.
        weights[RiskFactor.VEGETATION_STABILITY] = 0.5
        config = RiskEngineConfig(
            weights=weights, floor_threshold=999.0, model_version="rule-engine-v1", weights_version_id="v"
        )
        result = RiskEngine().compute(bundle, config)
        drought = next(f for f in result.factors if f.factor == RiskFactor.DROUGHT_RISK)
        assert drought.score > 0  # the factor is still computed and reported...
        # ...it just shouldn't be reachable in the weighted sum at 0 weight.
        # Sanity: recompute manually excluding drought and compare.
        others = [f for f in result.factors if f.factor != RiskFactor.DROUGHT_RISK]
        expected = sum(f.score * weights[f.factor] for f in others) / sum(
            weights[f.factor] for f in others
        )
        assert result.overall_score == pytest.approx(expected)
