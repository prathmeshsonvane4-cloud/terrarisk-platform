"""Google Earth Engine implementation of SatelliteDataProvider.

M1 scope (Blueprint §06/§10, approved methodology in docs/DECISIONS.md):
real monthly composites across a 3-year lookback, s2cloudless-based cloud
masking at the approved 20% probability threshold, and a CHIRPS-derived
rainfall climatology for the seasonal anomaly baseline. All heavy lifting
(joining collections, masking, per-month reduction) runs server-side in
Earth Engine and is retrieved in one `getInfo()` call per time series —
issuing 36 separate round-trips per farm would be wasteful of both latency
and Earth Engine's request quota.

No `ee.*` object is returned from any public method — everything crosses
back into plain dataclasses defined in provider.py, per the architectural
contract.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone

import ee

from app.core.config import get_settings
from app.services.satellite.provider import (
    IndexObservation,
    SatelliteDataProvider,
    SatelliteIndex,
    WaterHistorySummary,
)

_SENTINEL2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
_CLOUD_PROBABILITY_COLLECTION = "COPERNICUS/S2_CLOUD_PROBABILITY"
_CHIRPS_COLLECTION = "UCSB-CHG/CHIRPS/DAILY"
_JRC_SURFACE_WATER = "JRC/GSW1_4/GlobalSurfaceWater"

# Approved methodology (docs/DECISIONS.md) — frozen for M1, not a tunable
# left to guesswork: a scene pixel is masked out at or above this cloud
# probability.
_CLOUD_PROBABILITY_THRESHOLD = 20

# 30-year climate-normal window (WMO-standard normal period length),
# computed relative to the last fully-completed calendar year rather than
# hardcoded, so it doesn't silently go stale.
_CLIMATOLOGY_WINDOW_YEARS = 30

# Band math per the approved methodology (docs/DECISIONS.md — Water
# Availability factor): MNDWI is the primary water-body indicator, NDMI the
# supporting crop-moisture indicator. NDVI drives vegetation stability.
_INDEX_BANDS: dict[SatelliteIndex, tuple[str, str]] = {
    SatelliteIndex.NDVI: ("B8", "B4"),  # (NIR - RED) / (NIR + RED)
    SatelliteIndex.MNDWI: ("B3", "B11"),  # (GREEN - SWIR1) / (GREEN + SWIR1)
    SatelliteIndex.NDMI: ("B8", "B11"),  # (NIR - SWIR1) / (NIR + SWIR1)
}


def _monthly_periods(start: date, end: date) -> list[tuple[date, date]]:
    """(period_start, period_end) pairs for each calendar month touching
    [start, end), used as the compositing window for both the optical
    index series and the rainfall series (Blueprint §06 "Time-series
    generation": all indices composited on the same period boundaries)."""
    periods: list[tuple[date, date]] = []
    current = date(start.year, start.month, 1)
    while current < end:
        next_month = date(current.year + 1, 1, 1) if current.month == 12 else date(current.year, current.month + 1, 1)
        periods.append((current, next_month))
        current = next_month
    return periods


class GeeProvider(SatelliteDataProvider):
    _initialized = False
    # asyncio.to_thread() dispatches to a real OS thread pool, and every
    # report-generation background task constructs its own GeeProvider() —
    # two farms' reports generated around the same time can genuinely reach
    # this check-then-initialize sequence from different threads
    # concurrently. A plain `if cls._initialized: ... cls._initialized =
    # True` without a lock is a real race (not asyncio.Lock — this runs on
    # worker threads, not the event loop).
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        self._ensure_initialized()

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._initialized:
            return
        with cls._init_lock:
            if cls._initialized:  # re-check: another thread may have won the race while we waited for the lock
                return
            settings = get_settings()
            if not settings.gee_project_id or not settings.gee_service_account_json_path:
                raise RuntimeError(
                    "GEE_PROJECT_ID and GEE_SERVICE_ACCOUNT_JSON_PATH must be set to use GeeProvider — "
                    "see docs/DECISIONS.md for the setup walkthrough."
                )
            credentials = ee.ServiceAccountCredentials(
                email=None, key_file=settings.gee_service_account_json_path
            )
            ee.Initialize(credentials, project=settings.gee_project_id)
            cls._initialized = True

    def get_index_time_series(
        self, geometry_geojson: dict, index: SatelliteIndex, start: date, end: date
    ) -> list[IndexObservation]:
        region = ee.Geometry(geometry_geojson)
        numerator_band, denominator_band = _INDEX_BANDS[index]
        periods = _monthly_periods(start, end)

        sentinel2 = ee.ImageCollection(_SENTINEL2_COLLECTION).filterBounds(region)
        cloud_probability = ee.ImageCollection(_CLOUD_PROBABILITY_COLLECTION).filterBounds(region)
        joined = ee.ImageCollection(
            ee.Join.saveFirst("cloud_probability").apply(
                primary=sentinel2,
                secondary=cloud_probability,
                condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
            )
        )

        def _mask_clouds_and_compute_index(image: ee.Image) -> ee.Image:
            image = ee.Image(image)
            probability = ee.Image(image.get("cloud_probability")).select("probability")
            clear_mask = probability.lt(_CLOUD_PROBABILITY_THRESHOLD)
            return (
                image.updateMask(clear_mask)
                .normalizedDifference([numerator_band, denominator_band])
                .rename("index_value")
            )

        period_dicts = ee.List(
            [{"start": p_start.isoformat(), "end": p_end.isoformat()} for p_start, p_end in periods]
        )

        def _compute_period(period) -> ee.Feature:
            period = ee.Dictionary(period)
            period_start = ee.Date(period.get("start"))
            period_end = ee.Date(period.get("end"))
            month_images = joined.filterDate(period_start, period_end)
            composite = month_images.map(_mask_clouds_and_compute_index).mean()
            stats = composite.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9)
            return ee.Feature(
                None,
                {
                    "period_start": period_start.format("YYYY-MM-dd"),
                    "value": stats.get("index_value"),
                    "scene_count": month_images.size(),
                },
            )

        features = ee.FeatureCollection(period_dicts.map(_compute_period)).getInfo()["features"]
        return self._parse_monthly_features(features, periods)

    def get_rainfall_series(self, geometry_geojson: dict, start: date, end: date) -> list[IndexObservation]:
        region = ee.Geometry(geometry_geojson)
        periods = _monthly_periods(start, end)
        chirps = ee.ImageCollection(_CHIRPS_COLLECTION).filterBounds(region)

        period_dicts = ee.List(
            [{"start": p_start.isoformat(), "end": p_end.isoformat()} for p_start, p_end in periods]
        )

        def _compute_period(period) -> ee.Feature:
            period = ee.Dictionary(period)
            period_start = ee.Date(period.get("start"))
            period_end = ee.Date(period.get("end"))
            month_total = chirps.filterDate(period_start, period_end).sum()
            stats = month_total.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, scale=5000, maxPixels=1e9)
            return ee.Feature(None, {"period_start": period_start.format("YYYY-MM-dd"), "value": stats.get("precipitation")})

        features = ee.FeatureCollection(period_dicts.map(_compute_period)).getInfo()["features"]
        return self._parse_monthly_features(features, periods)

    def get_rainfall_climatology(self, geometry_geojson: dict) -> dict[int, float]:
        region = ee.Geometry(geometry_geojson)
        chirps = ee.ImageCollection(_CHIRPS_COLLECTION).filterBounds(region)

        end_year = datetime.now(timezone.utc).year - 1
        start_year = end_year - _CLIMATOLOGY_WINDOW_YEARS + 1
        years = ee.List.sequence(start_year, end_year)
        months = ee.List.sequence(1, 12)

        def _month_normal(month) -> ee.Feature:
            month = ee.Number(month)

            def _year_total(year):
                year = ee.Number(year)
                period_start = ee.Date.fromYMD(year, month, 1)
                period_end = period_start.advance(1, "month")
                year_month_total = chirps.filterDate(period_start, period_end).sum()
                stats = year_month_total.reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=region, scale=5000, maxPixels=1e9
                )
                return stats.get("precipitation")

            yearly_totals = years.map(_year_total)
            normal = ee.List(yearly_totals).reduce(ee.Reducer.mean())
            return ee.Feature(None, {"month": month, "normal": normal})

        features = ee.FeatureCollection(months.map(_month_normal)).getInfo()["features"]
        climatology: dict[int, float] = {}
        for feature in features:
            props = feature["properties"]
            normal = props.get("normal")
            if normal is not None:
                climatology[int(props["month"])] = float(normal)
        return climatology

    def get_water_history(self, geometry_geojson: dict) -> WaterHistorySummary:
        region = ee.Geometry(geometry_geojson)
        occurrence = ee.Image(_JRC_SURFACE_WATER).select("occurrence")
        stats = occurrence.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, scale=30, maxPixels=1e9)
        value = stats.get("occurrence").getInfo()

        # JRC dataset's own fixed reference period.
        return WaterHistorySummary(
            occurrence_percent=float(value) if value is not None else 0.0,
            period_start=date(1984, 3, 1),
            period_end=date(2021, 1, 1),
        )

    @staticmethod
    def _parse_monthly_features(features: list[dict], periods: list[tuple[date, date]]) -> list[IndexObservation]:
        """Converts Earth Engine's raw feature list into IndexObservation
        rows, one per requested period. A month whose reduceRegion returned
        null (no unmasked pixels — e.g. persistent monsoon cloud cover) is
        skipped entirely rather than coerced into a misleading zero."""
        observations: list[IndexObservation] = []
        for feature, (period_start, period_end) in zip(features, periods, strict=True):
            value = feature["properties"].get("value")
            if value is None:
                continue
            observations.append(
                IndexObservation(period_start=period_start, period_end=period_end, value=float(value))
            )
        return observations
