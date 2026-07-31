# Editable AOI — Technical Note

**Date:** 31 July 2026
**Scope:** Select Area workflow only. Draw and Upload are unchanged. No backend, API, recommendation-engine, or database-schema changes.

## What changed

Select Area used to force a binary choice once a village was previewed: **"Use Entire Village"** (submit the village's own polygon, unmodifiable) or **"Draw Inside Village"** (start from an empty map and hand-draw a new boundary, with the village shown only as a non-interactive reference). Neither option let an officer take the village's real shape and adjust it — trim off a strip that isn't actually irrigated, or extend slightly past the administrative line to include a farm pond just outside it.

The new flow removes that choice. Selecting a village now shows its boundary (read-only, green), and a single **"Create Editable AOI"** button seeds an editable polygon with that village's own shape and switches straight into edit mode. The user can then resize, reshape, expand, or contract that polygon — or leave it untouched and submit it exactly as the village's own boundary. One action, both previous outcomes, plus everything in between.

## How AOI editing works

The map tool is [Terra Draw](https://terradraw.io/), already the engine behind the Draw tab — nothing new was introduced for editing itself. Terra Draw's `TerraDrawSelectMode` was already configured (for the Draw tab, before this change) with:

```ts
new TerraDrawSelectMode({
  flags: {
    polygon: {
      feature: { draggable: false, coordinates: { midpoints: true, draggable: true, deletable: true } },
    },
  },
})
```

`coordinates.draggable` lets a vertex be moved (resize/reshape), `coordinates.midpoints` lets a midpoint be dragged out to insert a new vertex (add), and `coordinates.deletable` lets a vertex be removed. This is exactly the vertex editing, adding, deleting, and resizing the mission asked for — it already existed for hand-drawn boundaries; the only new work was making Select Area *start* in this mode with a real shape already loaded, instead of requiring the user to draw one from nothing.

Terra Draw exposes a public API for exactly that:

```ts
draw.addFeatures([{
  id: crypto.randomUUID(),
  type: "Feature",
  geometry: { type: "Polygon", coordinates: [villageRing] },
  properties: { mode: "polygon" },   // tags it as belonging to TerraDrawPolygonMode
}]);
draw.setMode("select");
draw.selectFeature(featureId);       // enters edit mode on it immediately
```

`properties.mode: "polygon"` is required so `TerraDrawSelectMode` recognises the feature as an editable polygon (confirmed against Terra Draw's own guides, not guessed). This happens once, right when the map finishes loading — `CatchmentMap` reads its new `initialAoiGeometry` prop exactly once per mount (via a ref, not a reactive effect), so a later re-render can never silently reset a user's in-progress edit. Selecting a *different* village remounts the map component (via a React `key`), which is what starts a genuinely fresh editing session.

Everything downstream of that point — live area calculation, the "change" event stream, the submit payload — is the same code path the Draw tab already used. No new drawing logic was written; only the seeding step is new.

## Which geometry is finally sent to the backend

Whatever the AOI currently looks like when "Create catchment" is submitted — the untouched village shape, or a reshaped version of it. The submission path is identical to every other Select Area or Draw submission that existed before this change: the current ring is wrapped into a `GeoJSONMultiPolygon` (`toCatchmentGeometry`, unchanged) and sent as `POST /catchments`' `geometry` field, with `admin_boundary_id` still set to the selected village's id (unchanged — this is what keeps the catchment linked to its village for display, independent of whatever shape was actually submitted). The backend re-validates and recomputes area itself exactly as it always has (`ST_Area` in `app/api/catchments.py`) — nothing about the server side changed, because nothing needed to.

## Why the village boundary itself is never modified

It's never loaded into an editable Terra Draw feature at all. The village boundary is rendered through a completely separate mechanism — `setGeoJsonOverlay`, a plain MapLibre GeoJSON source/layer (green fill + outline) with no Terra Draw involvement, no drag handles, no selection state. The AOI is a *second*, independent polygon, seeded with a *copy* of the village's coordinates at the moment "Create Editable AOI" is clicked. Editing the AOI mutates only Terra Draw's own feature store; the reference layer's source data is never touched by any drag, add, or delete interaction. There is structurally no code path by which reshaping the AOI could alter the green reference layer — they are different rendering systems, not the same polygon shown twice.

## Validation: warn, don't reject

Per the mission's explicit instruction, no edit is ever auto-reverted or silently blocked:

- **Too small / too large** — reuses the exact bounds (`0.5–50,000 ha`) and message (`catchmentAreaBoundsIssue`) the Draw tab has always enforced. This one *does* disable the submit button, because it mirrors a real, unchanged backend constraint (`_MIN_CATCHMENT_AREA_HA`/`_MAX_CATCHMENT_AREA_HA` in `app/api/catchments.py`) — submitting anyway would only fail server-side, so the UI says so first.
- **No longer overlaps the selected village** — new, computed client-side with `@turf/boolean-intersects` (`ringOverlapsGeometry`, `lib/catchment-geo.ts`). This is warning-only and never disables submission, because there is no backend rule requiring a catchment's geometry to overlap its `admin_boundary_id` at all — `admin_boundary_id` is a contextual link, not a geometric constraint. The warning exists purely so an officer who dragged the AOI far off the village by mistake notices before submitting, not to enforce a rule the system doesn't actually have.

## How this differs from editing administrative boundaries

It doesn't touch them, in either direction. `AdminBoundary` rows (the village polygons themselves, in PostGIS) are never read into an editable state, never targeted by any `PATCH`/`PUT`-style request (none exists), and never written to by this workflow. The AOI is a brand-new `Catchment` row with its own independently-stored geometry column — editing it end to end, including saving it, only ever touches `catchment.geometry`. `admin_boundary_id` is the one field that connects the two tables, and it is a plain foreign key reference (unchanged by this feature), not a shared geometry. Administrative boundaries remain exactly what they were before this ticket: read-only, source-controlled data imported by `load_admin_boundaries.py`, never editable from the product's own UI at all.
