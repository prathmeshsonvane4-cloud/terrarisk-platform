"""Unit tests for the PDF renderer — pure payload-in, PDF-out, no database
or network. Content assertions go through pypdf text extraction so they
verify what a reader of the document actually sees, not internals.
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
    ReportFarmContext,
    ReportResponse,
    ReportSeries,
)
from app.services.reporting.map_snapshot import _fit_zoom, _to_global_px
from app.services.reporting.pdf_renderer import render_report_pdf

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
    )


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_renders_every_required_section_from_the_payload():
    """Layout items 1–12 of the P6 spec, asserted through what a reader of
    the document sees — all of it traceable to the payload."""
    pdf_bytes = render_report_pdf(_full_report(), map_png=None)

    assert pdf_bytes.startswith(b"%PDF"), "not a PDF"
    text = _extract_text(pdf_bytes)

    assert "TerraRisk" in text  # 1 branding
    assert "rule-engine-v1" in text  # 2 metadata / 11 lineage
    assert "Killari" in text and "Ausa" in text and "Latur" in text  # 3 farm info
    assert "20.50 ha (50.7 acres)" in text
    assert "Integration Test Officer" in text
    assert "Moderate risk" in text  # 4 overall band
    assert "Score 42 / 100" in text  # 5 score
    assert "Confidence 97%" in text  # 6 confidence
    for label in ("Drought risk", "Water availability", "Vegetation stability", "Flood exposure"):
        assert label in text  # 7 factor cards
    assert "31st percentile" in text  # 7 driver sentences (with correct ordinal)
    assert "Vegetation health" in text and "Monthly rainfall" in text  # 8 charts
    assert "Farm boundary" in text  # 9 map section
    assert "moderate overall climate risk (score 42/100)" in text  # 10 narrative
    assert "Sentinel-2 SR Harmonized" in text  # 11 lineage datasets
    assert "credit decision remains with the bank" in text  # 12 disclaimer


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


def test_empty_series_renders_a_no_observations_note_not_a_crash():
    report = _full_report()
    report.series = ReportSeries(ndvi=[], mndwi=[], ndmi=[], rainfall=[])
    text = _extract_text(render_report_pdf(report, map_png=None))
    assert "No usable observations for this period." in text


def test_snapshot_zoom_fits_the_padded_boundary():
    """The chosen zoom must actually contain the boundary inside the
    snapshot frame — the polygon must never be cropped out of the PDF map."""
    ring = [(lon, lat) for lon, lat in _RING]
    zoom = _fit_zoom(ring)
    assert 1 <= zoom <= 17
    xs, ys = zip(*(_to_global_px(lon, lat, zoom) for lon, lat in ring))
    assert max(xs) - min(xs) <= 1200 - 2 * 80
    assert max(ys) - min(ys) <= 700 - 2 * 80
