"""PDF rendering for the farmer climate risk report (Blueprint §08).

The PDF is the artifact that enters the bank's loan file. It is rendered
from the SAME `ReportResponse` payload as the dashboard — two views of one
artifact — and every sentence comes from `report_text.py`, the pinned
mirror of the dashboard's templates. Nothing here computes risk; it only
typesets what the engine persisted.

`render_report_pdf` is a pure function of (payload, optional map PNG), so
tests exercise the full layout without a database or network.
"""

from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")  # headless server rendering; must precede pyplot import

import matplotlib.pyplot as plt
from PIL import Image as PILImage
from PIL import ImageDraw
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.enums import RiskBand
from app.schemas.report import FactorScoreResponse, ObservationPoint, ReportResponse
from app.services.reporting.map_snapshot import TILE_ATTRIBUTION
from app.services.reporting.report_text import (
    FACTOR_LABELS,
    FACTOR_ORDER,
    RISK_BAND_LABELS,
    factor_driver_text,
    format_area,
    js_round,
    report_narrative,
)

# Bump whenever the layout changes — the endpoint's disk cache keys on it,
# so stale-layout PDFs are re-rendered instead of served forever.
PDF_LAYOUT_VERSION = 1

# Verbatim from the dashboard's lineage footer (reports/[id]/page.tsx).
DATA_SOURCES = (
    "Sentinel-2 SR Harmonized (ESA/Copernicus) · CHIRPS Daily rainfall (UCSB) · "
    "JRC Global Surface Water v1.4 (EC-JRC)"
)
DISCLAIMER = (
    "This report is decision support for the lending officer. "
    "The credit decision remains with the bank."
)

_IST = ZoneInfo("Asia/Kolkata")

# Print palette — brand ink from the dashboard theme, risk-band colors are
# the exact Tailwind values behind risk-bands.ts (one visual language).
_INK = colors.HexColor("#1c2433")
_MUTED = colors.HexColor("#5b6472")
_BRAND = colors.HexColor("#1e4e8c")
_BORDER = colors.HexColor("#d8dee6")
_PANEL = colors.HexColor("#f4f6f9")
_BAND_STYLES: dict[RiskBand, tuple[colors.Color, colors.Color, colors.Color]] = {
    # (headline ink = *-700, chip background = *-100, chip ink = *-900)
    RiskBand.LOW: (colors.HexColor("#047857"), colors.HexColor("#d1fae5"), colors.HexColor("#064e3b")),
    RiskBand.MODERATE: (colors.HexColor("#b45309"), colors.HexColor("#fef3c7"), colors.HexColor("#78350f")),
    RiskBand.HIGH: (colors.HexColor("#c2410c"), colors.HexColor("#ffedd5"), colors.HexColor("#7c2d12")),
    RiskBand.VERY_HIGH: (colors.HexColor("#b91c1c"), colors.HexColor("#fee2e2"), colors.HexColor("#7f1d1d")),
}
# Chart series hues — identical to monthly-trend-chart.tsx; never band colors.
_CHART_GREEN = "#15803d"
_CHART_BLUE = "#1d4ed8"

_PAGE_WIDTH, _PAGE_HEIGHT = A4
_MARGIN = 16 * mm
_CONTENT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN


def _style(name: str, **kwargs) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=_INK)
    base.update(kwargs)
    return ParagraphStyle(name, **base)


_STYLES = {
    "brand": _style("brand", fontName="Helvetica-Bold", fontSize=21, leading=24, textColor=_BRAND),
    "tagline": _style("tagline", fontSize=8.5, leading=11, textColor=_MUTED),
    "doc_title": _style(
        "doc_title", fontName="Helvetica-Bold", fontSize=11.5, leading=14, alignment=TA_RIGHT
    ),
    "doc_subtitle": _style("doc_subtitle", fontSize=8.5, leading=11, textColor=_MUTED, alignment=TA_RIGHT),
    "meta": _style("meta", fontSize=8, leading=11, textColor=_MUTED),
    "section": _style(
        "section", fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=4, textColor=_INK
    ),
    "label": _style("label", fontSize=7, leading=9, textColor=_MUTED),
    "value": _style("value", fontSize=10, leading=13),
    "verdict_label": _style("verdict_label", fontSize=8, leading=11, textColor=_MUTED),
    "score": _style("score", fontName="Helvetica-Bold", fontSize=13, leading=17, alignment=TA_RIGHT),
    "score_note": _style("score_note", fontSize=8, leading=11, textColor=_MUTED, alignment=TA_RIGHT),
    "narrative": _style("narrative", fontSize=9.5, leading=14.5),
    "factor_name": _style("factor_name", fontName="Helvetica-Bold", fontSize=9, leading=12),
    "factor_score": _style("factor_score", fontName="Helvetica-Bold", fontSize=15, leading=18),
    "driver": _style("driver", fontSize=7.6, leading=10.4, textColor=_MUTED),
    "chart_caption": _style("chart_caption", fontSize=7.6, leading=10, textColor=_MUTED),
    "attribution": _style("attribution", fontSize=6.5, leading=8.5, textColor=_MUTED),
    "lineage": _style("lineage", fontSize=8, leading=11.5, textColor=_MUTED),
    "disclaimer": _style("disclaimer", fontSize=8.5, leading=12, textColor=_INK),
}


def _fmt_date(value: datetime) -> str:
    local = value.astimezone(_IST)
    return f"{local.day} {local.strftime('%b %Y')}"


def _fmt_datetime(value: datetime) -> str:
    local = value.astimezone(_IST)
    hour = local.hour % 12 or 12
    meridiem = "am" if local.hour < 12 else "pm"
    return f"{_fmt_date(value)}, {hour}:{local.minute:02d} {meridiem}"


def _chart_png(points: list[ObservationPoint], variant: str, color: str, integer_axis: bool) -> bytes:
    """One monthly-series chart, visually mirroring monthly-trend-chart.tsx:
    y-gridlines only, no spines, ~6 month labels across the series."""
    figure, axis = plt.subplots(figsize=(5.35, 2.3), dpi=200)
    try:
        x = range(len(points))
        y = [point.value for point in points]
        if variant == "line":
            axis.plot(x, y, color=color, linewidth=1.7, solid_capstyle="round")
        else:
            axis.bar(x, y, color=color, width=0.72)

        axis.grid(axis="y", color="#e6e9ef", linewidth=0.8)
        axis.set_axisbelow(True)
        for spine in axis.spines.values():
            spine.set_visible(False)

        step = max(1, -(-len(points) // 6))  # ceil — mirrors the dashboard's ~6 ticks
        tick_positions = list(range(0, len(points), step))
        axis.set_xticks(tick_positions)
        axis.set_xticklabels(
            [points[i].period_start.strftime("%b %y") for i in tick_positions], fontsize=7.5
        )
        axis.tick_params(colors="#5b6472", length=0, labelsize=7.5)
        if integer_axis:
            axis.yaxis.set_major_formatter(lambda value, _pos: f"{value:.0f}")
        axis.margins(x=0.015)
        figure.tight_layout(pad=0.5)

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        return buffer.getvalue()
    finally:
        plt.close(figure)


def _boundary_only_png(geometry: dict) -> bytes:
    """Imagery-unavailable fallback: the real officer-drawn boundary on a
    neutral panel. Real data, honestly degraded — never a placeholder."""
    width, height, pad = 1200, 700, 90
    ring = [(float(lon), float(lat)) for lon, lat in (geometry.get("coordinates") or [[]])[0]]
    image = PILImage.new("RGB", (width, height), "#eef1f5")
    if len(ring) >= 3:
        lons, lats = zip(*ring)
        # Linear lon/lat scaling is fine at farm extents; equalize the
        # scale so the shape isn't stretched.
        span = max(max(lons) - min(lons), (max(lats) - min(lats)), 1e-9)
        scale = min((width - 2 * pad), (height - 2 * pad)) / span
        cx, cy = (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2
        pixel_ring = [
            ((lon - cx) * scale + width / 2, (cy - lat) * scale + height / 2) for lon, lat in ring
        ]
        draw = ImageDraw.Draw(image)
        draw.polygon(pixel_ring, fill="#dfe5ec", outline="#1e4e8c", width=5)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _panel(rows: list[list], col_widths: list[float], style_extras: list | None = None) -> Table:
    table = Table(rows, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                *(style_extras or []),
            ]
        )
    )
    return table


def _chip(text: str, background: colors.Color, ink: colors.Color) -> Table:
    # Fixed to the text's measured width so the chip hugs its label like
    # the dashboard's, instead of stretching across the table column.
    chip = Table(
        [[Paragraph(text, _style("chip", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=ink))]],
        colWidths=[stringWidth(text, "Helvetica-Bold", 7) + 12],
    )
    chip.hAlign = "RIGHT"
    chip.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return chip


def _factor_cell(factor: FactorScoreResponse) -> Table:
    _, chip_bg, chip_ink = _BAND_STYLES[factor.band]
    inner = Table(
        [
            [Paragraph(FACTOR_LABELS[factor.factor], _STYLES["factor_name"]), _chip(RISK_BAND_LABELS[factor.band], chip_bg, chip_ink)],
            [
                Paragraph(
                    f"{js_round(factor.value)} <font size=8 color='#5b6472'>/ 100</font>",
                    _STYLES["factor_score"],
                ),
                "",
            ],
            [Paragraph(factor_driver_text(factor), _STYLES["driver"]), ""],
        ],
        colWidths=[None, None],
    )
    inner.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 1), (1, 1)),
                ("SPAN", (0, 2), (1, 2)),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return inner


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(_MUTED)
    canvas.drawString(_MARGIN, 9 * mm, "TerraRisk — Climate Risk Report")
    canvas.drawRightString(_PAGE_WIDTH - _MARGIN, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def render_report_pdf(report: ReportResponse, map_png: bytes | None) -> bytes:
    """Typeset the full climate risk report; returns the PDF bytes."""
    band_ink, band_bg, _ = _BAND_STYLES[report.overall_band]
    factors = [
        factor
        for name in FACTOR_ORDER
        for factor in report.factors
        if factor.factor == name
    ]

    story: list = []

    # 1 · Branding
    header = Table(
        [
            [
                [Paragraph("TerraRisk", _STYLES["brand"]), Paragraph("Climate Intelligence for Agricultural Credit", _STYLES["tagline"])],
                [Paragraph("Climate Risk Report", _STYLES["doc_title"]), Paragraph("Farmer report · Service 1", _STYLES["doc_subtitle"])],
            ]
        ],
        colWidths=[_CONTENT_WIDTH * 0.62, _CONTENT_WIDTH * 0.38],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(header)
    story.append(Spacer(0, 4))
    story.append(HRFlowable(width="100%", thickness=1.6, color=_BRAND, spaceAfter=4))

    # 2 · Report metadata
    story.append(
        Paragraph(
            f"Report {report.id} · Generated {_fmt_datetime(report.computed_at)} IST · "
            f"Model {report.model_version}",
            _STYLES["meta"],
        )
    )
    story.append(Spacer(0, 10))

    # 3 · Farm information
    def _field(label: str, value: str) -> list[Paragraph]:
        return [Paragraph(label.upper(), _STYLES["label"]), Paragraph(value, _STYLES["value"])]

    farm_rows = [
        [
            _field("Village", f"{report.farm.village_name} · {report.farm.taluka_name}, {report.farm.district_name}"),
            _field("Farm area", format_area(report.farm_area_ha)),
        ],
        [
            _field("Mapped by", report.farm.officer_name),
            _field("Assessed", _fmt_date(report.computed_at)),
        ],
    ]
    story.append(_panel(farm_rows, [_CONTENT_WIDTH * 0.58, _CONTENT_WIDTH * 0.42]))
    story.append(Spacer(0, 10))

    # 4–6 · Overall climate risk, score, confidence
    verdict_rows = [
        [
            [
                Paragraph("OVERALL CLIMATE RISK", _STYLES["verdict_label"]),
                Paragraph(
                    RISK_BAND_LABELS[report.overall_band],
                    _style("verdict", fontName="Times-Bold", fontSize=24, leading=28, textColor=band_ink),
                ),
            ],
            [
                Paragraph(f"Score {js_round(report.overall_score)} / 100", _STYLES["score"]),
                Paragraph(
                    f"Confidence {js_round(report.confidence)}% — share of usable cloud-free observations",
                    _STYLES["score_note"],
                ),
            ],
        ]
    ]
    story.append(
        _panel(
            verdict_rows,
            [_CONTENT_WIDTH * 0.62, _CONTENT_WIDTH * 0.38],
            [("BACKGROUND", (0, 0), (-1, -1), band_bg), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")],
        )
    )
    story.append(Spacer(0, 12))

    # 7 · Factor cards
    story.append(Paragraph("Risk factor breakdown", _STYLES["section"]))
    story.append(Spacer(0, 5))
    half = _CONTENT_WIDTH / 2
    factor_grid = [
        [_factor_cell(factors[0]), _factor_cell(factors[1])],
        [_factor_cell(factors[2]), _factor_cell(factors[3])],
    ] if len(factors) == 4 else [[_factor_cell(f) for f in factors]]
    grid = Table(factor_grid, colWidths=[half, half])
    grid.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.8, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(grid)
    story.append(Spacer(0, 12))

    # 8 · Charts
    drought = next((f for f in report.factors if f.factor.value == "drought_risk"), None)
    ratio = drought.raw_inputs.get("rainfall_ratio_to_normal") if drought else None
    rainfall_caption = (
        f"Total rainfall per month (mm). Most recent season: {js_round(ratio * 100)}% of the 30-year seasonal normal."
        if isinstance(ratio, (int, float))
        else "Total rainfall per month (mm) over this farm."
    )
    for title, caption, points, variant, color, integer_axis in (
        (
            "Vegetation health — 3-year NDVI",
            "Monthly cloud-free composite over this farm. Higher is greener, denser vegetation.",
            report.series.ndvi,
            "line",
            _CHART_GREEN,
            False,
        ),
        ("Monthly rainfall", rainfall_caption, report.series.rainfall, "bar", _CHART_BLUE, True),
    ):
        block: list = [Paragraph(title, _STYLES["section"]), Paragraph(caption, _STYLES["chart_caption"]), Spacer(0, 3)]
        if points:
            png = _chart_png(points, variant, color, integer_axis)
            block.append(Image(io.BytesIO(png), width=_CONTENT_WIDTH, height=_CONTENT_WIDTH * 2.3 / 5.35))
        else:
            block.append(Paragraph("No usable observations for this period.", _STYLES["driver"]))
        story.append(KeepTogether(block))
        story.append(Spacer(0, 10))

    # 9 · Farm map
    imagery_available = map_png is not None
    map_bytes = map_png if imagery_available else _boundary_only_png(report.farm.geometry)
    map_block: list = [
        Paragraph("Farm boundary", _STYLES["section"]),
        Spacer(0, 3),
        Image(io.BytesIO(map_bytes), width=_CONTENT_WIDTH, height=_CONTENT_WIDTH * 700 / 1200),
        Spacer(0, 2),
        Paragraph(
            TILE_ATTRIBUTION
            if imagery_available
            else "Officer-drawn boundary. Satellite imagery was unavailable at render time.",
            _STYLES["attribution"],
        ),
    ]
    story.append(KeepTogether(map_block))
    story.append(Spacer(0, 12))

    # 10 · Climate narrative
    story.append(
        KeepTogether(
            [
                Paragraph("Assessment summary", _STYLES["section"]),
                Spacer(0, 3),
                Paragraph(report_narrative(report), _STYLES["narrative"]),
            ]
        )
    )
    story.append(Spacer(0, 12))

    # 11–12 · Data lineage + disclaimer
    lineage_rows = [
        [
            [
                Paragraph(f"<b>Data sources:</b> {DATA_SOURCES}", _STYLES["lineage"]),
                Paragraph(
                    f"Model {report.model_version} · Generated {_fmt_datetime(report.computed_at)} IST · "
                    f"Confidence {js_round(report.confidence)}% (share of usable cloud-free observations)",
                    _STYLES["lineage"],
                ),
                Spacer(0, 4),
                Paragraph(DISCLAIMER, _STYLES["disclaimer"]),
            ]
        ]
    ]
    story.append(
        KeepTogether(
            [_panel(lineage_rows, [_CONTENT_WIDTH], [("BACKGROUND", (0, 0), (-1, -1), _PANEL)])]
        )
    )

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"TerraRisk Climate Risk Report — {report.farm.village_name}",
        author="TerraRisk",
        subject="Farm climate risk assessment (decision support)",
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
