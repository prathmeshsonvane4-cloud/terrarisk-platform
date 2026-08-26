"""Per-scene satellite report for one field.

Answers two questions for a single plot:
  1. How often does each satellite actually see it?
  2. How do the signals move as the crop grows?

Reports EVERY acquisition, not a monthly average, because the monthly
mean hides the thing that matters at this field size — how many usable
looks the month really contained.

    python ml/plot_report.py field.geojson --start 2025-11-01
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import ee

S2 = "COPERNICUS/S2_SR_HARMONIZED"
S2_CLOUD_PROB = "COPERNICUS/S2_CLOUD_PROBABILITY"
S1 = "COPERNICUS/S1_GRD"
CLOUD_PROB_THRESHOLD = 40


def initialise(key_path: Path, project: str) -> None:
    email = json.loads(key_path.read_text())["client_email"]
    ee.Initialize(ee.ServiceAccountCredentials(email, str(key_path)), project=project)


def optical_scenes(region: ee.Geometry, start: str, end: str) -> list[dict]:
    """One row per Sentinel-2 overpass, with its cloud fraction over the field."""
    scenes = ee.ImageCollection(S2).filterBounds(region).filterDate(start, end)
    clouds = ee.ImageCollection(S2_CLOUD_PROB).filterBounds(region)
    joined = ee.ImageCollection(
        ee.Join.saveFirst("cp").apply(
            primary=scenes,
            secondary=clouds,
            condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
        )
    )

    def describe(image: ee.Image) -> ee.Feature:
        image = ee.Image(image)
        probability = ee.Image(image.get("cp")).select("probability")
        # Cloud fraction measured over THIS FIELD, not the whole 100x100 km
        # tile. A tile can be 60% cloudy while this plot is clear, and the
        # scene-level metadata would wrongly discard it.
        cloudy = probability.gte(CLOUD_PROB_THRESHOLD).rename("cloudy")
        clear = image.updateMask(probability.lt(CLOUD_PROB_THRESHOLD))
        indices = clear.normalizedDifference(["B8", "B4"]).rename("ndvi").addBands(
            clear.normalizedDifference(["B8", "B11"]).rename("ndmi")
        )
        stats = indices.addBands(cloudy).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9
        )
        return ee.Feature(
            None,
            {
                "date": image.date().format("YYYY-MM-dd"),
                "cloud_fraction": stats.get("cloudy"),
                "ndvi": ee.Algorithms.If(stats.contains("ndvi"), stats.get("ndvi"), None),
                "ndmi": ee.Algorithms.If(stats.contains("ndmi"), stats.get("ndmi"), None),
            },
        )

    return [f["properties"] for f in ee.FeatureCollection(joined.map(describe)).getInfo()["features"]]


def radar_scenes(region: ee.Geometry, start: str, end: str) -> list[dict]:
    """One row per Sentinel-1 pass. Backscatter averaged in linear power."""
    scenes = (
        ee.ImageCollection(S1)
        .filterBounds(region)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )

    def describe(image: ee.Image) -> ee.Feature:
        image = ee.Image(image)
        power = image.select(["VV", "VH"]).divide(10.0).multiply(math.log(10.0)).exp()
        stats = power.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9
        )

        def as_db(band: str):
            return ee.Algorithms.If(
                stats.contains(band), ee.Number(stats.get(band)).log10().multiply(10.0), None
            )

        return ee.Feature(
            None,
            {
                "date": image.date().format("YYYY-MM-dd"),
                "orbit": image.get("orbitProperties_pass"),
                "vv": as_db("VV"),
                "vh": as_db("VH"),
            },
        )

    return [f["properties"] for f in ee.FeatureCollection(scenes.map(describe)).getInfo()["features"]]


def _bar(value: float | None, scale: float = 40.0) -> str:
    return "" if value is None else "#" * max(0, int(value * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("field", type=Path)
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end", default="2026-08-27")
    parser.add_argument("--edge-buffer", type=float, default=10.0)
    parser.add_argument("--key", type=Path, default=Path("terrarisk-platform-bfc1102a3c63.json"))
    parser.add_argument("--project", default="terrarisk-platform")
    args = parser.parse_args()

    initialise(args.key, args.project)
    geometry = json.loads(args.field.read_text())
    if geometry.get("type") == "FeatureCollection":
        geometry = geometry["features"][0]["geometry"]
    full = ee.Geometry(geometry)
    region = full.buffer(-args.edge_buffer)

    full_area = full.area(maxError=1).getInfo()
    interior = region.area(maxError=1).getInfo()
    print(f"field      {full_area:,.0f} m2  ({full_area / 4046.86:.2f} acres)")
    print(f"interior   {interior:,.0f} m2 after a {args.edge_buffer:.0f} m edge buffer")
    print(f"           ~{interior / 100:.0f} Sentinel-2 pixels at 10 m")

    optical = sorted(optical_scenes(region, args.start, args.end), key=lambda r: r["date"])
    radar = sorted(radar_scenes(region, args.start, args.end), key=lambda r: r["date"])

    print(f"\n{'=' * 74}")
    print("SENTINEL-2 (optical) — every overpass")
    print(f"{'=' * 74}")
    print(f"{'date':>12} {'cloud%':>7} {'NDVI':>7} {'NDMI':>7}")
    usable = 0
    for row in optical:
        cloud = row["cloud_fraction"]
        ndvi = row["ndvi"]
        if ndvi is not None and cloud is not None and cloud < 0.5:
            usable += 1
        print(
            f"{row['date']:>12} {('   -' if cloud is None else f'{cloud * 100:6.0f}')}"
            f" {('     -' if ndvi is None else f'{ndvi:7.3f}')}"
            f" {('     -' if row['ndmi'] is None else f'{row['ndmi']:7.3f}')}  {_bar(ndvi)}"
        )

    print(f"\n{'=' * 74}")
    print("SENTINEL-1 (radar) — every pass, unaffected by cloud")
    print(f"{'=' * 74}")
    print(f"{'date':>12} {'orbit':>10} {'VV dB':>8} {'VH dB':>8}")
    for row in radar:
        print(
            f"{row['date']:>12} {str(row['orbit'])[:10]:>10}"
            f" {('       -' if row['vv'] is None else f'{row['vv']:8.2f}')}"
            f" {('       -' if row['vh'] is None else f'{row['vh']:8.2f}')}"
        )

    # --- revisit summary -------------------------------------------------
    print(f"\n{'=' * 74}")
    print("REVISIT FREQUENCY")
    print(f"{'=' * 74}")
    by_month: dict[str, dict[str, int]] = defaultdict(lambda: {"s2": 0, "s2_clear": 0, "s1": 0})
    for row in optical:
        bucket = by_month[row["date"][:7]]
        bucket["s2"] += 1
        cloud = row["cloud_fraction"]
        if row["ndvi"] is not None and cloud is not None and cloud < 0.5:
            bucket["s2_clear"] += 1
    for row in radar:
        by_month[row["date"][:7]]["s1"] += 1

    print(f"{'month':>9} {'S2 passes':>10} {'S2 usable':>10} {'S1 passes':>10}")
    for month in sorted(by_month):
        counts = by_month[month]
        flag = "  <-- no optical" if counts["s2_clear"] == 0 else ""
        print(f"{month:>9} {counts['s2']:>10} {counts['s2_clear']:>10} {counts['s1']:>10}{flag}")

    print(f"\nSentinel-2: {len(optical)} passes, {usable} usable ({usable / max(len(optical), 1):.0%})")
    print(f"Sentinel-1: {len(radar)} passes, all usable (radar sees through cloud)")


if __name__ == "__main__":
    main()
