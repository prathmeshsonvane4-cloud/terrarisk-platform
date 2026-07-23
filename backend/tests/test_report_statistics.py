from __future__ import annotations

from datetime import date

from app.models.enums import RiskBand
from app.schemas.report import ObservationPoint
from app.services.reporting.report_statistics import (
    assessment_quality_label,
    historical_stats,
    monitoring_cadence,
    trend,
)


def _points(values: list[float]) -> list[ObservationPoint]:
    return [ObservationPoint(period_start=date(2024, (i % 12) + 1, 1), value=v) for i, v in enumerate(values)]


class TestHistoricalStats:
    def test_no_observations_returns_all_none_not_zero(self):
        stats = historical_stats([])
        assert stats.current is None
        assert stats.median is None
        assert stats.minimum is None
        assert stats.maximum is None
        assert stats.percentile is None
        assert stats.months_of_history == 0

    def test_current_is_the_most_recent_point_not_the_max(self):
        stats = historical_stats(_points([0.1, 0.5, 0.2]))
        assert stats.current == 0.2

    def test_median_min_max_are_real_statistics_over_the_real_series(self):
        stats = historical_stats(_points([0.1, 0.2, 0.3, 0.4, 0.5]))
        assert stats.median == 0.3
        assert stats.minimum == 0.1
        assert stats.maximum == 0.5
        assert stats.months_of_history == 5

    def test_percentile_rank_matches_engine_convention_current_included_in_its_own_history(self):
        # 5 values, current (last) is the maximum -> at-or-below = all 5 -> 100%.
        stats = historical_stats(_points([0.1, 0.2, 0.3, 0.4, 0.5]))
        assert stats.percentile == 100.0


class TestTrend:
    def test_no_previous_assessment_is_honestly_unavailable_not_a_fabricated_baseline(self):
        result = trend(current=50.0, previous=None)
        assert result.available is False
        assert result.delta is None
        assert result.direction == "unavailable"

    def test_higher_current_score_is_direction_up(self):
        result = trend(current=60.0, previous=40.0)
        assert result.available is True
        assert result.delta == 20.0
        assert result.direction == "up"

    def test_lower_current_score_is_direction_down(self):
        result = trend(current=30.0, previous=50.0)
        assert result.direction == "down"
        assert result.delta == -20.0

    def test_near_identical_scores_are_flat_not_noisy_up_down(self):
        result = trend(current=50.005, previous=50.0)
        assert result.direction == "flat"


class TestAssessmentQualityLabel:
    def test_buckets_match_documented_thresholds(self):
        assert assessment_quality_label(95) == "Excellent"
        assert assessment_quality_label(90) == "Excellent"
        assert assessment_quality_label(89.9) == "Good"
        assert assessment_quality_label(70) == "Good"
        assert assessment_quality_label(69.9) == "Fair"
        assert assessment_quality_label(50) == "Fair"
        assert assessment_quality_label(49.9) == "Limited"
        assert assessment_quality_label(0) == "Limited"


class TestMonitoringCadence:
    def test_low_band_high_confidence_is_annual(self):
        assert monitoring_cadence(RiskBand.LOW, 95, confidence_threshold=70) == "Annual reassessment"

    def test_very_high_band_is_immediate_verification(self):
        assert "Immediate field verification" in monitoring_cadence(RiskBand.VERY_HIGH, 95, confidence_threshold=70)

    def test_low_confidence_overrides_a_favorable_band(self):
        # Low risk band, but confidence below threshold -> treated like very_high cadence.
        result = monitoring_cadence(RiskBand.LOW, 50, confidence_threshold=70)
        assert result == monitoring_cadence(RiskBand.VERY_HIGH, 95, confidence_threshold=70)
