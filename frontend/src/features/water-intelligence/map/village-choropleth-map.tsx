"use client";

import maplibregl from "maplibre-gl";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { BaseMap } from "@/components/map/base-map";

import { NO_REPORT_MAP_COLOR, STRESS_BAND_MAP_COLORS } from "../band-styles";
import {
  BAND_PROPERTY,
  CATCHMENT_ID_PROPERTY,
  entriesBounds,
  toFeatureCollection,
  type VillageMapEntry,
} from "./village-map-entries";

// Raichur district center — the programme's own area of operation, so an
// empty or still-loading map still opens somewhere meaningful rather
// than on a gray void. Superseded by fitBounds as soon as real village
// geometry arrives.
const RAICHUR_CENTER: [number, number] = [76.94, 16.2];
const RAICHUR_ZOOM = 8.5;

const SOURCE_ID = "monitored-villages";
const FILL_LAYER_ID = "monitored-villages-fill";
const OUTLINE_LAYER_ID = "monitored-villages-outline";
const SELECTED_LAYER_ID = "monitored-villages-selected";

const FIT_PADDING = 56;

/** The data-driven fill colour: one `match` expression over the band
 * property, reading the same colours the chips and the PDF use. This is
 * what makes it a choropleth rather than a pile of overlays — every
 * village is one feature in one layer, coloured by its own band. */
const FILL_COLOR_EXPRESSION: maplibregl.ExpressionSpecification = [
  "match",
  ["get", BAND_PROPERTY],
  "low",
  STRESS_BAND_MAP_COLORS.low,
  "moderate",
  STRESS_BAND_MAP_COLORS.moderate,
  "high",
  STRESS_BAND_MAP_COLORS.high,
  "very_high",
  STRESS_BAND_MAP_COLORS.very_high,
  NO_REPORT_MAP_COLOR, // fallback, used by NO_REPORT_BAND_VALUE
];

interface ActivePopup {
  entry: VillageMapEntry;
  lng: number;
  lat: number;
}

interface VillageChoroplethMapProps {
  entries: VillageMapEntry[];
  /** Catchment ids currently staged for comparison — drawn with a heavy
   * outline so a comparison set is visible *as a shape on the map*, not
   * just as a count in a toolbar. */
  selectedIds: string[];
  /** Shift/ctrl-click toggles comparison selection directly, without
   * going through the popup — the "click A, click B, click C, compare"
   * path. */
  onToggleSelected: (catchmentId: string) => void;
  /** Zoom to this village and open its popup — how "Locate on Map" from
   * the Priority Queue arrives here. */
  focusCatchmentId?: string | null;
  /** Popup body. Owned by the caller so this component stays free of
   * navigation and comparison concerns; it only decides *where* the
   * popup goes. */
  renderPopup: (entry: VillageMapEntry, close: () => void) => ReactNode;
  className?: string;
}

/**
 * Every monitored village in one view, each polygon coloured by the
 * recharge stress band its own latest report already produced.
 *
 * This is a presentation layer and nothing more: it computes no score,
 * calls no endpoint, and applies no threshold. It exists because a
 * ranked list cannot answer the questions a water programme actually
 * asks — where the stressed villages are, whether they are contiguous
 * (a canal-system problem) or isolated (a local one), and which
 * neighbouring village is a fair comparison for another. Those are
 * spatial questions, and they need a map to be answerable at a glance.
 */
export function VillageChoroplethMap({
  entries,
  selectedIds,
  onToggleSelected,
  focusCatchmentId = null,
  renderPopup,
  className,
}: VillageChoroplethMapProps) {
  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapLoadedRef = useRef(false);
  const hasFitRef = useRef(false);
  const [active, setActive] = useState<ActivePopup | null>(null);

  // Latest values readable from map event handlers, which are registered
  // once on load and would otherwise close over the first render's props.
  const entriesRef = useRef(entries);
  entriesRef.current = entries;
  const onToggleSelectedRef = useRef(onToggleSelected);
  onToggleSelectedRef.current = onToggleSelected;

  const handleMapReady = useCallback((map: maplibregl.Map) => {
    mapRef.current = map;

    map.on("load", () => {
      mapLoadedRef.current = true;

      map.addSource(SOURCE_ID, { type: "geojson", data: toFeatureCollection(entriesRef.current) });

      map.addLayer({
        id: FILL_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        paint: { "fill-color": FILL_COLOR_EXPRESSION, "fill-opacity": 0.6 },
      });
      map.addLayer({
        id: OUTLINE_LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        paint: { "line-color": "#ffffff", "line-width": 1, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: SELECTED_LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        filter: ["in", ["get", CATCHMENT_ID_PROPERTY], ["literal", []]],
        paint: { "line-color": "#0f172a", "line-width": 3 },
      });

      map.on("click", FILL_LAYER_ID, (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const catchmentId = feature.properties?.[CATCHMENT_ID_PROPERTY] as string | undefined;
        if (!catchmentId) return;
        const entry = entriesRef.current.find((item) => item.catchmentId === catchmentId);
        if (!entry) return;

        // Shift/ctrl-click builds a comparison set directly on the map;
        // a plain click opens the village's popup.
        const originalEvent = event.originalEvent;
        if (originalEvent.shiftKey || originalEvent.ctrlKey || originalEvent.metaKey) {
          onToggleSelectedRef.current(catchmentId);
          return;
        }
        setActive({ entry, lng: event.lngLat.lng, lat: event.lngLat.lat });
      });

      map.on("mouseenter", FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = "";
      });

      fitToEntries(map, entriesRef.current, hasFitRef);
    });
  }, []);

  // Push new/changed villages into the existing source rather than
  // rebuilding layers — adding a village is a data update, not a map
  // rebuild.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const source = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (!source) return;
    source.setData(toFeatureCollection(entries));
    fitToEntries(map, entries, hasFitRef);
  }, [entries]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current || !map.getLayer(SELECTED_LAYER_ID)) return;
    map.setFilter(SELECTED_LAYER_ID, ["in", ["get", CATCHMENT_ID_PROPERTY], ["literal", selectedIds]]);
  }, [selectedIds]);

  // "Locate on Map" — zoom to one village and open it, so a queue row and
  // its place on the ground are one click apart.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current || !focusCatchmentId) return;
    const entry = entries.find((item) => item.catchmentId === focusCatchmentId);
    if (!entry) return;
    const bounds = entriesBounds([entry]);
    if (!bounds) return;
    map.fitBounds(bounds, { padding: 120, duration: 800, maxZoom: 13 });
    const center = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2] as const;
    setActive({ entry, lng: center[0], lat: center[1] });
  }, [focusCatchmentId, entries]);

  const closePopup = useCallback(() => setActive(null), []);

  return (
    <div className={className}>
      <BaseMap
        onMapReady={handleMapReady}
        initialCenter={RAICHUR_CENTER}
        initialZoom={RAICHUR_ZOOM}
        className="absolute inset-0"
      />
      {active && mapRef.current && (
        <MapPopup map={mapRef.current} lng={active.lng} lat={active.lat} onClose={closePopup}>
          {renderPopup(active.entry, closePopup)}
        </MapPopup>
      )}
    </div>
  );
}

function fitToEntries(map: maplibregl.Map, entries: VillageMapEntry[], hasFitRef: { current: boolean }) {
  // Fit once, on the first render that actually has geometry. Re-fitting
  // on every data change would yank the view out from under someone who
  // has panned or zoomed in to look at a specific cluster.
  if (hasFitRef.current || entries.length === 0) return;
  const bounds = entriesBounds(entries);
  if (!bounds) return;
  hasFitRef.current = true;
  map.fitBounds(bounds, { padding: FIT_PADDING, duration: 0, maxZoom: 12 });
}

/**
 * A real anchored MapLibre popup whose content is React. The alternative
 * — an absolutely-positioned card in a corner — would lose the one thing
 * that makes a popup worth having here: it points at the village it
 * describes, so "this reading belongs to that polygon" needs no
 * explaining.
 */
function MapPopup({
  map,
  lng,
  lat,
  onClose,
  children,
}: {
  map: maplibregl.Map;
  lng: number;
  lat: number;
  onClose: () => void;
  children: ReactNode;
}) {
  const [container] = useState(() => document.createElement("div"));
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: false, maxWidth: "320px", offset: 8 })
      .setLngLat([lng, lat])
      .setDOMContent(container)
      .addTo(map);
    popup.on("close", () => onCloseRef.current());
    return () => {
      popup.remove();
    };
  }, [map, lng, lat, container]);

  return createPortal(children, container);
}
