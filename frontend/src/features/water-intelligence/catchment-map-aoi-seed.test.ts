import { afterEach, describe, expect, it, vi } from "vitest";
import { TerraDraw, TerraDrawPolygonMode, TerraDrawSelectMode, ValidateNotSelfIntersecting } from "terra-draw";

import { ringFromGeometry, type Ring } from "@/lib/catchment-geo";
import { generateFeatureId } from "@/lib/feature-id";

// terra-draw's package.json "exports" map only publishes its root entry
// (types/require/default) — TerraDrawAdapter itself isn't re-exported
// from there, only used internally as the "adapter" constructor param
// type. Deriving it structurally from TerraDraw's own public constructor
// signature avoids a "terra-draw/dist/common" deep import that Vite's
// bundler resolution tolerates but `tsc` (moduleResolution: "bundler",
// which still honours a package's declared exports map) rejects.
type TerraDrawAdapter = ConstructorParameters<typeof TerraDraw>[0]["adapter"];

/**
 * Exercises the real terra-draw library (not a mock of it) against the
 * exact addFeatures/setMode/selectFeature sequence catchment-map.tsx uses
 * to seed Select Area's editable AOI — see
 * docs/TerraRisk_Editable_AOI_2026.md. A browser-only WebGL/MapLibre
 * render loop can't be exercised in this test environment (confirmed:
 * document.visibilityState reports "hidden" in the Browser pane tool
 * used for manual verification, which stalls MapLibre's requestAnimationFrame-
 * driven "load" event indefinitely — an environment limitation, not a
 * product bug), so this stands in a fake TerraDrawAdapter satisfying the
 * library's own adapter interface, which is the same boundary terra-draw's
 * own test suite draws the line at.
 */
function fakeAdapter(): TerraDrawAdapter {
  return {
    project: () => ({ x: 0, y: 0 }),
    unproject: () => ({ lng: 0, lat: 0 }),
    setCursor: () => {},
    getLngLatFromEvent: () => null,
    setDoubleClickToZoom: () => {},
    getMapEventElement: () => document.createElement("div"),
    register: () => {},
    unregister: () => {},
    render: () => {},
    clear: () => {},
    getCoordinatePrecision: () => 9,
  };
}

function buildDraw(): TerraDraw {
  return new TerraDraw({
    adapter: fakeAdapter(),
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
            feature: { draggable: false, coordinates: { midpoints: true, draggable: true, deletable: true } },
          },
        },
      }),
    ],
  });
}

// Mirrors catchment-map.tsx's seeding block exactly, including the real
// generateFeatureId() helper (not crypto.randomUUID() directly — that
// throws outside a secure context, which production is, see the
// dedicated test below) and the addFeatures-result guard: selectFeature()
// throws for a feature id that was never actually added, so a rejected
// add must short-circuit rather than proceed into select mode.
function seedAndSelect(draw: TerraDraw, ring: Ring) {
  const featureId = generateFeatureId();
  const [result] = draw.addFeatures([
    {
      id: featureId,
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [ring] },
      properties: { mode: "polygon" },
    },
  ]);
  let selected = false;
  if (result?.valid) {
    draw.setMode("select");
    draw.selectFeature(featureId);
    selected = true;
  }
  return { featureId, result, selected };
}

// The real Maski (Raichur) village boundary as served by the
// admin-boundaries API — a genuine 41-vertex administrative outline
// covering 4,991 ha, sourced from the DataMeet Census village dataset
// (backend/scripts/fetch_raichur_villages_datameet.py).
//
// This replaced a 5-point, 9.29 ha synthetic square: the previous
// pipeline had no village polygons at all and wrapped each OSM village
// *point* in a fixed ~150 m box. Keeping a real outline here matters for
// this test specifically — the seeding path has to survive an irregular,
// many-vertex, 6-decimal-place polygon, which is what it now actually
// receives in production, not a rectangle.
const MASKI_VILLAGE_GEOMETRY: GeoJSON.MultiPolygon = {
  type: "MultiPolygon",
  coordinates: [
    [
      [
        [76.634561, 15.996653],
        [76.645321, 15.998615],
        [76.657898, 16.000067],
        [76.662167, 16.000147],
        [76.66715, 15.999477],
        [76.672549, 15.99783],
        [76.683959, 15.990179],
        [76.689195, 15.989287],
        [76.688548, 15.982218],
        [76.686725, 15.97314],
        [76.685391, 15.969986],
        [76.682747, 15.967452],
        [76.680521, 15.965935],
        [76.679749, 15.963693],
        [76.678043, 15.957353],
        [76.676665, 15.953273],
        [76.676254, 15.949158],
        [76.675171, 15.946671],
        [76.672158, 15.94431],
        [76.670352, 15.940715],
        [76.668653, 15.934587],
        [76.666847, 15.930995],
        [76.665474, 15.919131],
        [76.661553, 15.911806],
        [76.659772, 15.913579],
        [76.657673, 15.91495],
        [76.654667, 15.916046],
        [76.65171, 15.916627],
        [76.638503, 15.918171],
        [76.634437, 15.926211],
        [76.633052, 15.931142],
        [76.629999, 15.935018],
        [76.620828, 15.94157],
        [76.615484, 15.950613],
        [76.613842, 15.954914],
        [76.617925, 15.967601],
        [76.620479, 15.972588],
        [76.624429, 15.97308],
        [76.626381, 15.975249],
        [76.630314, 15.985073],
        [76.634561, 15.996653],
      ],
    ],
  ],
};

// A synthetic ring far denser than any real Raichur village (the densest
// in the loaded dataset is 168 vertices), kept as a headroom check that
// the seeding path survives a many-vertex, non-self-intersecting shape.
// Rounded to 9 decimal places to match what PostGIS's ST_AsGeoJSON (and
// terra-draw's own default coordinatePrecision) actually produce — see
// the companion "excessive precision" test below for the unrounded case.
function denseRing(vertexCount: number): Ring {
  const centerLon = 76.657;
  const centerLat = 15.9585;
  const radius = 0.0015;
  const round9 = (n: number) => Math.round(n * 1e9) / 1e9;
  const points: Ring = [];
  for (let i = 0; i < vertexCount; i++) {
    const angle = (2 * Math.PI * i) / vertexCount;
    const wobble = 1 + 0.15 * Math.sin(angle * 5);
    points.push([round9(centerLon + radius * wobble * Math.cos(angle)), round9(centerLat + radius * wobble * Math.sin(angle))]);
  }
  points.push(points[0]);
  return points;
}

describe("generateFeatureId — production runs over plain HTTP, not a secure context", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("falls back to crypto.getRandomValues when crypto.randomUUID is unavailable (the exact production condition)", () => {
    // Root cause of the production bug this regression test locks in:
    // crypto.randomUUID() throws outside a secure context — HTTPS, or
    // "localhost" specifically. TerraRisk's production origin is plain
    // HTTP on a bare IP, confirmed via direct browser check against it
    // (window.isSecureContext === false, typeof crypto.randomUUID ===
    // "undefined", calling it throws TypeError). Local dev never caught
    // this because "localhost" itself is exempt from the secure-context
    // requirement. Simulating that exact absence here, rather than
    // stubbing a throw, matches what Chrome actually does on that origin.
    const original = crypto.randomUUID;
    // @ts-expect-error - simulating an insecure context, where this
    // property does not exist on the Crypto prototype at all.
    delete crypto.randomUUID;

    try {
      const id = generateFeatureId();
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    } finally {
      crypto.randomUUID = original;
    }
  });

  it("the fallback ID is actually accepted by terra-draw's addFeatures — not just well-formed", () => {
    const original = crypto.randomUUID;
    // @ts-expect-error - see above
    delete crypto.randomUUID;

    try {
      const draw = buildDraw();
      draw.start();
      draw.setMode("static");

      const seedRing = ringFromGeometry(MASKI_VILLAGE_GEOMETRY) as Ring;
      const { result, selected } = seedAndSelect(draw, seedRing);

      expect(result?.valid).toBe(true);
      expect(selected).toBe(true);
    } finally {
      crypto.randomUUID = original;
    }
  });
});

describe("editable AOI seeding — real terra-draw library", () => {
  it("accepts the real Maski village geometry, selects it, and reports it back through getSnapshot", () => {
    const draw = buildDraw();
    draw.start();
    draw.setMode("static");

    const seedRing = ringFromGeometry(MASKI_VILLAGE_GEOMETRY);
    expect(seedRing).not.toBeNull();

    const { featureId, result, selected } = seedAndSelect(draw, seedRing as Ring);

    expect(result).toEqual({ id: featureId, valid: true });
    expect(selected).toBe(true);
    expect(draw.getMode()).toBe("select");

    const snapshot = draw.getSnapshot();
    const polygon = snapshot.find((f) => f.id === featureId);
    expect(polygon).toBeDefined();
    expect(polygon?.geometry.type).toBe("Polygon");
    expect(polygon?.properties.selected).toBe(true);
    expect((polygon?.geometry as GeoJSON.Polygon).coordinates[0]).toEqual(seedRing);
  });

  it("accepts a dense, non-self-intersecting ring (the shape real OSM village boundaries will have)", () => {
    const draw = buildDraw();
    draw.start();
    draw.setMode("static");

    const ring = denseRing(48);
    const { featureId, result, selected } = seedAndSelect(draw, ring);

    expect(result).toEqual({ id: featureId, valid: true });
    expect(selected).toBe(true);
    const polygon = draw.getSnapshot().find((f) => f.id === featureId);
    expect(polygon).toBeDefined();
    expect((polygon?.geometry as GeoJSON.Polygon).coordinates[0]).toHaveLength(ring.length);
  });

  it("never throws when the seed geometry is rejected (e.g. coordinates with excessive precision) — it just doesn't select anything", () => {
    // The exact scenario the addFeatures-result guard in catchment-map.tsx
    // exists for: without it, selectFeature() would throw on a feature id
    // that addFeatures silently refused to store, crashing the "load"
    // handler outright instead of leaving the AOI to be drawn from scratch.
    const draw = buildDraw();
    draw.start();
    draw.setMode("static");

    const centerLon = 76.657;
    const centerLat = 15.9585;
    const radius = 0.0015;
    const excessivePrecisionRing: Ring = Array.from({ length: 8 }, (_, i) => {
      const angle = (2 * Math.PI * i) / 8;
      return [centerLon + radius * Math.cos(angle), centerLat + radius * Math.sin(angle)] as [number, number];
    });
    excessivePrecisionRing.push(excessivePrecisionRing[0]);

    expect(() => seedAndSelect(draw, excessivePrecisionRing)).not.toThrow();

    const { result, selected } = seedAndSelect(draw, excessivePrecisionRing);
    expect(result?.valid).toBe(false);
    expect(selected).toBe(false);
    expect(draw.getMode()).toBe("static");
    expect(draw.getSnapshot()).toHaveLength(0);
  });

  it("still lets vertex edits happen after seeding — updateFeatureGeometry mutates the seeded ring", () => {
    const draw = buildDraw();
    draw.start();
    draw.setMode("static");

    const seedRing = ringFromGeometry(MASKI_VILLAGE_GEOMETRY) as Ring;
    const { featureId } = seedAndSelect(draw, seedRing);

    // Rounded to terra-draw's own default coordinatePrecision (9 decimal
    // places) — real vertex drags go through terra-draw's own coordinate
    // rounding before reaching updateFeatureGeometry, so a raw
    // floating-point sum (which can overshoot 9 decimals from binary
    // rounding) isn't representative of what a real drag produces.
    const round9 = (n: number) => Math.round(n * 1e9) / 1e9;
    const movedRing: Ring = [...seedRing];
    movedRing[0] = [round9(movedRing[0][0] + 0.001), round9(movedRing[0][1] + 0.001)];
    movedRing[movedRing.length - 1] = movedRing[0];

    draw.updateFeatureGeometry(featureId, { type: "Polygon", coordinates: [movedRing] });

    const polygon = draw.getSnapshot().find((f) => f.id === featureId);
    expect((polygon?.geometry as GeoJSON.Polygon).coordinates[0][0]).toEqual(movedRing[0]);
  });
});
