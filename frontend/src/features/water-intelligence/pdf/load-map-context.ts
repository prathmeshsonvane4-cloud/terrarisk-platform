import type { components } from "@/lib/api/schema";

import { fetchAdminBoundaryChildren } from "../select-area/use-admin-boundary-children";
import { fetchAdminBoundaryDetail } from "../select-area/use-admin-boundary-detail";
import type { WaterReportMapContext } from "./generate-water-report-pdf";

type CatchmentResponse = components["schemas"]["CatchmentResponse"];

const EMPTY: WaterReportMapContext = {
  village: null,
  villageName: null,
  villageAreaHa: null,
  taluka: null,
  talukaName: null,
};

/**
 * Gathers the geometry for the PDF's one map, using only endpoints that
 * already exist.
 *
 * The village comes straight from `catchment.admin_boundary_id`. The
 * taluka — drawn underneath as locational context — needs a short walk
 * down the hierarchy, because `AdminBoundaryDetail` resolves its
 * ancestors by *name* but not by id, and the list endpoint is the only
 * way to turn a name back into an id. That is three small, already-cached
 * list calls (states, districts, talukas) plus one detail call, and it
 * avoids adding a backend field purely for this report.
 *
 * Every step degrades to "no map" rather than throwing: a Draw or Upload
 * catchment has no `admin_boundary_id` at all, and a PDF that is missing
 * its locator is still a usable report, whereas a download that fails
 * outright is not.
 */
export async function loadWaterReportMapContext(catchment: CatchmentResponse): Promise<WaterReportMapContext> {
  if (!catchment.admin_boundary_id) return EMPTY;

  try {
    const village = await fetchAdminBoundaryDetail(catchment.admin_boundary_id);
    const base: WaterReportMapContext = {
      village: village.geometry as unknown as GeoJSON.Geometry,
      villageName: village.village ?? village.name,
      villageAreaHa: village.area_ha,
      taluka: null,
      talukaName: village.taluka ?? null,
    };

    if (!village.state || !village.district || !village.taluka) return base;

    const states = await fetchAdminBoundaryChildren(null);
    const stateRow = states.find((row) => row.name === village.state);
    if (!stateRow) return base;

    const districts = await fetchAdminBoundaryChildren(stateRow.id);
    const districtRow = districts.find((row) => row.name === village.district);
    if (!districtRow) return base;

    const talukas = await fetchAdminBoundaryChildren(districtRow.id);
    const talukaRow = talukas.find((row) => row.name === village.taluka);
    if (!talukaRow) return base;

    const taluka = await fetchAdminBoundaryDetail(talukaRow.id);
    return { ...base, taluka: taluka.geometry as unknown as GeoJSON.Geometry };
  } catch {
    // A locator is a nice-to-have; never let it block the download.
    return EMPTY;
  }
}
