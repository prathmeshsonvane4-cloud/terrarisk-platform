"use client";

import maplibregl from "maplibre-gl";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { TerraDraw, TerraDrawPolygonMode, TerraDrawSelectMode, ValidateNotSelfIntersecting } from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";

import { BaseMap } from "@/components/map/base-map";
import { Button } from "@/components/ui/button";
import { ringFromGeometry, type Ring } from "@/lib/catchment-geo";
import { generateFeatureId } from "@/lib/feature-id";
import { removeGeoJsonOverlay, setGeoJsonOverlay } from "@/lib/map-overlay";

// Latur district center — same pre-selection view farm-map.tsx uses, so
// a catchment (there is no village to fly to) still opens on a real,
// oriented view rather than a gray void.
const DISTRICT_CENTER: [number, number] = [76.65, 18.35];
const DISTRICT_ZOOM = 9;

type DrawUiMode = "static" | "polygon" | "select";

const REFERENCE_SOURCE_ID = "catchment-map-reference-boundary";

interface CatchmentMapProps {
  hasPolygon: boolean;
  onPolygonChange: (ring: Ring | null, complete: boolean) => void;
  locked?: boolean;
  className?: string;
  /** A non-editable boundary shown underneath the draw layer — Select
   * Area's village reference (docs/TerraRisk_Editable_AOI_2026.md), so
   * an officer can see the village they picked while reshaping the AOI
   * against it. Purely visual: this component never edits it, and
   * nothing here constrains what Terra Draw lets the AOI become —
   * overlap is checked and explained by the caller, never enforced
   * here. */
  referenceGeometry?: GeoJSON.Geometry | null;
  /** Seeds the editable polygon with this geometry's own shape the
   * moment the map is ready, then immediately selects it (Terra Draw's
   * edit/select mode) — Select Area's "Create Editable AOI" entry
   * point. Read exactly once per mount (a fresh `key` on this component
   * is how a caller starts a new seeded session); later prop changes
   * are ignored so a re-render mid-edit can never silently overwrite a
   * user's in-progress reshape. `null`/omitted keeps this component's
   * original empty-start behaviour (the Draw tab). */
  initialAoiGeometry?: GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
}

/**
 * Single-polygon draw/edit tool for a catchment boundary — the "Draw"
 * path of /catchments/new. A deliberate simplification of
 * features/farm-drawing/farm-map.tsx, not a fork that drifted: the
 * Terra Draw setup, self-intersection validation, throttled
 * change-report shape, and static/polygon/select mode machine are the
 * same approach, because catchment boundary drawing is the same real
 * problem farm boundary drawing already solved. Two things farm-map.tsx
 * has are deliberately omitted, not forgotten: village-centering/fly-to
 * (a catchment has no village to center on) and restoreRing/clearSignal
 * draft-persistence (this ticket has no draft-persistence requirement
 * for catchments). The drawn ring is wrapped into a one-element
 * MultiPolygon by the caller (toCatchmentGeometry, lib/catchment-geo.ts)
 * — this component only ever produces one simple ring, the same "a
 * client submitting a single simply-connected boundary still uses
 * [MultiPolygon]" case the backend schema itself documents.
 */
export const CatchmentMap = memo(function CatchmentMap({
  hasPolygon,
  onPolygonChange,
  locked = false,
  className,
  referenceGeometry = null,
  initialAoiGeometry = null,
}: CatchmentMapProps) {
  const mapRef = useRef<maplibregl.Map | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const throttleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [uiMode, setUiMode] = useState<DrawUiMode>("static");
  const mapLoadedRef = useRef(false);
  const referenceGeometryRef = useRef(referenceGeometry);
  referenceGeometryRef.current = referenceGeometry;
  // Read once at seed time, deliberately not kept in sync with prop
  // changes afterward — see initialAoiGeometry's own doc comment.
  const initialAoiGeometryRef = useRef(initialAoiGeometry);

  const onPolygonChangeRef = useRef(onPolygonChange);
  onPolygonChangeRef.current = onPolygonChange;

  const reportSnapshot = useCallback((draw: TerraDraw) => {
    const polygonFeature = draw.getSnapshot().find((feature) => feature.geometry.type === "Polygon");
    if (!polygonFeature) {
      onPolygonChangeRef.current(null, false);
      return;
    }
    const ring = (polygonFeature.geometry.coordinates as [number, number][][])[0];
    onPolygonChangeRef.current(ring, draw.getMode() !== "polygon");
  }, []);

  // Draw/edit change events fire per mouse-move; collapsing to at most one
  // report per 50ms keeps the live area preview smooth — identical
  // reasoning and value to farm-map.tsx's own scheduleReport.
  const scheduleReport = useCallback(
    (draw: TerraDraw) => {
      if (throttleRef.current !== null) return;
      throttleRef.current = setTimeout(() => {
        throttleRef.current = null;
        reportSnapshot(draw);
      }, 50);
    },
    [reportSnapshot],
  );

  const handleMapReady = useCallback(
    (map: maplibregl.Map) => {
      mapRef.current = map;
      map.on("load", () => {
        mapLoadedRef.current = true;
        if (referenceGeometryRef.current) {
          setGeoJsonOverlay(map, REFERENCE_SOURCE_ID, referenceGeometryRef.current, { color: "#16a34a" });
        }

        const draw = new TerraDraw({
          adapter: new TerraDrawMapLibreGLAdapter({ map }),
          modes: [
            new TerraDrawPolygonMode({
              validation: (feature, { updateType }) => {
                if (updateType === "finish" || updateType === "commit") {
                  return ValidateNotSelfIntersecting(feature);
                }
                return { valid: true };
              },
            }),
            new TerraDrawSelectMode({
              flags: {
                polygon: {
                  feature: {
                    draggable: false,
                    coordinates: { midpoints: true, draggable: true, deletable: true },
                  },
                },
              },
            }),
          ],
        });
        draw.start();
        draw.setMode("static");

        draw.on("change", (_ids, type) => {
          if (type === "create" || type === "update" || type === "delete") {
            scheduleReport(draw);
          }
        });
        draw.on("finish", (_id, context) => {
          if (context.action === "draw") {
            // Single-polygon rule: leaving polygon mode immediately after
            // the first boundary closes prevents a second one.
            draw.setMode("static");
            setUiMode("static");
          }
          scheduleReport(draw);
        });

        drawRef.current = draw;

        // Select Area's "Create Editable AOI": seed the draw store with
        // the village's own shape as a real, already-selected polygon
        // feature — not an empty canvas the user draws from scratch.
        // Terra Draw's own documented pattern for this is addFeatures()
        // (tagged properties.mode: "polygon" so TerraDrawSelectMode will
        // operate on it) followed by selectFeature(), which immediately
        // shows drag handles/midpoints exactly as if the user had just
        // finished drawing and switched to edit mode themselves.
        const seedGeometry = initialAoiGeometryRef.current;
        const seedRing = seedGeometry ? ringFromGeometry(seedGeometry) : null;
        if (seedRing) {
          const featureId = generateFeatureId();
          const [result] = draw.addFeatures([
            {
              id: featureId,
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [seedRing] },
              properties: { mode: "polygon" },
            },
          ]);
          // addFeatures rejects rather than throwing (e.g. a source with
          // coordinate precision beyond terra-draw's default 9 decimal
          // places, which real village geometry never has today — PostGIS's
          // own ST_AsGeoJSON default matches that same 9-digit limit — but
          // selectFeature() below throws for a feature id that was never
          // actually added, so this must be checked rather than assumed.
          // Falling through leaves the map exactly as it starts empty
          // (the pre-existing Draw behaviour): the officer draws the AOI
          // from scratch instead of it being pre-seeded.
          if (result?.valid) {
            draw.setMode("select");
            draw.selectFeature(featureId);
            setUiMode("select");
            reportSnapshot(draw);
          }
        }
      });
    },
    [scheduleReport, reportSnapshot],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    if (referenceGeometry) {
      setGeoJsonOverlay(map, REFERENCE_SOURCE_ID, referenceGeometry, { color: "#16a34a", fitBounds: false });
    } else {
      removeGeoJsonOverlay(map, REFERENCE_SOURCE_ID);
    }
  }, [referenceGeometry]);

  // Entering the locked state (submit in flight) forces the map out of
  // any draw/edit mode so no interaction can mutate geometry the server
  // is recording.
  useEffect(() => {
    if (locked) {
      drawRef.current?.setMode("static");
      setUiMode("static");
    }
  }, [locked]);

  useEffect(() => {
    return () => {
      if (throttleRef.current !== null) clearTimeout(throttleRef.current);
      drawRef.current?.stop();
      drawRef.current = null;
    };
  }, []);

  function enterDrawMode() {
    drawRef.current?.setMode("polygon");
    setUiMode("polygon");
  }

  function enterEditMode() {
    drawRef.current?.setMode("select");
    setUiMode("select");
  }

  function exitToStatic() {
    drawRef.current?.setMode("static");
    setUiMode("static");
  }

  function cancelDrawing() {
    drawRef.current?.clear();
    onPolygonChangeRef.current(null, false);
    exitToStatic();
  }

  function deleteBoundary() {
    drawRef.current?.clear();
    onPolygonChangeRef.current(null, false);
    exitToStatic();
  }

  return (
    <div className={className}>
      <BaseMap
        onMapReady={handleMapReady}
        initialCenter={DISTRICT_CENTER}
        initialZoom={DISTRICT_ZOOM}
        className="absolute inset-0"
      />

      {!locked && (
        <div className="absolute top-3 left-3 z-10 flex flex-col items-start gap-2">
          {uiMode === "static" && !hasPolygon && (
            <Button size="sm" onClick={enterDrawMode}>
              Draw catchment boundary
            </Button>
          )}
          {uiMode === "static" && hasPolygon && (
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={enterEditMode}>
                Edit boundary
              </Button>
              <Button size="sm" variant="destructive" onClick={deleteBoundary}>
                Delete
              </Button>
            </div>
          )}
          {uiMode === "polygon" && (
            <>
              <Button size="sm" variant="outline" onClick={cancelDrawing}>
                Cancel drawing
              </Button>
              <p className="max-w-60 rounded-lg bg-background/90 px-2.5 py-1.5 text-xs">
                Click to place points around the watershed boundary. Click the first point to finish. Esc cancels.
              </p>
            </>
          )}
          {uiMode === "select" && (
            <>
              <div className="flex gap-2">
                <Button size="sm" onClick={exitToStatic}>
                  Done editing
                </Button>
                <Button size="sm" variant="destructive" onClick={deleteBoundary}>
                  Delete
                </Button>
              </div>
              <p className="max-w-60 rounded-lg bg-background/90 px-2.5 py-1.5 text-xs">
                Click the boundary to select it, then drag points to adjust. Drag a midpoint to add detail.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
});
