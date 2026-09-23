"""Turn labelled field polygons into a training table.

    python ml/extract_features.py ml/labels.geojson ml/features.csv

RESUMABLE. Each field is appended as soon as it is fetched, and fields
already present in the output are skipped on a re-run. Three hundred
fields is roughly an hour of Earth Engine round trips; a failure at field
250 must not cost the first 249.

Each input feature needs these properties:

    field_id   unique
    label      1 = sugarcane, 0 = not sugarcane
    village    used ONLY to build spatial validation folds

WHY THE DEFAULTS ARE WHAT THEY ARE
----------------------------------
`--edge-buffer 10` shrinks each polygon inward before sampling. At
Sentinel-2's 10 m a field's boundary pixels mix the crop with the bund,
the track and the neighbour. On the 0.6 acre Shera plot this leaves about
7 interior pixels out of 25 — small, but measuring the field rather than
its surroundings.

Radar is averaged in LINEAR POWER, not decibels. dB is a logarithm, so
averaging dB yields a geometric mean of power and biases low. The same
defect was found and fixed in the hydrology provider.

A month with no cloud-free scene is recorded as missing, never as 0.
NDVI 0 means bare rock; a clouded month means we did not see. Over
Maharashtra this is routine rather than exceptional — July and August
2026 gave fourteen passes and no usable optical observation on the Shera
plot.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).parent))
from features import greenup_index, in_planting_window, phenology_features  # noqa: E402

S2 = "COPERNICUS/S2_SR_HARMONIZED"
S2_CLOUD_PROB = "COPERNICUS/S2_CLOUD_PROBABILITY"
S1 = "COPERNICUS/S1_GRD"
CLOUD_PROB_THRESHOLD = 40

_TRANSIENT = ("too many", "quota", "timed out", "backend error", "internal error", "unavailable")


def initialise(key_path: Path, project: str) -> None:
    email = json.loads(key_path.read_text())["client_email"]
    ee.Initialize(ee.ServiceAccountCredentials(email, str(key_path)), project=project)


def with_retry(operation, *, attempts: int = 4, base_delay: float = 3.0):
    """Retry transient Earth Engine throttling, nothing else.

    A malformed geometry or a missing asset fails the same way on every
    attempt; retrying it spends quota to reach the same error and hides
    the cause behind a delay.
    """
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except ee.EEException as error:
            transient = any(marker in str(error).lower() for marker in _TRANSIENT)
            if not transient or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(f"      throttled, retrying in {delay:.0f}s", flush=True)
            time.sleep(delay)
    raise AssertionError("unreachable")


def monthly_optical(region: ee.Geometry, start: str, months: int) -> list[dict]:
    end = ee.Date(start).advance(months, "month")
    scenes = ee.ImageCollection(S2).filterBounds(region).filterDate(start, end)
    clouds = ee.ImageCollection(S2_CLOUD_PROB).filterBounds(region)
    joined = ee.ImageCollection(
        ee.Join.saveFirst("cp").apply(
            primary=scenes,
            secondary=clouds,
            condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
        )
    )

    def mask(image: ee.Image) -> ee.Image:
        image = ee.Image(image)
        probability = ee.Image(image.get("cp")).select("probability")
        clear = image.updateMask(probability.lt(CLOUD_PROB_THRESHOLD))
        # NDVI saturates once a canopy closes, so on its own it cannot
        # tell a five-month cane field from a ten-month one. NDRE (red
        # edge, B8A/B5) keeps responding past that point and EVI resists
        # the same saturation, which is what makes an age estimate
        # possible at all. Both come from 20 m bands — fine on an acre,
        # thin on a tenth of one.
        return (
            clear.normalizedDifference(["B8", "B4"]).rename("ndvi")
            .addBands(clear.normalizedDifference(["B8", "B11"]).rename("ndmi"))
            .addBands(clear.normalizedDifference(["B8A", "B5"]).rename("ndre"))
            .addBands(
                clear.expression(
                    "2.5 * ((nir - red) / (nir + 6 * red - 7.5 * blue + 1))",
                    {
                        # Surface reflectance is scaled by 10000 in this
                        # collection; EVI's coefficients assume 0-1
                        # reflectance, so it must be divided back down.
                        "nir": clear.select("B8").divide(10000),
                        "red": clear.select("B4").divide(10000),
                        "blue": clear.select("B2").divide(10000),
                    },
                ).rename("evi")
            )
        )

    def per_month(offset) -> ee.Feature:
        month_start = ee.Date(start).advance(offset, "month")
        window = joined.filterDate(month_start, month_start.advance(1, "month"))
        stats = window.map(mask).mean().reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9
        )
        return ee.Feature(
            None,
            {
                "month": month_start.format("YYYY-MM"),
                # Guarded: a month with no clear scene produces a
                # band-less composite, and a bare .get() throws.
                "ndvi": ee.Algorithms.If(stats.contains("ndvi"), stats.get("ndvi"), None),
                "ndmi": ee.Algorithms.If(stats.contains("ndmi"), stats.get("ndmi"), None),
                "ndre": ee.Algorithms.If(stats.contains("ndre"), stats.get("ndre"), None),
                "evi": ee.Algorithms.If(stats.contains("evi"), stats.get("evi"), None),
            },
        )

    collection = ee.FeatureCollection(ee.List.sequence(0, months - 1).map(per_month))
    return [f["properties"] for f in with_retry(collection.getInfo)["features"]]


def monthly_radar(region: ee.Geometry, start: str, months: int) -> list[dict]:
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
        power = window.map(
            lambda image: ee.Image(image).select(["VV", "VH"]).divide(10.0).multiply(math.log(10.0)).exp()
        )
        stats = power.mean().reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9
        )

        def as_db(band: str):
            return ee.Algorithms.If(
                stats.contains(band), ee.Number(stats.get(band)).log10().multiply(10.0), None
            )

        # Radar vegetation index, 4*VH/(VV+VH), computed in LINEAR power
        # where the ratio is meaningful — in dB it would be a difference
        # of logarithms, which is not the same quantity. It tracks canopy
        # structure and keeps working through monsoon cloud, so it carries
        # the growth months optical loses entirely.
        rvi = ee.Algorithms.If(
            stats.contains("VV"),
            ee.Algorithms.If(
                stats.contains("VH"),
                ee.Number(stats.get("VH"))
                .multiply(4)
                .divide(ee.Number(stats.get("VV")).add(ee.Number(stats.get("VH")))),
                None,
            ),
            None,
        )

        return ee.Feature(
            None,
            {"month": month_start.format("YYYY-MM"), "vv": as_db("VV"), "vh": as_db("VH"), "rvi": rvi},
        )

    collection = ee.FeatureCollection(ee.List.sequence(0, months - 1).map(per_month))
    return [f["properties"] for f in with_retry(collection.getInfo)["features"]]


def already_done(output: Path) -> set[str]:
    if not output.exists():
        return set()
    with output.open(newline="", encoding="utf-8") as handle:
        return {row["field_id"] for row in csv.DictReader(handle)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", default="2025-06-01", help="Window start (agricultural year)")
    parser.add_argument("--months", type=int, default=14)
    parser.add_argument("--edge-buffer", type=float, default=10.0)
    parser.add_argument("--key", type=Path, default=Path("terrarisk-platform-bfc1102a3c63.json"))
    parser.add_argument("--project", default="terrarisk-platform")
    parser.add_argument("--skip-radar", action="store_true")
    args = parser.parse_args()

    initialise(args.key, args.project)
    fields = json.loads(args.labels.read_text())["features"]
    done = already_done(args.output)
    pending = [f for f in fields if f["properties"].get("field_id") not in done]

    print(f"{len(fields)} labelled fields | {len(done)} already extracted | {len(pending)} to do")
    if not pending:
        print("nothing to do")
        return

    writer = None
    handle = args.output.open("a", newline="", encoding="utf-8")
    failures: list[tuple[str, str]] = []

    try:
        for index, field in enumerate(pending, start=1):
            properties = field["properties"]
            field_id = properties["field_id"]
            try:
                region = ee.Geometry(field["geometry"]).buffer(-args.edge_buffer)
                area = with_retry(lambda: region.area(maxError=1).getInfo())
                if area <= 0:
                    raise ValueError(f"nothing left after the {args.edge_buffer:g} m edge buffer")

                optical = monthly_optical(region, args.start, args.months)
                ndvi = [row["ndvi"] for row in optical]
                ndmi = [row["ndmi"] for row in optical]
                ndre = [row["ndre"] for row in optical]
                evi = [row["evi"] for row in optical]
                vv = vh = rvi = None
                if not args.skip_radar:
                    radar = monthly_radar(region, args.start, args.months)
                    vv = [row["vv"] for row in radar]
                    vh = [row["vh"] for row in radar]
                    rvi = [row["rvi"] for row in radar]

                row = {
                    "field_id": field_id,
                    "label": properties["label"],
                    "village": properties.get("village", "unknown"),
                    "crop": properties.get("crop", ""),
                    "cane_type": properties.get("cane_type", ""),
                    # Carried through so the age tools can compare their
                    # estimate against the date the farmer gave. Its
                    # absence was why train_age.py crashed rather than
                    # reporting that no field had a planting date.
                    "planted": properties.get("planted", ""),
                    "sown_year": properties.get("sown_year", ""),
                    "source": properties.get("source", ""),
                    "interior_area_m2": round(area),
                    "interior_pixels_10m": round(area / 100),
                }
                row["window_start"] = optical[0]["month"]
                row["window_end"] = optical[-1]["month"]
                row.update(phenology_features(ndvi, ndmi, vv, vh, ndre=ndre, evi=evi, rvi=rvi))

                # The calendar month the canopy started from bare ground,
                # and whether that falls in the local planting window
                # (November-March). A green-up outside it is usually
                # ratoon regrowth after a harvest rather than a planting,
                # which matters because age is counted from a different
                # event in each case.
                onset = greenup_index(ndvi)
                if onset is not None:
                    month_label = optical[onset]["month"]
                    row["greenup_month"] = month_label
                    row["greenup_in_planting_window"] = int(in_planting_window(int(month_label[5:7])))
                else:
                    row["greenup_month"] = ""
                    row["greenup_in_planting_window"] = ""
                for month, value in zip((r["month"] for r in optical), ndvi):
                    row[f"ndvi_{month}"] = value
                # Radar month by month as well as in summary. Optical
                # misses whole months to cloud — over Maharashtra, most of
                # the monsoon — while Sentinel-1 returns every month, so a
                # harvest that optical cannot date may still be datable
                # from the fall in backscatter.
                if not args.skip_radar:
                    for month, vh_value, rvi_value in zip((r["month"] for r in radar), vh, rvi):
                        row[f"vh_{month}"] = vh_value
                        row[f"rvi_{month}"] = rvi_value

            except Exception as error:  # noqa: BLE001 - one bad field must not end the run
                failures.append((field_id, str(error)[:120]))
                print(f"  [{index}/{len(pending)}] {field_id}  FAILED: {str(error)[:90]}", flush=True)
                continue

            if writer is None:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                if not done:
                    writer.writeheader()
            writer.writerow(row)
            handle.flush()  # survive a crash on the very next field

            print(
                f"  [{index}/{len(pending)}] {field_id}  label={row['label']}  "
                f"px={row['interior_pixels_10m']}  run={row.get('longest_green_run')}  "
                f"min={row.get('min_ndvi'):.3f}" if row.get("min_ndvi") is not None else "",
                flush=True,
            )
    finally:
        handle.close()

    print(f"\nwrote {args.output}")
    if failures:
        print(f"{len(failures)} field(s) failed — re-run to retry just those:")
        for field_id, message in failures[:10]:
            print(f"  {field_id}: {message}")


if __name__ == "__main__":
    main()
