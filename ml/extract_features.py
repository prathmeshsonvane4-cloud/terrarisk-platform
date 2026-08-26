"""Turn labelled field polygons into a training table.

Reads a GeoJSON FeatureCollection of labelled fields and writes one CSV
row per field: a monthly satellite time series plus the phenology
features a model actually learns from.

    python ml/extract_features.py labels.geojson features.csv \
        --start 2025-06-01 --months 12

Each input feature needs these properties:

    field_id   unique id
    label      1 = sugarcane, 0 = not sugarcane
    village    used ONLY to form spatial validation folds

WHY THE DEFAULTS ARE WHAT THEY ARE
----------------------------------
`--edge-buffer 15` shrinks every polygon inward before sampling. At
Sentinel-2's 10 m resolution a field's boundary pixels are mixtures of
the field, the bund, the track and the neighbour's crop. On a 0.6 acre
plot (~49 m across) the edge ring is most of the field, so sampling it
raw measures the neighbourhood rather than the crop.

Months with no cloud-free observation are written as empty, never as 0.
An NDVI of 0 means bare rock; a cloudy August means we do not know. The
two must not be confused, and the monsoon months over Maharashtra are
frequently the latter — both test locations lost August entirely.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import ee

S2 = "COPERNICUS/S2_SR_HARMONIZED"
S2_CLOUD_PROB = "COPERNICUS/S2_CLOUD_PROBABILITY"
S1 = "COPERNICUS/S1_GRD"
CLOUD_PROB_THRESHOLD = 40


def initialise(key_path: Path, project: str) -> None:
    credentials = ee.ServiceAccountCredentials(
        json.loads(key_path.read_text())["client_email"], str(key_path)
    )
    ee.Initialize(credentials, project=project)


def _optical_monthly(region: ee.Geometry, start: str, months: int) -> ee.FeatureCollection:
    """Monthly cloud-masked NDVI and NDMI inside `region`."""
    end = ee.Date(start).advance(months, "month")
    scenes = ee.ImageCollection(S2).filterBounds(region).filterDate(start, end)
    clouds = ee.ImageCollection(S2_CLOUD_PROB).filterBounds(region)
    joined = ee.ImageCollection(
        ee.Join.saveFirst("cloud_probability").apply(
            primary=scenes,
            secondary=clouds,
            condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
        )
    )

    def mask(image: ee.Image) -> ee.Image:
        image = ee.Image(image)
        probability = ee.Image(image.get("cloud_probability")).select("probability")
        clear = image.updateMask(probability.lt(CLOUD_PROB_THRESHOLD))
        # NDVI: greenness. NDMI: canopy water — sugarcane holds moisture
        # well past the point annual crops have dried off, so it is a
        # useful second opinion rather than a restatement of NDVI.
        return clear.normalizedDifference(["B8", "B4"]).rename("ndvi").addBands(
            clear.normalizedDifference(["B8", "B11"]).rename("ndmi")
        )

    def per_month(offset) -> ee.Feature:
        month_start = ee.Date(start).advance(offset, "month")
        month_end = month_start.advance(1, "month")
        window = joined.filterDate(month_start, month_end)
        stats = window.map(mask).mean().reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9
        )
        return ee.Feature(
            None,
            {
                "month": month_start.format("YYYY-MM"),
                # Guarded: a month with no clear scene yields a band-less
                # composite, and a bare .get() throws server-side.
                "ndvi": ee.Algorithms.If(stats.contains("ndvi"), stats.get("ndvi"), None),
                "ndmi": ee.Algorithms.If(stats.contains("ndmi"), stats.get("ndmi"), None),
                "scenes": window.size(),
            },
        )

    return ee.FeatureCollection(ee.List.sequence(0, months - 1).map(per_month))


def _radar_monthly(region: ee.Geometry, start: str, months: int) -> ee.FeatureCollection:
    """Monthly Sentinel-1 VV/VH backscatter — unaffected by cloud.

    Averaged in LINEAR power, not decibels. dB is a logarithm, so an
    arithmetic mean of dB is a geometric mean of power and biases low.
    """
    end = ee.Date(start).advance(months, "month")
    scenes = (
        ee.ImageCollection(S1)
        .filterBounds(region)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )

    def per_month(offset) -> ee.Feature:
        month_start = ee.Date(start).advance(offset, "month")
        window = scenes.filterDate(month_start, month_start.advance(1, "month"))

        def to_power(image: ee.Image) -> ee.Image:
            image = ee.Image(image).select(["VV", "VH"])
            return image.divide(10.0).multiply(math.log(10.0)).exp()

        stats = window.map(to_power).mean().reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9
        )

        def as_db(band: str):
            value = stats.get(band)
            return ee.Algorithms.If(
                stats.contains(band), ee.Number(value).log10().multiply(10.0), None
            )

        return ee.Feature(
            None,
            {
                "month": month_start.format("YYYY-MM"),
                "vv": as_db("VV"),
                "vh": as_db("VH"),
                "scenes": window.size(),
            },
        )

    return ee.FeatureCollection(ee.List.sequence(0, months - 1).map(per_month))


def derive_features(ndvi: list[float | None], ndmi: list[float | None]) -> dict:
    """The columns the model actually sees.

    `min_ndvi` is the one that matters: sugarcane runs 12-18 months and
    never goes bare, while every annual crop here drops to soil between
    seasons. Amplitude carries the same information from the other side.
    """
    clean = [v for v in ndvi if v is not None]
    clean_ndmi = [v for v in ndmi if v is not None]
    if not clean:
        return {}

    longest = current = 0
    for value in ndvi:
        if value is not None and value > 0.4:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    return {
        "min_ndvi": min(clean),
        "max_ndvi": max(clean),
        "mean_ndvi": sum(clean) / len(clean),
        "amplitude_ndvi": max(clean) - min(clean),
        "months_above_0_4": sum(1 for v in clean if v > 0.4),
        "months_above_0_3": sum(1 for v in clean if v > 0.3),
        "longest_green_run": longest,
        "peak_month_index": ndvi.index(max(clean)),
        "min_ndmi": min(clean_ndmi) if clean_ndmi else None,
        "mean_ndmi": sum(clean_ndmi) / len(clean_ndmi) if clean_ndmi else None,
        "observed_months": len(clean),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", type=Path, help="GeoJSON FeatureCollection of labelled fields")
    parser.add_argument("output", type=Path, help="CSV to write")
    parser.add_argument("--start", default="2025-06-01", help="First month (agricultural year start)")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--edge-buffer", type=float, default=15.0, help="Metres to shrink each polygon")
    parser.add_argument("--key", type=Path, default=Path("terrarisk-platform-bfc1102a3c63.json"))
    parser.add_argument("--project", default="terrarisk-platform")
    parser.add_argument("--skip-radar", action="store_true")
    args = parser.parse_args()

    initialise(args.key, args.project)
    collection = json.loads(args.labels.read_text())["features"]
    print(f"{len(collection)} labelled fields", flush=True)

    rows: list[dict] = []
    for index, feature in enumerate(collection, start=1):
        properties = feature["properties"]
        field_id = properties.get("field_id", f"field-{index}")
        region = ee.Geometry(feature["geometry"]).buffer(-args.edge_buffer)

        try:
            area_m2 = region.area(maxError=1).getInfo()
        except Exception as error:  # noqa: BLE001 - reported per field, never fatal
            print(f"  SKIP {field_id}: geometry failed ({error})", flush=True)
            continue
        if area_m2 <= 0:
            print(f"  SKIP {field_id}: nothing left after the {args.edge_buffer} m edge buffer", flush=True)
            continue

        optical = _optical_monthly(region, args.start, args.months).getInfo()["features"]
        ndvi = [f["properties"]["ndvi"] for f in optical]
        ndmi = [f["properties"]["ndmi"] for f in optical]
        months = [f["properties"]["month"] for f in optical]

        row = {
            "field_id": field_id,
            "label": properties["label"],
            "village": properties.get("village", "unknown"),
            "interior_area_m2": round(area_m2),
            "interior_pixels_10m": round(area_m2 / 100),
        }
        row.update(derive_features(ndvi, ndmi))
        for month, value in zip(months, ndvi):
            row[f"ndvi_{month}"] = value

        if not args.skip_radar:
            radar = _radar_monthly(region, args.start, args.months).getInfo()["features"]
            for f in radar:
                row[f"vv_{f['properties']['month']}"] = f["properties"]["vv"]
                row[f"vh_{f['properties']['month']}"] = f["properties"]["vh"]

        rows.append(row)
        print(
            f"  [{index}/{len(collection)}] {field_id}  label={row['label']}  "
            f"px={row['interior_pixels_10m']}  min_ndvi={row.get('min_ndvi')}",
            flush=True,
        )

    if not rows:
        sys.exit("no usable fields")

    import pandas as pd

    frame = pd.DataFrame(rows)
    frame.to_csv(args.output, index=False)
    print(f"\nwrote {args.output}  ({len(frame)} rows x {len(frame.columns)} columns)")


if __name__ == "__main__":
    main()
