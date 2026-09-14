"""Tests for decision sufficiency — pure, no database.

Two anchors:
- the production Shera assessment, which was reported as Moderate at 83%
  "confidence" and must now be insufficient for every tier, with reasons a
  credit officer can read;
- the brief's motivating case: identical evidence that is adequate for a
  small, reversible loan and inadequate for a larger one.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.enums import EvidenceValidation, RiskFactor
from app.services.risk.engine import RiskEngine
from app.services.risk.models import MonthlyValue, ObservationBundle, RiskEngineConfig
from app.services.sufficiency import (
    DEFAULT_POLICY,
    EvidenceFacts,
    StakesTier,
    SufficiencyPolicy,
    evaluate_sufficiency,
)

_WEIGHTS = {factor: 0.25 for factor in RiskFactor}
_CONFIG = RiskEngineConfig(weights=_WEIGHTS, floor_threshold=80.0, model_version="t", weights_version_id="t")


def _months(n: int, start_year: int = 2023) -> list[date]:
    return [date(start_year + (m // 12), (m % 12) + 1, 1) for m in range(n)]


def _facts(result_months: list[date], *, latest_optical: date | None = None, statuses=None, **overrides) -> EvidenceFacts:
    values = dict(
        window_last_period=result_months[-1],
        latest_optical_period=latest_optical if latest_optical is not None else result_months[-1],
        error_findings=0,
        warning_findings=0,
        input_validation_statuses=statuses if statuses is not None else [EvidenceValidation.UNVALIDATED] * 12,
        farm_area_ha=0.25,
    )
    values.update(overrides)
    return EvidenceFacts(**values)


def _varied_baseline(n_years: int = 8) -> list[MonthlyValue]:
    """Eight years in which each calendar month varies, so neither the
    percentile nor VCI is degenerate."""
    months = _months(12 * n_years, 2015)
    return [MonthlyValue(m, 0.3 + 0.05 * (i % 7)) for i, m in enumerate(months)]


def _healthy_bundle(stale_months: int = 0) -> tuple[ObservationBundle, list[date]]:
    window = _months(36)
    def series(value):
        return [MonthlyValue(m, value if i < len(window) - stale_months else None) for i, m in enumerate(window)]
    baseline = _varied_baseline() + [MonthlyValue(m, 0.45) for m in window]
    bundle = ObservationBundle(
        ndvi_monthly=series(0.45),
        mndwi_monthly=series(0.45),
        ndmi_monthly=series(0.45),
        rainfall_monthly=[MonthlyValue(m, 80.0) for m in window],
        rainfall_normal_by_month={i: 80.0 for i in range(1, 13)},
        jrc_water_occurrence_percent=5.0,
        ndvi_baseline=baseline,
        mndwi_baseline=baseline,
        ndmi_baseline=baseline,
    )
    return bundle, window


def _production_shera() -> tuple[ObservationBundle, list[date]]:
    window = _months(36)
    three_years = [MonthlyValue(m, 0.5) for m in window]
    bundle = ObservationBundle(
        ndvi_monthly=[MonthlyValue(m, 0.5) for m in window[:-1]] + [MonthlyValue(window[-1], None)],
        mndwi_monthly=[MonthlyValue(m, -0.4) for m in window],
        ndmi_monthly=[MonthlyValue(m, 0.3) for m in window],
        rainfall_monthly=[MonthlyValue(m, None) for m in window],
        rainfall_normal_by_month={},
        jrc_water_occurrence_percent=0.0,
        ndvi_baseline=three_years,
        mndwi_baseline=three_years,
        ndmi_baseline=three_years,
    )
    return bundle, window


def _verdicts(bundle, window, **fact_overrides):
    result = RiskEngine().compute(bundle, _CONFIG)
    latest = next((o.period_start for o in reversed(bundle.ndvi_monthly) if o.value is not None), None)
    sufficiency = evaluate_sufficiency(result, _facts(window, latest_optical=latest, **fact_overrides), DEFAULT_POLICY)
    return {v.tier: v for v in sufficiency.tiers}, sufficiency


class TestProductionAssessment:
    def test_it_is_not_sufficient_for_any_decision(self):
        verdicts, sufficiency = _verdicts(*_production_shera())
        assert not any(v.sufficient for v in verdicts.values())
        assert "not sufficient for a decision at any stakes tier" in sufficiency.statement

    def test_the_reasons_name_the_actual_evidence_gaps(self):
        """A credit officer should read why, not a code."""
        verdicts, _ = _verdicts(*_production_shera())
        statements = " ".join(i.statement for i in verdicts[StakesTier.LOW].inadequacies)
        assert "No overall risk score could be estimated" in statements
        assert "1 of 4 risk factors computed" in statements
        assert "3 year(s) of" in statements and "5 needed" in statements
        assert "no rainfall for the last three months" in statements


class TestSameEvidenceDifferentStakes:
    def test_stale_imagery_is_enough_for_a_small_loan_and_not_for_a_larger_one(self):
        """The brief's motivating case. The last four months of the window
        were lost to cloud: within the four months a reversible seasonal
        renewal allows, beyond the three a new limit does."""
        verdicts, sufficiency = _verdicts(*_healthy_bundle(stale_months=4))
        assert verdicts[StakesTier.LOW].sufficient
        assert not verdicts[StakesTier.MEDIUM].sufficient
        stale = [i for i in verdicts[StakesTier.MEDIUM].inadequacies if i.code == "stale_optical"]
        assert stale and "4 month(s) before the window ends" in stale[0].statement
        assert "sufficient for low-stakes decisions only" in sufficiency.statement

    def test_high_stakes_cannot_rest_on_unvalidated_satellite_evidence(self):
        verdicts, _ = _verdicts(*_healthy_bundle())
        high = verdicts[StakesTier.HIGH]
        assert not high.sufficient
        assert any(i.code == "no_validated_evidence" and "field visit" in i.statement for i in high.inadequacies)

    def test_a_cross_checked_input_removes_that_gap_and_nothing_else(self):
        statuses = [EvidenceValidation.UNVALIDATED] * 11 + [EvidenceValidation.CROSS_CHECKED]
        verdicts, _ = _verdicts(*_healthy_bundle(), statuses=statuses)
        assert not any(i.code == "no_validated_evidence" for i in verdicts[StakesTier.HIGH].inadequacies)


class TestIndividualRequirements:
    def test_validation_errors_block_every_tier(self):
        verdicts, _ = _verdicts(*_healthy_bundle(), error_findings=1)
        assert not any(v.sufficient for v in verdicts.values())

    def test_warnings_block_medium_but_not_low(self):
        verdicts, _ = _verdicts(*_healthy_bundle(), warning_findings=2)
        assert verdicts[StakesTier.LOW].sufficient
        assert any(i.code == "validation_warnings" for i in verdicts[StakesTier.MEDIUM].inadequacies)

    def test_no_optical_reading_at_all_is_stated(self):
        bundle, window = _healthy_bundle()
        result = RiskEngine().compute(bundle, _CONFIG)
        facts = EvidenceFacts(
            window_last_period=window[-1],
            latest_optical_period=None,
            error_findings=0,
            warning_findings=0,
            input_validation_statuses=[],
        )
        low = next(v for v in evaluate_sufficiency(result, facts, DEFAULT_POLICY).tiers if v.tier is StakesTier.LOW)
        assert any(i.code == "no_recent_optical" for i in low.inadequacies)


class TestHonesty:
    def test_every_verdict_says_the_policy_is_uncalibrated(self):
        _, sufficiency = _verdicts(*_healthy_bundle())
        assert sufficiency.calibration_status == "uncalibrated"
        assert "not agreed with a bank" in sufficiency.statement

    def test_a_small_farm_is_told_its_rainfall_is_regional(self):
        _, sufficiency = _verdicts(*_healthy_bundle())
        assert any(c.code == "rainfall_regional" and "0.25 ha" in c.statement for c in sufficiency.caveats)

    def test_sufficiency_refuses_to_run_without_model_confidence(self):
        from dataclasses import replace

        bundle, window = _healthy_bundle()
        result = replace(RiskEngine().compute(bundle, _CONFIG), model_confidence=None)
        with pytest.raises(ValueError):
            evaluate_sufficiency(result, _facts(window), DEFAULT_POLICY)


class TestPolicy:
    def test_the_default_policy_covers_every_tier(self):
        assert set(DEFAULT_POLICY.tiers) == set(StakesTier)

    def test_an_unknown_requirement_is_rejected_rather_than_ignored(self):
        """A typo in a stored policy must fail loudly, not silently drop a
        requirement and pass assessments it should block."""
        payload = DEFAULT_POLICY.model_dump(mode="json")
        payload["tiers"]["low"]["min_datacompleteness"] = 10
        with pytest.raises(ValidationError):
            SufficiencyPolicy.model_validate(payload)

    def test_stakes_rise_monotonically_through_the_tiers(self):
        low, medium, high = (DEFAULT_POLICY.requirement(t) for t in StakesTier)
        assert low.min_data_completeness <= medium.min_data_completeness <= high.min_data_completeness
        assert low.min_factors_computed <= medium.min_factors_computed <= high.min_factors_computed
