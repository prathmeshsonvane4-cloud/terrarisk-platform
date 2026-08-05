import type { StorageChangeBand, StressBand } from "../band-styles";
import { deriveRecommendations, highestSeverity, type Recommendation } from "../priority-queue/recommendations";
import { numberField } from "../raw-inputs";
import type { CatchmentResponse } from "../use-catchments";
import type { WaterReportHistoryItem } from "../use-water-report-history";

/** One monitored village, resolved to everything the choropleth and its
 * popup need. Every field here is read from data the platform already
 * computes — nothing is derived by a new model, and nothing is invented
 * when a value is genuinely absent (hence the nulls). */
export interface VillageMapEntry {
  catchmentId: string;
  name: string;
  areaHa: number;
  geometry: GeoJSON.Geometry;
  /** null when this village has no completed report yet — rendered grey,
   * never as a low-stress green. */
  band: StressBand | null;
  stressScore: number | null;
  storageChangeBand: StorageChangeBand | null;
  confidence: number | null;
  lastGeneratedAt: string | null;
  /** The single highest-severity recommendation, chosen with the queue's
   * own existing ordering so the map and the Priority Queue can never
   * disagree about what a village's top priority is. */
  topRecommendation: Recommendation;
}

export interface VillageMapData {
  entries: VillageMapEntry[];
  /** Monitored catchments that cannot be placed on the map because they
   * were drawn or uploaded freehand rather than picked from the
   * administrative hierarchy, so no village polygon exists for them in
   * any endpoint. Surfaced to the user rather than silently dropped. */
  unmappable: CatchmentResponse[];
}

/** The queue's severity ordering, reused rather than re-derived: pick the
 * worst-severity recommendation as the one to show on the map. */
export function topRecommendationOf(recommendations: Recommendation[]): Recommendation {
  const worst = highestSeverity(recommendations);
  return recommendations.find((recommendation) => recommendation.severity === worst) ?? recommendations[0];
}

interface BuildArgs {
  catchments: CatchmentResponse[];
  /** boundaryId -> geometry, for boundaries whose fetch has resolved. */
  geometryByBoundaryId: Map<string, GeoJSON.Geometry>;
  /** catchmentId -> report history, newest first. */
  historyByCatchmentId: Map<string, WaterReportHistoryItem[]>;
}

/**
 * Composes the choropleth's rows out of three things the platform already
 * has — the catchment list, village geometry from the admin-boundary
 * endpoint, and report history — plus the existing recommendation
 * engine. Pure and deterministic: no fetching, no new scoring, no new
 * thresholds. The map is a presentation of already-computed state, which
 * is the whole point of this redesign.
 *
 * A catchment with no `admin_boundary_id` (drawn or uploaded freehand)
 * has no village polygon anywhere in the API and is returned under
 * `unmappable` instead of being guessed at. A catchment whose geometry
 * request simply hasn't resolved yet is omitted from both lists — it is
 * still loading, not unmappable.
 */
export function buildVillageMapData({ catchments, geometryByBoundaryId, historyByCatchmentId }: BuildArgs): VillageMapData {
  const entries: VillageMapEntry[] = [];
  const unmappable: CatchmentResponse[] = [];

  for (const catchment of catchments) {
    if (!catchment.admin_boundary_id) {
      unmappable.push(catchment);
      continue;
    }
    const geometry = geometryByBoundaryId.get(catchment.admin_boundary_id);
    if (!geometry) continue; // still loading, or that one boundary failed

    const history = historyByCatchmentId.get(catchment.id) ?? [];
    const latest = history[0];
    const recommendations = deriveRecommendations(history);

    entries.push({
      catchmentId: catchment.id,
      name: catchment.name,
      areaHa: catchment.area_ha,
      geometry,
      band: latest ? latest.recharge_stress.stress_band : null,
      stressScore: latest ? latest.recharge_stress.stress_score : null,
      storageChangeBand: latest ? latest.water_balance.storage_change_band : null,
      confidence: latest ? numberField(latest.recharge_stress.raw_inputs, "confidence") : null,
      lastGeneratedAt: latest ? latest.generated_at : null,
      topRecommendation: topRecommendationOf(recommendations),
    });
  }

  return { entries, unmappable };
}

/** The property name carrying a village's stress band on the GL feature —
 * the key the fill layer's data-driven `match` expression reads. */
export const BAND_PROPERTY = "band";
export const CATCHMENT_ID_PROPERTY = "catchmentId";
/** The literal used for "no report yet", since a GL `match` expression
 * cannot branch on a null property value. */
export const NO_REPORT_BAND_VALUE = "none";

/**
 * One FeatureCollection for the whole district — a single MapLibre source
 * with per-feature colouring, rather than one overlay per village. This
 * is what makes "every village visible simultaneously" cheap: adding a
 * village adds a feature, not a source and two layers.
 */
export function toFeatureCollection(entries: VillageMapEntry[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: entries.map((entry) => ({
      type: "Feature",
      id: entry.catchmentId,
      geometry: entry.geometry,
      properties: {
        [CATCHMENT_ID_PROPERTY]: entry.catchmentId,
        [BAND_PROPERTY]: entry.band ?? NO_REPORT_BAND_VALUE,
        name: entry.name,
      },
    })),
  };
}

/** Bounding box across every mapped village, for the initial fit — the
 * "show me the whole district at once" view. Returns null when there is
 * nothing to fit. */
export function entriesBounds(entries: VillageMapEntry[]): [[number, number], [number, number]] | null {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;

  function visit(coordinates: unknown): void {
    const list = coordinates as unknown[];
    if (typeof list[0] === "number") {
      const [lon, lat] = list as [number, number];
      minLon = Math.min(minLon, lon);
      maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
      return;
    }
    for (const item of list) visit(item);
  }

  for (const entry of entries) {
    if ("coordinates" in entry.geometry) visit(entry.geometry.coordinates);
  }

  if (!Number.isFinite(minLon) || !Number.isFinite(minLat)) return null;
  return [
    [minLon, minLat],
    [maxLon, maxLat],
  ];
}
