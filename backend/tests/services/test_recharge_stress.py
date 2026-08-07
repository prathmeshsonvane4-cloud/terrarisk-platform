"""Unit tests for RechargeStressEngine (ticket M3-001). No database, no
network, no Earth Engine — every test constructs a
RechargeStressBundle/RechargeStressConfig by hand, mirroring
test_risk_engine.py/test_water_balance_engine.py's exact style.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import BaselineWindow, StressBand
from app.services.hydrology import recharge_stress as recharge_stress_module
from app.services.hydrology.recharge_stress import (
    RechargeStressBundle,
    RechargeStressConfig,
    RechargeStressEngine,
    RechargeStressFactor,
)
from app.services.risk.models import MonthlyValue


def _months(n: int) -> list[date]:
    return [date(2023 + (m // 12), (m % 12) + 1, 1) for m in range(n)]


def _series(values: list[float | None]) -> list[MonthlyValue]:
    dates = _months(len(values))
    return [MonthlyValue(period_start=d, value=v) for d, v in zip(dates, values, strict=True)]


def _config(
    weights: dict[RechargeStressFactor, float] | None = None,
    weights_version_id: str = "cw-1",
) -> RechargeStressConfig:
    default_weights = {
        RechargeStressFactor.RAINFALL_ANOMALY: 1 / 3,
        RechargeStressFactor.VEGETATION_CONDITION: 1 / 3,
        RechargeStressFactor.SURFACE_WATER_TREND: 1 / 3,
    }
    return RechargeStressConfig(weights=weights if weights is not None else default_weights, weights_version_id=weights_version_id)


def _bundle(
    rainfall_monthly: list[MonthlyValue] | None = None,
    rainfall_normal_by_month: dict[int, float] | None = None,
    ndvi_monthly: list[MonthlyValue] | None = None,
    surface_water_monthly: list[MonthlyValue] | None = None,
    baseline_window: BaselineWindow = BaselineWindow.CLIMATOLOGY_30YR,
) -> RechargeStressBundle:
    months = _months(3)
    return RechargeStressBundle(
        rainfall_monthly=rainfall_monthly if rainfall_monthly is not None else [MonthlyValue(m, 80.0) for m in months],
        rainfall_normal_by_month=rainfall_normal_by_month if rainfall_normal_by_month is not None else {m: 80.0 for m in range(1, 13)},
        ndvi_monthly=ndvi_monthly if ndvi_monthly is not None else _series([0.3, 0.5, 0.7]),
        surface_water_monthly=surface_water_monthly if surface_water_monthly is not None else _series([5.0, 10.0, 15.0]),
        baseline_window=baseline_window,
    )


class TestConstruction:
    def test_engine_constructs_with_no_arguments(self):
        engine = RechargeStressEngine()
        assert engine is not None

    def test_a_single_engine_instance_is_reusable_across_calls(self):
        engine = RechargeStressEngine()
        bundle, config = _bundle(), _config()
        first = engine.compute(bundle, config)
        second = engine.compute(bundle, config)
        assert first == second


class TestBundleValidation:
    def test_none_bundle_is_rejected(self):
        with pytest.raises(ValueError, match="RechargeStressBundle is required"):
            RechargeStressEngine().compute(None, _config())

    def test_non_list_rainfall_monthly_is_rejected(self):
        bundle = _bundle()
        object.__setattr__(bundle, "rainfall_monthly", "not-a-list")
        with pytest.raises(TypeError, match="rainfall_monthly"):
            RechargeStressEngine().compute(bundle, _config())

    def test_non_dict_rainfall_normal_by_month_is_rejected(self):
        bundle = _bundle()
        object.__setattr__(bundle, "rainfall_normal_by_month", "not-a-dict")
        with pytest.raises(TypeError, match="rainfall_normal_by_month"):
            RechargeStressEngine().compute(bundle, _config())

    def test_non_list_ndvi_monthly_is_rejected(self):
        bundle = _bundle()
        object.__setattr__(bundle, "ndvi_monthly", "not-a-list")
        with pytest.raises(TypeError, match="ndvi_monthly"):
            RechargeStressEngine().compute(bundle, _config())

    def test_non_list_surface_water_monthly_is_rejected(self):
        bundle = _bundle()
        object.__setattr__(bundle, "surface_water_monthly", "not-a-list")
        with pytest.raises(TypeError, match="surface_water_monthly"):
            RechargeStressEngine().compute(bundle, _config())


class TestConfigValidation:
    def test_none_config_is_rejected(self):
        with pytest.raises(ValueError, match="RechargeStressConfig is required"):
            RechargeStressEngine().compute(_bundle(), None)

    def test_non_dict_weights_is_rejected(self):
        config = _config()
        object.__setattr__(config, "weights", "not-a-dict")
        with pytest.raises(TypeError, match="weights"):
            RechargeStressEngine().compute(_bundle(), config)

    def test_empty_weights_version_id_is_rejected(self):
        with pytest.raises(ValueError, match="weights_version_id"):
            RechargeStressEngine().compute(_bundle(), _config(weights_version_id=""))


class TestRainfallAnomalyScoring:
    def test_ratio_exactly_normal_is_neutral_stress(self):
        stress, ratio = recharge_stress_module._score_rainfall_anomaly(
            _series([80.0, 80.0, 80.0]), {m: 80.0 for m in range(1, 13)}
        )
        assert ratio == pytest.approx(1.0)
        assert stress == pytest.approx(50.0)

    def test_zero_rainfall_is_maximum_stress(self):
        stress, ratio = recharge_stress_module._score_rainfall_anomaly(
            _series([0.0, 0.0, 0.0]), {m: 80.0 for m in range(1, 13)}
        )
        assert ratio == pytest.approx(0.0)
        assert stress == pytest.approx(100.0)

    def test_double_normal_rainfall_is_zero_stress_clamped(self):
        stress, ratio = recharge_stress_module._score_rainfall_anomaly(
            _series([160.0, 160.0, 160.0]), {m: 80.0 for m in range(1, 13)}
        )
        assert ratio == pytest.approx(2.0)
        assert stress == 0.0

    def test_triple_normal_rainfall_is_still_clamped_to_zero(self):
        stress, _ratio = recharge_stress_module._score_rainfall_anomaly(
            _series([240.0, 240.0, 240.0]), {m: 80.0 for m in range(1, 13)}
        )
        assert stress == 0.0

    def test_missing_rainfall_data_falls_back_to_neutral(self):
        stress, ratio = recharge_stress_module._score_rainfall_anomaly(_series([None, None, None]), {m: 80.0 for m in range(1, 13)})
        assert ratio is None
        assert stress == 50.0

    def test_empty_normal_by_month_falls_back_to_neutral(self):
        stress, ratio = recharge_stress_module._score_rainfall_anomaly(_series([80.0, 80.0, 80.0]), {})
        assert ratio is None
        assert stress == 50.0


def _same_month_across_years(values: list[float | None], month: int = 7) -> list[MonthlyValue]:
    """One observation per YEAR for a single calendar month, oldest first.

    VCI ranks a reading against the same calendar month in other years,
    so a valid fixture has to vary the year and hold the month fixed.
    These tests previously used three CONSECUTIVE months, which only
    passed because the implementation was comparing across the seasonal
    cycle — the exact defect app/services/risk/seasonal.py now documents.
    """
    return [MonthlyValue(period_start=date(2023 + i, month, 1), value=v) for i, v in enumerate(values)]


class TestVegetationConditionScoring:
    def test_current_at_historical_maximum_is_zero_stress(self):
        """VCI=100 (this July is the greenest July on record) -> stress 0."""
        julys = _same_month_across_years([0.2, 0.3, 0.5, 0.6, 0.8])
        stress, vci = recharge_stress_module._score_vegetation_condition(julys, julys)
        assert vci == pytest.approx(100.0)
        assert stress == pytest.approx(0.0)

    def test_current_at_historical_minimum_is_maximum_stress(self):
        julys = _same_month_across_years([0.8, 0.6, 0.5, 0.3, 0.2])
        stress, vci = recharge_stress_module._score_vegetation_condition(julys, julys)
        assert vci == pytest.approx(0.0)
        assert stress == pytest.approx(100.0)

    def test_current_at_the_midpoint_is_neutral_stress(self):
        julys = _same_month_across_years([0.2, 0.8, 0.3, 0.6, 0.5])
        stress, vci = recharge_stress_module._score_vegetation_condition(julys, julys)
        assert vci == pytest.approx(50.0)
        assert stress == pytest.approx(50.0)

    def test_seasonal_cycle_alone_does_not_register_as_stress(self):
        """The regression that motivated the shared implementation.

        A dry pre-monsoon month (NDVI 0.2) following green monsoon months
        (0.8) is an ordinary seasonal trough, not vegetation stress. The
        old all-months-mixed comparison scored it VCI=0 / stress=100 —
        "severe stress" for a perfectly normal year, purely because of
        WHEN the report was run. With no other April on record it is now
        correctly reported as not computable, falling back to neutral
        rather than inventing an alarming number.
        """
        seasonal = [
            MonthlyValue(period_start=date(2024, 7, 1), value=0.8),
            MonthlyValue(period_start=date(2024, 8, 1), value=0.8),
            MonthlyValue(period_start=date(2025, 4, 1), value=0.2),
        ]
        stress, vci = recharge_stress_module._score_vegetation_condition(seasonal, seasonal)
        assert vci is None
        assert stress == 50.0

    def test_no_valid_observations_falls_back_to_neutral(self):
        empty = _series([None, None, None])
        stress, vci = recharge_stress_module._score_vegetation_condition(empty, empty)
        assert vci is None
        assert stress == 50.0

    def test_degenerate_flat_history_falls_back_to_neutral(self):
        """max == min: VCI's denominator would be zero — must not raise
        ZeroDivisionError, falls back to neutral instead."""
        flat = _same_month_across_years([0.5, 0.5, 0.5, 0.5, 0.5])
        stress, vci = recharge_stress_module._score_vegetation_condition(flat, flat)
        assert vci is None
        assert stress == 50.0


class TestSurfaceWaterTrendScoring:
    """Percentile rank now uses the MIDPOINT convention for ties (values
    strictly below, plus half the values exactly equal) and ranks against
    the same calendar month across years.

    The previous at-or-below convention counted the current reading
    against itself, so a value could never rank below 1/n and the maximum
    always scored exactly 100. Midpoint ranks are symmetric — the lowest
    of five Julys scores 10, the median 50, the highest 90 — and, more
    importantly, a saturated index that reports the same extent for
    several months lands at its own centre instead of at an extreme.
    """

    def test_current_at_historical_maximum_is_lowest_stress(self):
        julys = _same_month_across_years([10.0, 20.0, 30.0, 40.0, 50.0])
        stress, trend = recharge_stress_module._score_surface_water_trend(julys, julys)
        assert trend == pytest.approx(90.0)
        assert stress == pytest.approx(10.0)

    def test_current_at_historical_minimum_is_high_stress(self):
        julys = _same_month_across_years([50.0, 40.0, 30.0, 20.0, 10.0])
        stress, trend = recharge_stress_module._score_surface_water_trend(julys, julys)
        assert trend == pytest.approx(10.0)
        assert stress == pytest.approx(90.0)

    def test_current_at_the_median_produces_the_correct_percentile(self):
        julys = _same_month_across_years([10.0, 20.0, 50.0, 40.0, 30.0])
        stress, trend = recharge_stress_module._score_surface_water_trend(julys, julys)
        assert trend == pytest.approx(50.0)
        assert stress == pytest.approx(50.0)

    def test_a_saturated_index_ranks_at_its_centre_not_at_an_extreme(self):
        """A catchment with no surface water reports 0% every July. Neither
        "lowest on record" nor "highest on record" describes that fairly;
        the midpoint convention puts it at 50."""
        julys = _same_month_across_years([0.0, 0.0, 0.0, 0.0, 0.0])
        stress, trend = recharge_stress_module._score_surface_water_trend(julys, julys)
        assert trend == pytest.approx(50.0)
        assert stress == pytest.approx(50.0)

    def test_no_valid_observations_falls_back_to_neutral(self):
        empty = _series([None, None, None])
        stress, trend = recharge_stress_module._score_surface_water_trend(empty, empty)
        assert trend is None
        assert stress == 50.0

    def test_too_few_baseline_samples_falls_back_to_neutral(self):
        """Below MIN_BASELINE_SAMPLES the rank carries no information, so
        the factor reports not-computable rather than a number derived
        from a handful of points."""
        julys = _same_month_across_years([10.0, 20.0])
        stress, trend = recharge_stress_module._score_surface_water_trend(julys, julys)
        assert trend is None
        assert stress == 50.0


class TestWeightedComposite:
    def test_weighted_average_matches_hand_computed_value(self, monkeypatch):
        """rainfall_stress=80 (w=0.5), vegetation_stress=40 (w=0.3),
        surface_water_stress=60 (w=0.2) -> 80*0.5+40*0.3+60*0.2 = 64.0."""
        monkeypatch.setattr(recharge_stress_module, "_score_rainfall_anomaly", lambda *a: (80.0, 0.5))
        monkeypatch.setattr(recharge_stress_module, "_score_vegetation_condition", lambda *a: (40.0, 60.0))
        monkeypatch.setattr(recharge_stress_module, "_score_surface_water_trend", lambda *a: (60.0, 70.0))

        weights = {
            RechargeStressFactor.RAINFALL_ANOMALY: 0.5,
            RechargeStressFactor.VEGETATION_CONDITION: 0.3,
            RechargeStressFactor.SURFACE_WATER_TREND: 0.2,
        }
        result = RechargeStressEngine().compute(_bundle(), _config(weights=weights))

        assert result.stress_score == pytest.approx(64.0)
        assert result.stress_band == StressBand.HIGH

    def test_zero_total_weight_falls_back_to_neutral_score(self):
        zero_weights = {
            RechargeStressFactor.RAINFALL_ANOMALY: 0.0,
            RechargeStressFactor.VEGETATION_CONDITION: 0.0,
            RechargeStressFactor.SURFACE_WATER_TREND: 0.0,
        }
        result = RechargeStressEngine().compute(_bundle(), _config(weights=zero_weights))
        assert result.stress_score == 50.0

    def test_missing_weight_for_a_factor_defaults_to_zero_contribution(self, monkeypatch):
        """A factor absent from the weights dict contributes 0 weight —
        mirrors RiskEngine.compute()'s config.weights.get(f.factor, 0.0)."""
        monkeypatch.setattr(recharge_stress_module, "_score_rainfall_anomaly", lambda *a: (100.0, 0.0))
        monkeypatch.setattr(recharge_stress_module, "_score_vegetation_condition", lambda *a: (0.0, 100.0))
        monkeypatch.setattr(recharge_stress_module, "_score_surface_water_trend", lambda *a: (0.0, 100.0))

        weights = {RechargeStressFactor.VEGETATION_CONDITION: 1.0}  # rainfall/surface-water omitted
        result = RechargeStressEngine().compute(_bundle(), _config(weights=weights))

        assert result.stress_score == pytest.approx(0.0)  # only vegetation_stress=0.0 counted


class TestStressBandThresholds:
    """Table-driven test over every named band boundary — mirrors
    test_water_balance_engine.py's TestBandForStorageChange discipline."""

    @pytest.mark.parametrize(
        "stress_score,expected_band",
        [
            (0.0, StressBand.LOW),
            (25.0, StressBand.LOW),  # inclusive upper bound
            (25.01, StressBand.MODERATE),
            (50.0, StressBand.MODERATE),  # inclusive upper bound
            (50.01, StressBand.HIGH),
            (75.0, StressBand.HIGH),  # inclusive upper bound
            (75.01, StressBand.VERY_HIGH),
            (100.0, StressBand.VERY_HIGH),
        ],
    )
    def test_boundary_values(self, stress_score, expected_band):
        assert recharge_stress_module._band_for_stress(stress_score) == expected_band


class TestConfidence:
    def test_confidence_reflects_only_the_ndvi_series(self):
        """Mirrors RiskEngine._compute_confidence()'s exact reasoning: NDVI
        is cloud-limited; rainfall (CHIRPS) and surface water (SAR-primary,
        all-weather) are not, and are excluded."""
        bundle = _bundle(
            ndvi_monthly=_series([0.3, 0.5, None]),  # 2/3 valid
            rainfall_monthly=_series([None, None, None]),  # fully missing, irrelevant
            surface_water_monthly=_series([None, None, None]),  # fully missing, irrelevant
        )
        result = RechargeStressEngine().compute(bundle, _config())
        assert result.confidence == pytest.approx((2 / 3) * 100.0)

    def test_fully_complete_ndvi_series_is_100_percent(self):
        bundle = _bundle(ndvi_monthly=_series([0.3, 0.5, 0.7]))
        result = RechargeStressEngine().compute(bundle, _config())
        assert result.confidence == pytest.approx(100.0)

    def test_fully_missing_ndvi_series_is_zero_percent(self):
        bundle = _bundle(ndvi_monthly=_series([None, None, None]))
        result = RechargeStressEngine().compute(bundle, _config())
        assert result.confidence == 0.0


class TestMissingData:
    def test_all_series_missing_does_not_raise_and_falls_back_to_neutral(self):
        bundle = _bundle(
            rainfall_monthly=_series([None, None, None]),
            ndvi_monthly=_series([None, None, None]),
            surface_water_monthly=_series([None, None, None]),
        )
        result = RechargeStressEngine().compute(bundle, _config())

        assert result.rainfall_anomaly_ratio is None
        assert result.vci is None
        assert result.surface_water_trend is None
        # pytest.approx, not ==: the default _config() fixture uses 1/3
        # weights per factor, and 50*(1/3+1/3+1/3) is not exactly 50.0 in
        # binary floating point — a fixture-precision fact, not an engine
        # bug (mirrors why test_water_balance_engine.py uses approx for
        # any arithmetic that isn't provably exact).
        assert result.stress_score == pytest.approx(50.0)
        assert result.stress_band == StressBand.MODERATE
        assert result.confidence == 0.0

    def test_empty_series_are_valid_input_not_an_error(self):
        bundle = _bundle(rainfall_monthly=[], ndvi_monthly=[], surface_water_monthly=[])
        result = RechargeStressEngine().compute(bundle, _config())
        assert result.stress_score == pytest.approx(50.0)


class TestBaselineWindow:
    def test_baseline_window_is_copied_through_unchanged(self):
        bundle = _bundle(baseline_window=BaselineWindow.CLIMATOLOGY_30YR)
        result = RechargeStressEngine().compute(bundle, _config())
        assert result.baseline_window == BaselineWindow.CLIMATOLOGY_30YR

    def test_trailing_3yr_baseline_window_is_also_supported(self):
        """Both BaselineWindow members are supported — this engine does
        not restrict which one it accepts, it only records whichever the
        caller provides."""
        bundle = _bundle(baseline_window=BaselineWindow.TRAILING_3YR)
        result = RechargeStressEngine().compute(bundle, _config())
        assert result.baseline_window == BaselineWindow.TRAILING_3YR


class TestModelVersion:
    def test_engine_has_a_model_version_class_constant(self):
        assert RechargeStressEngine.MODEL_VERSION == "recharge-stress-engine-v1"

    def test_result_is_stamped_with_the_engines_own_model_version(self):
        result = RechargeStressEngine().compute(_bundle(), _config())
        assert result.model_version == RechargeStressEngine.MODEL_VERSION


class TestWeightsVersionIdPassthrough:
    def test_weights_version_id_is_copied_through_from_config(self):
        result = RechargeStressEngine().compute(_bundle(), _config(weights_version_id="cw-42"))
        assert result.weights_version_id == "cw-42"


class TestDeterminism:
    def test_same_inputs_always_produce_the_same_outputs(self):
        bundle = _bundle(
            rainfall_monthly=_series([73.4, 12.9, 45.0]),
            ndvi_monthly=_series([0.31, 0.42, 0.55]),
            surface_water_monthly=_series([4.1, 6.3, 5.9]),
        )
        config = _config()
        engine = RechargeStressEngine()

        results = [engine.compute(bundle, config) for _ in range(5)]

        assert all(r == results[0] for r in results)
