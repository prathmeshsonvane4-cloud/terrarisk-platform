"""Unit tests for the PDF renderer — pure payload-in, PDF-out, no database
or network. Content assertions go through pypdf text extraction so they
verify what a reader of the document actually sees, not internals.

REPORT V2: rewritten for the 7-section, 9-physical-page structure (some
sections spill across a page break — expected, not a bug, since each of
the 7 sections gets its own PageBreak()). Assertions are scoped per-page
where practical so a change to one page can't silently pass by matching
text that actually lives on a different page.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from uuid import uuid4

from pypdf import PdfReader

from app.models.enums import RiskBand, RiskFactor
from app.schemas.report import (
    FactorScoreResponse,
    ObservationPoint,
    ReportComparisonContext,
    ReportEvidenceContext,
    ReportFarmContext,
    ReportMethodContext,
    ReportResponse,
    ReportSeries,
)
from app.services.reporting.map_snapshot import _fit_zoom, _to_global_px
from app.services.reporting.pdf_renderer import PDF_LAYOUT_VERSION, render_report_pdf

_RING = [[76.588, 18.07], [76.593, 18.07], [76.593, 18.0735], [76.588, 18.0735], [76.588, 18.07]]


def _series(months: int = 36, base: float = 0.2) -> list[ObservationPoint]:
    points = []
    for index in range(months):
        year, month = divmod(index, 12)
        points.append(
            ObservationPoint(period_start=date(2023 + year, month + 1, 1), value=base + 0.01 * index)
        )
    return points


def _full_report() -> ReportResponse:
    """First assessment (no prior RiskScore), Moderate band, high
    confidence — the baseline scenario. Individual tests mutate a fresh
    copy for other scenarios rather than sharing state."""
    return ReportResponse(
        id=uuid4(),
        farm_id=uuid4(),
        farm_area_ha=20.5046,
        village_id=uuid4(),
        overall_score=41.94,
        overall_band=RiskBand.MODERATE,
        confidence=97.22,
        model_version="rule-engine-v1",
        computed_at=datetime(2026, 7, 12, 5, 13, 22, tzinfo=timezone.utc),
        factors=[
            FactorScoreResponse(
                factor=RiskFactor.DROUGHT_RISK,
                value=50.63,
                band=RiskBand.HIGH,
                raw_inputs={"vci": 40.9, "rainfall_ratio_to_normal": 1.156},
            ),
            FactorScoreResponse(
                factor=RiskFactor.WATER_AVAILABILITY,
                value=40.72,
                band=RiskBand.MODERATE,
                raw_inputs={
                    "mndwi_current": -0.268,
                    "ndmi_current": -0.046,
                    "rainfall_ratio_to_normal": 1.156,
                },
            ),
            FactorScoreResponse(
                factor=RiskFactor.VEGETATION_STABILITY,
                value=68.57,
                band=RiskBand.HIGH,
                raw_inputs={"current_ndvi": 0.167, "ndvi_percentile": 31.43},
            ),
            FactorScoreResponse(
                factor=RiskFactor.FLOOD_EXPOSURE,
                value=7.84,
                band=RiskBand.LOW,
                raw_inputs={"jrc_water_occurrence_percent": 0.0, "rainfall_ratio_to_normal": 1.156},
            ),
        ],
        farm=ReportFarmContext(
            geometry={"type": "Polygon", "coordinates": [_RING]},
            village_name="Killari",
            taluka_name="Ausa",
            district_name="Latur",
            officer_name="Integration Test Officer",
        ),
        series=ReportSeries(
            ndvi=_series(base=0.15),
            mndwi=_series(base=-0.3),
            ndmi=_series(base=-0.05),
            rainfall=_series(base=120.0),
        ),
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
            weighted_average_score=41.94,
        ),
    )


def _with_previous_assessment(report: ReportResponse) -> ReportResponse:
    """A farm with a real prior RiskScore — drought_risk clearly up,
    vegetation_stability clearly down, so both trend glyphs get exercised."""
    report.comparison = ReportComparisonContext(
        has_previous_assessment=True,
        previous_computed_at=datetime(2026, 1, 12, 5, 0, 0, tzinfo=timezone.utc),
        previous_overall_score=35.0,
        previous_factor_scores={
            RiskFactor.DROUGHT_RISK.value: 30.0,  # 50.63 vs 30.0 -> up
            RiskFactor.WATER_AVAILABILITY.value: 40.70,  # ~flat
            RiskFactor.VEGETATION_STABILITY.value: 85.0,  # 68.57 vs 85.0 -> down
            RiskFactor.FLOOD_EXPOSURE.value: 7.84,  # exactly flat
        },
    )
    return report


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _extract_pages(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() for page in reader.pages]


def test_page_1_executive_summary_answers_the_core_credit_questions():
    """Page 1 must let a reader answer, within 30 seconds: what's the
    score/band, why, confidence, and what to do about it."""
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    assert pdf_bytes.startswith(b"%PDF"), "not a PDF"
    page1 = _extract_pages(pdf_bytes)[0]

    assert "TerraRisk" in page1  # branding
    assert "Climate Credit Report" in page1
    assert "Executive Climate Credit Summary" in page1
    assert "Moderate risk" in page1  # overall band
    assert "Score 42 / 100" in page1  # overall score
    # Named for what it measures (Phase C): data completeness, not confidence.
    assert "Data completeness 97%" in page1
    assert "Confidence 97%" not in page1
    assert "Assessment quality: Excellent" in page1  # quality label
    assert "Killari" in page1 and "Ausa" in page1 and "Latur" in page1
    assert "20.50 ha (50.7 acres)" in page1
    assert "rule-engine-v1" in page1

    # Credit Recommendation: narrative + posture + WHY bullets, reusing the
    # approved review-posture wording verbatim (never a loan verdict).
    assert "Credit Recommendation" in page1
    assert "moderate overall climate risk (score 42/100)" in page1  # narrative
    assert "Standard appraisal. Note the leading risk factor below in the loan file." in page1
    assert "WHY" in page1
    assert "31st percentile" in page1  # primary driver sentence
    assert "Decision support only" in page1 and "credit decision remains with the bank" in page1

    assert "Key Findings" in page1


def test_page_2_risk_dashboard_has_four_real_cards_and_two_honest_placeholders():
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    page2 = _extract_pages(pdf_bytes)[1]

    assert "Risk Dashboard" in page2
    for label in ("Drought risk", "Water availability", "Vegetation stability", "Flood exposure"):
        assert label in page2
    assert "WHAT HAPPENED" in page2
    assert "RECOMMENDED ACTION" in page2

    # Real factors get a genuine trend statement (first assessment here).
    assert page2.count("First assessment") == 4

    # The two unimplemented factors are explicit placeholders, never a
    # fabricated score.
    assert "Future Heat Risk" in page2
    assert "Soil Moisture Stability" in page2
    assert page2.count("Not yet implemented") == 2


def test_placeholder_factor_cards_never_render_a_fabricated_score():
    """Regression guard: a placeholder card must never show a '<number> /
    100' score — that would misrepresent absence-of-data as a real
    reading."""
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    page2 = _extract_pages(pdf_bytes)[1]

    placeholder_start = page2.index("Future Heat Risk")
    placeholder_section = page2[placeholder_start:]
    assert "/ 100" not in placeholder_section


def test_trend_renders_against_a_real_prior_assessment_when_one_exists():
    report = _with_previous_assessment(_full_report())
    pdf_bytes = render_report_pdf(report, map_png=None)
    page2 = _extract_pages(pdf_bytes)[1]

    assert "First assessment" not in page2
    assert "vs previous assessment" in page2
    assert "▲" in page2  # drought_risk rose
    assert "▼" in page2  # vegetation_stability fell


def test_historical_analysis_covers_all_four_indices_with_real_stats():
    """Logical section 3 spans physical pages 3-4 — checked as one
    concatenated block since the split point isn't a contract."""
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    pages = _extract_pages(pdf_bytes)
    section = pages[2] + pages[3]

    assert "Historical Analysis" in section
    for heading in ("Vegetation (NDVI)", "Surface water (MNDWI)", "Crop moisture (NDMI)", "Monthly rainfall"):
        assert heading in section
    assert section.count("Current") >= 4 and section.count("Median") >= 4 and section.count("Percentile") >= 4
    assert "Year-over-year comparison" in section
    assert "2023" in section and "2024" in section and "2025" in section


def test_climate_outlook_is_honest_about_missing_forecasts():
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    page5 = _extract_pages(pdf_bytes)[4]

    assert "Climate Outlook" in page5
    for heading in ("Expected Rainfall", "Temperature Outlook", "Expected Vegetation Trend", "Expected Water Stress"):
        assert heading in page5
    assert page5.count("Data unavailable") == 4  # never a fabricated forecast number
    assert "Monitoring Recommendation" in page5
    assert "Field Verification" in page5


def test_monitoring_cadence_and_field_verification_vary_by_band_and_confidence():
    # Baseline: Moderate band, high confidence -> semi-annual, no field visit forced.
    base_page5 = _extract_pages(render_report_pdf(_full_report(), map_png=None))[4]
    assert "Semi-annual reassessment (6 months)" in base_page5
    assert "Not required for a standard appraisal at this risk band and confidence level." in base_page5

    # Low confidence overrides a favorable band -> immediate verification.
    low_confidence = _full_report()
    low_confidence.confidence = 55.0
    low_confidence_page5 = _extract_pages(render_report_pdf(low_confidence, map_png=None))[4]
    assert "Immediate field verification, then monthly monitoring until resolved" in low_confidence_page5
    assert "Recommended before proceeding." in low_confidence_page5
    assert "Indicative only" in _extract_pages(render_report_pdf(low_confidence, map_png=None))[0]

    # Very High band -> escalation posture and immediate verification, even at high confidence.
    very_high = _full_report()
    very_high.overall_band = RiskBand.VERY_HIGH
    very_high_pages = _extract_pages(render_report_pdf(very_high, map_png=None))
    assert "Refer to branch manager. Recommend independent field verification before sanction." in very_high_pages[0]
    assert "Immediate field verification, then monthly monitoring until resolved" in very_high_pages[4]
    assert "Recommended before proceeding." in very_high_pages[4]


def test_farm_intelligence_page_shows_real_metadata_and_honest_road_gap():
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    page6 = _extract_pages(pdf_bytes)[5]

    assert "Farm Intelligence" in page6
    assert "20.50 ha (50.7 acres)" in page6
    assert "Killari" in page6
    assert "Integration Test Officer" in page6  # field-officer provenance
    assert "Esri World Imagery" in page6
    assert "Nearby road" in page6
    assert "Data unavailable" in page6 and "road-network data is not currently integrated" in page6


def test_without_imagery_the_map_degrades_honestly():
    text = _extract_text(render_report_pdf(_full_report(), map_png=None))
    assert "Satellite imagery was unavailable at render time" in text
    assert "Powered by Esri" not in text  # never attribute imagery that isn't there


def test_with_imagery_the_map_carries_the_esri_attribution():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1200, 700), "#334455").save(buffer, format="PNG")

    text = _extract_text(render_report_pdf(_full_report(), map_png=buffer.getvalue()))
    assert "Powered by Esri" in text
    assert "unavailable at render time" not in text


def test_methodology_explains_every_index_in_plain_english():
    """Logical section 6 spans physical pages 7-8."""
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    pages = _extract_pages(pdf_bytes)
    section = pages[6] + pages[7]

    assert "Methodology" in section
    for heading in ("NDVI", "MNDWI", "NDMI", "VCI", "JRC Global Surface Water", "CHIRPS rainfall"):
        assert heading in section
    assert "Confidence" in section and "Cloud filtering" in section and "Percentile rank" in section
    assert "Quality control" in section
    assert "Risk factor definitions" in section
    for label in ("Drought risk", "Water availability", "Vegetation stability", "Flood exposure"):
        assert label in section


def test_audit_appendix_has_real_traceable_metadata_and_no_duplicate_fields():
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    page9 = _extract_pages(pdf_bytes)[8]

    assert "Audit Appendix" in page9
    assert "PROCESSING DATE" in page9
    assert "Not recorded for this assessment" in page9  # honest: no Job row in this fixture
    assert "EARTH ENGINE SDK VERSION" in page9
    assert "DATA COMPLETENESS" in page9 and "97%" in page9
    assert "0 of 36 expected months" in page9
    assert "Latur" in page9
    assert "REPORT TEMPLATE VERSION" in page9 and str(PDF_LAYOUT_VERSION) in page9
    assert "Sentinel-2 SR Harmonized" in page9
    assert "Known limitations" in page9
    assert "credit decision remains with the bank" in page9

    # Regression guard: Model version and Report template version must be
    # two distinct facts, never the same string duplicated under two labels.
    assert page9.count("rule-engine-v1") == 1


def test_processing_time_is_real_when_a_job_record_is_available():
    from app.schemas.report import ReportAuditContext

    report = _full_report()
    report.audit = ReportAuditContext(
        processing_started_at=datetime(2026, 7, 12, 5, 10, 0, tzinfo=timezone.utc),
        processing_completed_at=datetime(2026, 7, 12, 5, 13, 22, tzinfo=timezone.utc),
    )
    page9 = _extract_pages(render_report_pdf(report, map_png=None))[8]
    assert "202 seconds" in page9  # 3 minutes 22 seconds, real arithmetic, not invented


def test_empty_series_renders_a_no_observations_note_not_a_crash():
    report = _full_report()
    report.series = ReportSeries(ndvi=[], mndwi=[], ndmi=[], rainfall=[])
    text = _extract_text(render_report_pdf(report, map_png=None))
    assert "No usable observations for this period." in text


def test_long_village_and_officer_names_do_not_crash_or_get_clipped():
    report = _full_report()
    report.farm.village_name = "Shri Chhatrapati Shivaji Maharaj Nagar Gram Panchayat Extension Colony"
    report.farm.officer_name = "Vishwanath Ramchandra Deshpande-Kulkarni, Senior Agricultural Extension Officer"
    pdf_bytes = render_report_pdf(report, map_png=None)
    assert pdf_bytes.startswith(b"%PDF")

    pages = _extract_pages(pdf_bytes)
    assert "Deshpande-Kulkarni" in pages[5]  # reaches the Farm Intelligence panel intact


def test_page_count_matches_the_seven_section_structure():
    """Seven PageBreak()-separated sections is the contract; physical pages
    can exceed that when a section's content overflows, never fall short."""
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)
    pages = _extract_pages(pdf_bytes)
    total = len(pages)
    assert total >= 7
    assert f"Page 1 of {total}" in pages[0]
    assert f"Page {total} of {total}" in pages[-1]


def test_snapshot_zoom_fits_the_padded_boundary():
    """The chosen zoom must actually contain the boundary inside the
    snapshot frame — the polygon must never be cropped out of the PDF map."""
    ring = [(lon, lat) for lon, lat in _RING]
    zoom = _fit_zoom(ring)
    assert 1 <= zoom <= 17
    xs, ys = zip(*(_to_global_px(lon, lat, zoom) for lon, lat in ring))
    assert max(xs) - min(xs) <= 1200 - 2 * 80
    assert max(ys) - min(ys) <= 700 - 2 * 80



def test_an_assessment_with_no_overall_score_renders_honestly():
    """Phase C: the production Shera shape — three factors uncomputed, no
    composite. The PDF must render without a score, a band, a gauge or a
    radar, and must say what is missing rather than draw it as low risk."""
    from app.schemas.report import DecisionSufficiencyResponse, ModelConfidenceResponse

    report = _full_report()
    factors = [
        f.model_copy(update={"value": None, "band": None, "computed": False}) if i < 3 else f
        for i, f in enumerate(report.factors)
    ]
    report = report.model_copy(
        update={
            "overall_score": None,
            "overall_band": None,
            "factors": factors,
            "model_confidence": ModelConfidenceResponse(
                factors_computed=1,
                factors_total=4,
                weight_coverage=0.25,
                overall_estimable=False,
                overall_interval=None,
                interval_coverage="none",
                confidence_level=0.9,
                statement="1 of 4 factors computed (25% of the configured weight). No overall score.",
            ),
            "decision_sufficiency": DecisionSufficiencyResponse(
                policy_version="sufficiency-v1",
                calibration_status="uncalibrated",
                tiers=[
                    {
                        "tier": tier,
                        "sufficient": False,
                        "description": f"{tier} description",
                        "inadequacies": [{"code": "no_overall_estimate", "statement": "No overall risk score could be estimated."}],
                    }
                    for tier in ("low", "medium", "high")
                ],
                caveats=[],
                statement="The evidence is not sufficient for a decision at any stakes tier.",
            ),
        }
    )

    # Whitespace-normalised: PDF text extraction breaks lines wherever the
    # layout wraps, and these assertions are about content, not layout.
    pages = [" ".join(page.split()) for page in _extract_pages(render_report_pdf(report, map_png=None))]
    page1, page2 = pages[0], pages[1]

    assert "Not estimable" in page1
    assert "No overall score" in page1
    assert "Score " not in page1.split("Credit Recommendation")[0]
    assert "Do not rely on this report for a credit decision" in page1
    assert "Model Confidence and Evidence Sufficiency" in page1
    assert "not sufficient for a decision at any stakes tier" in page1
    assert "No risk radar: only 1 of 4 factors could be computed" in page2
    assert "Not computed" in page2
