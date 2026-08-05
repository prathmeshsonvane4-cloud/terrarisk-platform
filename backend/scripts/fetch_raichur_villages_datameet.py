"""Sources REAL Raichur village polygons from the DataMeet Indian Village
Boundaries dataset, superseding the synthetic squares that
`fetch_raichur_villages_osm.py` produced.

Why this replaces the OSM village step (and only that step):

`fetch_raichur_villages_osm.py`'s own docstring is explicit that OSM has
no village-level administrative *polygons* in Raichur, so it wrapped each
real OSM village *point* in a fixed ~150 m synthetic square. Measured
against the district, those squares average **9.28 ha** where the true
average Raichur village is **~1,557 ha** — 168x too small. Because
Select Area seeds a catchment's AOI from the village polygon, every water
report generated that way was computed over a ~310 m box centred on the
settlement (rooftops), not the village's agricultural extent. That is a
scientific-validity problem, not a cosmetic one, and it is what this
script fixes.

That same docstring already named this exit path: *"Supersede this
entirely once real ... village polygon data is available: point
`load_admin_boundaries.py --file` at that dataset instead. No code change
needed elsewhere."* This script is that dataset swap. Nothing else
changes: no schema, no API, no frontend.

**State, district and taluka polygons are NOT re-sourced.** They were
already genuine OSM relation polygons (cross-checked against `ref:LGD:*`
codes) and are copied through from the existing fixture verbatim, so this
change is provably village-geometry-only.

Dataset: DataMeet Indian Village Boundaries, Karnataka (`ka/ka.geojson`).
  - Licence: ODbL (attribution required; commercial use permitted).
  - Provenance: District Census Handbook maps, geo-rectified against
    Survey of India toposheets, carrying Census 2011 attributes and
    `LOC_CODE` village identifiers.
  - Documented spatial registration error: +/- 500 m. Good enough for
    village-scale screening and adjacency; NOT a cadastral boundary, and
    must never be presented as one.
  - Chosen over KGIS/KSRSAC (better geometry, but its terms forbid
    commercial use, which TerraRisk's DCCB product is) and over SHRUG
    (0-2 km error vs DataMeet's +/- 500 m for Karnataka).

Two deliberate transformations are applied, both required for the
existing product to keep working unchanged:

1. **Coordinate rounding to 6 dp (~0.11 m).** Terra Draw rejects features
   whose coordinates exceed 9 decimal places, and DataMeet ships ~14.
   Without this, "Create Editable AOI" would silently refuse to seed
   (`addFeatures` returns invalid; see `catchment-map.tsx`'s result
   guard). 6 dp is three orders of magnitude finer than the dataset's own
   +/- 500 m accuracy, so nothing real is lost.

2. **Vertex-budget simplification.** `Catchment` enforces
   `ST_NPoints(geometry) <= 2000`, and an AOI seeded at exactly the limit
   would leave a user unable to add a single vertex. Polygons above
   `_MAX_VILLAGE_VERTICES` are simplified with progressively coarser
   `preserve_topology=True` tolerances until they fit. Villages already
   under budget are left untouched.

Usage:
    python scripts/fetch_raichur_villages_datameet.py \
        --source path/to/ka.geojson \
        --base scripts/fixtures/raichur_villages_osm.geojson \
        --out scripts/fixtures/raichur_villages_datameet.geojson
"""

import argparse
import json
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

# Raichur's spelling in the DataMeet DISTRICT field is not guaranteed to
# match ours; accept the known variants rather than a single literal.
_RAICHUR_DISTRICT_ALIASES = {"raichur", "raichuru", "rayachuru", "raichur "}

# Terra Draw's default coordinatePrecision is 9; anything above that is
# rejected outright. 6 dp (~0.11 m) sits far inside that limit and far
# inside the dataset's own +/- 500 m registration error.
_COORDINATE_DECIMALS = 6

# Chosen well below Catchment's own chk_catchment_vertex_count (2000) so a
# seeded AOI still has room for the user to add vertices while editing.
_MAX_VILLAGE_VERTICES = 1200

# Progressively coarser simplification tolerances, in degrees. 1e-5 is
# ~1.1 m; the coarsest here is ~55 m, still an order of magnitude finer
# than the source's own accuracy.
_SIMPLIFY_TOLERANCES = (1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4)


def _round_coordinates(geometry: dict) -> dict:
    """Rounds every coordinate to _COORDINATE_DECIMALS in place-by-copy."""

    def walk(node):
        if isinstance(node, (int, float)):
            return round(float(node), _COORDINATE_DECIMALS)
        return [walk(item) for item in node]

    return {"type": geometry["type"], "coordinates": walk(geometry["coordinates"])}


def _vertex_count(geometry: BaseGeometry) -> int:
    if geometry.geom_type == "Polygon":
        return len(geometry.exterior.coords) + sum(len(ring.coords) for ring in geometry.interiors)
    if geometry.geom_type == "MultiPolygon":
        return sum(_vertex_count(part) for part in geometry.geoms)
    return 0


def _fit_vertex_budget(geometry: BaseGeometry, name: str) -> tuple[BaseGeometry, float | None]:
    """Simplifies only if over budget, at the gentlest tolerance that fits.

    Returns the geometry and the tolerance actually applied (None if the
    polygon was already within budget and left untouched).
    """
    if _vertex_count(geometry) <= _MAX_VILLAGE_VERTICES:
        return geometry, None

    for tolerance in _SIMPLIFY_TOLERANCES:
        simplified = geometry.simplify(tolerance, preserve_topology=True)
        if not simplified.is_empty and simplified.is_valid and _vertex_count(simplified) <= _MAX_VILLAGE_VERTICES:
            return simplified, tolerance

    # Never silently ship a polygon that would break AOI seeding.
    raise RuntimeError(
        f"Village {name!r} still exceeds {_MAX_VILLAGE_VERTICES} vertices at the coarsest tolerance "
        f"({_SIMPLIFY_TOLERANCES[-1]}); investigate before loading."
    )


def _repair(geometry: BaseGeometry, name: str) -> BaseGeometry:
    """Hand-digitised boundaries occasionally self-intersect; PostGIS and
    Shapely both reject those. buffer(0) is the standard repair and is a
    no-op for already-valid geometry."""
    if geometry.is_valid:
        return geometry
    repaired = geometry.buffer(0)
    if repaired.is_empty or not repaired.is_valid:
        raise RuntimeError(f"Village {name!r} has geometry that could not be repaired")
    return repaired


def build(source_path: Path, base_path: Path, out_path: Path) -> None:
    print(f"Reading base fixture (state/district/taluka kept verbatim): {base_path}")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    carried = [f for f in base["features"] if f["properties"]["level"] != "village"]
    replaced_village_count = len(base["features"]) - len(carried)
    taluka_shapes = {
        f["properties"]["name"]: shape(f["geometry"]) for f in carried if f["properties"]["level"] == "taluka"
    }
    print(f"  carried {len(carried)} non-village features ({len(taluka_shapes)} talukas)")
    print(f"  replacing {replaced_village_count} synthetic village squares")

    print(f"Reading DataMeet Karnataka dataset: {source_path}")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    print(f"  {len(source['features'])} Karnataka village features")

    raichur = [
        f
        for f in source["features"]
        if str(f.get("properties", {}).get("DISTRICT", "")).strip().lower() in _RAICHUR_DISTRICT_ALIASES
    ]
    print(f"  {len(raichur)} features in Raichur district")
    if not raichur:
        districts = sorted({str(f.get("properties", {}).get("DISTRICT", "")) for f in source["features"]})
        raise RuntimeError(f"No Raichur features found. Districts present: {districts}")

    features = list(carried)
    assigned = 0
    outside = 0
    simplified_count = 0
    skipped_no_name = 0
    seen: set[tuple[str, str]] = set()

    for feature in raichur:
        props = feature["properties"]
        name = (props.get("NAME") or "").strip()
        if not name:
            skipped_no_name += 1
            continue

        geometry = _repair(shape(feature["geometry"]), name)

        # Assign to one of the CURRENT 7 talukas by centroid
        # point-in-polygon. Census 2011 predates the Sirwar and Maski
        # splits, so the source's own TALUK field is out of date; the real
        # taluka polygons already in the fixture are the authority. Same
        # method fetch_raichur_villages_osm.py used for its own points.
        centroid = geometry.representative_point()
        taluka_name = next((t for t, poly in taluka_shapes.items() if poly.contains(centroid)), None)
        if taluka_name is None:
            outside += 1
            continue

        key = (name, taluka_name)
        if key in seen:
            continue
        seen.add(key)

        geometry, tolerance = _fit_vertex_budget(geometry, name)
        if tolerance is not None:
            simplified_count += 1

        features.append(
            {
                "type": "Feature",
                "geometry": _round_coordinates(mapping(geometry)),
                "properties": {
                    "level": "village",
                    "name": name,
                    "parent_level": "taluka",
                    "parent_name": taluka_name,
                    # Census 2011 village location code — the dataset's own
                    # stable identifier, stored in the column the loader
                    # already reads (admin_boundary.lgd_code).
                    "lgd_code": str(props.get("LOC_CODE") or "") or None,
                },
            }
        )
        assigned += 1

    print(
        f"  {assigned} villages assigned to a taluka; {outside} outside all taluka polygons; "
        f"{skipped_no_name} without a name; {simplified_count} simplified to fit the vertex budget."
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    print(f"Wrote {out_path} ({len(features)} features, {out_path.stat().st_size / 1e6:.1f} MB).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="DataMeet ka.geojson")
    parser.add_argument("--base", required=True, type=Path, help="Existing fixture supplying state/district/taluka")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    build(args.source, args.base, args.out)


if __name__ == "__main__":
    main()
