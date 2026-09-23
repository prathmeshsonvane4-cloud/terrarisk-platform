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


def cut_month(
    months: list[str],
    series: list[float | None],
    threshold: float = GREEN_THRESHOLD,
    allowed=None,
) -> str | None:
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
        if allowed is not None and not allowed(months[index]):
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


# Radar harvest: cutting a tall cane canopy removes the volume that
# scatters radar back as VH (cross-polarised) power, so VH falls. Reported
# falls for sugarcane harvest are a few dB; 1.5 dB is set deliberately
# below that as a conservative floor, and — as with the optical rule —
# NOT tuned against the farmer's dates. Speckle on a plot of a few pixels
# is large, which is why a monthly mean of several passes is used, never
# a single pass.
RADAR_HARVEST_DROP_DB = 1.5
# A canopy cannot rebuild in a month. A fall that is back within this of
# the old level the following month was speckle or wet soil, not a cut.
RADAR_REBOUND_DB = 0.5


def series_for(row: dict, prefix: str) -> tuple[list[str], list[float | None]]:
    months = sorted(key[len(prefix) + 1:] for key in row if key.startswith(f"{prefix}_2"))
    return months, [float(row[f"{prefix}_{m}"]) if row.get(f"{prefix}_{m}") else None for m in months]


def radar_cut_month(months: list[str], vh_db: list[float | None], allowed=None) -> tuple[str, float] | None:
    """The month VH backscatter fell most, if it fell like a harvest.

    Returns the month and the size of the fall in dB, so a reader can see
    a marginal detection for what it is.
    """
    best: tuple[float, str] | None = None
    for index in range(1, len(vh_db)):
        current = vh_db[index]
        before = [v for v in vh_db[max(0, index - 2):index] if v is not None]
        if current is None or not before:
            continue
        if allowed is not None and not allowed(months[index]):
            continue
        prior = fmean(before)
        drop = prior - current
        if drop < RADAR_HARVEST_DROP_DB:
            continue
        following = vh_db[index + 1] if index + 1 < len(vh_db) else None
        if following is not None and following > prior - RADAR_REBOUND_DB:
            continue
        if best is None or drop > best[0]:
            best = (drop, months[index])
    return (best[1], best[0]) if best else None


# When cane is cut here: Maharashtra's crushing season runs roughly
# November to April, and mills do not cut in the monsoon. The search for a
# harvest is confined to these months because outside them radar VH swings
# with soil moisture — on the 23 Sep 2026 block, radar alone picked a
# monsoon month as the "harvest" on two fields out of fourteen.
#
# DISCLOSED: this restriction was added after seeing that result. It is a
# fact about the crop calendar, not a number fitted to the labels, but it
# means the 23 Sep batch cannot serve as evidence for it. The next batch,
# ideally from another village, is the test.
HARVEST_SEASON_MONTHS = (11, 12, 1, 2, 3, 4)


def in_harvest_season(month_label: str) -> bool:
    return int(month_label[5:7]) in HARVEST_SEASON_MONTHS


def fused_cut_month(row: dict) -> tuple[str, str] | None:
    """Harvest month from both sensors, searched only in the harvest season.

    Optical is sharp when it has a clear view; radar always has a view but,
    on plots of a few pixels, is noisier. So optical is used when it found
    a cut in season, and radar only fills in when it did not — the case
    radar exists for, a harvest hidden by cloud.

    The first version let the EARLIER detection win. On the 23 Sep 2026
    block that made dating worse than optical alone (radar often fell a
    month early), so it was replaced. This rule was also chosen after
    seeing that batch, so that batch is not evidence for it.
    """
    optical = cut_month(*monthly_series(row), allowed=in_harvest_season)
    radar = None
    if any(key.startswith("vh_2") for key in row):
        found = radar_cut_month(*series_for(row, "vh"), allowed=in_harvest_season)
        radar = found[0] if found else None

    if optical:
        agrees = radar is not None and abs(_month_number(optical) - _month_number(radar)) <= 1
        return optical, "both" if agrees else "optical"
    if radar:
        return radar, "radar"
    return None


def _month_number(label: str) -> int:
    return int(label[:4]) * 12 + int(label[5:7])


def month_gap(seen: str, stated: str) -> int:
    """Months between a detection and what the farmer stated.

    A stated range ("2026-01..2026-02" for "cut between January and
    February") scores 0 anywhere inside it. Recording such a range as a
    single month would charge the detector for the vagueness of the label
    — which is exactly what the first scoring of the 23 Sep batch did.
    """
    earliest, _, latest = stated.partition("..")
    latest = latest or earliest
    value = _month_number(seen)
    if value < _month_number(earliest):
        return value - _month_number(earliest)
    if value > _month_number(latest):
        return value - _month_number(latest)
    return 0


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

    radar_rows = [row for row in rows if any(key.startswith("vh_2") for key in row)]
    if radar_rows:
        print("\nRADAR — Sentinel-1 VH backscatter, dB  (sees through cloud)\n")
        radar_months, _ = series_for(radar_rows[0], "vh")
        print("field         " + " ".join(m[2:] for m in radar_months))
        for row in radar_rows:
            _, vh_db = series_for(row, "vh")
            print(f"{row['field_id']:13} " + " ".join(f"{v:5.1f}" if v is not None else "    ." for v in vh_db))

        optical_months = sum(1 for row in rows for m in months if row.get(f"ndvi_{m}"))
        radar_filled = sum(1 for row in radar_rows for m in radar_months if row.get(f"vh_{m}"))
        print(f"\n  months with a usable reading: optical {optical_months}/{len(rows) * len(months)}, "
              f"radar {radar_filled}/{len(radar_rows) * len(radar_months)}")

        print(f"\n{'field':13} {'stated':8} {'optical cut':12} {'radar cut':16} radar vs stated")
        radar_gaps, optical_gaps = [], []
        for row in radar_rows:
            stated = row.get("planted", "")
            optical = cut_month(*monthly_series(row))
            found = radar_cut_month(*series_for(row, "vh"))
            radar_text = f"{found[0]} ({found[1]:.1f} dB)" if found else "none"
            verdict = "-"
            if row.get("cane_type") == "ratoon" and stated:
                if found:
                    gap = month_gap(found[0], stated)
                    radar_gaps.append(gap)
                    verdict = "same month" if gap == 0 else f"{gap:+d} month(s)"
                if optical:
                    optical_gaps.append(month_gap(optical, stated))
            print(f"{row['field_id']:13} {stated:8} {optical or 'none':12} {radar_text:16} {verdict}")

        print(f"\nCOMBINED — both sensors, harvest season only (Nov-Apr)\n")
        print(f"{'field':13} {'stated':8} {'combined':10} {'from':8} vs stated")
        fused_gaps = []
        for row in radar_rows:
            stated = row.get("planted", "")
            found = fused_cut_month(row)
            verdict = "-"
            if row.get("cane_type") == "ratoon" and stated and found:
                gap = month_gap(found[0], stated)
                fused_gaps.append(gap)
                verdict = "same month" if gap == 0 else f"{gap:+d} month(s)"
            print(f"{row['field_id']:13} {stated:8} {found[0] if found else 'none':10} "
                  f"{found[1] if found else '':8} {verdict}")

        ratoon_count = sum(1 for row in radar_rows if row.get("cane_type") == "ratoon" and row.get("planted"))
        for name, gaps in (("optical", optical_gaps), ("radar", radar_gaps), ("combined", fused_gaps)):
            exact = sum(1 for g in gaps if g == 0)
            within = sum(1 for g in gaps if abs(g) <= 1)
            print(f"  {name:8} found a cut on {len(gaps)}/{ratoon_count} ratoon fields; "
                  f"exact month {exact}, within one month {within}")

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
