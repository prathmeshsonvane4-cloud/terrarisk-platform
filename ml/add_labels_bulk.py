"""Add many labelled fields at once, from a plain text file.

    python ml/add_labels_bulk.py ml/incoming/2026-09-21.txt
    python ml/add_labels_bulk.py ml/incoming/2026-09-21.txt --dry-run

One field per line, `|` between columns, `#` starts a comment:

    # coordinates            | village | crop      | cane type | planted    | source | radius_m
    18.5527, 76.4970         | Shera   | sugarcane | plant     | 2025-12-20 | owner  |
    18.5541, 76.4983         | Shera   | soybean   |           |            | visual |
    18.5502,76.4951; 18.5504,76.4958; 18.5499,76.4959; 18.5497,76.4952 | Shera | sugarcane | ratoon | | field |

Only the first three columns are required; the rest may be blank. Give
one point (a square is drawn around it) or three or more points (used as
the field boundary exactly).

WHY A BULK FILE AT ALL
----------------------
Labels arrive as a handful of coordinates a day, collected on a phone in
the field. Typing one `add_label.py` command per field invites the two
mistakes that quietly ruin a training set: the same field entered twice
under different ids, and latitude and longitude swapped. Both are caught
here, per line, before anything is written.

WHAT IS AND IS NOT CHECKED
--------------------------
Checked, because they are facts about geometry: the point is a plausible
Latur-district coordinate, it is not a repeat of a field already
labelled, and a sugarcane label carries its plant/ratoon type.

NOT checked: whether the crop really is sugarcane. Nothing here looks at
satellite data to second-guess a label, and it never will — the labels
are the ground truth the model is measured against, so deciding them
from the same imagery the model learns from would measure nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from add_label import load, square_around  # noqa: E402

DEFAULT_PATH = Path("ml/labels.geojson")

# Latur district, generously bounded. A coordinate outside this is far
# more likely to be a typo than a real field, and a single wrong digit in
# a longitude lands the square in another district without looking wrong.
LATUR_BOUNDS = (17.8, 19.0, 75.9, 77.3)  # lat_min, lat_max, lon_min, lon_max

# Two pins closer than this are treated as the same field submitted
# twice. At 40 m the 50 m squares would overlap heavily, so the model
# would see one field's curve twice and leave-one-village-out would be
# scoring on a field it had effectively trained on.
DUPLICATE_DISTANCE_M = 40.0

# Anything in this set is sugarcane; everything else is not. Deliberately
# explicit: a silent "unknown crop means not cane" is how a mislabelled
# positive becomes a negative and teaches the model the opposite lesson.
CANE_WORDS = {"sugarcane", "sugar cane", "cane", "us", "oos", "ऊस", "uus"}


@dataclass
class Row:
    line_number: int
    raw: str
    ring: list[list[float]]
    centre: tuple[float, float]
    village: str
    crop: str
    label: int
    cane_type: str
    planted: str
    source: str


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle metres between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def parse_pairs(text: str) -> list[tuple[float, float]]:
    """Read one or more `lat,lon` pairs, separated by `;`.

    Accepts the shapes a phone actually produces: "18.5527, 76.4970",
    "18.5527,76.4970", and Google Maps' "18.5527° N, 76.4970° E".
    """
    cleaned = re.sub(r"[°NEne]", " ", text)
    pairs: list[tuple[float, float]] = []
    for chunk in cleaned.split(";"):
        numbers = re.findall(r"-?\d+\.?\d*", chunk)
        if not numbers:
            continue
        if len(numbers) != 2:
            raise ValueError(f"expected 'lat, lon' but found {len(numbers)} numbers in {chunk.strip()!r}")
        pairs.append((float(numbers[0]), float(numbers[1])))
    if not pairs:
        raise ValueError("no coordinates found")
    return pairs


def fix_order(lat: float, lon: float) -> tuple[float, float, bool]:
    """Undo a swapped lat/lon, but only when it is unambiguous.

    In this district latitude is ~18 and longitude ~76, so a first value
    in the 70s is certainly a longitude. Anything less clear-cut is left
    alone and validated normally — silently "correcting" an ambiguous
    pair would move a field without anyone noticing.
    """
    if 70 <= lat <= 80 and 15 <= lon <= 25:
        return lon, lat, True
    return lat, lon, False


def parse_line(line: str, number: int) -> Row:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 3:
        raise ValueError("need at least: coordinates | village | crop")
    while len(parts) < 7:
        parts.append("")
    coords, village, crop, cane_type, planted, source, radius = parts[:7]

    if not village:
        raise ValueError("village is required — it forms the validation folds")

    pairs = parse_pairs(coords)
    fixed: list[tuple[float, float]] = []
    swapped = False
    for lat, lon in pairs:
        lat, lon, was_swapped = fix_order(lat, lon)
        swapped = swapped or was_swapped
        lat_min, lat_max, lon_min, lon_max = LATUR_BOUNDS
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            raise ValueError(f"{lat:.5f},{lon:.5f} is outside Latur district — check the digits")
        fixed.append((lat, lon))

    label = 1 if crop.strip().lower() in CANE_WORDS else 0
    cane_type = cane_type.strip().lower()
    if label == 1 and cane_type not in ("plant", "ratoon"):
        raise ValueError(
            "sugarcane needs its type: 'plant' (this cycle's new planting) or "
            "'ratoon' (regrown after a harvest). They look different from space."
        )
    if label == 0 and cane_type:
        raise ValueError("cane type only applies to sugarcane")
    if label == 0 and not crop:
        raise ValueError("crop is required — 'fallow' or 'bare' is fine, blank is not")

    if len(fixed) == 1:
        metres = float(radius) if radius else 25.0
        if not 5 <= metres <= 200:
            raise ValueError(f"radius {metres} m is out of range (5-200)")
        ring = square_around(fixed[0][0], fixed[0][1], metres)
        centre = fixed[0]
    elif len(fixed) == 2:
        raise ValueError("two points describe a line, not a field — give one centre or 3+ corners")
    else:
        ring = [[lon, lat] for lat, lon in fixed]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        centre = (sum(p[0] for p in fixed) / len(fixed), sum(p[1] for p in fixed) / len(fixed))

    row = Row(
        line_number=number,
        raw=line.strip(),
        ring=ring,
        centre=centre,
        village=village,
        crop=crop,
        label=label,
        cane_type=cane_type,
        planted=planted,
        source=(source or "visual").lower(),
    )
    if row.source not in ("visual", "field", "mill", "owner"):
        raise ValueError(f"source {row.source!r} must be one of visual, field, mill, owner")
    if swapped:
        print(f"  line {number}: latitude and longitude were swapped — corrected to {centre[0]:.5f},{centre[1]:.5f}")
    return row


def ring_centre(ring: list[list[float]]) -> tuple[float, float]:
    points = ring[:-1] if ring[0] == ring[-1] else ring
    return (sum(p[1] for p in points) / len(points), sum(p[0] for p in points) / len(points))


def slug(village: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", village.lower()).strip("-") or "field"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Text file of fields, one per line")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH, help="Label set to append to")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report, write nothing")
    args = parser.parse_args()

    collection = load(args.path)
    existing = collection["features"]
    existing_centres = [(f["properties"]["field_id"], ring_centre(f["geometry"]["coordinates"][0])) for f in existing]
    used_ids = {f["properties"]["field_id"] for f in existing}

    accepted: list[Row] = []
    rejected: list[tuple[int, str, str]] = []
    skipped: list[tuple[int, str]] = []

    for number, line in enumerate(args.input.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            row = parse_line(line, number)
        except ValueError as error:
            rejected.append((number, line.strip(), str(error)))
            continue

        near = [
            (field_id, distance_m(row.centre, centre))
            for field_id, centre in existing_centres
            if distance_m(row.centre, centre) < DUPLICATE_DISTANCE_M
        ]
        near += [
            (f"line {other.line_number}", distance_m(row.centre, other.centre))
            for other in accepted
            if distance_m(row.centre, other.centre) < DUPLICATE_DISTANCE_M
        ]
        if near:
            field_id, metres = near[0]
            skipped.append((number, f"{metres:.0f} m from {field_id} — same field already labelled"))
            continue
        accepted.append(row)

    # Ids are assigned only after every line is parsed, so a rejected line
    # does not leave a gap in the numbering of the fields that did pass.
    per_village: dict[str, int] = {}
    for field_id in used_ids:
        match = re.match(r"(.+)-(\d+)$", field_id)
        if match:
            per_village[match.group(1)] = max(per_village.get(match.group(1), 0), int(match.group(2)))

    new_features = []
    for row in accepted:
        prefix = slug(row.village)
        per_village[prefix] = per_village.get(prefix, 0) + 1
        field_id = f"{prefix}-{per_village[prefix]:02d}"
        new_features.append(
            {
                "type": "Feature",
                "properties": {
                    "field_id": field_id,
                    "label": row.label,
                    "village": row.village,
                    "crop": row.crop,
                    "planted": row.planted,
                    "cane_type": row.cane_type,
                    "sown_year": row.planted[:4] if row.planted else "",
                    "source": row.source,
                },
                "geometry": {"type": "Polygon", "coordinates": [row.ring]},
            }
        )
        print(f"  {field_id:16} {row.crop:12} {'cane ' + row.cane_type if row.label else 'not cane':14} {row.village}")

    if rejected:
        print(f"\n{len(rejected)} line(s) REJECTED — fix and re-run just these:")
        for number, raw, reason in rejected:
            print(f"  line {number}: {reason}\n    {raw}")
    if skipped:
        print(f"\n{len(skipped)} line(s) skipped as duplicates:")
        for number, reason in skipped:
            print(f"  line {number}: {reason}")

    if args.dry_run:
        print(f"\ndry run — nothing written. {len(new_features)} field(s) would be added.")
        return

    if new_features:
        collection["features"].extend(new_features)
        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
        print(f"\nadded {len(new_features)} field(s) to {args.path}")
    else:
        print("\nnothing added")

    total = collection["features"]
    cane = sum(1 for f in total if f["properties"]["label"] == 1)
    villages = {f["properties"]["village"] for f in total}
    print(f"label set now: {len(total)} fields | {cane} sugarcane, {len(total) - cane} other | {len(villages)} village(s)")
    print("run  python ml/dataset_status.py  to see what is still needed")


if __name__ == "__main__":
    main()
