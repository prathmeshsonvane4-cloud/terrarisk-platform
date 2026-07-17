"use client";

import maplibregl from "maplibre-gl";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  TerraDraw,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
  ValidateNotSelfIntersecting,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";

import { BaseMap } from "@/components/map/base-map";
import { Button } from "@/components/ui/button";
import { toFarmGeometry, type Ring } from "@/lib/geo";

import type { Village } from "./types";

// Latur district center — the pre-selection view so the map is never a
// gray void, just not yet zoomed to a field.
const DISTRICT_CENTER: [number, number] = [76.65, 18.35];
const DISTRICT_ZOOM = 9;
// Village scale: individual fields are clearly distinguishable on
// imagery at ~15.5, without being so close the officer loses context.
const VILLAGE_ZOOM = 15.5;

type DrawUiMode = "static" | "polygon" | "select";

interface FarmMapProps {
  village: Village | null;
  /** Derived by the owner from its polygon state — passed down instead of
   * mirrored here, so there is exactly one source of truth for "a
   * boundary exists". */
  hasPolygon: boolean;
  /** Fired with the current ring on every draw/edit change (null when the
   * boundary is removed), and `complete` once drawing has finished. */
  onPolygonChange: (ring: Ring | null, complete: boolean) => void;
  /** Hides every drawing control and forces static mode — set while a
   * submission is in flight and after the farm is saved, so the geometry
   * on screen can never drift from what the server recorded. */
  locked?: boolean;
  /** Incrementing this clears any drawn boundary (used by "Draw another
   * farm" after a save) — an imperative act expressed as data so the page
   * never needs a ref into map internals. Initial value never triggers. */
  clearSignal?: number;
  /** A previously-drawn ring to load onto the map as an already-complete,
   * editable boundary, applied exactly once as soon as the map is ready
   * (P10 draft restore — refreshing/resuming must bring the actual
   * boundary back, not just its computed area). A one-shot operation
   * (tracked via an internal ref, not a prop signal) rather than something
   * that re-applies on every `restoreRing` identity change — the officer
   * may go on to edit or delete the restored boundary, and this must never
   * fight that by re-adding it. */
  restoreRing?: Ring | null;
  className?: string;
}

// P10 requirement 10 (performance): a WebGL map is the single most
// expensive thing this app renders — memoized so the wizard's frequent
// submit-phase re-renders (aria-live status text ticking, stepper state)
// don't re-run FarmMap's render for props that haven't actually changed.
// The wizard already passes a useCallback-stabilized onPolygonChange and
// otherwise-primitive props, so this is a real hit rate, not a no-op.
export const FarmMap = memo(function FarmMap({
  village,
  hasPolygon,
  onPolygonChange,
  locked = false,
  clearSignal = 0,
  restoreRing = null,
  className,
}: FarmMapProps) {
  const mapRef = useRef<maplibregl.Map | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const throttleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [uiMode, setUiMode] = useState<DrawUiMode>("static");
  const [mapLoaded, setMapLoaded] = useState(false);

  const onPolygonChangeRef = useRef(onPolygonChange);
  onPolygonChangeRef.current = onPolygonChange;

  const reportSnapshot = useCallback((draw: TerraDraw) => {
    const polygonFeature = draw
      .getSnapshot()
      .find((feature) => feature.geometry.type === "Polygon");
    if (!polygonFeature) {
      onPolygonChangeRef.current(null, false);
      return;
    }
    const ring = (polygonFeature.geometry.coordinates as [number, number][][])[0];
    // Still in polygon mode = the officer is mid-draw; anything else
    // (static after finish, select during edits) is a complete boundary.
    onPolygonChangeRef.current(ring, draw.getMode() !== "polygon");
  }, []);

  // Draw/edit change events fire per mouse-move; collapsing to at most one
  // report per 50ms keeps the live area preview smooth without
  // re-rendering the page tree for every intermediate cursor position.
  // Deliberately a timer, not requestAnimationFrame: browsers stop
  // delivering animation frames to hidden/backgrounded tabs entirely, so
  // an rAF-throttled report would silently freeze the sidebar state if
  // the officer switches tabs mid-draw. Timers keep firing (clamped, but
  // firing) in hidden tabs.
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
        const draw = new TerraDraw({
          adapter: new TerraDrawMapLibreGLAdapter({ map }),
          modes: [
            new TerraDrawPolygonMode({
              validation: (feature, { updateType }) => {
                // Terra Draw's recommended pattern: enforce on finish and
                // committed updates, so transient states while placing
                // points aren't over-rejected. The backend re-validates
                // regardless — this is UX, not the security boundary.
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
                    // Whole-boundary dragging is deliberately off: sliding
                    // the entire polygon off the field is a data hazard
                    // with no legitimate use. Vertex-level editing only.
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
        setMapLoaded(true);
      });
    },
    [scheduleReport],
  );

  // Recenter on the selected village. Any in-progress or finished boundary
  // is cleared: a farm belongs to exactly one village, and geometry drawn
  // near the previous village would be silently wrong data for this one.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !village) return;

    const draw = drawRef.current;
    if (draw && draw.getSnapshot().length > 0) {
      draw.clear();
      onPolygonChangeRef.current(null, false);
    }
    draw?.setMode("static");
    setUiMode("static");

    const center: [number, number] = [village.centroid.lon, village.centroid.lat];
    markerRef.current?.remove();
    markerRef.current = new maplibregl.Marker().setLngLat(center).addTo(map);
    map.flyTo({ center, zoom: VILLAGE_ZOOM, duration: 2500, essential: true });
  }, [village]);

  // Draft restore (P10): load a previously-drawn ring back onto the map as
  // an already-complete, editable boundary — exactly once, the first time
  // the map becomes ready with a restoreRing present. Declared after the
  // village-centering effect above so, on the resuming mount where both
  // fire together, the (at that point empty, so harmless) clear the
  // village effect performs happens first, never after.
  const hasRestoredRef = useRef(false);
  useEffect(() => {
    if (!mapLoaded || hasRestoredRef.current) return;
    const draw = drawRef.current;
    if (!draw || !restoreRing || restoreRing.length < 3) return;
    hasRestoredRef.current = true;

    const [closedRing] = toFarmGeometry(restoreRing).coordinates;
    draw.addFeatures([
      {
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [closedRing] },
        properties: { mode: "polygon" },
      },
    ]);
    draw.setMode("select");
    setUiMode("select");
    onPolygonChangeRef.current(restoreRing, true);
  }, [mapLoaded, restoreRing]);

  // Entering the locked state (submit in flight / farm saved) forces the
  // map out of any draw/edit mode so no interaction can mutate geometry
  // the server is recording or has recorded.
  useEffect(() => {
    if (locked) {
      drawRef.current?.setMode("static");
      setUiMode("static");
    }
  }, [locked]);

  // "Discard and start over": the wizard bumps clearSignal to reset the
  // map; skip the mount-time initial value so a fresh page never self-clears.
  const lastClearSignalRef = useRef(clearSignal);
  useEffect(() => {
    if (clearSignal === lastClearSignalRef.current) return;
    lastClearSignalRef.current = clearSignal;
    drawRef.current?.clear();
    onPolygonChangeRef.current(null, false);
    drawRef.current?.setMode("static");
    setUiMode("static");
  }, [clearSignal]);

  // Unmount cleanup: stop Terra Draw before BaseMap removes the map, and
  // drop any queued throttled report.
  useEffect(() => {
    return () => {
      if (throttleRef.current !== null) clearTimeout(throttleRef.current);
      drawRef.current?.stop();
      drawRef.current = null;
      markerRef.current?.remove();
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
            <Button size="sm" onClick={enterDrawMode} disabled={!village}>
              Draw farm boundary
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
                Click to place points around the field. Click the first point to finish. Esc cancels.
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
          {!village && (
            <p className="max-w-60 rounded-lg bg-background/90 px-2.5 py-1.5 text-xs">
              Search and select a village to begin.
            </p>
          )}
        </div>
      )}
    </div>
  );
});
