import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";

import type { WaterReportDetailResponse } from "../use-latest-water-report";
import { generateWaterReportPdf, type WaterReportMapContext } from "./generate-water-report-pdf";

type CatchmentResponse = components["schemas"]["CatchmentResponse"];

// The real Maski (Raichur) boundary, trimmed to 8 vertices — a genuine
// irregular outline rather than a box, so the projection and the
// polygon-drawing path are exercised on the shape they actually receive.
const MASKI: GeoJSON.Polygon = {
  type: "Polygon",
  coordinates: [
    [
      [76.634561, 15.996653],
      [76.657898, 16.000067],
      [76.683959, 15.990179],
      [76.688548, 15.982218],
      [76.676254, 15.949158],
      [76.661553, 15.911806],
      [76.620828, 15.94157],
      [76.634561, 15.996653],
    ],
  ],
};

const TALUKA: GeoJSON.Polygon = {
  type: "Polygon",
  coordinates: [
    [
      [76.55, 15.85],
      [76.78, 15.85],
      [76.78, 16.06],
      [76.55, 16.06],
      [76.55, 15.85],
    ],
  ],
};

function catchment(overrides: Partial<CatchmentResponse> = {}): CatchmentResponse {
  return {
    id: "c-1",
    name: "Maski (village AOI)",
    area_ha: 4990.9,
    delineation_method: "manual",
    organization_id: null,
    admin_boundary_id: "b-1",
    resolution_flags: [],
    created_by: "00000000-0000-0000-0000-000000000000",
    created_at: "2026-08-01T00:00:00Z",
    ...overrides,
  } as CatchmentResponse;
}

function report(): WaterReportDetailResponse {
  return {
    catchment_id: "c-1",
    generated_at: "2026-08-05T00:00:00Z",
    job: { job_id: "j-1", status: "done", created_at: "2026-08-05T00:00:00Z" },
    water_balance: {
      rainfall_mm: 1692.31,
      et_mm: 339.94,
      runoff_mm: 688.1,
      storage_change_mm: 664.27,
      storage_change_band: "much_above_normal",
      data_completeness: 100,
      calibration_status: "uncalibrated",
      closed_catchment_assumed: true,
      resolution_flags: [],
      period_start: "2023-08-01",
      period_end: "2026-08-01",
      model_version: "wb-1.0",
    },
    recharge_stress: {
      stress_score: 44.19,
      stress_band: "moderate",
      baseline_window: "climatology_30yr",
      rainfall_anomaly_ratio: 1.26,
      vci: 21.56,
      surface_water_trend: 82.857,
      cgwb_category: null,
      cgwb_category_as_of: null,
      raw_inputs: { confidence: 97.2, rainfall_stress: 37, vegetation_stress: 78, surface_water_stress: 17 },
    },
  } as unknown as WaterReportDetailResponse;
}

const FULL_CONTEXT: WaterReportMapContext = {
  village: MASKI,
  villageName: "Maski",
  villageAreaHa: 4990.9,
  taluka: TALUKA,
  talukaName: "Maski",
};

function pageText(doc: ReturnType<typeof generateWaterReportPdf>): string {
  // jsPDF keeps every page's content stream in its internal pages array;
  // joining them is enough to assert which sections were emitted.
  const pages = (doc as unknown as { internal: { pages: string[][] } }).internal.pages;
  return pages.flat().join("\n");
}

describe("generateWaterReportPdf — location map", () => {
  it("emits a Location section when village geometry is supplied", () => {
    const doc = generateWaterReportPdf(report(), catchment(), FULL_CONTEXT);
    expect(pageText(doc)).toContain("Location");
  });

  it("omits the map entirely for a Draw/Upload catchment that has no village boundary", () => {
    // No admin_boundary_id means no polygon exists in any endpoint. The
    // report must still generate — a missing locator is not a failure.
    const doc = generateWaterReportPdf(report(), catchment({ admin_boundary_id: null }), {
      village: null,
      villageName: null,
      villageAreaHa: null,
      taluka: null,
      talukaName: null,
    });
    expect(pageText(doc)).not.toContain("Location");
    expect(pageText(doc)).toContain("Water Balance");
  });

  it("still generates when the map context is omitted altogether (backwards compatible)", () => {
    const doc = generateWaterReportPdf(report(), catchment());
    expect(pageText(doc)).toContain("Water Balance");
  });

  it("renders without a taluka, so a missing context layer never blocks the locator", () => {
    const doc = generateWaterReportPdf(report(), catchment(), { ...FULL_CONTEXT, taluka: null, talukaName: null });
    expect(pageText(doc)).toContain("Location");
  });

  it("keeps every pre-existing report section — the map is additive, not a redesign", () => {
    const text = pageText(generateWaterReportPdf(report(), catchment(), FULL_CONTEXT));
    for (const section of ["Catchment Summary", "Water Balance", "Recharge Stress", "Surface Water", "Groundwater", "Key Insights", "Disclaimer"]) {
      expect(text).toContain(section);
    }
  });

  it("flags in the caption when the analysed area does not match the village boundary", () => {
    // An AOI reshaped away from the administrative boundary: the drawn
    // outline is then NOT the analysed area, and the PDF must say so.
    const doc = generateWaterReportPdf(report(), catchment({ area_ha: 1200 }), FULL_CONTEXT);
    expect(pageText(doc)).toContain("adjusted");
  });
});
