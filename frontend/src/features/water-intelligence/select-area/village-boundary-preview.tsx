"use client";

import maplibregl from "maplibre-gl";
import { useCallback, useEffect, useRef } from "react";

import { BaseMap } from "@/components/map/base-map";
import { setGeoJsonOverlay } from "@/lib/map-overlay";

// Same fallback view catchment-map.tsx uses before any geometry exists —
// there is no village chosen yet, so there's nothing to zoom to.
const DISTRICT_CENTER: [number, number] = [76.65, 18.35];
const DISTRICT_ZOOM = 7;

const OVERLAY_SOURCE_ID = "select-area-boundary-preview";

interface VillageBoundaryPreviewProps {
  /** The selected boundary's geometry (from GET /admin-boundaries/{id}),
   * or null while nothing is selected yet / still loading. */
  geometry: GeoJSON.Geometry | null;
  className?: string;
}

/**
 * Renders the picked administrative boundary as a highlighted overlay and
 * zooms to it — the "zoom to village, display village boundary" step of
 * Select Area (docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md Part
 * 4). Deliberately not CatchmentMap: this step never draws or edits
 * anything, it only previews a boundary that was picked from a dropdown,
 * so it's a thinner component built directly on BaseMap.
 */
export function VillageBoundaryPreview({ geometry, className }: VillageBoundaryPreviewProps) {
  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapLoadedRef = useRef(false);

  const handleMapReady = useCallback((map: maplibregl.Map) => {
    mapRef.current = map;
    map.on("load", () => {
      mapLoadedRef.current = true;
      if (geometry) {
        setGeoJsonOverlay(map, OVERLAY_SOURCE_ID, geometry);
      }
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial geometry read via closure is intentional; updates handled below

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current || !geometry) return;
    setGeoJsonOverlay(map, OVERLAY_SOURCE_ID, geometry);
  }, [geometry]);

  return (
    <BaseMap
      onMapReady={handleMapReady}
      initialCenter={DISTRICT_CENTER}
      initialZoom={DISTRICT_ZOOM}
      className={className}
    />
  );
}
