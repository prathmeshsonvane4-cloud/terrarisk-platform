import { jsPDF } from "jspdf";

import type { components } from "@/lib/api/schema";
import { formatArea } from "@/lib/format";

import {
  STORAGE_CHANGE_BAND_PDF_COLORS,
  STORAGE_CHANGE_BANDS,
  STRESS_BAND_PDF_COLORS,
  STRESS_BANDS,
} from "../band-styles";
import { deriveWaterReportInsights } from "../insights";
import { DELINEATION_METHOD_LABELS } from "../labels";
import { numberField } from "../raw-inputs";
import { bandForFactorScore } from "../stress-factor-bands";
import type { WaterReportDetailResponse } from "../use-latest-water-report";
import { WATER_BALANCE_BAR_COLORS } from "../water-balance-chart";

type CatchmentResponse = components["schemas"]["CatchmentResponse"];
type RGB = [number, number, number];

/**
 * Client-side PDF generation (ticket M6-003) — no new backend endpoint:
 * `Do NOT modify backend APIs` rules out mirroring Service 1's
 * server-rendered `/reports/{id}/pdf` (reportlab + matplotlib,
 * app/services/reporting/pdf_renderer.py) for Water Intelligence, so
 * this builds the PDF entirely in the browser from the SAME
 * WaterReportDetailResponse the dashboard already fetched (M6-002's
 * useLatestWaterReport) — one fetch, two renderers (the on-screen
 * dashboard, and this document), never a second read or a
 * recalculation. Every number below is copied from `report`/
 * `catchment`, never re-derived; Key Insights literally calls
 * deriveWaterReportInsights() (the identical function the dashboard
 * page uses), not a re-implementation.
 *
 * "Charts rendered from existing dashboard data where possible": the
 * water-balance and surface-water visuals are redrawn as native jsPDF
 * vector shapes (rects, not a captured screenshot) using the SAME
 * validated colors the on-screen recharts/percentile components use
 * (WATER_BALANCE_BAR_COLORS, band PDF-color maps) — vector output looks
 * crisp at print resolution, which a rasterized DOM capture would not,
 * and needed no second charting dependency. No monthly series exists in
 * the response (see water-balance-chart.tsx's own docstring for why) —
 * this PDF doesn't fabricate one either.
 */

const PAGE_WIDTH = 210;
const PAGE_HEIGHT = 297;
const MARGIN = 20;
const CONTENT_WIDTH = PAGE_WIDTH - MARGIN * 2;
const FOOTER_RULE_Y = PAGE_HEIGHT - 15;
const FOOTER_TEXT_Y = PAGE_HEIGHT - 10;
const CONTENT_BOTTOM_LIMIT = FOOTER_RULE_Y - 6;
const CONTENT_TOP_START = 28;

// Matches the dataviz skill's own chart-chrome ink roles (primary/
// secondary/muted) — this PDF reuses the identical roles, not a
// separately invented text-color scheme.
const INK: RGB = [11, 11, 11];
const MUTED: RGB = [82, 81, 78];
const HAIRLINE: RGB = [225, 224, 217];
// #1d4ed8 — this app's own existing "blue" series color
// (monthly-trend-chart.tsx), reused as the brand accent rather than a
// new hex invented for this PDF.
const BRAND: RGB = [29, 78, 216];

function ensureSpace(doc: jsPDF, y: number, needed: number, pageLabel: string): number {
  if (y + needed <= CONTENT_BOTTOM_LIMIT) return y;
  doc.addPage();
  drawSectionMarker(doc, pageLabel);
  return CONTENT_TOP_START;
}

/** A faint running label in the page's top-right corner so a reader who
 * jumps to a page mid-document (or prints a subset) still knows what
 * section they're in — set once per addPage() call, not per section, so
 * a section spanning a page break still shows a coherent label. */
function drawSectionMarker(doc: jsPDF, label: string): void {
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.setTextColor(...MUTED);
  doc.text(label, PAGE_WIDTH - MARGIN, 14, { align: "right" });
}

function sectionHeading(doc: jsPDF, title: string, y: number): number {
  doc.setFont("helvetica", "bold");
  doc.setFontSize(13);
  doc.setTextColor(...INK);
  doc.text(title, MARGIN, y);
  doc.setDrawColor(...BRAND);
  doc.setLineWidth(0.6);
  doc.line(MARGIN, y + 2, MARGIN + 14, y + 2);
  return y + 9;
}

function bodyText(doc: jsPDF, text: string, y: number, options: { size?: number; color?: RGB } = {}): number {
  doc.setFont("helvetica", "normal");
  doc.setFontSize(options.size ?? 10);
  doc.setTextColor(...(options.color ?? INK));
  const lines: string[] = doc.splitTextToSize(text, CONTENT_WIDTH);
  doc.text(lines, MARGIN, y);
  return y + lines.length * ((options.size ?? 10) * 0.42) + 3;
}

function keyValueRow(doc: jsPDF, label: string, value: string, y: number): number {
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9.5);
  doc.setTextColor(...MUTED);
  doc.text(label, MARGIN, y);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(...INK);
  doc.text(value, MARGIN + 65, y);
  return y + 6.5;
}

function bandDot(doc: jsPDF, x: number, y: number, label: string, color: RGB): void {
  doc.setFillColor(...color);
  doc.circle(x, y - 1.2, 1.4, "F");
  doc.setFont("helvetica", "bold");
  doc.setFontSize(9);
  doc.setTextColor(...color);
  doc.text(label, x + 4, y);
}

function drawCoverPage(doc: jsPDF, report: WaterReportDetailResponse, catchment: CatchmentResponse): void {
  doc.setFillColor(...BRAND);
  doc.rect(0, 0, PAGE_WIDTH, 85, "F");

  doc.setTextColor(255, 255, 255);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(28);
  doc.text("TerraRisk", MARGIN, 38);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(11);
  doc.text("Climate Intelligence for Agricultural Credit", MARGIN, 48);

  doc.setFont("helvetica", "bold");
  doc.setFontSize(15);
  doc.text("Water Intelligence Report", MARGIN, 70);

  doc.setTextColor(...INK);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(22);
  const nameLines: string[] = doc.splitTextToSize(catchment.name, CONTENT_WIDTH);
  doc.text(nameLines, MARGIN, 112);

  const infoY = 112 + nameLines.length * 8 + 8;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(11);
  doc.setTextColor(...MUTED);
  doc.text(`${formatArea(catchment.area_ha)} · ${DELINEATION_METHOD_LABELS[catchment.delineation_method]}`, MARGIN, infoY);
  doc.text(
    `Generated ${new Date(report.generated_at).toLocaleString("en-IN", { dateStyle: "long", timeStyle: "short" })}`,
    MARGIN,
    infoY + 7,
  );

  doc.setDrawColor(...BRAND);
  doc.setLineWidth(0.8);
  doc.line(MARGIN, PAGE_HEIGHT - 32, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 32);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  doc.setTextColor(...MUTED);
  const coverNote: string[] = doc.splitTextToSize(
    "Generated from satellite-derived observations. Decision support only — see the Disclaimer section before acting on any figure in this report.",
    CONTENT_WIDTH,
  );
  doc.text(coverNote, MARGIN, PAGE_HEIGHT - 24);
}

function drawCatchmentSummary(doc: jsPDF, y: number, report: WaterReportDetailResponse, catchment: CatchmentResponse): number {
  y = sectionHeading(doc, "Catchment Summary", y);
  y = keyValueRow(doc, "Catchment name", catchment.name, y);
  y = keyValueRow(doc, "Catchment area", formatArea(catchment.area_ha), y);
  y = keyValueRow(doc, "Delineation method", DELINEATION_METHOD_LABELS[catchment.delineation_method], y);
  y = keyValueRow(
    doc,
    "Report generated",
    new Date(report.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }),
    y,
  );
  y = keyValueRow(doc, "Job status", report.job.status, y);
  return y + 6;
}

function drawWaterBalanceChart(
  doc: jsPDF,
  y: number,
  terms: { label: string; value: number; color: RGB }[],
): number {
  if (terms.length === 0) return y;
  const chartHeight = 44;
  const barWidth = 22;
  const gap = (CONTENT_WIDTH - barWidth * terms.length) / (terms.length + 1);

  const positiveMax = Math.max(0, ...terms.map((t) => t.value));
  const negativeMin = Math.min(0, ...terms.map((t) => t.value));
  const range = positiveMax - negativeMin || 1;
  const scale = (chartHeight - 14) / range;
  const zeroLineY = y + 6 + positiveMax * scale;

  doc.setDrawColor(...HAIRLINE);
  doc.setLineWidth(0.2);
  doc.line(MARGIN, zeroLineY, MARGIN + CONTENT_WIDTH, zeroLineY);

  terms.forEach((term, index) => {
    const x = MARGIN + gap + index * (barWidth + gap);
    const barHeight = Math.max(Math.abs(term.value) * scale, 0.5);
    const barY = term.value >= 0 ? zeroLineY - barHeight : zeroLineY;
    doc.setFillColor(...term.color);
    doc.rect(x, barY, barWidth, barHeight, "F");

    doc.setFont("helvetica", "bold");
    doc.setFontSize(8);
    doc.setTextColor(...INK);
    doc.text(`${term.value.toFixed(0)}`, x + barWidth / 2, term.value >= 0 ? barY - 2 : barY + barHeight + 5, {
      align: "center",
    });

    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    doc.setTextColor(...MUTED);
    doc.text(term.label, x + barWidth / 2, y + chartHeight + 4, { align: "center" });
  });

  return y + chartHeight + 10;
}

function drawWaterBalance(doc: jsPDF, y: number, report: WaterReportDetailResponse): number {
  const wb = report.water_balance;
  y = sectionHeading(doc, "Water Balance", y);

  y = bodyText(
    doc,
    `${new Date(wb.period_start).toLocaleDateString("en-IN", { dateStyle: "medium" })} – ${new Date(wb.period_end).toLocaleDateString("en-IN", { dateStyle: "medium" })} · Data completeness ${wb.data_completeness.toFixed(0)}% · ${wb.calibration_status.replace(/_/g, " ")}`,
    y,
    { size: 9, color: MUTED },
  );

  y = keyValueRow(doc, "Total rainfall", wb.rainfall_mm === null ? "—" : `${wb.rainfall_mm.toFixed(1)} mm`, y);
  y = keyValueRow(doc, "Evapotranspiration (ET)", wb.et_mm === null ? "—" : `${wb.et_mm.toFixed(1)} mm`, y);
  y = keyValueRow(doc, "Runoff", wb.runoff_mm === null ? "—" : `${wb.runoff_mm.toFixed(1)} mm`, y);
  // "Recharge" and "Storage change" are the same backend field —
  // WaterBalanceEngine computes no separate recharge term (P - ET - Q =
  // dS is the whole equation) — labeled to say so, not repeated twice.
  y = keyValueRow(
    doc,
    "Recharge (storage change)",
    wb.storage_change_mm === null ? "—" : `${wb.storage_change_mm.toFixed(1)} mm`,
    y,
  );
  bandDot(doc, MARGIN, y, STORAGE_CHANGE_BANDS[wb.storage_change_band].label, STORAGE_CHANGE_BAND_PDF_COLORS[wb.storage_change_band]);
  y += 9;

  const terms = [
    { label: "Rainfall", value: wb.rainfall_mm, color: hexToRgb(WATER_BALANCE_BAR_COLORS.rainfall) },
    { label: "ET", value: wb.et_mm, color: hexToRgb(WATER_BALANCE_BAR_COLORS.et) },
    { label: "Runoff", value: wb.runoff_mm, color: hexToRgb(WATER_BALANCE_BAR_COLORS.runoff) },
    { label: "Storage change", value: wb.storage_change_mm, color: hexToRgb(WATER_BALANCE_BAR_COLORS.storageChange) },
  ].filter((t): t is { label: string; value: number; color: RGB } => t.value !== null);

  y = ensureSpace(doc, y, 60, "Water Balance");
  y = drawWaterBalanceChart(doc, y, terms);
  return y + 6;
}

function drawRechargeStress(doc: jsPDF, y: number, report: WaterReportDetailResponse): number {
  const rs = report.recharge_stress;
  y = sectionHeading(doc, "Recharge Stress", y);

  doc.setFont("helvetica", "bold");
  doc.setFontSize(20);
  doc.setTextColor(...INK);
  doc.text(`${Math.round(rs.stress_score)} / 100`, MARGIN, y + 5);
  bandDot(doc, MARGIN, y + 13, STRESS_BANDS[rs.stress_band].label, STRESS_BAND_PDF_COLORS[rs.stress_band]);

  const confidence = numberField(rs.raw_inputs, "confidence");
  if (confidence !== null) {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(...MUTED);
    doc.text(`Confidence ${Math.round(confidence)}%`, MARGIN + 60, y + 13);
  }
  y += 22;

  const factors: { label: string; rawLabel: string; stressScore: number | null }[] = [
    {
      label: "Rainfall anomaly",
      rawLabel: rs.rainfall_anomaly_ratio === null ? "—" : rs.rainfall_anomaly_ratio.toFixed(2),
      stressScore: numberField(rs.raw_inputs, "rainfall_stress"),
    },
    {
      label: "Vegetation condition (VCI)",
      rawLabel: rs.vci === null ? "—" : `${rs.vci.toFixed(0)}%`,
      stressScore: numberField(rs.raw_inputs, "vegetation_stress"),
    },
    {
      label: "Surface water trend",
      rawLabel: rs.surface_water_trend === null ? "—" : `${rs.surface_water_trend.toFixed(0)}%`,
      stressScore: numberField(rs.raw_inputs, "surface_water_stress"),
    },
  ];

  doc.setFont("helvetica", "bold");
  doc.setFontSize(9.5);
  doc.setTextColor(...MUTED);
  doc.text("Factor", MARGIN, y);
  doc.text("Value", MARGIN + 85, y);
  doc.text("Stress contribution", MARGIN + 110, y);
  y += 2;
  doc.setDrawColor(...HAIRLINE);
  doc.line(MARGIN, y, MARGIN + CONTENT_WIDTH, y);
  y += 6;

  for (const factor of factors) {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9.5);
    doc.setTextColor(...INK);
    doc.text(factor.label, MARGIN, y);
    doc.text(factor.rawLabel, MARGIN + 85, y);
    if (factor.stressScore !== null) {
      const band = bandForFactorScore(factor.stressScore);
      bandDot(doc, MARGIN + 110, y, `${Math.round(factor.stressScore)} / 100`, STRESS_BAND_PDF_COLORS[band]);
    } else {
      doc.setTextColor(...MUTED);
      doc.text("—", MARGIN + 110, y);
    }
    y += 7;
  }

  return y + 5;
}

function drawSurfaceWater(doc: jsPDF, y: number, report: WaterReportDetailResponse): number {
  const rs = report.recharge_stress;
  y = sectionHeading(doc, "Surface Water", y);

  y = bodyText(doc, "Surface water trend — current extent's position within its own historical range.", y, {
    size: 9,
    color: MUTED,
  });
  y += 2;

  if (rs.surface_water_trend === null) {
    y = bodyText(doc, "No surface-water reading available for this period.", y);
    return y + 4;
  }

  const percentile = Math.max(0, Math.min(100, rs.surface_water_trend));
  const barHeight = 4;
  doc.setFillColor(230, 229, 222);
  doc.rect(MARGIN, y, CONTENT_WIDTH, barHeight, "F");
  doc.setFillColor(...hexToRgb("#2a78d6"));
  doc.rect(MARGIN, y, (CONTENT_WIDTH * percentile) / 100, barHeight, "F");

  doc.setFont("helvetica", "normal");
  doc.setFontSize(7.5);
  doc.setTextColor(...MUTED);
  doc.text("Lowest on record", MARGIN, y + barHeight + 5);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(...INK);
  doc.text(`${Math.round(percentile)}th percentile`, MARGIN + CONTENT_WIDTH / 2, y + barHeight + 5, { align: "center" });
  doc.setFont("helvetica", "normal");
  doc.setTextColor(...MUTED);
  doc.text("Highest on record", MARGIN + CONTENT_WIDTH, y + barHeight + 5, { align: "right" });
  y += barHeight + 14;

  const stressContribution = numberField(rs.raw_inputs, "surface_water_stress");
  y = keyValueRow(
    doc,
    "Surface water stress contribution",
    stressContribution === null ? "—" : `${stressContribution.toFixed(0)}%`,
    y,
  );
  return y + 4;
}

function drawGroundwater(doc: jsPDF, y: number, report: WaterReportDetailResponse): number {
  const wb = report.water_balance;
  const rs = report.recharge_stress;
  y = sectionHeading(doc, "Groundwater", y);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(9.5);
  doc.setTextColor(...MUTED);
  doc.text("Recharge trend (from water balance)", MARGIN, y);
  bandDot(doc, MARGIN, y + 7, STORAGE_CHANGE_BANDS[wb.storage_change_band].label, STORAGE_CHANGE_BAND_PDF_COLORS[wb.storage_change_band]);

  doc.text("Stress indicator", MARGIN + 85, y);
  bandDot(doc, MARGIN + 85, y + 7, `${STRESS_BANDS[rs.stress_band].label} · ${Math.round(rs.stress_score)}`, STRESS_BAND_PDF_COLORS[rs.stress_band]);
  y += 18;

  if (rs.cgwb_category) {
    doc.setFont("helvetica", "bold");
    doc.setFontSize(10.5);
    doc.setTextColor(...INK);
    doc.text(`CGWB block-scale category: ${rs.cgwb_category}`, MARGIN, y);
    y += 6;
    if (rs.cgwb_category_as_of) {
      doc.setFont("helvetica", "normal");
      doc.setFontSize(9);
      doc.setTextColor(...MUTED);
      doc.text(
        `As of ${new Date(rs.cgwb_category_as_of).toLocaleDateString("en-IN", { dateStyle: "medium" })}`,
        MARGIN,
        y,
      );
      y += 6;
    }
    y = bodyText(doc, "Government block-scale context — never blended numerically into the stress score above.", y, {
      size: 8.5,
      color: MUTED,
    });
  } else {
    y = bodyText(doc, "CGWB category not yet available for this catchment's block.", y, { size: 9.5, color: MUTED });
  }

  return y + 4;
}

function drawInsights(doc: jsPDF, y: number, report: WaterReportDetailResponse): number {
  y = sectionHeading(doc, "Key Insights", y);
  const insights = deriveWaterReportInsights(report);

  if (insights.length === 0) {
    return bodyText(doc, "No notable observations for this report.", y) + 4;
  }

  for (const insight of insights) {
    y = ensureSpace(doc, y, 10, "Key Insights");
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9.5);
    doc.setTextColor(...INK);
    const lines: string[] = doc.splitTextToSize(`•  ${insight}`, CONTENT_WIDTH - 3);
    doc.text(lines, MARGIN, y);
    y += lines.length * 4.5 + 2.5;
  }
  return y + 4;
}

function drawDisclaimer(doc: jsPDF, y: number): number {
  y = sectionHeading(doc, "Disclaimer", y);
  y = bodyText(
    doc,
    "This report is decision support only, generated by TerraRisk's Water Intelligence service from satellite " +
      "observations (rainfall, evapotranspiration, vegetation condition, and surface-water extent). Water balance " +
      "figures assume a closed catchment with no lateral subsurface flow and a single, literature-typical Curve " +
      "Number, and have not been checked against field measurements — calibration status is shown as " +
      "\"uncalibrated\" alongside every figure above for exactly this reason. CGWB groundwater categories are " +
      "block-scale government context, never blended numerically into the recharge-stress score. This report is " +
      "not a substitute for an on-ground hydrogeological survey, and the credit or investment decision remains " +
      "with the reader.",
    y,
    { size: 8.5, color: MUTED },
  );
  return y + 4;
}

function hexToRgb(hex: string): RGB {
  const clean = hex.replace("#", "");
  return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)];
}

function drawFooters(doc: jsPDF): void {
  const totalPages = doc.getNumberOfPages();
  for (let page = 2; page <= totalPages; page += 1) {
    doc.setPage(page);
    doc.setDrawColor(...HAIRLINE);
    doc.setLineWidth(0.2);
    doc.line(MARGIN, FOOTER_RULE_Y, PAGE_WIDTH - MARGIN, FOOTER_RULE_Y);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(8);
    doc.setTextColor(...BRAND);
    doc.text("TerraRisk", MARGIN, FOOTER_TEXT_Y);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...MUTED);
    doc.text(`Page ${page - 1} of ${totalPages - 1}`, PAGE_WIDTH - MARGIN, FOOTER_TEXT_Y, { align: "right" });
  }
}

/** The reference-boundary green the on-screen map already uses
 * (`#16a34a`, catchment-map.tsx's `setGeoJsonOverlay` call) — reused so
 * the printed figure and the screen agree on what green means. */
const REFERENCE_GREEN: RGB = [22, 163, 74];

const MAP_HEIGHT = 76;
const METRES_PER_DEGREE_LAT = 110_574;

/** Geometry for the one map in this report. Both layers are optional:
 * a catchment created by Draw or Upload has no `admin_boundary_id` and
 * therefore no village polygon in any endpoint, in which case the map is
 * skipped rather than faked. */
export interface WaterReportMapContext {
  village: GeoJSON.Geometry | null;
  villageName: string | null;
  villageAreaHa: number | null;
  /** The parent taluka, drawn as surrounding context. */
  taluka: GeoJSON.Geometry | null;
  talukaName: string | null;
}

function eachRing(geometry: GeoJSON.Geometry, visit: (ring: [number, number][]) => void): void {
  if (geometry.type === "Polygon") {
    for (const ring of geometry.coordinates) visit(ring as [number, number][]);
  } else if (geometry.type === "MultiPolygon") {
    for (const polygon of geometry.coordinates) for (const ring of polygon) visit(ring as [number, number][]);
  }
}

/** Equirectangular projection with a cos(lat) correction — exact enough
 * at taluka extent (tens of km) and keeps north straight up, which is
 * what makes a single static north arrow honest. */
function makeProjector(geometries: GeoJSON.Geometry[], box: { x: number; y: number; w: number; h: number }) {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const geometry of geometries) {
    eachRing(geometry, (ring) => {
      for (const [lon, lat] of ring) {
        minLon = Math.min(minLon, lon);
        maxLon = Math.max(maxLon, lon);
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
      }
    });
  }
  if (!Number.isFinite(minLon)) return null;

  const midLat = (minLat + maxLat) / 2;
  const lonScale = Math.cos((midLat * Math.PI) / 180);
  const spanX = Math.max((maxLon - minLon) * lonScale, 1e-9);
  const spanY = Math.max(maxLat - minLat, 1e-9);
  const scale = Math.min(box.w / spanX, box.h / spanY) * 0.9; // 10% breathing room
  const offsetX = box.x + (box.w - spanX * scale) / 2;
  const offsetY = box.y + (box.h - spanY * scale) / 2;

  return {
    project: ([lon, lat]: [number, number]): [number, number] => [
      offsetX + (lon - minLon) * lonScale * scale,
      // PDF y grows downward; latitude grows upward.
      offsetY + (maxLat - lat) * scale,
    ],
    /** Ground metres represented by one page millimetre. */
    metresPerMm: METRES_PER_DEGREE_LAT / scale,
  };
}

function drawGeometry(
  doc: jsPDF,
  geometry: GeoJSON.Geometry,
  project: (point: [number, number]) => [number, number],
  options: { stroke: RGB; fill?: RGB; lineWidth: number },
): void {
  doc.setDrawColor(...options.stroke);
  doc.setLineWidth(options.lineWidth);
  if (options.fill) doc.setFillColor(...options.fill);

  eachRing(geometry, (ring) => {
    if (ring.length < 3) return;
    const points = ring.map(project);
    const [startX, startY] = points[0];
    const deltas: [number, number][] = [];
    for (let i = 1; i < points.length; i += 1) {
      deltas.push([points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]]);
    }
    doc.lines(deltas, startX, startY, [1, 1], options.fill ? "FD" : "S", true);
  });
}

function drawNorthArrow(doc: jsPDF, x: number, y: number): void {
  doc.setFillColor(...INK);
  doc.triangle(x, y, x - 1.8, y + 4.6, x + 1.8, y + 4.6, "F");
  doc.setFont("helvetica", "bold");
  doc.setFontSize(7);
  doc.setTextColor(...INK);
  doc.text("N", x, y + 8.4, { align: "center" });
}

/** A round-number scale bar, chosen from the map's own ground scale
 * rather than a fixed length, so the printed figure is measurable. */
function drawScaleBar(doc: jsPDF, x: number, y: number, metresPerMm: number): void {
  const targetMm = 26;
  const rawMetres = targetMm * metresPerMm;
  const niceSteps = [100, 200, 500, 1000, 2000, 5000, 10_000, 20_000, 50_000];
  const metres = niceSteps.reduce((best, step) =>
    Math.abs(step - rawMetres) < Math.abs(best - rawMetres) ? step : best,
  );
  const barMm = metres / metresPerMm;

  doc.setDrawColor(...INK);
  doc.setFillColor(...INK);
  doc.setLineWidth(0.3);
  doc.rect(x, y, barMm / 2, 1.4, "F");
  doc.rect(x + barMm / 2, y, barMm / 2, 1.4, "S");

  doc.setFont("helvetica", "normal");
  doc.setFontSize(7);
  doc.setTextColor(...MUTED);
  doc.text("0", x, y - 1);
  doc.text(metres >= 1000 ? `${metres / 1000} km` : `${metres} m`, x + barMm, y - 1, { align: "right" });
}

/**
 * The report's one map: the administrative village this report is linked
 * to, drawn inside its taluka for locational context, with a north arrow
 * and a scale bar.
 *
 * Deliberately honest about one limit: `CatchmentResponse` carries no
 * geometry, so an AOI that was reshaped away from the village boundary
 * cannot be drawn here. Rather than imply the green outline IS the
 * analysed area, the caption states the analysed area numerically and
 * flags when it differs materially from the village — which is exactly
 * the case where the two are not the same shape.
 */
function drawLocationMap(
  doc: jsPDF,
  y: number,
  catchment: CatchmentResponse,
  context: WaterReportMapContext,
): number {
  if (!context.village) return y;

  y = sectionHeading(doc, "Location", y);

  const box = { x: MARGIN, y, w: CONTENT_WIDTH, h: MAP_HEIGHT };
  const layers = [context.taluka, context.village].filter((geometry): geometry is GeoJSON.Geometry => Boolean(geometry));
  const projector = makeProjector(layers, box);
  if (!projector) return y;

  doc.setFillColor(250, 250, 249);
  doc.setDrawColor(...HAIRLINE);
  doc.setLineWidth(0.3);
  doc.rect(box.x, box.y, box.w, box.h, "FD");

  if (context.taluka) {
    drawGeometry(doc, context.taluka, projector.project, { stroke: HAIRLINE, fill: [242, 241, 237], lineWidth: 0.4 });
  }
  drawGeometry(doc, context.village, projector.project, { stroke: REFERENCE_GREEN, fill: [214, 240, 223], lineWidth: 0.7 });

  drawNorthArrow(doc, box.x + box.w - 8, box.y + 5);
  drawScaleBar(doc, box.x + 5, box.y + box.h - 5, projector.metresPerMm);

  y = box.y + box.h + 5;

  const villageLabel = context.villageName ?? "Selected village";
  const talukaLabel = context.talukaName ? `, shown within ${context.talukaName} taluka` : "";
  y = bodyText(doc, `${villageLabel} administrative boundary${talukaLabel}. North is up.`, y, { size: 9 });

  // If the AOI was reshaped, the green outline is not the analysed area
  // — say so rather than let the reader assume otherwise.
  const villageArea = context.villageAreaHa;
  const differs = villageArea !== null && Math.abs(catchment.area_ha - villageArea) / villageArea > 0.02;
  y = bodyText(
    doc,
    differs
      ? `Analysed area ${formatArea(catchment.area_ha)} — the area of interest was adjusted and does not match the village boundary drawn above (${formatArea(villageArea)}).`
      : `Analysed area ${formatArea(catchment.area_ha)}.`,
    y,
    { size: 9, color: MUTED },
  );

  return y + 3;
}

export function generateWaterReportPdf(
  report: WaterReportDetailResponse,
  catchment: CatchmentResponse,
  mapContext?: WaterReportMapContext,
): jsPDF {
  const doc = new jsPDF({ unit: "mm", format: "a4" });

  drawCoverPage(doc, report, catchment);

  doc.addPage();
  drawSectionMarker(doc, "Catchment Summary");
  let y = CONTENT_TOP_START;
  y = drawCatchmentSummary(doc, y, report, catchment);

  // Where before what: the reader should see the place this report is
  // about before any of its numbers.
  if (mapContext?.village) {
    y = ensureSpace(doc, y, MAP_HEIGHT + 24, "Location");
    y = drawLocationMap(doc, y, catchment, mapContext);
  }

  y = ensureSpace(doc, y, 80, "Water Balance");
  y = drawWaterBalance(doc, y, report);

  y = ensureSpace(doc, y, 70, "Recharge Stress");
  y = drawRechargeStress(doc, y, report);

  y = ensureSpace(doc, y, 40, "Surface Water");
  y = drawSurfaceWater(doc, y, report);

  y = ensureSpace(doc, y, 40, "Groundwater");
  y = drawGroundwater(doc, y, report);

  y = ensureSpace(doc, y, 30, "Key Insights");
  y = drawInsights(doc, y, report);

  y = ensureSpace(doc, y, 40, "Disclaimer");
  drawDisclaimer(doc, y);

  drawFooters(doc);

  return doc;
}
