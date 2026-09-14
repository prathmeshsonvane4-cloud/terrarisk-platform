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


# Seasonal scorers rank a reading against the SAME CALENDAR MONTH across
# the baseline years, so a bundle needs enough years for each month to
# clear seasonal.MIN_BASELINE_SAMPLES. 96 months is 8 samples per
# calendar month, matching seasonal.BASELINE_YEARS.
BASELINE_MONTHS = 96


def _baseline(value: float) -> list[MonthlyValue]:
    """A flat baseline. Flat is deliberate for bundles under test that
    are not exercising the seasonal factors: every month shares one
    value, so a percentile lands at the midpoint and the factor stays
    neutral instead of injecting an unrelated signal."""
    return [MonthlyValue(m, value) for m in _months(BASELINE_MONTHS)]


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
        ndvi_baseline=_baseline(ndvi),
        mndwi_baseline=_baseline(mndwi),
        ndmi_baseline=_baseline(ndmi),
    )


class TestVegetationStability:
    def test_current_value_at_historical_peak_is_lowest_risk(self):
        """NDVI trending upward to a new high => this month is the
        greenest that calendar month has been across the 8 baseline years.

        Under the midpoint tie convention that is the 93.75th percentile
        ((7 strictly below + half of the 1 equal) / 8), so risk is 6.25 —
        not 0. A self-inclusive rank can never place a value above
        (n-1+0.5)/n, and pretending otherwise would claim the reading beat
        a history it is itself part of."""
        months = _months(BASELINE_MONTHS)
        rising = [MonthlyValue(m, 0.2 + (i * 0.01)) for i, m in enumerate(months)]
        bundle = ObservationBundle(
            ndvi_baseline=rising,
            ndvi_monthly=rising,
            mndwi_monthly=[MonthlyValue(m, 0.1) for m in months],
            ndmi_monthly=[MonthlyValue(m, 0.1) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config())
        veg = next(f for f in result.factors if f.factor == RiskFactor.VEGETATION_STABILITY)
        assert veg.score == pytest.approx(6.25)
        assert veg.band == RiskBand.LOW

    def test_current_value_at_historical_low_is_highest_risk(self):
        """NDVI trending downward to a new low => this month is the
        poorest that calendar month has been across the 8 baseline years.

        Mirror of the peak case: the 6.25th percentile ((0 strictly below
        + half of the 1 equal) / 8), so risk 93.75 — the highest a
        self-inclusive rank can produce, and symmetric with the peak,
        which the previous at-or-below convention was not."""
        months = _months(BASELINE_MONTHS)
        falling = [MonthlyValue(m, 0.8 - (i * 0.01)) for i, m in enumerate(months)]
        bundle = ObservationBundle(
            ndvi_baseline=falling,
            ndvi_monthly=falling,
            mndwi_monthly=[MonthlyValue(m, 0.1) for m in months],
            ndmi_monthly=[MonthlyValue(m, 0.1) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        result = RiskEngine().compute(bundle, _config())
        veg = next(f for f in result.factors if f.factor == RiskFactor.VEGETATION_STABILITY)
        assert veg.score == pytest.approx(93.75)
        assert veg.band == RiskBand.VERY_HIGH

    def test_insufficient_history_is_not_computed_and_says_why(self):
        """REPLACES a test that asserted a neutral 50 here. That 50 was
        averaged into the overall score as though measured; the only Service 1
        assessment in production was three-quarters made of it."""
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
        assert veg.score is None and veg.band is None and not veg.computed
        assert veg.sub_signals[0].missing_reason == "baseline_samples_below_minimum"

    def test_all_months_missing_leaves_factor_uncomputed_and_zero_completeness(self):
        """REPLACES a test that asserted a neutral 50 here."""
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
        assert veg.score is None
        assert veg.sub_signals[0].missing_reason == "no_current_reading"


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
        months = _months(BASELINE_MONTHS)
        # NDVI craters in the final month after years of healthy, stable
        # values — including every previous instance of that same calendar
        # month, so the collapse is a genuine seasonal anomaly rather than
        # an artefact of comparing across the seasonal cycle.
        collapsing = [MonthlyValue(m, 0.7) for m in months[:-1]] + [MonthlyValue(months[-1], 0.05)]
        bundle = ObservationBundle(
            ndvi_baseline=collapsing,
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

    def test_weighted_average_score_exposes_the_pre_floor_value_for_transparency(self):
        """M2B P9 Method tab: weighted_average_score must be the true
        pre-floor average, distinct from overall_score exactly when (and
        only when) the floor rule actually fired — the UI's sole signal
        for whether to explain the floor rule to the officer."""
        months = _months(BASELINE_MONTHS)
        collapsing = [MonthlyValue(m, 0.7) for m in months[:-1]] + [MonthlyValue(months[-1], 0.05)]
        bundle = ObservationBundle(
            ndvi_baseline=collapsing,
            ndvi_monthly=collapsing,
            mndwi_monthly=[MonthlyValue(m, 0.1) for m in months],
            ndmi_monthly=[MonthlyValue(m, 0.2) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        floored = RiskEngine().compute(bundle, _config(floor_threshold=80.0))
        assert floored.weighted_average_score < floored.overall_score  # the floor rule raised it

        unfloored = RiskEngine().compute(bundle, _config(floor_threshold=999.0))
        assert unfloored.weighted_average_score == unfloored.overall_score  # never triggered, so equal

    def test_weighted_average_score_equals_overall_score_when_floor_rule_never_fires(self):
        bundle = _uniform_bundle()
        result = RiskEngine().compute(bundle, _config(floor_threshold=80.0))
        assert result.weighted_average_score == result.overall_score


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


# =====================================================================
# Phase C — no invented scores; model confidence as its own field
# =====================================================================

from app.services.risk.confidence import percentile_risk_interval, wilson_interval  # noqa: E402


def _production_shera_bundle() -> ObservationBundle:
    """The only Service 1 assessment in production (26 Aug 2026), rebuilt
    from its stored inputs: a 0.25 ha plot whose seasonal baseline had been
    truncated to three years by a cache defect, and whose rainfall was null
    at CHIRPS scale. It was reported as Moderate (37.5) at 83% confidence.
    The one measured value was JRC occurrence 0.0."""
    months = _months(36)
    three_years = [MonthlyValue(m, 0.5) for m in months]
    return ObservationBundle(
        ndvi_monthly=[MonthlyValue(m, 0.5) for m in months[:-1]] + [MonthlyValue(months[-1], None)],
        mndwi_monthly=[MonthlyValue(m, -0.4) for m in months],
        ndmi_monthly=[MonthlyValue(m, 0.3) for m in months],
        rainfall_monthly=[MonthlyValue(m, None) for m in months],
        rainfall_normal_by_month={},
        jrc_water_occurrence_percent=0.0,
        ndvi_baseline=three_years,
        mndwi_baseline=three_years,
        ndmi_baseline=three_years,
    )


class TestNoInventedScores:
    def test_the_production_assessment_no_longer_produces_a_composite(self):
        """Previously Moderate 37.5 from (50 + 50 + 50 + 0) / 4. Re-averaging
        only what survived would give Low 0 from one number — equally
        unjustified. The honest answer is that no composite exists."""
        result = RiskEngine().compute(_production_shera_bundle(), _config())
        computed = [f.factor for f in result.factors if f.computed]
        assert computed == [RiskFactor.FLOOD_EXPOSURE]
        assert result.overall_score is None
        assert result.overall_band is None
        assert result.weighted_average_score is None
        assert result.model_confidence.overall_estimable is False
        assert "1 of 4 factors computed" in result.model_confidence.statement

    def test_data_completeness_stays_high_while_the_composite_is_unavailable(self):
        """The exact conflation Phase C removes: plenty of optical months, and
        almost nothing measurable from them."""
        result = RiskEngine().compute(_production_shera_bundle(), _config())
        assert result.confidence > 80.0
        assert result.overall_score is None

    def test_an_uncomputed_factor_is_excluded_from_the_average_not_scored_fifty(self):
        """Two computed factors at half the weight: the composite is their
        average alone."""
        months = _months()
        bundle = ObservationBundle(
            ndvi_monthly=[MonthlyValue(m, 0.5) for m in months],
            mndwi_monthly=[MonthlyValue(m, None) for m in months],
            ndmi_monthly=[MonthlyValue(m, None) for m in months],
            rainfall_monthly=[MonthlyValue(m, None) for m in months],
            rainfall_normal_by_month={},
            jrc_water_occurrence_percent=30.0,
            ndvi_baseline=_baseline(0.5),
        )
        result = RiskEngine().compute(bundle, _config(floor_threshold=999.0))
        by_factor = {f.factor: f for f in result.factors}
        # Water: no index reading, no rainfall. Drought: VCI undefined on a
        # flat baseline, no rainfall. Two of four remain, at exactly the
        # minimum weight share for a composite.
        assert not by_factor[RiskFactor.WATER_AVAILABILITY].computed
        assert not by_factor[RiskFactor.DROUGHT_RISK].computed
        expected = (by_factor[RiskFactor.VEGETATION_STABILITY].score + by_factor[RiskFactor.FLOOD_EXPOSURE].score) / 2
        assert result.overall_score == pytest.approx(expected)
        assert result.model_confidence.weight_coverage == pytest.approx(0.5)

    def test_a_factor_built_from_fewer_sub_signals_records_how_many(self):
        months = _months()
        bundle = ObservationBundle(
            ndvi_monthly=[MonthlyValue(m, 0.5) for m in months],
            mndwi_monthly=[MonthlyValue(m, None) for m in months],
            ndmi_monthly=[MonthlyValue(m, None) for m in months],
            rainfall_monthly=[MonthlyValue(m, 80.0) for m in months],
            rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
            jrc_water_occurrence_percent=0.0,
        )
        water = next(f for f in RiskEngine().compute(bundle, _config()).factors if f.factor == RiskFactor.WATER_AVAILABILITY)
        assert water.computed
        assert (water.raw_inputs["sub_signals_computed"], water.raw_inputs["sub_signals_total"]) == (1, 3)
        assert {s.name: s.missing_reason for s in water.sub_signals}["mndwi_percentile"] == "no_current_reading"

    def test_a_severe_computed_factor_still_triggers_the_floor(self):
        """Excluding uncomputed factors must not weaken the floor rule. Here
        the computed average is low (vegetation near its best, VCI at its
        top), but flood exposure — JRC alone, with rainfall unavailable — is
        severe, so the composite is still forced to at least High."""
        months = _months(BASELINE_MONTHS)
        rising = [MonthlyValue(m, 0.2 + (i * 0.01)) for i, m in enumerate(months)]
        bundle = ObservationBundle(
            ndvi_monthly=rising,
            ndvi_baseline=rising,
            mndwi_monthly=[MonthlyValue(m, None) for m in months],
            ndmi_monthly=[MonthlyValue(m, None) for m in months],
            rainfall_monthly=[MonthlyValue(m, None) for m in months],
            rainfall_normal_by_month={},
            jrc_water_occurrence_percent=95.0,
        )
        result = RiskEngine().compute(bundle, _config(floor_threshold=80.0))
        assert result.weighted_average_score < 50.0
        assert result.overall_band in (RiskBand.HIGH, RiskBand.VERY_HIGH)

    def test_the_model_version_marks_the_changed_semantics(self):
        assert RiskEngine().compute(_uniform_bundle(), _config()).model_version == "rule-engine-v2"


class TestModelConfidence:
    def test_wilson_interval_matches_the_closed_form_at_n_8(self):
        """p = 0.5, n = 8, z = 1.645: hand-computed 0.2486 to 0.7514."""
        low, high = wilson_interval(0.5, 8)
        assert low == pytest.approx(0.2486, abs=5e-4)
        assert high == pytest.approx(0.7514, abs=5e-4)

    def test_the_interval_narrows_as_the_baseline_lengthens(self):
        narrow = percentile_risk_interval(0.5, 30)
        wide = percentile_risk_interval(0.5, 8)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])

    def test_a_percentile_factor_carries_an_interval_and_vci_does_not(self):
        result = RiskEngine().compute(_uniform_bundle(), _config())
        by_factor = {f.factor: f for f in result.factors}
        assert by_factor[RiskFactor.VEGETATION_STABILITY].interval is not None
        assert by_factor[RiskFactor.DROUGHT_RISK].interval is None

    def test_overall_interval_is_labelled_partial_and_says_what_is_missing(self):
        """Drought and flood have no uncertainty model, so the overall
        interval can only be a lower bound — and must say so."""
        mc = RiskEngine().compute(_uniform_bundle(), _config()).model_confidence
        assert mc.overall_estimable
        assert mc.interval_coverage == "partial"
        low, high = mc.overall_interval
        assert low <= high
        assert "No uncertainty model for" in mc.statement
        assert "true uncertainty is wider" in mc.statement

    def test_the_interval_contains_the_point_estimate(self):
        result = RiskEngine().compute(_uniform_bundle(), _config(floor_threshold=999.0))
        low, high = result.model_confidence.overall_interval
        assert low <= result.overall_score <= high
