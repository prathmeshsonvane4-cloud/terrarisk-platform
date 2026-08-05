"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchAdminBoundaryChildren } from "../select-area/use-admin-boundary-children";
import { useAdminBoundaryDetail } from "../select-area/use-admin-boundary-detail";
import type { CatchmentDetailResponse } from "../use-catchment-detail";
import { deriveAnalysedGeometry, filterNeighbours } from "./spatial-context-logic";

export interface SpatialNeighbour {
  id: string;
  name: string;
  geometry: GeoJSON.Geometry;
}

export interface SpatialContext {
  village: GeoJSON.Geometry | null;
  villageName: string | null;
  villageAreaHa: number | null;
  taluka: GeoJSON.Geometry | null;
  talukaName: string | null;
  /** Every other village under the same taluka — never includes the
   * current village itself. */
  neighbours: SpatialNeighbour[];
  /** The catchment's own analysed geometry, whenever it differs from the
   * village boundary above by more than a trivial amount — i.e. only
   * when there is something distinct worth drawing. `null` both when the
   * AOI was never reshaped and when the catchment has no village at all
   * (Draw/Upload), so the map never draws two identical outlines on top
   * of each other. */
  analysedGeometry: GeoJSON.Geometry | null;
  isPending: boolean;
  isError: boolean;
}

const EMPTY: SpatialContext = {
  village: null,
  villageName: null,
  villageAreaHa: null,
  taluka: null,
  talukaName: null,
  neighbours: [],
  analysedGeometry: null,
  isPending: false,
  isError: false,
};

/**
 * Assembles the report page's orientation map out of endpoints that
 * already exist — nothing here computes anything, and nothing is fetched
 * that isn't already part of the product:
 *
 *   1. The village's own boundary + area, from the same
 *      GET /admin-boundaries/{id} the Select Area preview already uses.
 *   2. Its taluka's boundary, via `parent_id` (village.parent_id is the
 *      taluka's id) — a second call to that identical endpoint, not a
 *      new one.
 *   3. Every sibling village under that taluka, in ONE request
 *      (`include_geometry=true` on the existing list endpoint) rather
 *      than one request per neighbour — a taluka can have 185 of them.
 *   4. The catchment's own analysed geometry, from GET /catchments/{id},
 *      compared against the village boundary so the map only draws it
 *      when the AOI was actually reshaped away from the village.
 *
 * A catchment with no `admin_boundary_id` (drawn or uploaded freehand)
 * has no village to orient against at all — returns EMPTY immediately
 * rather than treating that as still-loading.
 */
export function useSpatialContext(catchment: CatchmentDetailResponse | undefined): SpatialContext {
  const hasVillage = Boolean(catchment?.admin_boundary_id);

  const villageDetail = useAdminBoundaryDetail(catchment?.admin_boundary_id ?? null);
  const talukaId = villageDetail.data?.parent_id ?? null;

  const talukaDetail = useAdminBoundaryDetail(talukaId);

  const siblingsQuery = useQuery({
    queryKey: ["admin-boundaries", "children-with-geometry", talukaId],
    queryFn: () => fetchAdminBoundaryChildren(talukaId, { includeGeometry: true }),
    enabled: talukaId !== null,
  });

  if (!hasVillage) return EMPTY;

  const isPending =
    villageDetail.isPending ||
    (Boolean(villageDetail.data) && talukaId !== null && (talukaDetail.isPending || siblingsQuery.isPending));
  const isError = villageDetail.isError || talukaDetail.isError || siblingsQuery.isError;

  const neighbours = filterNeighbours(siblingsQuery.data ?? [], catchment?.admin_boundary_id ?? null);

  const village = (villageDetail.data?.geometry as unknown as GeoJSON.Geometry) ?? null;
  const villageAreaHa = villageDetail.data?.area_ha ?? null;
  const catchmentGeometry = (catchment?.geometry as unknown as GeoJSON.Geometry) ?? null;
  const analysedGeometry =
    catchment !== undefined ? deriveAnalysedGeometry(catchment.area_ha, villageAreaHa, catchmentGeometry) : null;

  return {
    village,
    villageName: villageDetail.data?.village ?? villageDetail.data?.name ?? null,
    villageAreaHa,
    taluka: (talukaDetail.data?.geometry as unknown as GeoJSON.Geometry) ?? null,
    talukaName: villageDetail.data?.taluka ?? null,
    neighbours,
    analysedGeometry,
    isPending,
    isError,
  };
}
