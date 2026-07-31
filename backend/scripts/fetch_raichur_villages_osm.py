"""One-off data-sourcing script: builds a real (not synthetic-names) Raichur
district admin-boundary GeoJSON from OpenStreetMap, for
`load_admin_boundaries.py` to load — the Karnataka/Raichur counterpart of
`fetch_latur_villages_osm.py`, built by the same method for parity (see
docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md Part 4 — "Karnataka
must be sourced through the SAME disclosed methodology, not a
better-looking but undisclosed one").

Why this exists: OSM has no village-level administrative *polygons*
anywhere in Raichur district either (verified directly, same as Latur) —
India's official village boundaries live in Bhuvan/LGD, not scriptably
bulk-downloadable from this environment. This script is the same
documented, honest middle ground `fetch_latur_villages_osm.py` uses:

    - State / district / taluka: REAL polygons, fetched from OSM
      (Nominatim's `polygon_geojson` lookup against real relation ids,
      cross-checked against the ref:LGD:* codes embedded in each
      relation's own OSM tags — verified interactively via Nominatim
      search + an Overpass administrative-boundary query against the
      Raichur district relation before being hardcoded below, not
      guessed).
    - Villages: REAL names and REAL approximate locations (OSM
      `place=village`/`place=town`/`place=city` point nodes, assigned to
      their containing taluka by point-in-polygon against the real taluka
      polygons above), each wrapped in the SAME small synthetic square
      buffer (~150m) `fetch_latur_villages_osm.py` uses — not a claim
      about the village's actual cadastral boundary, only about where it
      really is, and deliberately not a better (and therefore
      inconsistent, undisclosed) method than the one already shipped for
      Latur.

Supersede this entirely once real Bhuvan/LGD village polygon data is
available for either district: point `load_admin_boundaries.py --file`
at that dataset instead. No code change needed elsewhere.

Raichur district was reorganised into 7 taluks (the two newest, Sirwar
and Maski, split out of Lingsugur and Manvi/Raichur respectively) — this
script covers all 7, since it is what OSM's own administrative data
currently reflects, not the older 5-taluk map some public sources still
show. All relation ids below cross-checked against their `ref:LGD:*`
subdistrict codes returned by the same Overpass query that discovered
them (546 for the district; taluka LGD codes noted alongside each
relation id).

Usage:
    python scripts/fetch_raichur_villages_osm.py --out scripts/fixtures/raichur_villages_osm.geojson
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
_USER_AGENT = "TerraRisk-DataSourcing/1.0 (Select Area Phase 1 - Raichur village dataset build)"

# Real OSM relation ids, found and verified interactively before writing
# this script (Nominatim search + Overpass administrative-boundary query
# against the Raichur district relation, logged in the discovery session
# for this ticket) — not guessed. Cross-checked against the ref:LGD:*
# codes embedded in each relation's own OSM tags.
_STATE_RELATION_ID = 2019939  # Karnataka
_DISTRICT_RELATION_ID = 2020694  # Raichur (ref:LGD:district=546)
_TALUKA_RELATION_IDS: dict[str, int] = {
    "Raichur": 3724947,  # OSM name "Rayachuru taluku", ref:LGD:subdistrict=5461
    "Manvi": 3724946,  # ref:LGD:subdistrict=5462
    "Sindhanur": 3724948,  # OSM name "Sindhanuru taluku", ref:LGD:subdistrict=5463
    "Lingsugur": 3724945,  # OSM name "Lingasuguru taluku", ref:LGD:subdistrict=5459
    "Devadurga": 6532860,  # ref:LGD:subdistrict=5460
    "Sirwar": 14931879,  # OSM name "Siravara taluku", ref:LGD:subdistrict=7097
    "Maski": 14931880,  # OSM name "Maski taluku", ref:LGD:subdistrict=7101
}

# Same synthetic-buffer size as fetch_latur_villages_osm.py, deliberately
# — parity, not improvement, is the point (see module docstring).
_VILLAGE_BUFFER_DEGREES = 0.0014


def _http_get_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _fetch_polygon_geojson(osm_relation_id: int, simplify_threshold: float = 0.0) -> dict:
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
    print("Fetching Karnataka state polygon (simplified for a manageable file size)...")
    state_geom = _fetch_polygon_geojson(_STATE_RELATION_ID, simplify_threshold=0.01)

    print("Fetching Raichur district polygon...")
    district_geom = _fetch_polygon_geojson(_DISTRICT_RELATION_ID)

    taluka_geoms: dict[str, dict] = {}
    taluka_shapes: dict[str, object] = {}
    for name, relation_id in _TALUKA_RELATION_IDS.items():
        print(f"Fetching {name} taluka polygon...")
        geom = _fetch_polygon_geojson(relation_id)
        taluka_geoms[name] = geom
        taluka_shapes[name] = shape(geom)

    print("Fetching real village/town place nodes within Raichur district...")
    village_nodes = _fetch_village_nodes_in_district()
    print(f"  {len(village_nodes)} place nodes returned.")

    features = [
        {
            "type": "Feature",
            "geometry": state_geom,
            "properties": {"level": "state", "name": "Karnataka", "parent_level": None, "parent_name": None},
        },
        {
            "type": "Feature",
            "geometry": district_geom,
            "properties": {
                "level": "district",
                "name": "Raichur",
                "parent_level": "state",
                "parent_name": "Karnataka",
            },
        },
    ]
    for name, geom in taluka_geoms.items():
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "level": "taluka",
                    "name": name,
                    "parent_level": "district",
                    "parent_name": "Raichur",
                },
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
