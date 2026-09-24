"""Everything around a farm, day by day: canopy, water, weather, soil.

    python ml/farm_context.py --field shera-13 --plot
    python ml/farm_context.py --point 18.5527,76.4970 --start 2025-10-01 --end 2026-09-22

One daily table per farm, joining:

  canopy      NDVI, NIRv and NDMI, fused daily from Sentinel-2 + Landsat
              (ml/timeseries.py), with harvests found on NDVI
  rainfall    GPM IMERG V07 (11 km, ~1 day behind) and CHIRPS v3 (5.5 km,
              ~3-4 weeks behind, better for history)
  weather     ERA5-Land: max/min temperature, dewpoint, solar radiation,
              surface pressure; wind speed averaged from HOURLY components
  ET0         FAO-56 Penman-Monteith reference evapotranspiration,
              computed here from the ERA5-Land variables
  balance     rainfall minus ET0, daily and over the last 30 days
  soil        SMAP L4 surface and root-zone moisture (9 km); ERA5-Land
              soil water in three layers (11 km)
  heat        MODIS land surface temperature, day and night (1 km)
  haze        MODIS MAIAC aerosol optical depth (1 km) — to check whether
              an odd optical pass was the atmosphere rather than the crop
  water       Dynamic World (10 m): water probability on the field and the
              share of water pixels within 1 km, per Sentinel-2 scene

WHAT THIS CANNOT GIVE, AND SAYS SO
----------------------------------
- Groundwater at farm scale. No satellite measures it: GRACE-FO's pixel is
  hundreds of kilometres across and months late. It comes from wells —
  CGWB / Maharashtra GSDA observation wells, 2-4 readings a year — and the
  platform's CGWB table is still empty (checked 24 Sep 2026).
- Field-scale rainfall, weather or soil moisture. Those grids are 1-11 km;
  every farm in a village shares one value. They describe the setting the
  crop is in, not the plot.
- Crop evapotranspiration. ET0 is the demand of a reference grass surface.
  Turning it into cane water use needs a crop coefficient curve tied to the
  crop's stage, which is a model with assumptions of its own — not done
  here yet, so nothing is labelled as crop water use.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))

SIGMA = 4.903e-9          # Stefan-Boltzmann, MJ K^-4 m^-2 day^-1 (FAO-56)
SOLAR_CONSTANT = 0.0820   # MJ m^-2 min^-1 (FAO-56)
ALBEDO = 0.23             # FAO-56 reference grass
WATER_BUFFER_M = 1000     # how far around the farm to look for open water


# ----------------------------------------------------------------------
# FAO-56 Penman-Monteith — pure functions, checked against FAO's own
# worked examples in test_farm_context.py
# ----------------------------------------------------------------------


def saturation_vapour_pressure(t_c: float) -> float:
    """e°(T), kPa (FAO-56 eq. 11)."""
    return 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))


def extraterrestrial_radiation(latitude_deg: float, day_of_year: int) -> float:
    """Ra, MJ m^-2 day^-1 (FAO-56 eqs. 21-25)."""
    phi = math.radians(latitude_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    omega = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    return (24 * 60 / math.pi) * SOLAR_CONSTANT * dr * (
        omega * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(omega)
    )


def wind_10m_to_2m(u10: float) -> float:
    """FAO-56 eq. 47: log wind profile from 10 m to the 2 m reference."""
    return u10 * 4.87 / math.log(67.8 * 10 - 5.42)


def et0_fao56(tmax: float, tmin: float, ea: float, rs: float, u2: float, pressure_kpa: float,
              latitude_deg: float, day_of_year: int, elevation_m: float) -> float:
    """Daily reference evapotranspiration, mm/day (FAO-56 eq. 6), soil heat
    flux taken as zero as FAO-56 recommends for daily steps."""
    tmean = (tmax + tmin) / 2
    delta = 4098 * saturation_vapour_pressure(tmean) / (tmean + 237.3) ** 2
    gamma = 0.000665 * pressure_kpa
    es = (saturation_vapour_pressure(tmax) + saturation_vapour_pressure(tmin)) / 2
    ra = extraterrestrial_radiation(latitude_deg, day_of_year)
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rns = (1 - ALBEDO) * rs
    relative = min(rs / rso, 1.0) if rso > 0 else 1.0
    rnl = SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * math.sqrt(max(ea, 0))) * (
        1.35 * relative - 0.35)
    rn = rns - rnl
    numerator = 0.408 * delta * rn + gamma * (900 / (tmean + 273)) * u2 * max(es - ea, 0)
    return max(numerator / (delta + gamma * (1 + 0.34 * u2)), 0.0)


def vapour_pressure_deficit(tmax: float, tmin: float, ea: float) -> float:
    es = (saturation_vapour_pressure(tmax) + saturation_vapour_pressure(tmin)) / 2
    return max(es - ea, 0.0)


def rolling_sum(values: list[float | None], window: int) -> list[float | None]:
    """Sum over the last `window` days; None until the window has no gaps,
    because a 30-day balance missing ten days of rain is not a 30-day balance."""
    out: list[float | None] = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1):i + 1]
        out.append(sum(chunk) if len(chunk) == window and all(v is not None for v in chunk) else None)
    return out


# ----------------------------------------------------------------------
# Earth Engine
# ----------------------------------------------------------------------


def _daily(collection, bands: list[str], geometry, start: date, end: date, scale: float,
           reducer: str = "mean", multiplier: float = 1.0) -> dict[date, dict]:
    """One value per day per band at `geometry`, reduced server-side.

    `reducer` combines the images inside one day (mean for 3-hourly soil
    moisture, sum for half-hourly rain); `multiplier` converts units after.
    Days with no image come back as absent, never as zero.
    """
    import ee

    begin = ee.Date(start.isoformat())
    n = (end - start).days + 1

    def one_day(offset):
        day = begin.advance(offset, "day")
        images = collection.filterDate(day, day.advance(1, "day")).select(bands)
        combined = ee.Algorithms.If(
            images.size().gt(0),
            (images.sum() if reducer == "sum" else images.mean()).multiply(multiplier),
            ee.Image.constant([0] * len(bands)).rename(bands).updateMask(0),
        )
        values = ee.Image(combined).reduceRegion(ee.Reducer.mean(), geometry, scale, maxPixels=1e8)
        return ee.Feature(None, values).set("date", day.format("YYYY-MM-dd"))

    features = ee.FeatureCollection(ee.List.sequence(0, n - 1).map(one_day)).getInfo()["features"]
    out = {}
    for f in features:
        p = f["properties"]
        values = {b: p.get(b) for b in bands}
        if any(v is not None for v in values.values()):
            out[date.fromisoformat(p["date"])] = values
    return out


def fetch_context(geometry: dict, start: date, end: date) -> dict:
    import ee

    field = ee.Geometry(geometry)
    point = field.centroid(1)
    lon, lat = point.coordinates().getInfo()
    context: dict = {"latitude": lat, "longitude": lon, "sources": {}}

    def note(key, name, pixel, behind):
        context["sources"][key] = {"dataset": name, "pixel": pixel, "latency": behind}

    # --- rainfall ----------------------------------------------------------
    imerg = ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
    context["imerg"] = _daily(imerg, ["precipitation"], point, start, end, 11132, "sum", 0.5)
    note("imerg", "GPM IMERG V07 (half-hourly mm/h, summed x0.5 h; UTC days)", "11 km", "~1 day")
    chirps = ee.ImageCollection("UCSB-CHC/CHIRPS/V3/DAILY_SAT")
    context["chirps"] = _daily(chirps, ["precipitation"], point, start, end, 5566)
    note("chirps", "CHIRPS v3 daily", "5.5 km", "~3-4 weeks")

    # --- weather ----------------------------------------------------------
    era5 = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
    context["era5"] = _daily(era5, [
        "temperature_2m_max", "temperature_2m_min", "dewpoint_temperature_2m",
        "surface_solar_radiation_downwards_sum", "surface_pressure", "total_precipitation_sum",
        "volumetric_soil_water_layer_1", "volumetric_soil_water_layer_2", "volumetric_soil_water_layer_3",
    ], point, start, end, 11132)
    note("era5", "ERA5-Land daily aggregates", "11 km", "~5-8 days")
    # Wind speed from HOURLY components: the daily mean of u and v is the
    # speed of the average vector, which is smaller than the average speed
    # whenever the wind turns during the day — and would bias ET0 low.
    hourly = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY").map(
        lambda image: image.expression("sqrt(u*u + v*v)", {
            "u": image.select("u_component_of_wind_10m"),
            "v": image.select("v_component_of_wind_10m"),
        }).rename("wind").copyProperties(image, ["system:time_start"])
    )
    context["wind"] = _daily(hourly, ["wind"], point, start, end, 11132)

    # --- soil moisture, heat, haze -----------------------------------------
    smap = ee.ImageCollection("NASA/SMAP/SPL4SMGP/008")
    context["smap"] = _daily(smap, ["sm_surface", "sm_rootzone"], point, start, end, 11000)
    note("smap", "SMAP L4 v8 (0-5 cm and root zone)", "9 km", "~3 days")
    lst = ee.ImageCollection("MODIS/061/MOD11A1")
    context["lst"] = _daily(lst, ["LST_Day_1km", "LST_Night_1km"], field.buffer(500), start, end, 1000,
                            multiplier=0.02)
    note("lst", "MODIS Terra LST (MOD11A1)", "1 km", "~4 days")
    aod = ee.ImageCollection("MODIS/061/MCD19A2_GRANULES")
    context["aod"] = _daily(aod, ["Optical_Depth_055"], field.buffer(500), start, end, 1000, multiplier=0.001)
    note("aod", "MODIS MAIAC AOD 550 nm", "1 km", "~2 days")

    # --- surface water, per Sentinel-2 scene -------------------------------
    surroundings = field.buffer(WATER_BUFFER_M)
    dynamic_world = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(surroundings)
                     .filterDate(start.isoformat(), (end + timedelta(days=1)).isoformat()))

    def water_stats(image):
        image = ee.Image(image)
        on_field = image.select("water").reduceRegion(ee.Reducer.mean(), field, 10, maxPixels=1e8)
        around = image.select("label").eq(0).rename("is_water").reduceRegion(
            ee.Reducer.mean(), surroundings, 10, maxPixels=1e8)
        return ee.Feature(None, {
            "date": image.date().format("YYYY-MM-dd"),
            "water_probability_field": on_field.get("water"),
            "water_share_1km": around.get("is_water"),
        })

    water = {}
    for f in dynamic_world.map(water_stats).getInfo()["features"]:
        p = f["properties"]
        if p.get("water_share_1km") is None:
            continue
        day = date.fromisoformat(p["date"])
        water[day] = {"water_probability_field": p.get("water_probability_field"),
                      "water_share_1km": p["water_share_1km"]}
    context["water"] = water
    note("water", "Dynamic World V1 (per Sentinel-2 scene)", "10 m", "~7 days")

    # --- static setting -----------------------------------------------------
    elevation = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").select("DEM").mosaic().reduceRegion(
        ee.Reducer.mean(), field, 30).get("DEM")
    clay = ee.Image("OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02").select(["b0", "b30"]).reduceRegion(
        ee.Reducer.mean(), point.buffer(250), 250)
    sand = ee.Image("OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02").select(["b0", "b30"]).reduceRegion(
        ee.Reducer.mean(), point.buffer(250), 250)
    occurrence = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    ever_water = occurrence.gt(0).unmask(0).reduceRegion(ee.Reducer.mean(), surroundings, 30)
    statics = ee.Dictionary({
        "elevation_m": elevation,
        "clay_pct_0cm": clay.get("b0"), "clay_pct_30cm": clay.get("b30"),
        "sand_pct_0cm": sand.get("b0"), "sand_pct_30cm": sand.get("b30"),
        "share_of_1km_ever_water_1984_2021": ever_water.get("occurrence"),
    }).getInfo()
    context["static"] = statics
    return context


# ----------------------------------------------------------------------
# Joining it all into one row per day
# ----------------------------------------------------------------------


def daily_rows(context: dict, fused: dict, start: date, end: date) -> list[dict]:
    elevation = context["static"].get("elevation_m") or 0.0
    latitude = context["latitude"]
    rows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        era5 = context["era5"].get(day, {})
        row: dict = {"date": day.isoformat()}
        for name, series in fused.items():
            i = offset
            row[name] = None if series.ndvi[i] is None else round(series.ndvi[i], 4)
            if name == "ndvi":
                row["canopy_flag"] = series.flag[i]
                row["days_to_view"] = series.days_to_view[i]

        imerg = context["imerg"].get(day, {}).get("precipitation")
        chirps = context["chirps"].get(day, {}).get("precipitation")
        row["rain_imerg_mm"] = None if imerg is None else round(imerg, 2)
        row["rain_chirps_mm"] = None if chirps is None else round(chirps, 2)

        tmax_k, tmin_k = era5.get("temperature_2m_max"), era5.get("temperature_2m_min")
        tdew_k, solar = era5.get("dewpoint_temperature_2m"), era5.get("surface_solar_radiation_downwards_sum")
        pressure = era5.get("surface_pressure")
        wind10 = context["wind"].get(day, {}).get("wind")
        et0 = vpd = None
        if None not in (tmax_k, tmin_k, tdew_k, solar, pressure, wind10):
            tmax, tmin, tdew = tmax_k - 273.15, tmin_k - 273.15, tdew_k - 273.15
            ea = saturation_vapour_pressure(tdew)
            et0 = et0_fao56(tmax, tmin, ea, solar / 1e6, wind_10m_to_2m(wind10), pressure / 1000,
                            latitude, day.timetuple().tm_yday, elevation)
            vpd = vapour_pressure_deficit(tmax, tmin, ea)
            row.update({"tmax_c": round(tmax, 1), "tmin_c": round(tmin, 1), "dewpoint_c": round(tdew, 1),
                        "solar_mj_m2": round(solar / 1e6, 2), "wind_2m_ms": round(wind_10m_to_2m(wind10), 2)})
        row["et0_mm"] = None if et0 is None else round(et0, 2)
        row["vpd_kpa"] = None if vpd is None else round(vpd, 2)
        row["rain_minus_et0_mm"] = (None if et0 is None or imerg is None else round(imerg - et0, 2))
        for layer, label in ((1, "0_7cm"), (2, "7_28cm"), (3, "28_100cm")):
            value = era5.get(f"volumetric_soil_water_layer_{layer}")
            row[f"soil_water_era5_{label}"] = None if value is None else round(value, 3)

        smap = context["smap"].get(day, {})
        for key in ("sm_surface", "sm_rootzone"):
            row[f"smap_{key}"] = None if smap.get(key) is None else round(smap[key], 3)
        lst = context["lst"].get(day, {})
        for key, label in (("LST_Day_1km", "lst_day_c"), ("LST_Night_1km", "lst_night_c")):
            row[label] = None if lst.get(key) is None else round(lst[key] - 273.15, 1)
        aod = context["aod"].get(day, {}).get("Optical_Depth_055")
        row["aod_550"] = None if aod is None else round(aod, 3)
        water = context["water"].get(day, {})
        row["water_probability_field"] = water.get("water_probability_field")
        row["water_share_1km"] = water.get("water_share_1km")
        rows.append(row)

    balance = rolling_sum([r["rain_minus_et0_mm"] for r in rows], 30)
    for row, value in zip(rows, balance):
        row["rain_minus_et0_30d_mm"] = None if value is None else round(value, 1)
    return rows


def haze_check(rows: list[dict], outliers: list[date], view_days: list[date]) -> dict:
    """Were the passes the robust smoother rejected hazier than the ones it
    kept? If so, the rejection was the atmosphere, not a missed crop event."""
    aod = {r["date"]: r["aod_550"] for r in rows if r.get("aod_550") is not None}
    rejected = [aod[d.isoformat()] for d in outliers if d.isoformat() in aod]
    kept = [aod[d.isoformat()] for d in view_days if d.isoformat() in aod and d not in set(outliers)]
    return {
        "rejected_passes_with_aod": len(rejected),
        "median_aod_rejected": round(median(rejected), 3) if rejected else None,
        "median_aod_kept": round(median(kept), 3) if kept else None,
        "per_rejected_pass": {d.isoformat(): aod.get(d.isoformat()) for d in outliers},
    }


# ----------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------


def main() -> None:
    import timeseries

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--point", help="lat,lon of a field centre")
    where.add_argument("--field", help="a field_id from the label set")
    parser.add_argument("--radius", type=float, default=25.0)
    parser.add_argument("--labels", default="ml/labels.geojson")
    parser.add_argument("--start", default=(date.today() - timedelta(days=365)).isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--edge-buffer", type=float, default=5.0)
    parser.add_argument("--out-dir", type=Path, default=Path("ml/output"))
    parser.add_argument("--key", type=Path, default=Path("terrarisk-platform-bfc1102a3c63.json"))
    parser.add_argument("--project", default="terrarisk-platform")
    parser.add_argument("--any-season", action="store_true")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()

    name, geometry = timeseries.field_geometry(args)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    timeseries.initialise(args.key, args.project)

    print(f"{name}: canopy views ...", flush=True)
    observations = timeseries.fetch_observations(geometry, start, end, args.edge_buffer)
    season = timeseries.season_filter(args)
    ndvi = timeseries.build_daily(observations, start, end, harvest_season=season)
    fused = {
        "ndvi": ndvi,
        "nirv": timeseries.build_daily(observations, start, end, index="nirv", breaks=ndvi.breaks),
        "ndmi": timeseries.build_daily(observations, start, end, index="ndmi", breaks=ndvi.breaks),
    }
    print(f"{name}: rainfall, weather, soil, heat, haze, water ...", flush=True)
    context = fetch_context(geometry, start, end)
    rows = daily_rows(context, fused, start, end)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / f"{name}_context.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    view_days = sorted({o.day for o in observations if o.optical})
    summary = {
        "field": name,
        "window": [start.isoformat(), end.isoformat()],
        "location": [context["latitude"], context["longitude"]],
        "static": context["static"],
        "sources": context["sources"],
        "harvests": [[a.isoformat(), b.isoformat()] for a, b in ndvi.breaks],
        "haze_check": haze_check(rows, ndvi.outliers, view_days),
        "coverage_days": {key: sum(1 for r in rows if r.get(col) is not None) for key, col in (
            ("canopy_ndvi", "ndvi"), ("rain_imerg", "rain_imerg_mm"), ("rain_chirps", "rain_chirps_mm"),
            ("et0", "et0_mm"), ("smap", "smap_sm_surface"), ("lst_day", "lst_day_c"), ("aod", "aod_550"),
            ("surface_water_scenes", "water_share_1km"))},
        "totals": {
            "rain_imerg_mm": round(sum(r["rain_imerg_mm"] for r in rows if r["rain_imerg_mm"] is not None)),
            "rain_chirps_mm": round(sum(r["rain_chirps_mm"] for r in rows if r["rain_chirps_mm"] is not None)),
            "et0_mm": round(sum(r["et0_mm"] for r in rows if r["et0_mm"] is not None)),
        },
        "not_available": {
            "groundwater": "No farm-scale satellite measurement exists; needs CGWB/GSDA well data, "
                           "and the platform's CGWB table is empty.",
            "crop_water_use": "ET0 is reference demand, not cane water use; no crop-coefficient model yet.",
        },
    }
    json_path = args.out_dir / f"{name}_context.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{name}  {start} to {end}")
    for key, value in summary["coverage_days"].items():
        print(f"  {key:22} {value:4d} of {len(rows)} days")
    print(f"  rainfall: IMERG {summary['totals']['rain_imerg_mm']} mm, CHIRPS {summary['totals']['rain_chirps_mm']} mm "
          f"(CHIRPS ends earlier); reference ET0 {summary['totals']['et0_mm']} mm")
    print(f"  setting: {json.dumps(summary['static'])}")
    hc = summary["haze_check"]
    print(f"  haze check: median AOD on rejected passes {hc['median_aod_rejected']} vs kept {hc['median_aod_kept']} "
          f"({hc['rejected_passes_with_aod']} rejected passes with an AOD reading)")
    print(f"  wrote {csv_path} and {json_path}")

    if args.plot:
        from farm_context_plot import plot_context

        print(f"  plot: {plot_context(name, rows, ndvi, args.out_dir)}")


if __name__ == "__main__":
    main()
