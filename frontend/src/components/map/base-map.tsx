"use client";

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, type ReactNode } from "react";

import { MAP_MAX_ZOOM, MAP_TILE_ATTRIBUTION, MAP_TILE_URL } from "@/config";

// Scope-agnostic satellite base map (M2A spec §7: components/map is shared,
// M4's choropleths reuse this shell). Owns exactly one concern: a MapLibre
// instance over the configured raster basemap, handed to the caller via
// onMapReady. Everything feature-specific (fly-to, drawing, overlays)
// belongs to the feature component driving it.

interface BaseMapProps {
  /** Called once, after the map instance is created. */
  onMapReady: (map: maplibregl.Map) => void;
  /** [lon, lat] */
  initialCenter: [number, number];
  initialZoom: number;
  className?: string;
  children?: ReactNode;
}

export function BaseMap({ onMapReady, initialCenter, initialZoom, className, children }: BaseMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // The map must be created exactly once (not per render, not per prop
  // change) — refs keep the effect's dependencies genuinely empty.
  const onMapReadyRef = useRef(onMapReady);
  onMapReadyRef.current = onMapReady;
  const initialViewRef = useRef({ center: initialCenter, zoom: initialZoom });

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          satellite: {
            type: "raster",
            tiles: [MAP_TILE_URL],
            tileSize: 256,
            maxzoom: MAP_MAX_ZOOM,
            attribution: MAP_TILE_ATTRIBUTION,
          },
        },
        layers: [{ id: "satellite", type: "raster", source: "satellite" }],
      },
      center: initialViewRef.current.center,
      zoom: initialViewRef.current.zoom,
      maxZoom: MAP_MAX_ZOOM,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    // Testability hooks (consumed by E2E checks; GL canvas contents are
    // not directly assertable): "loaded" = style + first render ready,
    // "idle" = all in-view tiles fetched and rendered.
    const container = containerRef.current;
    map.on("load", () => container.setAttribute("data-map-loaded", "true"));
    map.on("idle", () => container.setAttribute("data-map-idle", "true"));
    map.on("dataloading", () => container.removeAttribute("data-map-idle"));

    onMapReadyRef.current(map);

    return () => {
      map.remove();
    };
  }, []);

  return (
    <div ref={containerRef} className={className} data-testid="base-map">
      {children}
    </div>
  );
}
