"use client";

import type { Feature, Polygon } from "geojson";
import maplibregl from "maplibre-gl";
import { useCallback, useRef } from "react";

import { BaseMap } from "@/components/map/base-map";

interface ReportMapProps {
  /** The officer-drawn farm boundary (GeoJSON, WGS84) from the report payload. */
  geometry: Record<string, unknown>;
  className?: string;
}

/** Read-only satellite map with the saved farm boundary — Blueprint §08:
 * "the fastest trust-builder in the whole document". No drawing, no
 * controls beyond zoom; the polygon is fitted with padding on load. */
export function ReportMap({ geometry, className }: ReportMapProps) {
  const geometryRef = useRef(geometry);
  geometryRef.current = geometry;

  const handleMapReady = useCallback((map: maplibregl.Map) => {
    map.on("load", () => {
      const feature = {
        type: "Feature",
        properties: {},
        geometry: geometryRef.current,
      } as unknown as Feature<Polygon>;

      map.addSource("farm-boundary", { type: "geojson", data: feature });
      map.addLayer({
        id: "farm-boundary-fill",
        type: "fill",
        source: "farm-boundary",
        paint: { "fill-color": "#ffffff", "fill-opacity": 0.12 },
      });
      map.addLayer({
        id: "farm-boundary-line",
        type: "line",
        source: "farm-boundary",
        paint: { "line-color": "#ffffff", "line-width": 2.5 },
      });

      const ring = (feature.geometry.coordinates?.[0] ?? []) as [number, number][];
      if (ring.length > 0) {
        const bounds = ring.reduce(
          (acc, coordinate) => acc.extend(coordinate),
          new maplibregl.LngLatBounds(ring[0], ring[0]),
        );
        map.fitBounds(bounds, { padding: 48, duration: 0, maxZoom: 17 });
      }
    });
  }, []);

  return (
    <BaseMap
      onMapReady={handleMapReady}
      initialCenter={[76.65, 18.35]}
      initialZoom={9}
      className={className}
    />
  );
}
