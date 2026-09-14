"""Pin recommendation.py to the dashboard's recommendation.ts — this file
asserts the SAME behavior `recommendation.test.ts` asserts, on the same
inputs (same twin-test discipline as test_report_text.py <-> report-text.test.ts).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.enums import RiskBand, RiskFactor
from app.schemas.report import (
    FactorScoreResponse,
    ReportEvidenceContext,
    ReportFarmContext,
    ReportMethodContext,
    ReportResponse,
    ReportSeries,
)
from app.services.reporting.recommendation import (
    RECOMMENDATION_CONFIDENCE_THRESHOLD,
    build_recommendation,
    field_verification_recommended,
    recommendation_why_bullets,
)


def _factor(name: RiskFactor, value: float, band: RiskBand, raw: dict | None = None) -> FactorScoreResponse:
    return FactorScoreResponse(factor=name, value=value, band=band, raw_inputs=raw or {})


def _report(**overrides) -> ReportResponse:
    defaults = dict(
        id=uuid4(),
        farm_id=uuid4(),
        farm_area_ha=2.5,
        village_id=uuid4(),
        overall_score=62,
        overall_band=RiskBand.HIGH,
        confidence=90,
        model_version="rule-engine-v1",
        computed_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        factors=[
            _factor(RiskFactor.VEGETATION_STABILITY, 30, RiskBand.LOW),
            _factor(RiskFactor.WATER_AVAILABILITY, 55, RiskBand.MODERATE),
            _factor(RiskFactor.DROUGHT_RISK, 62, RiskBand.HIGH, {"vci": 41, "rainfall_ratio_to_normal": 0.87}),
            _factor(
                RiskFactor.FLOOD_EXPOSURE,
                88,
                RiskBand.VERY_HIGH,
                {"jrc_water_occurrence_percent": 40, "rainfall_ratio_to_normal": 0.87},
            ),
        ],
        farm=ReportFarmContext(
            geometry={"type": "Polygon", "coordinates": []},
            village_name="Killari",
            taluka_name="Ausa",
            district_name="Latur",
            officer_name="Test Officer",
        ),
        series=ReportSeries(ndvi=[], mndwi=[], ndmi=[], rainfall=[]),
        evidence=ReportEvidenceContext(observation_window_start=None, observation_window_end=None, expected_months=None),
        method=ReportMethodContext(
            weights_version_id=uuid4(),
            weights={},
            weights_effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            floor_threshold=80.0,
            weighted_average_score=62.0,
        ),
    )
    defaults.update(overrides)
    return ReportResponse(**defaults)


def test_reuses_the_pinned_narrative_as_the_summary_never_a_second_description():
    rec = build_recommendation(_report())
    assert "high overall climate risk (score 62/100)" in rec.summary


def test_lists_only_high_and_very_high_factors_as_primary_drivers_worst_first():
    rec = build_recommendation(_report())
    assert [d.factor for d in rec.primary_drivers] == ["flood_exposure", "drought_risk"]
    assert rec.primary_drivers[0].value == 88


def test_returns_an_empty_driver_list_when_nothing_scored_high_or_very_high_never_padded():
    all_moderate = _report(
        factors=[
            _factor(RiskFactor.VEGETATION_STABILITY, 30, RiskBand.LOW),
            _factor(RiskFactor.WATER_AVAILABILITY, 40, RiskBand.MODERATE),
            _factor(RiskFactor.DROUGHT_RISK, 45, RiskBand.MODERATE),
            _factor(RiskFactor.FLOOD_EXPOSURE, 20, RiskBand.LOW),
        ]
    )
    assert build_recommendation(all_moderate).primary_drivers == []


def test_maps_each_band_to_its_fixed_deterministic_action_posture():
    assert "Standard appraisal. No climate-driven escalation" in build_recommendation(
        _report(overall_band=RiskBand.LOW, confidence=95)
    ).action
    assert "Standard appraisal. Note the leading risk factor" in build_recommendation(
        _report(overall_band=RiskBand.MODERATE, confidence=95)
    ).action
    assert "Escalate to branch-manager review" in build_recommendation(
        _report(overall_band=RiskBand.HIGH, confidence=95)
    ).action
    assert "Refer to branch manager" in build_recommendation(
        _report(overall_band=RiskBand.VERY_HIGH, confidence=95)
    ).action


def test_adds_the_indicative_only_qualifier_only_below_the_confidence_threshold():
    confident = build_recommendation(_report(confidence=RECOMMENDATION_CONFIDENCE_THRESHOLD))
    assert confident.is_indicative_only is False
    assert "Indicative only" not in confident.action

    sparse = build_recommendation(_report(confidence=RECOMMENDATION_CONFIDENCE_THRESHOLD - 1))
    assert sparse.is_indicative_only is True
    assert "Indicative only — limited satellite data available (data completeness 69%)" in sparse.action


def test_never_invents_advice_beyond_the_fixed_template_action_is_always_one_of_the_four_postures():
    rec = build_recommendation(_report(overall_band=RiskBand.VERY_HIGH, confidence=50))
    assert "Refer to branch manager. Recommend independent field verification" in rec.action


def test_field_verification_recommended_true_for_very_high_band():
    report = _report(overall_band=RiskBand.VERY_HIGH, confidence=95)
    rec = build_recommendation(report)
    assert field_verification_recommended(report, rec) is True


def test_field_verification_recommended_true_when_indicative_only_even_at_low_band():
    report = _report(overall_band=RiskBand.LOW, confidence=RECOMMENDATION_CONFIDENCE_THRESHOLD - 1)
    rec = build_recommendation(report)
    assert field_verification_recommended(report, rec) is True


def test_field_verification_not_recommended_for_standard_moderate_appraisal():
    report = _report(overall_band=RiskBand.MODERATE, confidence=95)
    rec = build_recommendation(report)
    assert field_verification_recommended(report, rec) is False


def test_why_bullets_capped_at_five_and_always_end_with_the_standing_disclaimer():
    report = _report(confidence=50)  # indicative-only, adds the caveat bullet
    rec = build_recommendation(report)
    bullets = recommendation_why_bullets(report, rec)
    assert len(bullets) <= 5
    assert bullets[-1] == "Decision support only — the credit decision remains with the bank."
    assert any("Data completeness is 50%" in b for b in bullets)


def test_why_bullets_never_empty_even_with_no_primary_drivers():
    report = _report(
        overall_band=RiskBand.LOW,
        confidence=95,
        factors=[
            _factor(RiskFactor.VEGETATION_STABILITY, 10, RiskBand.LOW),
            _factor(RiskFactor.WATER_AVAILABILITY, 15, RiskBand.LOW),
            _factor(RiskFactor.DROUGHT_RISK, 5, RiskBand.LOW),
            _factor(RiskFactor.FLOOD_EXPOSURE, 0, RiskBand.LOW),
        ],
    )
    rec = build_recommendation(report)
    bullets = recommendation_why_bullets(report, rec)
    assert "No factor scored High or Very High risk." in bullets
    assert bullets[-1] == "Decision support only — the credit decision remains with the bank."
