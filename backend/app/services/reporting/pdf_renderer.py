"""PDF rendering for the Climate Credit Report (Blueprint §08, REPORT V2).

The PDF is the artifact that enters the bank's loan file. It is rendered
from the SAME `ReportResponse` payload as the dashboard — two views of one
artifact — and every sentence comes from report_text.py/recommendation.py/
report_findings.py/methodology_text.py, the pinned mirrors of the
dashboard's templates. Nothing here computes risk; it only typesets what
the engine (and the small, deterministic derivation layer in
report_statistics.py) already produced.

`render_report_pdf` is a pure function of (payload, optional map PNG), so
tests exercise the full layout without a database or network.

REPORT V2 restructured this from a 1-2 page descriptive report into a
7-page decision-support document (Executive Summary, Risk Dashboard,
Historical Analysis, Climate Outlook, Farm Intelligence, Methodology,
Audit Appendix). Every page-level design decision — what's real vs. an
honest "Data unavailable" — is recorded in docs/DECISIONS.md's REPORT V2
entry; the short version: nothing on any page states a number the engine
didn't actually compute from a real observation.
"""

from __future__ import annotations

import io
from datetime import datetime
from math import pi
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
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.enums import RiskBand, RiskFactor
from app.schemas.report import FactorScoreResponse, ObservationPoint, ReportResponse
from app.services.reporting import methodology_text, report_findings, report_statistics
from app.services.reporting.map_snapshot import TILE_ATTRIBUTION, annotate_cartography
from app.services.reporting.recommendation import (
    RECOMMENDATION_CONFIDENCE_THRESHOLD,
    build_recommendation,
    field_verification_recommended,
    recommendation_why_bullets,
)
from app.services.reporting.report_text import (
    FACTOR_LABELS,
    FACTOR_ORDER,
    RISK_BAND_LABELS,
    factor_driver_text,
    format_area,
    js_round,
)

# Bumped for REPORT V2's full restructure — the endpoint's disk cache keys
# on this, so every farm's PDF re-renders under the new layout instead of
# serving a stale cached v1 file. Old *-v1.pdf files are simply orphaned on
# disk, matching the existing cache design (never expired, never cleaned up).
PDF_LAYOUT_VERSION = 2

# Verbatim from the dashboard's lineage footer (reports/[id]/page.tsx).
DATA_SOURCES = (
    "Sentinel-2 SR Harmonized (ESA/Copernicus) · CHIRPS Daily rainfall (UCSB) · "
    "JRC Global Surface Water v1.4 (EC-JRC)"
)
DISCLAIMER = (
    "This report is decision support for the lending officer. "
    "The credit decision remains with the bank."
)

# Static, from requirements.txt's pin — a real fact about what generated
# this report, not a live runtime lookup (earthengine-api has no public
# "server processed this with version X" signal to query per-request).
EARTH_ENGINE_SDK_VERSION = "1.7.34"

_IST = ZoneInfo("Asia/Kolkata")

# Print palette — brand ink from the dashboard theme, risk-band colors are
# the exact Tailwind values behind risk-bands.ts (one visual language).
_INK = colors.HexColor("#1c2433")
_MUTED = colors.HexColor("#5b6472")
_BRAND = colors.HexColor("#1e4e8c")
_BORDER = colors.HexColor("#d8dee6")
_PANEL = colors.HexColor("#f4f6f9")
_AMBER_PANEL = colors.HexColor("#fffbeb")
_AMBER_INK = colors.HexColor("#92400e")
_BAND_STYLES: dict[RiskBand, tuple[colors.Color, colors.Color, colors.Color]] = {
    # (headline ink = *-700, chip background = *-100, chip ink = *-900)
    RiskBand.LOW: (colors.HexColor("#047857"), colors.HexColor("#d1fae5"), colors.HexColor("#064e3b")),
    RiskBand.MODERATE: (colors.HexColor("#b45309"), colors.HexColor("#fef3c7"), colors.HexColor("#78350f")),
    RiskBand.HIGH: (colors.HexColor("#c2410c"), colors.HexColor("#ffedd5"), colors.HexColor("#7c2d12")),
    RiskBand.VERY_HIGH: (colors.HexColor("#b91c1c"), colors.HexColor("#fee2e2"), colors.HexColor("#7f1d1d")),
}
# -300-tier tints of the same emerald/amber/orange/red family, for the
# Page 1 gauge's zone fill — bolder than the *-100 chip tint (needs to
# read as a "band" of color at a glance) without introducing a new hue.
_GAUGE_ZONE_HEX: dict[RiskBand, str] = {
    RiskBand.LOW: "#6ee7b7",
    RiskBand.MODERATE: "#fcd34d",
    RiskBand.HIGH: "#fdba74",
    RiskBand.VERY_HIGH: "#fca5a5",
}
# Chart series hues — identical to monthly-trend-chart.tsx; never band colors.
_CHART_GREEN = "#15803d"
_CHART_BLUE = "#1d4ed8"
_CHART_TEAL = "#0f766e"
_CHART_PURPLE = "#7e22ce"
_RADAR_FILL = "#1e4e8c"

_PAGE_WIDTH, _PAGE_HEIGHT = A4
_MARGIN = 16 * mm
_CONTENT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN

# Chart resolution — print-quality raster (not true vector; see
# docs/DECISIONS.md's REPORT V2 entry for the disclosed trade-off).
_CHART_DPI = 300


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
    "page_title": _style(
        "page_title", fontName="Helvetica-Bold", fontSize=15, leading=19, spaceBefore=0, spaceAfter=6, textColor=_BRAND
    ),
    "section": _style(
        "section", fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=4, textColor=_INK
    ),
    "subsection": _style(
        "subsection", fontName="Helvetica-Bold", fontSize=9.5, leading=12, spaceBefore=2, textColor=_INK
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
    "card_label": _style("card_label", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=_MUTED),
    "card_body": _style("card_body", fontSize=8, leading=11.5),
    "chart_caption": _style("chart_caption", fontSize=7.6, leading=10, textColor=_MUTED),
    "attribution": _style("attribution", fontSize=6.5, leading=8.5, textColor=_MUTED),
    "lineage": _style("lineage", fontSize=8, leading=11.5, textColor=_MUTED),
    "disclaimer": _style("disclaimer", fontSize=8.5, leading=12, textColor=_INK),
    "bullet": _style("bullet", fontSize=8.5, leading=12.5),
    "unavailable": _style("unavailable", fontSize=8.5, leading=12, textColor=_MUTED, fontName="Helvetica-Oblique"),
    "recommendation_action": _style(
        "recommendation_action", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=_BRAND
    ),
}


def _fmt_date(value: datetime) -> str:
    local = value.astimezone(_IST)
    return f"{local.day} {local.strftime('%b %Y')}"


def _fmt_datetime(value: datetime) -> str:
    local = value.astimezone(_IST)
    hour = local.hour % 12 or 12
    meridiem = "am" if local.hour < 12 else "pm"
    return f"{_fmt_date(value)}, {hour}:{local.minute:02d} {meridiem}"


def _ordered_factors(report: ReportResponse) -> list[FactorScoreResponse]:
    return [factor for name in FACTOR_ORDER for factor in report.factors if factor.factor == name]


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _chart_png(points: list[ObservationPoint], variant: str, color: str, integer_axis: bool) -> bytes:
    """One monthly-series chart, visually mirroring monthly-trend-chart.tsx:
    y-gridlines only, no spines, ~6 month labels across the series."""
    figure, axis = plt.subplots(figsize=(5.35, 2.3), dpi=_CHART_DPI)
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


def _gauge_chart_png(score: float) -> bytes:
    """Horizontal risk gauge, 0-100, four zones matching the real
    _BAND_THRESHOLDS quartiles exactly (risk/engine.py) — not a 5th
    invented tier, so this stays consistent with the band shown everywhere
    else in the app. A triangular marker shows the actual score."""
    zones = [
        (0, 25, RiskBand.LOW),
        (25, 50, RiskBand.MODERATE),
        (50, 75, RiskBand.HIGH),
        (75, 100, RiskBand.VERY_HIGH),
    ]
    figure, axis = plt.subplots(figsize=(7.0, 1.55), dpi=_CHART_DPI)
    try:
        for start, end, zone_band in zones:
            axis.axvspan(start, end, color=_GAUGE_ZONE_HEX[zone_band], zorder=1)
            axis.text(
                (start + end) / 2, 0.72, RISK_BAND_LABELS[zone_band].replace(" risk", ""),
                ha="center", va="center", fontsize=8, color="#1c2433", zorder=2,
            )

        marker_x = max(0.0, min(100.0, score))
        axis.plot(
            [marker_x], [0.18], marker="^", markersize=16, color="#1c2433",
            markeredgecolor="white", markeredgewidth=1.2, zorder=3,
        )
        axis.text(marker_x, -0.28, f"{js_round(score)}", ha="center", va="top", fontsize=11, fontweight="bold", color="#1c2433")

        axis.set_xlim(0, 100)
        axis.set_ylim(-0.5, 1.0)
        axis.set_xticks([0, 25, 50, 75, 100])
        axis.tick_params(axis="x", colors="#5b6472", length=0, labelsize=8)
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)
        figure.tight_layout(pad=0.3)

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        return buffer.getvalue()
    finally:
        plt.close(figure)


def _radar_chart_png(factors: list[FactorScoreResponse]) -> bytes:
    """4-axis risk radar (drought/water/vegetation/flood) — the 4 REAL
    factors only. The two placeholder factors (Future Heat Risk, Soil
    Moisture Stability) are never plotted here: a "0" or blank spoke on a
    radar chart would visually misrepresent absence-of-data as a
    confirmed low-risk score, which is exactly the fabrication this
    redesign must not do."""
    labels = [FACTOR_LABELS[f.factor] for f in factors]
    values = [f.value for f in factors]
    count = len(values)
    angles = [2 * pi * i / count for i in range(count)]
    angles_closed = angles + angles[:1]
    values_closed = values + values[:1]

    figure = plt.figure(figsize=(4.6, 4.6), dpi=_CHART_DPI)
    axis = figure.add_subplot(111, polar=True)
    try:
        axis.set_theta_offset(pi / 2)
        axis.set_theta_direction(-1)
        axis.set_ylim(0, 100)
        axis.set_yticks([25, 50, 75, 100])
        axis.set_yticklabels(["25", "50", "75", "100"], fontsize=6.5, color="#5b6472")
        axis.set_xticks(angles)
        axis.set_xticklabels(labels, fontsize=8.5, color="#1c2433")
        axis.plot(angles_closed, values_closed, color=_RADAR_FILL, linewidth=1.8)
        axis.fill(angles_closed, values_closed, color=_RADAR_FILL, alpha=0.18)
        axis.spines["polar"].set_color("#d8dee6")
        axis.grid(color="#e6e9ef")
        figure.tight_layout(pad=1.2)

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        return buffer.getvalue()
    finally:
        plt.close(figure)


def _boundary_only_png(geometry: dict) -> bytes:
    """Imagery-unavailable fallback: the real officer-drawn boundary on a
    neutral panel, with the same cartographic annotations (north arrow,
    scale bar, coordinate label) the imagery path gets. Real data,
    honestly degraded — never a placeholder."""
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
        # Approximate meters/pixel: this fallback has no real tile zoom to
        # derive resolution from, so it uses the standard ~111,320 m/degree
        # constant against the same `scale` (pixels per degree) already
        # computed above — a reasonable approximation for a "no imagery"
        # fallback, not the primary cartography path.
        meters_per_pixel = 111_320.0 / scale
        image = annotate_cartography(image, ring, meters_per_pixel)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Small building blocks (tables, chips, panels)
# ---------------------------------------------------------------------------


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


def _trend_glyph(trend: report_statistics.Trend) -> str:
    """Small inline vector-free glyph for trend direction — plain
    Unicode arrows, not an imported icon asset."""
    if not trend.available:
        return "—"
    return {"up": "▲", "down": "▼", "flat": "→"}[trend.direction]


def _trend_text(trend: report_statistics.Trend) -> str:
    if not trend.available:
        return "First assessment — no trend available"
    sign = "+" if trend.delta >= 0 else ""
    return f"{_trend_glyph(trend)} {sign}{js_round(trend.delta)} vs previous assessment"


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


def _dashboard_card(factor: FactorScoreResponse, trend: report_statistics.Trend) -> Table:
    """Page 2's fuller dashboard card: score, band, trend vs previous
    assessment, interpretation (what happened), and a recommended action
    (what to do) — more content than the compact Page-1-era factor cell."""
    _, chip_bg, chip_ink = _BAND_STYLES[factor.band]
    rows = [
        [Paragraph(FACTOR_LABELS[factor.factor], _STYLES["factor_name"]), _chip(RISK_BAND_LABELS[factor.band], chip_bg, chip_ink)],
        [
            Paragraph(f"{js_round(factor.value)} <font size=8 color='#5b6472'>/ 100</font>", _STYLES["factor_score"]),
            Paragraph(_trend_text(trend), _style("trend", fontSize=7.5, leading=10, textColor=_MUTED, alignment=TA_RIGHT)),
        ],
        [Paragraph("WHAT HAPPENED", _STYLES["card_label"]), ""],
        [Paragraph(factor_driver_text(factor), _STYLES["card_body"]), ""],
        [Paragraph("RECOMMENDED ACTION", _STYLES["card_label"]), ""],
        [Paragraph(report_findings.recommended_action(factor), _STYLES["card_body"]), ""],
    ]
    table = Table(rows, colWidths=[None, None])
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 2), (1, 2)),
                ("SPAN", (0, 3), (1, 3)),
                ("SPAN", (0, 4), (1, 4)),
                ("SPAN", (0, 5), (1, 5)),
                ("ALIGN", (1, 0), (1, 1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("TOPPADDING", (0, 2), (1, 2), 5),
                ("TOPPADDING", (0, 4), (1, 4), 5),
            ]
        )
    )
    return table


def _placeholder_card(title: str) -> Table:
    """A dashboard card for a factor with no real backing data source
    (Future Heat Risk, Soil Moisture Stability) — explicit, honest, never
    a fabricated score. No chart, no number, no band."""
    rows = [
        [Paragraph(title, _STYLES["factor_name"])],
        [Paragraph("Not yet implemented", _style("placeholder_status", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=_MUTED))],
        [
            Paragraph(
                "No data source is currently integrated for this factor. This card is reserved for a future "
                "release and intentionally shows no score.",
                _STYLES["card_body"],
            )
        ],
    ]
    table = Table(rows, colWidths=[None])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _card_grid(cells: list, columns: int = 2) -> Table:
    rows = [cells[i : i + columns] for i in range(0, len(cells), columns)]
    if rows and len(rows[-1]) < columns:
        rows[-1] += [""] * (columns - len(rows[-1]))
    width = _CONTENT_WIDTH / columns
    grid = Table(rows, colWidths=[width] * columns)
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
    return grid


def _field(label: str, value: str) -> list[Paragraph]:
    return [Paragraph(label.upper(), _STYLES["label"]), Paragraph(value, _STYLES["value"])]


def _unavailable_block(title: str, reason: str) -> list:
    return [
        Paragraph(title, _STYLES["subsection"]),
        Paragraph(f"Data unavailable — {reason}", _STYLES["unavailable"]),
        Spacer(0, 6),
    ]


def _stats_table(index_label: str, stats: report_statistics.HistoricalStats, unit: str = "") -> Table:
    def fmt(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}{unit}"

    rows = [
        [Paragraph("", _STYLES["label"]), Paragraph("Current", _STYLES["label"]), Paragraph("Median", _STYLES["label"]), Paragraph("Min", _STYLES["label"]), Paragraph("Max", _STYLES["label"]), Paragraph("Percentile", _STYLES["label"])],
        [
            Paragraph(index_label, _style("stats_row_label", fontName="Helvetica-Bold", fontSize=8, leading=11)),
            Paragraph(fmt(stats.current), _STYLES["value"]),
            Paragraph(fmt(stats.median), _STYLES["value"]),
            Paragraph(fmt(stats.minimum), _STYLES["value"]),
            Paragraph(fmt(stats.maximum), _STYLES["value"]),
            Paragraph("—" if stats.percentile is None else f"{js_round(stats.percentile)}th", _STYLES["value"]),
        ],
    ]
    widths = [_CONTENT_WIDTH * w for w in (0.24, 0.15, 0.15, 0.15, 0.15, 0.16)]
    table = Table(rows, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _year_over_year_table(points: list[ObservationPoint]) -> Table | None:
    """Yearly mean per calendar year — a simple grouping of already-stored
    monthly data, computed fresh at render time (real derivation, not a
    stored field)."""
    if not points:
        return None
    by_year: dict[int, list[float]] = {}
    for point in points:
        by_year.setdefault(point.period_start.year, []).append(point.value)
    years = sorted(by_year)
    header = [Paragraph(str(y), _STYLES["label"]) for y in years]
    values = [Paragraph(f"{sum(by_year[y]) / len(by_year[y]):.2f}", _STYLES["value"]) for y in years]
    width = _CONTENT_WIDTH / len(years)
    table = Table([header, values], colWidths=[width] * len(years))
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _BORDER),
                ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _footer_furniture(canvas: Canvas, doc) -> None:
    """Running header (pages 2+) and the base footer text; the "Page X of
    Y" page count is layered on top of this by _NumberedCanvas.save(),
    since the total page count isn't known until the whole document has
    been built once."""
    canvas.saveState()
    if doc.page > 1:
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(_BRAND)
        canvas.drawString(_MARGIN, _PAGE_HEIGHT - 10 * mm, "TerraRisk — Climate Credit Report")
        canvas.setStrokeColor(_BORDER)
        canvas.setLineWidth(0.8)
        canvas.line(_MARGIN, _PAGE_HEIGHT - 12 * mm, _PAGE_WIDTH - _MARGIN, _PAGE_HEIGHT - 12 * mm)
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(_MUTED)
    canvas.drawString(_MARGIN, 9 * mm, "TerraRisk — Climate Credit Report")
    canvas.restoreState()


class _NumberedCanvas(Canvas):
    """Standard two-pass ReportLab recipe for "Page X of Y": the total
    page count isn't known until the document has been fully built once,
    so every page's drawing is buffered and replayed once the real total
    is known."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_count(total_pages)
            super().showPage()
        super().save()

    def _draw_page_count(self, total_pages: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 6.5)
        self.setFillColor(_MUTED)
        self.drawRightString(_PAGE_WIDTH - _MARGIN, 9 * mm, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _build_page_1(report: ReportResponse, factors: list[FactorScoreResponse]) -> list:
    band_ink, band_bg, _ = _BAND_STYLES[report.overall_band]
    recommendation = build_recommendation(report)
    story: list = []

    header = Table(
        [
            [
                [Paragraph("TerraRisk", _STYLES["brand"]), Paragraph("Climate Intelligence for Agricultural Credit", _STYLES["tagline"])],
                [Paragraph("Climate Credit Report", _STYLES["doc_title"]), Paragraph("Farmer report · Service 1", _STYLES["doc_subtitle"])],
            ]
        ],
        colWidths=[_CONTENT_WIDTH * 0.62, _CONTENT_WIDTH * 0.38],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(header)
    story.append(Spacer(0, 4))
    story.append(HRFlowable(width="100%", thickness=1.6, color=_BRAND, spaceAfter=4))
    story.append(
        Paragraph(
            f"Report {report.id} · Generated {_fmt_datetime(report.computed_at)} IST · Model {report.model_version}",
            _STYLES["meta"],
        )
    )
    story.append(Spacer(0, 8))
    story.append(Paragraph("Executive Climate Credit Summary", _STYLES["page_title"]))

    # Verdict: large score, large band, confidence, assessment quality.
    quality_label = report_statistics.assessment_quality_label(report.confidence)
    verdict_rows = [
        [
            [
                Paragraph("OVERALL CLIMATE RISK", _STYLES["verdict_label"]),
                Paragraph(
                    RISK_BAND_LABELS[report.overall_band],
                    _style("verdict", fontName="Times-Bold", fontSize=28, leading=32, textColor=band_ink),
                ),
            ],
            [
                Paragraph(f"Score {js_round(report.overall_score)} / 100", _STYLES["score"]),
                Paragraph(
                    f"Confidence {js_round(report.confidence)}% · Assessment quality: {quality_label}",
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
    story.append(Spacer(0, 8))

    # Risk gauge.
    gauge_png = _gauge_chart_png(report.overall_score)
    story.append(Image(io.BytesIO(gauge_png), width=_CONTENT_WIDTH, height=_CONTENT_WIDTH * 1.55 / 7.0))
    story.append(Spacer(0, 10))

    # Metadata strip.
    meta_rows = [
        [
            _field("Village", f"{report.farm.village_name} · {report.farm.taluka_name}, {report.farm.district_name}"),
            _field("Farm area", format_area(report.farm_area_ha)),
        ],
        [
            _field("Assessment date", _fmt_date(report.computed_at)),
            _field("Model version", report.model_version),
        ],
    ]
    story.append(_panel(meta_rows, [_CONTENT_WIDTH * 0.58, _CONTENT_WIDTH * 0.42]))
    story.append(Spacer(0, 10))

    # Credit Recommendation box.
    why_bullets = recommendation_why_bullets(report, recommendation)
    recommendation_block = [
        Paragraph("Credit Recommendation", _STYLES["section"]),
        Spacer(0, 3),
        Paragraph(recommendation.summary, _STYLES["narrative"]),
        Spacer(0, 6),
        Paragraph(recommendation.action, _STYLES["recommendation_action"]),
        Spacer(0, 5),
        Paragraph("WHY", _STYLES["card_label"]),
        *[Paragraph(f"• {bullet}", _STYLES["bullet"]) for bullet in why_bullets],
    ]
    story.append(KeepTogether([_panel([[recommendation_block]], [_CONTENT_WIDTH], [("BACKGROUND", (0, 0), (-1, -1), _PANEL)])]))
    story.append(Spacer(0, 10))

    # Key Findings.
    findings = report_findings.key_findings_for_report(factors)
    findings_block = [Paragraph("Key Findings", _STYLES["section"]), Spacer(0, 4)] + [
        Paragraph(f"• {finding}", _STYLES["bullet"]) for finding in findings
    ]
    story.append(KeepTogether(findings_block))
    return story


def _build_page_2(report: ReportResponse, factors: list[FactorScoreResponse]) -> list:
    story: list = [Paragraph("Risk Dashboard", _STYLES["page_title"])]

    radar_png = _radar_chart_png(factors)
    radar_caption = Paragraph(
        "Risk radar — all four factors on one chart, on the same 0-100 risk scale. A larger shape means more "
        "risk overall; a spike toward one point means that specific factor is driving the shape.",
        _STYLES["chart_caption"],
    )
    story.append(
        KeepTogether(
            [
                Image(io.BytesIO(radar_png), width=90 * mm, height=90 * mm, hAlign="CENTER"),
                radar_caption,
            ]
        )
    )
    story.append(Spacer(0, 10))

    previous_scores = report.comparison.previous_factor_scores
    cards = []
    for factor in factors:
        previous = previous_scores.get(factor.factor.value)
        cards.append(_dashboard_card(factor, report_statistics.trend(factor.value, previous)))
    cards.append(_placeholder_card("Future Heat Risk"))
    cards.append(_placeholder_card("Soil Moisture Stability"))
    story.append(_card_grid(cards, columns=2))
    return story


def _build_page_3(report: ReportResponse) -> list:
    story: list = [Paragraph("Historical Analysis", _STYLES["page_title"])]
    story.append(
        Paragraph(
            "Three years of monthly satellite observations for this exact farm boundary — never assumed, "
            "always read back from what was actually observed. Months with no usable cloud-free imagery are "
            "omitted, not estimated.",
            _STYLES["narrative"],
        )
    )
    story.append(Spacer(0, 8))

    drought = next((f for f in report.factors if f.factor == RiskFactor.DROUGHT_RISK), None)
    ratio = drought.raw_inputs.get("rainfall_ratio_to_normal") if drought else None
    rainfall_caption = (
        f"Total rainfall per month (mm). Most recent season: {js_round(ratio * 100)}% of the 30-year seasonal normal."
        if isinstance(ratio, (int, float))
        else "Total rainfall per month (mm) over this farm."
    )

    series_specs = (
        (
            "Vegetation (NDVI)",
            "How green and dense this farm's crop canopy is — see the Methodology page for what NDVI measures.",
            report.series.ndvi, "line", _CHART_GREEN, False,
        ),
        (
            "Surface water (MNDWI)",
            "Detects standing/surface water on and around the farm — the primary Water Availability signal.",
            report.series.mndwi, "line", _CHART_BLUE, False,
        ),
        (
            "Crop moisture (NDMI)",
            "Water content in the crop canopy itself — the supporting Water Availability signal.",
            report.series.ndmi, "line", _CHART_TEAL, False,
        ),
        ("Monthly rainfall", rainfall_caption, report.series.rainfall, "bar", _CHART_PURPLE, True),
    )
    for title, caption, points, variant, color, integer_axis in series_specs:
        block: list = [Paragraph(title, _STYLES["subsection"]), Paragraph(caption, _STYLES["chart_caption"]), Spacer(0, 3)]
        if points:
            png = _chart_png(points, variant, color, integer_axis)
            block.append(Image(io.BytesIO(png), width=_CONTENT_WIDTH, height=_CONTENT_WIDTH * 2.3 / 5.35))
            block.append(Spacer(0, 3))
            stats = report_statistics.historical_stats(points)
            block.append(_stats_table(title, stats))
        else:
            block.append(Paragraph("No usable observations for this period.", _STYLES["driver"]))
        story.append(KeepTogether(block))
        story.append(Spacer(0, 10))

    if report.series.ndvi:
        story.append(Paragraph("Year-over-year comparison — NDVI (calendar-year mean)", _STYLES["subsection"]))
        story.append(Spacer(0, 3))
        yoy = _year_over_year_table(report.series.ndvi)
        if yoy is not None:
            story.append(yoy)

    return story


def _build_page_4(report: ReportResponse) -> list:
    recommendation = build_recommendation(report)
    story: list = [Paragraph("Climate Outlook", _STYLES["page_title"])]
    story.append(
        Paragraph(
            "TerraRisk's assessment is entirely backward-looking — real satellite observations of what already "
            "happened on this farm. It does not currently integrate a forward-looking seasonal forecast. The "
            "sections below say so honestly rather than estimating a number with nothing behind it.",
            _STYLES["narrative"],
        )
    )
    story.append(Spacer(0, 8))

    for title, reason in (
        ("Expected Rainfall", "no seasonal rainfall forecast data source (e.g. IMD monsoon outlook, ECMWF seasonal forecast) is currently integrated."),
        ("Temperature Outlook", "no temperature or land-surface-temperature data source is currently integrated."),
        ("Expected Vegetation Trend", "vegetation trend requires a forecast baseline, which is not available; see Historical Analysis for the real observed trend instead."),
        ("Expected Water Stress", "water-stress outlook requires a rainfall forecast, which is not available; see the Water Availability card for the real current reading."),
    ):
        story.extend(_unavailable_block(title, reason))

    story.append(Spacer(0, 4))
    story.append(Paragraph("Monitoring Recommendation", _STYLES["section"]))
    story.append(Spacer(0, 3))
    cadence = report_statistics.monitoring_cadence(
        report.overall_band, report.confidence, RECOMMENDATION_CONFIDENCE_THRESHOLD
    )
    story.append(Paragraph(cadence, _STYLES["narrative"]))
    story.append(Spacer(0, 8))

    story.append(Paragraph("Field Verification", _STYLES["section"]))
    story.append(Spacer(0, 3))
    verification_text = (
        "Recommended before proceeding."
        if field_verification_recommended(report, recommendation)
        else "Not required for a standard appraisal at this risk band and confidence level."
    )
    story.append(Paragraph(verification_text, _STYLES["narrative"]))
    return story


def _build_page_5(report: ReportResponse, map_png: bytes | None) -> list:
    story: list = [Paragraph("Farm Intelligence", _STYLES["page_title"])]

    imagery_available = map_png is not None
    map_bytes = map_png if imagery_available else _boundary_only_png(report.farm.geometry)
    story.append(Image(io.BytesIO(map_bytes), width=_CONTENT_WIDTH, height=_CONTENT_WIDTH * 700 / 1200))
    story.append(Spacer(0, 2))
    story.append(
        Paragraph(
            TILE_ATTRIBUTION if imagery_available else "Officer-drawn boundary. Satellite imagery was unavailable at render time.",
            _STYLES["attribution"],
        )
    )
    story.append(Spacer(0, 10))

    info_rows = [
        [_field("Farm area", format_area(report.farm_area_ha)), _field("Village", f"{report.farm.village_name}, {report.farm.taluka_name}")],
        [_field("Assessment ID", str(report.id)), _field("Map date", _fmt_date(report.computed_at))],
        [_field("Satellite source", "Esri World Imagery"), _field("Field officer", report.farm.officer_name)],
    ]
    story.append(_panel(info_rows, [_CONTENT_WIDTH * 0.5, _CONTENT_WIDTH * 0.5]))
    story.append(Spacer(0, 8))
    story.extend(_unavailable_block("Nearby road", "road-network data is not currently integrated."))
    return story


def _build_page_6() -> list:
    story: list = [Paragraph("Methodology", _STYLES["page_title"])]
    story.append(
        Paragraph(
            "This page explains, in plain language, every satellite measurement and statistical concept behind "
            "this report — written for lending staff, not remote-sensing specialists.",
            _STYLES["narrative"],
        )
    )
    story.append(Spacer(0, 8))

    for index_name, explanation in methodology_text.INDEX_EXPLANATIONS.items():
        story.append(KeepTogether([Paragraph(index_name, _STYLES["subsection"]), Paragraph(explanation, _STYLES["card_body"]), Spacer(0, 6)]))

    for title, text in (
        ("Confidence", methodology_text.CONFIDENCE_EXPLANATION),
        ("Cloud filtering", methodology_text.CLOUD_FILTERING_EXPLANATION),
        ("Percentile rank", methodology_text.PERCENTILE_EXPLANATION),
        ("Quality control", methodology_text.QUALITY_CONTROL_EXPLANATION),
    ):
        story.append(KeepTogether([Paragraph(title, _STYLES["subsection"]), Paragraph(text, _STYLES["card_body"]), Spacer(0, 6)]))

    story.append(Paragraph("Risk factor definitions", _STYLES["section"]))
    story.append(Spacer(0, 4))
    for name in FACTOR_ORDER:
        story.append(
            KeepTogether(
                [
                    Paragraph(FACTOR_LABELS[name], _STYLES["subsection"]),
                    Paragraph(methodology_text.FACTOR_DEFINITIONS[name], _STYLES["card_body"]),
                    Spacer(0, 5),
                ]
            )
        )
    return story


def _build_page_7(report: ReportResponse) -> list:
    story: list = [Paragraph("Audit Appendix", _STYLES["page_title"])]

    if report.audit.processing_started_at and report.audit.processing_completed_at:
        duration = report.audit.processing_completed_at - report.audit.processing_started_at
        processing_time = f"{duration.total_seconds():.0f} seconds"
    else:
        processing_time = "Not recorded for this assessment"

    missing_months = None
    if report.evidence.expected_months is not None:
        usable = len(report.series.ndvi)
        missing_months = max(0, report.evidence.expected_months - usable)

    audit_rows = [
        [_field("Processing date", _fmt_datetime(report.computed_at) + " IST"), _field("Processing time", processing_time)],
        [_field("Earth Engine SDK version", EARTH_ENGINE_SDK_VERSION), _field("Model version", report.model_version)],
        [
            _field("Confidence", f"{js_round(report.confidence)}%"),
            _field("Missing data", "Not available" if missing_months is None else f"{missing_months} of {report.evidence.expected_months} expected months"),
        ],
        [_field("Processing region", f"{report.farm.district_name}, {report.farm.taluka_name}"), _field("Report template version", str(PDF_LAYOUT_VERSION))],
    ]
    story.append(_panel(audit_rows, [_CONTENT_WIDTH * 0.5, _CONTENT_WIDTH * 0.5]))
    story.append(Spacer(0, 10))

    story.append(Paragraph("Satellite sources", _STYLES["section"]))
    story.append(Paragraph(DATA_SOURCES, _STYLES["lineage"]))
    story.append(Spacer(0, 10))

    story.append(Paragraph("Known limitations", _STYLES["section"]))
    story.append(Spacer(0, 4))
    for line in methodology_text.ASSUMPTIONS_AND_LIMITATIONS:
        story.append(Paragraph(f"• {line}", _STYLES["bullet"]))
    story.append(Spacer(0, 10))

    story.append(_panel([[[Paragraph(DISCLAIMER, _STYLES["disclaimer"])]]], [_CONTENT_WIDTH], [("BACKGROUND", (0, 0), (-1, -1), _PANEL)]))
    return story


def render_report_pdf(report: ReportResponse, map_png: bytes | None) -> bytes:
    """Typeset the full 7-page Climate Credit Report; returns the PDF bytes."""
    factors = _ordered_factors(report)

    story: list = []
    story.extend(_build_page_1(report, factors))
    story.append(PageBreak())
    story.extend(_build_page_2(report, factors))
    story.append(PageBreak())
    story.extend(_build_page_3(report))
    story.append(PageBreak())
    story.extend(_build_page_4(report))
    story.append(PageBreak())
    story.extend(_build_page_5(report, map_png))
    story.append(PageBreak())
    story.extend(_build_page_6())
    story.append(PageBreak())
    story.extend(_build_page_7(report))

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"TerraRisk Climate Credit Report — {report.farm.village_name}",
        author="TerraRisk",
        subject="Farm climate credit risk assessment (decision support)",
    )
    document.build(story, onFirstPage=_footer_furniture, onLaterPages=_footer_furniture, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
