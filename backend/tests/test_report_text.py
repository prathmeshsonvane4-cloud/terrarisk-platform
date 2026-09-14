"""Pin the PDF's prose templates (report_text.py) to the dashboard's
(`drivers.ts` / `narrative.ts`) — this file asserts the IDENTICAL strings
the frontend's `report-text.test.ts` asserts, on the same inputs. If one
side's template changes, the other side's copy of these tests fails and
tells you to mirror the change (Blueprint §08: dashboard and PDF must
never disagree).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
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
from app.services.reporting.report_text import factor_driver_text, report_narrative


def _factor(name: RiskFactor, value: float, raw: dict) -> FactorScoreResponse:
    return FactorScoreResponse(factor=name, value=value, band=RiskBand.MODERATE, raw_inputs=raw)


FULL_FACTORS = [
    _factor(
        RiskFactor.VEGETATION_STABILITY,
        30,
        {"current_ndvi": 0.42, "ndvi_percentile": 70, "history_months": 34},
    ),
    _factor(
        RiskFactor.WATER_AVAILABILITY,
        55,
        {"mndwi_current": -0.31, "ndmi_current": 0.12, "rainfall_ratio_to_normal": 0.87},
    ),
    _factor(RiskFactor.DROUGHT_RISK, 62, {"vci": 41, "rainfall_ratio_to_normal": 0.87}),
    _factor(
        RiskFactor.FLOOD_EXPOSURE,
        12,
        {"jrc_water_occurrence_percent": 1.4, "rainfall_ratio_to_normal": 0.87},
    ),
]


def _report(factors: list[FactorScoreResponse]) -> ReportResponse:
    return ReportResponse(
        id=uuid4(),
        farm_id=uuid4(),
        farm_area_ha=2.5,
        village_id=uuid4(),
        overall_score=47.2,
        overall_band=RiskBand.MODERATE,
        confidence=94.4,
        model_version="rule-engine-v1",
        computed_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        factors=factors,
        farm=ReportFarmContext(
            geometry={"type": "Polygon", "coordinates": []},
            village_name="Killari",
            taluka_name="Ausa",
            district_name="Latur",
            officer_name="Test Officer",
        ),
        series=ReportSeries(ndvi=[], mndwi=[], ndmi=[], rainfall=[]),
        evidence=ReportEvidenceContext(
            observation_window_start=date(2023, 7, 1),
            observation_window_end=date(2026, 7, 1),
            expected_months=36,
        ),
        method=ReportMethodContext(
            weights_version_id=uuid4(),
            weights={f.value: 0.25 for f in RiskFactor},
            weights_effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            floor_threshold=80.0,
            weighted_average_score=47.2,
        ),
    )


class TestFactorDriverText:
    def test_states_real_numbers_from_raw_inputs_no_invented_causes(self):
        assert factor_driver_text(FULL_FACTORS[0]) == (
            # Was "of this farm's own 3-year range" — wrong since the seasonal
            # fix, which ranks against the same calendar month across years.
            "Current NDVI 0.42 sits at the 70th percentile of the same calendar month across the baseline years."
        )
        assert "Vegetation Condition Index at 41" in factor_driver_text(FULL_FACTORS[2])
        assert "87% of the seasonal normal" in factor_driver_text(FULL_FACTORS[2])
        assert "1.4% (JRC satellite record, 1984–2021)" in factor_driver_text(FULL_FACTORS[3])

    def test_uses_correct_ordinal_suffixes_for_the_ndvi_percentile(self):
        def at(percentile: float) -> str:
            return factor_driver_text(
                _factor(
                    RiskFactor.VEGETATION_STABILITY,
                    30,
                    {"current_ndvi": 0.17, "ndvi_percentile": percentile},
                )
            )

        assert "31st percentile" in at(31)
        assert "42nd percentile" in at(42)
        assert "53rd percentile" in at(53)
        assert "11th percentile" in at(11)
        assert "12th percentile" in at(12)

    def test_degrades_honestly_when_raw_inputs_are_missing(self):
        sparse = _factor(
            RiskFactor.VEGETATION_STABILITY,
            50,
            {"current_ndvi": None, "ndvi_percentile": None, "history_months": 0},
        )
        # A computed factor with no percentile is a legacy rule-engine-v1 row,
        # for which the neutral-50 statement is true — and says whose it was.
        assert "neutral score of 50 was applied by the previous engine version" in factor_driver_text(sparse)

    def test_mentions_only_the_sub_signals_actually_present(self):
        rainfall_only = _factor(
            RiskFactor.DROUGHT_RISK, 40, {"vci": None, "rainfall_ratio_to_normal": 1.1}
        )
        text = factor_driver_text(rainfall_only)
        assert "Vegetation Condition Index" not in text
        assert "110% of the seasonal normal" in text


class TestReportNarrative:
    def test_summarizes_strictly_from_engine_outputs(self):
        text = report_narrative(_report(FULL_FACTORS))
        assert "moderate overall climate risk (score 47/100)" in text
        assert "highest-scoring factor is drought risk at 62/100" in text
        assert "recent seasonal rainfall was 87% of the long-term normal" in text
        assert "Flood exposure scores lowest at 12/100" in text
        # Named for what it is: data completeness, not confidence.
        assert "Data completeness is 94%" in text
        assert "not a measure of confidence in the score" in text

    def test_omits_the_rainfall_clause_when_the_engine_had_no_ratio(self):
        no_ratio = [
            _factor(f.factor, f.value, {**f.raw_inputs, "rainfall_ratio_to_normal": None})
            for f in FULL_FACTORS
        ]
        assert "long-term normal" not in report_narrative(_report(no_ratio))



class TestNotComputed:
    """Phase C: a factor the engine could not compute has no value, and the
    text says so — never a neutral score, never a band."""

    def test_an_uncomputed_factor_is_described_as_not_computed(self):
        factor = FactorScoreResponse(
            factor=RiskFactor.VEGETATION_STABILITY, value=None, band=None, computed=False, raw_inputs={}
        )
        text = factor_driver_text(factor)
        assert text.startswith("Not computed")
        assert "neutral" not in text

    def test_a_report_with_no_overall_score_does_not_state_a_band(self):
        """The production Shera shape: three factors uncomputed, flood alone
        computed, no composite."""
        factors = [
            f.model_copy(update={"value": None, "band": None, "computed": False}) if i < 3 else f
            for i, f in enumerate(FULL_FACTORS)
        ]
        report = _report(factors).model_copy(update={"overall_score": None, "overall_band": None})
        text = report_narrative(report)
        assert "No overall climate risk score could be estimated" in text
        assert "1 of 4 risk factors" in text
        assert "moderate" not in text.lower()
