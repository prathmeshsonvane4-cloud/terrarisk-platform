"""One-off data-sourcing script: builds a real (not synthetic-names) Latur
district admin-boundary GeoJSON from OpenStreetMap, for
`load_admin_boundaries.py` to load.

Why this exists (see docs/DECISIONS.md, M2A P1 entry): the M0 sample
fixture (`scripts/fixtures/sample_admin_boundaries.geojson`) used invented
placeholder names ("Sample Village 1", etc.) — fine for schema/pipeline
testing, unacceptable for the M2A demo, where an officer is meant to
search for a village they actually recognize. OSM has *no* village-level
administrative polygons anywhere in Latur district (verified directly,
not assumed) — India's official village boundaries live in Bhuvan/LGD,
a government GIS portal with no scriptable bulk-download API reachable
from this environment. This script is the documented, honest middle
ground:

    - State / district / taluka: REAL polygons, fetched from OSM
      (Nominatim's `polygon_geojson` lookup against real relation ids,
      cross-checked against LGD codes embedded in the OSM tags).
    - Villages: REAL names and REAL approximate locations (OSM
      `place=village`/`place=town`/`place=city` point nodes, assigned to their
      containing taluka by point-in-polygon against the real taluka
      polygons above) — but since `admin_boundary.geometry` is a
      NOT NULL MULTIPOLYGON column (no schema change in M2A scope), each
      village's true point location is wrapped in a small synthetic
      square buffer (~150m) around it. This is a standard, well-understood
      GIS placeholder-extent technique — it is NOT a claim about the
      village's actual cadastral boundary, only about where it real is.

Supersede this entirely once real Bhuvan/LGD village polygon data is
available: point `load_admin_boundaries.py --file` at that dataset
instead. No code change needed elsewhere — this is exactly the
source-agnostic seam the loader was built for.

Usage:
    python scripts/fetch_latur_villages_osm.py --out scripts/fixtures/latur_villages_osm.geojson
"""

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import Point, mapping, shape
from shapely.geometry.polygon import orient

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_OVERPASS_BASE = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "TerraRisk-DataSourcing/1.0 (M2A P1 village dataset build)"

# Real OSM relation ids, found and verified interactively before writing
# this script (Overpass queries logged in the P1 implementation notes) —
# not guessed. Cross-checked against the ref:LGD:* codes embedded in each
# relation's own OSM tags, which trace back to India's official Local
# Government Directory.
_STATE_RELATION_ID = 1950884  # Maharashtra (ref:LGD:state=27)
_DISTRICT_RELATION_ID = 1991624  # Latur (ref:LGD:district=481)
_TALUKA_RELATION_IDS: dict[str, int] = {
    "Latur": 10348487,
    "Ahmadpur": 10348489,
    "Ausa": 10348486,
    "Chakur": 10348482,
    "Deoni": 10348483,
    "Jalkot": 10348480,
    "Nilanga": 10348484,
    "Renapur": 10348488,
    "Shirur Anantpal": 10348485,
    "Udgir": 10348481,
}

# Half-width of the synthetic per-village placeholder square, in degrees —
# ~150m at this latitude. Deliberately small: never meant to be rendered
# as a real boundary (the M2A spec defers the boundary-overlay layer to
# M2B), only to satisfy the NOT NULL MULTIPOLYGON column with something
# centered on the village's real location.
_VILLAGE_BUFFER_DEGREES = 0.0014


def _http_get_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _fetch_polygon_geojson(osm_relation_id: int, simplify_threshold: float = 0.0) -> dict:
    """Real polygon for a real OSM relation, via Nominatim's lookup
    endpoint (which resolves administrative relations to GeoJSON directly
    — much simpler than reassembling multipolygon rings from Overpass'
    raw way/node output by hand)."""
    params = {
        "osm_ids": f"R{osm_relation_id}",
        "format": "json",
        "polygon_geojson": "1",
    }
    if simplify_threshold:
        params["polygon_threshold"] = str(simplify_threshold)
    url = f"{_NOMINATIM_BASE}/lookup?{urllib.parse.urlencode(params)}"
    results = _http_get_json(url)
    if not results:
        raise RuntimeError(f"Nominatim returned no result for relation {osm_relation_id}")
    time.sleep(1.1)  # Nominatim usage policy: max 1 request/second.
    return results[0]["geojson"]


def _fetch_village_nodes_in_district() -> list[dict]:
    """Real OSM place nodes (name + point location) for every
    village/town within Latur district — the only granularity at which
    OSM actually has point coverage for this area (verified: zero
    village-level *polygons* exist, but point nodes do)."""
    query = (
        "[out:json][timeout:60];"
        f"area({3_600_000_000 + _DISTRICT_RELATION_ID})->.a;"
        '(node["place"~"village|town|city"](area.a););'
        "out body;"
    )
    url = f"{_OVERPASS_BASE}?{urllib.parse.urlencode({'data': query})}"
    for attempt in range(3):
        try:
            data = _http_get_json(url)
            return data["elements"]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    return []


def _assign_taluka(point: Point, taluka_polygons: dict[str, object]) -> str | None:
    for name, polygon in taluka_polygons.items():
        if polygon.contains(point):
            return name
    return None


def _village_buffer_polygon(lon: float, lat: float) -> dict:
    d = _VILLAGE_BUFFER_DEGREES
    square = shape(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon - d, lat - d],
                    [lon + d, lat - d],
                    [lon + d, lat + d],
                    [lon - d, lat + d],
                    [lon - d, lat - d],
                ]
            ],
        }
    )
    return mapping(orient(square))


def build(out_path: Path) -> None:
    print("Fetching Maharashtra state polygon (simplified for a manageable file size)...")
    state_geom = _fetch_polygon_geojson(_STATE_RELATION_ID, simplify_threshold=0.01)

    print("Fetching Latur district polygon...")
    district_geom = _fetch_polygon_geojson(_DISTRICT_RELATION_ID)

    taluka_geoms: dict[str, dict] = {}
    taluka_shapes: dict[str, object] = {}
    for name, relation_id in _TALUKA_RELATION_IDS.items():
        print(f"Fetching {name} taluka polygon...")
        geom = _fetch_polygon_geojson(relation_id)
        taluka_geoms[name] = geom
        taluka_shapes[name] = shape(geom)

    print("Fetching real village/town place nodes within Latur district...")
    village_nodes = _fetch_village_nodes_in_district()
    print(f"  {len(village_nodes)} place nodes returned.")

    features = [
        {
            "type": "Feature",
            "geometry": state_geom,
            "properties": {"level": "state", "name": "Maharashtra", "parent_level": None, "parent_name": None},
        },
        {
            "type": "Feature",
            "geometry": district_geom,
            "properties": {
                "level": "district",
                "name": "Latur",
                "parent_level": "state",
                "parent_name": "Maharashtra",
            },
        },
    ]
    for name, geom in taluka_geoms.items():
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {"level": "taluka", "name": name, "parent_level": "district", "parent_name": "Latur"},
            }
        )

    seen: set[tuple[str, str]] = set()
    skipped_outside_any_taluka = 0
    for node in village_nodes:
        name = node.get("tags", {}).get("name")
        lat, lon = node.get("lat"), node.get("lon")
        if not name or lat is None or lon is None:
            continue
        taluka_name = _assign_taluka(Point(lon, lat), taluka_shapes)
        if taluka_name is None:
            skipped_outside_any_taluka += 1
            continue
        key = (name, taluka_name)
        if key in seen:
            continue  # duplicate OSM node for the same real village name+taluka
        seen.add(key)
        features.append(
            {
                "type": "Feature",
                "geometry": _village_buffer_polygon(lon, lat),
                "properties": {
                    "level": "village",
                    "name": name,
                    "parent_level": "taluka",
                    "parent_name": taluka_name,
                },
            }
        )

    print(f"  {len(seen)} villages assigned to a taluka, {skipped_outside_any_taluka} skipped (outside all talukas).")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    print(f"Wrote {out_path} ({len(features)} features total).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
