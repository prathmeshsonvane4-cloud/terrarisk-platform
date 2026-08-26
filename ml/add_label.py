"""Add one labelled field to the label set.

Two ways in. A point plus a radius, when you know roughly where a field
is and it is broadly square:

    python ml/add_label.py --point 18.5527,76.4970 --radius 28 \
        --label 1 --crop sugarcane --village Shera --id shera-01

Or an exact boundary, pasted as a coordinate ring:

    python ml/add_label.py --coords "76.4967,18.5530 76.4969,18.5523 ..." \
        --label 0 --crop soybean --village Shera --id shera-02

Appends to ml/labels.geojson, creating it if absent. Refuses to
overwrite an existing field_id, so re-running a command by accident
cannot silently replace a label with a different one.

ON LABEL QUALITY
----------------
`--source` records HOW you know. It defaults to `visual`, and the value
carries through to the training table so the eventual accuracy claim can
say what its ground truth actually was. A label from a sugar mill's
supplier record and a label from squinting at a basemap are not the same
evidence, and a model trained on both should not pretend otherwise.

Never label a field by looking at the NDVI curve. That is the input the
model learns from, so labelling by it teaches the model your own rule and
produces a score that measures nothing. Label from what you know on the
ground, or from what the field looks like in high-resolution imagery.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

DEFAULT_PATH = Path("ml/labels.geojson")


def square_around(lat: float, lon: float, radius_m: float) -> list[list[float]]:
    """A square of side 2*radius centred on the point.

    Longitude degrees shrink with latitude, so the east-west step is
    divided by cos(lat) — without it a plot at 18 degrees north comes out
    noticeably rectangular.
    """
    lat_step = radius_m / 111_320.0
    lon_step = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return [
        [lon - lon_step, lat - lat_step],
        [lon + lon_step, lat - lat_step],
        [lon + lon_step, lat + lat_step],
        [lon - lon_step, lat + lat_step],
        [lon - lon_step, lat - lat_step],
    ]


def parse_ring(text: str) -> list[list[float]]:
    ring = []
    for pair in text.replace(";", " ").split():
        lon, lat = (float(part) for part in pair.split(","))
        ring.append([lon, lat])
    if len(ring) < 3:
        sys.exit("a boundary needs at least 3 points")
    if ring[0] != ring[-1]:
        ring.append(ring[0])  # GeoJSON rings must close
    return ring


def load(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"type": "FeatureCollection", "features": []}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--point", help="lat,lon of the field centre")
    parser.add_argument("--radius", type=float, default=25.0, help="Half-width in metres, with --point")
    parser.add_argument("--coords", help='Boundary as "lon,lat lon,lat ..."')
    parser.add_argument("--label", type=int, required=True, choices=[0, 1], help="1 = sugarcane")
    parser.add_argument("--id", dest="field_id", required=True)
    parser.add_argument("--village", required=True, help="Used to form spatial validation folds")
    parser.add_argument("--crop", default="", help="Free text, e.g. sugarcane / soybean / tur")
    parser.add_argument("--planted", default="", help="Planting date if known, YYYY-MM-DD")
    parser.add_argument(
        "--source",
        default="visual",
        choices=["visual", "field", "mill", "owner"],
        help="How the label is known — recorded so the accuracy claim can state its ground truth",
    )
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    if bool(args.point) == bool(args.coords):
        sys.exit("give exactly one of --point or --coords")

    if args.point:
        lat, lon = (float(part) for part in args.point.split(","))
        ring = square_around(lat, lon, args.radius)
    else:
        ring = parse_ring(args.coords)

    collection = load(args.path)
    if any(f["properties"]["field_id"] == args.field_id for f in collection["features"]):
        sys.exit(f"field_id {args.field_id!r} already exists — pick another or edit the file")

    collection["features"].append(
        {
            "type": "Feature",
            "properties": {
                "field_id": args.field_id,
                "label": args.label,
                "village": args.village,
                "crop": args.crop,
                "planted": args.planted,
                "source": args.source,
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }
    )

    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(json.dumps(collection, indent=2), encoding="utf-8")

    features = collection["features"]
    cane = sum(1 for f in features if f["properties"]["label"] == 1)
    villages = {f["properties"]["village"] for f in features}
    print(f"added {args.field_id} ({args.crop or 'label ' + str(args.label)}) to {args.path}")
    print(f"  {len(features)} fields | {cane} sugarcane, {len(features) - cane} other")
    print(f"  {len(villages)} village(s): {', '.join(sorted(villages))}")

    if len(villages) < 3:
        print("  NOTE: leave-one-village-out needs several villages to mean anything.")
    if cane and cane / len(features) > 0.6:
        print("  NOTE: heavily weighted to sugarcane. Real fields are mostly not cane,")
        print("        and a balanced label set will mis-calibrate against the district.")


if __name__ == "__main__":
    main()
