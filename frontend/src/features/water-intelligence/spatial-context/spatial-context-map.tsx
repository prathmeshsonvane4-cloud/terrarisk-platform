"use client";

import maplibregl from "maplibre-gl";
import { useCallback, useRef } from "react";

import { BaseMap } from "@/components/map/base-map";

import type { SpatialContext } from "./use-spatial-context";

// Same fallback view every other Water Intelligence map uses before real
// geometry is known.
const DISTRICT_CENTER: [number, number] = [76.65, 18.35];
const DISTRICT_ZOOM = 7;

const TALUKA_SOURCE = "spatial-context-taluka";
const NEIGHBOURS_SOURCE = "spatial-context-neighbours";
const VILLAGE_SOURCE = "spatial-context-village";
const AOI_SOURCE = "spatial-context-aoi";

// Matches catchment-map.tsx's own reference-boundary green — this panel
// and the AOI editor should not disagree about what "the village
// boundary" looks like.
const VILLAGE_GREEN = "#16a34a";
const TALUKA_GREY = "#94a3b8";
const NEIGHBOUR_GREY = "#cbd5e1";
const AOI_BLUE = "#2563eb";

function eachRing(geometry: GeoJSON.Geometry, visit: (ring: [number, number][]) => void): void {
  if (geometry.type === "Polygon") {
    for (const ring of geometry.coordinates) visit(ring as [number, number][]);
  } else if (geometry.type === "MultiPolygon") {
    for (const polygon of geometry.coordinates) for (const ring of polygon) visit(ring as [number, number][]);
  }
}

function unionBounds(geometries: GeoJSON.Geometry[]): [[number, number], [number, number]] | null {
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
  return [
    [minLon, minLat],
    [maxLon, maxLat],
  ];
}

function toFeatureCollection(geometries: GeoJSON.Geometry[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: geometries.map((geometry) => ({ type: "Feature", properties: {}, geometry })),
  };
}

interface SpatialContextMapProps {
  context: SpatialContext;
  className?: string;
}

/**
 * Orientation, not analysis: where this village sits, what surrounds it,
 * and — only when it was actually reshaped — what area the report is
 * really computed over. No stress colouring, no satellite imagery, no
 * per-village data beyond the boundary itself; that distinction is the
 * whole point (docs/WELL_Labs_Spatial_Redesign_2026.md's Option B: the
 * report page gets a locator, not a second choropleth).
 *
 * Rotation is disabled so a fixed "N" badge stays honest without needing
 * to track map bearing — this is a locator, not a navigable GIS tool.
 */
export function SpatialContextMap({ context, className }: SpatialContextMapProps) {
  const hasFitRef = useRef(false);

  const handleMapReady = useCallback(
    (map: maplibregl.Map) => {
      map.dragRotate.disable();
      map.touchZoomRotate.disableRotation();
      map.keyboard.disableRotation();

      map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");

      map.on("load", () => {
        if (context.taluka) {
          map.addSource(TALUKA_SOURCE, { type: "geojson", data: { type: "Feature", properties: {}, geometry: context.taluka } });
          map.addLayer({
            id: `${TALUKA_SOURCE}-fill`,
            type: "fill",
            source: TALUKA_SOURCE,
            paint: { "fill-color": TALUKA_GREY, "fill-opacity": 0.08 },
          });
          map.addLayer({
            id: `${TALUKA_SOURCE}-line`,
            type: "line",
            source: TALUKA_SOURCE,
            paint: { "line-color": TALUKA_GREY, "line-width": 1, "line-dasharray": [2, 2] },
          });
        }

        map.addSource(NEIGHBOURS_SOURCE, {
          type: "geojson",
          data: toFeatureCollection(context.neighbours.map((neighbour) => neighbour.geometry)),
        });
        map.addLayer({
          id: `${NEIGHBOURS_SOURCE}-fill`,
          type: "fill",
          source: NEIGHBOURS_SOURCE,
          paint: { "fill-color": NEIGHBOUR_GREY, "fill-opacity": 0.25 },
        });
        map.addLayer({
          id: `${NEIGHBOURS_SOURCE}-line`,
          type: "line",
          source: NEIGHBOURS_SOURCE,
          paint: { "line-color": "#64748b", "line-width": 1 },
        });

        if (context.village) {
          map.addSource(VILLAGE_SOURCE, { type: "geojson", data: { type: "Feature", properties: {}, geometry: context.village } });
          map.addLayer({
            id: `${VILLAGE_SOURCE}-fill`,
            type: "fill",
            source: VILLAGE_SOURCE,
            paint: { "fill-color": VILLAGE_GREEN, "fill-opacity": 0.2 },
          });
          map.addLayer({
            id: `${VILLAGE_SOURCE}-line`,
            type: "line",
            source: VILLAGE_SOURCE,
            paint: { "line-color": VILLAGE_GREEN, "line-width": 2.5 },
          });
        }

        if (context.analysedGeometry) {
          map.addSource(AOI_SOURCE, { type: "geojson", data: { type: "Feature", properties: {}, geometry: context.analysedGeometry } });
          map.addLayer({
            id: `${AOI_SOURCE}-line`,
            type: "line",
            source: AOI_SOURCE,
            paint: { "line-color": AOI_BLUE, "line-width": 2.5, "line-dasharray": [3, 2] },
          });
        }

        if (!hasFitRef.current) {
          const bounds = unionBounds(
            [context.taluka, context.village, context.analysedGeometry, ...context.neighbours.map((n) => n.geometry)].filter(
              (geometry): geometry is GeoJSON.Geometry => Boolean(geometry),
            ),
          );
          if (bounds) {
            hasFitRef.current = true;
            map.fitBounds(bounds, { padding: 40, duration: 0, maxZoom: 14 });
          }
        }
      });
    },
    [context],
  );

  return (
    <div className={className}>
      <BaseMap onMapReady={handleMapReady} initialCenter={DISTRICT_CENTER} initialZoom={DISTRICT_ZOOM} className="absolute inset-0" />

      {/* Rotation is disabled above, so north is always up — a static
          badge is accurate without tracking map bearing. */}
      <div
        aria-hidden
        className="absolute top-3 right-3 z-10 flex size-8 flex-col items-center justify-center rounded-full bg-background/90 text-xs font-semibold shadow-sm"
      >
        <span aria-hidden>&uarr;</span>
        <span>N</span>
      </div>

      <div className="absolute bottom-3 right-3 z-10 flex flex-col gap-1 rounded-lg bg-background/95 p-2.5 text-xs shadow-sm">
        <LegendRow color={VILLAGE_GREEN} label="This village" />
        {context.analysedGeometry && <LegendRow color={AOI_BLUE} dashed label="Area actually analysed" />}
        {context.neighbours.length > 0 && <LegendRow color={NEIGHBOUR_GREY} label="Neighbouring villages" />}
        {context.taluka && <LegendRow color={TALUKA_GREY} dashed label="Taluka boundary" />}
      </div>
    </div>
  );
}

function LegendRow({ color, label, dashed = false }: { color: string; label: string; dashed?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span
        aria-hidden
        className="h-0 w-4 shrink-0"
        style={{ borderTop: `2.5px ${dashed ? "dashed" : "solid"} ${color}` }}
      />
      <span className="text-muted-foreground">{label}</span>
    </div>
  );
}
