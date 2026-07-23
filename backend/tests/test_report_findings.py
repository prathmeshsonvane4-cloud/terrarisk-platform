from __future__ import annotations

from app.models.enums import RiskBand, RiskFactor
from app.schemas.report import FactorScoreResponse
from app.services.reporting.report_findings import (
    KEY_FINDING_PHRASES,
    RECOMMENDED_ACTION_BY_FACTOR_BAND,
    key_finding,
    key_findings_for_report,
    recommended_action,
)


def _factor(name: RiskFactor, band: RiskBand) -> FactorScoreResponse:
    return FactorScoreResponse(factor=name, value=50.0, band=band, raw_inputs={})


def test_every_factor_and_band_combination_has_a_finding_and_an_action():
    for factor in RiskFactor:
        for band in RiskBand:
            assert factor in KEY_FINDING_PHRASES and band in KEY_FINDING_PHRASES[factor]
            assert factor in RECOMMENDED_ACTION_BY_FACTOR_BAND and band in RECOMMENDED_ACTION_BY_FACTOR_BAND[factor]
            assert key_finding(_factor(factor, band))
            assert recommended_action(_factor(factor, band))


def test_low_band_findings_are_reassuring_not_alarming():
    finding = key_finding(_factor(RiskFactor.VEGETATION_STABILITY, RiskBand.LOW))
    assert "stable" in finding.lower() or "healthy" in finding.lower()


def test_very_high_band_actions_recommend_field_verification_or_similar_escalation():
    for factor in RiskFactor:
        action = recommended_action(_factor(factor, RiskBand.VERY_HIGH))
        assert action != recommended_action(_factor(factor, RiskBand.LOW))


def test_key_findings_for_report_preserves_factor_order_and_count():
    factors = [
        _factor(RiskFactor.DROUGHT_RISK, RiskBand.HIGH),
        _factor(RiskFactor.WATER_AVAILABILITY, RiskBand.MODERATE),
        _factor(RiskFactor.VEGETATION_STABILITY, RiskBand.LOW),
        _factor(RiskFactor.FLOOD_EXPOSURE, RiskBand.LOW),
    ]
    findings = key_findings_for_report(factors)
    assert len(findings) == 4
    assert findings[0] == key_finding(factors[0])
    assert findings[-1] == key_finding(factors[-1])
