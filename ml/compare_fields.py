"""Compare fields against each other: do they share one pattern?

    python ml/compare_fields.py ml/features.csv

Prints the monthly NDVI of every field side by side, the month each one
was cut and each one greened up again, how well the curves agree, and
whether the satellite's reading matches the dates the farmer gave.

WHY SHARED PIXELS INFLATE AGREEMENT
-----------------------------------
Fields in one block sit 20-40 m apart, and a Sentinel-2 pixel is 10 m
across. Two sample squares that nearly touch read partly the same ground,
so their curves are bound to look alike whatever the crop is doing. The
report therefore prints the distance between each pair alongside their
correlation: agreement between two fields 25 m apart says much less than
the same agreement between two fields 200 m apart, and only the reader
can weigh that if both numbers are visible.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import fmean, pstdev

sys.path.insert(0, str(Path(__file__).parent))
from add_labels_bulk import distance_m, ring_centre  # noqa: E402
from features import GREEN_THRESHOLD, interpolate_gaps  # noqa: E402


def monthly_series(row: dict) -> tuple[list[str], list[float | None]]:
    months = sorted(key[5:] for key in row if key.startswith("ndvi_2"))
    return months, [float(row[f"ndvi_{m}"]) if row[f"ndvi_{m}"] else None for m in months]


# A harvest is an abrupt loss of biomass, so it is found by the SIZE of
# the fall, not by the field staying bare afterwards. The first attempt
# here required two bare months and missed most real cuts: ratoon regrows
# within weeks, and several fields in the 23 Sep 2026 block were already
# back above 0.30 the month after they were cut.
#
# These three numbers are set from what the crop does, not fitted to the
# farmer's dates — a threshold tuned until it matched 14 labels from one
# block would measure nothing but itself:
#   a standing cane canopy sits well above 0.45;
#   cutting it removes most of the canopy, a fall of at least 0.20;
#   what remains is stubble, below 0.40.
STANDING_CANOPY_NDVI = 0.45
HARVEST_DROP_NDVI = 0.20
STUBBLE_NDVI = 0.40
# Cane takes months to rebuild a canopy. Anything back above this the
# very next month was never cut — it was a hazy reading.
IMPOSSIBLE_REBOUND_NDVI = 0.45


def cut_month(months: list[str], series: list[float | None], threshold: float = GREEN_THRESHOLD) -> str | None:
    """The month a standing canopy was cut — the largest qualifying fall.

    Returns None when no fall in the record looks like a harvest, which
    is the right answer for a field that was bare all year or one whose
    cut happened before the window opened.
    """
    filled = interpolate_gaps(series)
    best: tuple[float, str] | None = None
    for index in range(1, len(filled)):
        current = filled[index]
        if current is None or current > STUBBLE_NDVI:
            continue
        before = [v for v in filled[max(0, index - 2):index] if v is not None]
        if not before:
            continue
        prior = fmean(before)
        if prior < STANDING_CANOPY_NDVI or prior - current < HARVEST_DROP_NDVI:
            continue
        following = filled[index + 1] if index + 1 < len(filled) else None
        if following is not None and following >= IMPOSSIBLE_REBOUND_NDVI:
            continue  # a canopy cannot regrow that fast; this was cloud
        drop = prior - current
        if best is None or drop > best[0]:
            best = (drop, months[index])
    return best[1] if best else None


def regrowth_month(months: list[str], series: list[float | None], after: str | None,
                   threshold: float = GREEN_THRESHOLD) -> str | None:
    """First month back above the threshold after the cut, and staying."""
    filled = interpolate_gaps(series)
    start = months.index(after) if after in months else 0
    for index in range(start, len(filled) - 1):
        window = [v for v in filled[index:index + 2] if v is not None]
        if len(window) == 2 and all(v >= threshold for v in window) and (
            filled[index - 1] is None or filled[index - 1] < threshold
        ):
            return months[index]
    return None


def correlation(a: list[float | None], b: list[float | None]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 4:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    sx, sy = pstdev(xs), pstdev(ys)
    if sx == 0 or sy == 0:
        return None
    mx, my = fmean(xs), fmean(ys)
    return sum((x - mx) * (y - my) for x, y in pairs) / (len(pairs) * sx * sy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("features", type=Path)
    parser.add_argument("--labels", type=Path, default=Path("ml/labels.geojson"))
    args = parser.parse_args()

    with args.features.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("no fields")
        return

    centres = {}
    if args.labels.exists():
        for feature in json.loads(args.labels.read_text(encoding="utf-8"))["features"]:
            centres[feature["properties"]["field_id"]] = ring_centre(feature["geometry"]["coordinates"][0])

    months, _ = monthly_series(rows[0])

    print("MONTHLY NDVI   (. = no cloud-free view that month)\n")
    header = "field         type    cycle    " + " ".join(m[2:] for m in months)
    print(header)
    for row in rows:
        _, series = monthly_series(row)
        cells = " ".join(f"{v:5.2f}" if v is not None else "    ." for v in series)
        print(f"{row['field_id']:13} {row.get('cane_type', ''):7} {row.get('planted', ''):8} {cells}")

    print("\nWHAT THE SATELLITE SEES vs WHAT THE FARMER SAID\n")
    print(f"{'field':13} {'stated cycle start':19} {'cut seen':10} {'regrowth seen':14} agreement")
    agreements = []
    for row in rows:
        months_list, series = monthly_series(row)
        cut = cut_month(months_list, series)
        regrowth = regrowth_month(months_list, series, cut)
        stated = row.get("planted", "")
        verdict = "-"
        if row.get("cane_type") == "ratoon" and stated and cut:
            gap = (int(cut[:4]) - int(stated[:4])) * 12 + int(cut[5:7]) - int(stated[5:7])
            verdict = "same month" if gap == 0 else f"{gap:+d} month(s)"
            agreements.append(gap)
        print(f"{row['field_id']:13} {stated:19} {cut or 'none':10} {regrowth or 'none':14} {verdict}")

    if agreements:
        exact = sum(1 for g in agreements if g == 0)
        within = sum(1 for g in agreements if abs(g) <= 1)
        print(f"\n  cut month matched exactly on {exact}/{len(agreements)} ratoon fields, "
              f"within one month on {within}/{len(agreements)}")
        print("  A cut is only visible in the month a cloud-free scene caught the bare field,")
        print("  so a one-month lag is the expected resolution, not an error.")

    print("\nHOW ALIKE ARE THE CURVES (correlation, and how far apart the fields are)\n")
    pairs = []
    for i, first in enumerate(rows):
        for second in rows[i + 1:]:
            _, a = monthly_series(first)
            _, b = monthly_series(second)
            r = correlation(a, b)
            if r is None:
                continue
            metres = None
            if first["field_id"] in centres and second["field_id"] in centres:
                metres = distance_m(centres[first["field_id"]], centres[second["field_id"]])
            pairs.append((r, metres, first["field_id"], second["field_id"]))

    if pairs:
        values = [p[0] for p in pairs]
        print(f"  {len(pairs)} pairs | median correlation {sorted(values)[len(values)//2]:.2f} "
              f"| range {min(values):.2f} to {max(values):.2f}")
        far = [p for p in pairs if p[1] and p[1] > 100]
        if far:
            far_values = [p[0] for p in far]
            print(f"  of the {len(far)} pairs more than 100 m apart (no shared pixels): "
                  f"median {sorted(far_values)[len(far_values)//2]:.2f}")
        print("\n  least alike pairs:")
        for r, metres, one, two in sorted(pairs)[:5]:
            print(f"    {one:13} {two:13} r={r:5.2f}  {f'{metres:.0f} m apart' if metres else ''}")

    plant = [r for r in rows if r.get("cane_type") == "plant"]
    ratoon = [r for r in rows if r.get("cane_type") == "ratoon"]
    if plant and ratoon:
        print("\nPLANT CANE vs RATOON")
        for label, group in (("plant", plant), ("ratoon", ratoon)):
            runs = [float(r["longest_green_run"]) for r in group if r.get("longest_green_run")]
            greenups = [r.get("greenup_month", "") for r in group]
            print(f"  {label:7} n={len(group):2d}  longest green run {fmean(runs):.1f} months  "
                  f"green-up months: {', '.join(sorted({g for g in greenups if g}))}")


if __name__ == "__main__":
    main()
