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

import logging
import threading
from datetime import date, datetime, timezone

import ee

from app.core.config import get_settings
from app.services.satellite._gee_common import CLOUD_PROBABILITY_COLLECTION as _CLOUD_PROBABILITY_COLLECTION
from app.services.satellite._gee_common import CLOUD_PROBABILITY_THRESHOLD as _CLOUD_PROBABILITY_THRESHOLD
from app.services.satellite._gee_common import SENTINEL2_COLLECTION as _SENTINEL2_COLLECTION
from app.services.satellite._gee_common import monthly_periods as _monthly_periods
from app.services.risk.models import MonthlyValue
from app.services.satellite.ee_retry import fetch_mapped_features, with_ee_retry
from app.services.satellite.provider import (
    IndexObservation,
    SatelliteDataProvider,
    SatelliteIndex,
    WaterHistorySummary,
)

logger = logging.getLogger(__name__)

_CHIRPS_COLLECTION = "UCSB-CHG/CHIRPS/DAILY"
_JRC_SURFACE_WATER = "JRC/GSW1_4/GlobalSurfaceWater"

# CHIRPS's own ~0.05 degree (~5.5 km) native grid. Named rather than
# repeated inline so the daily and monthly rainfall paths cannot drift
# apart — they must sample the same product at the same scale for the
# daily runoff term and the monthly P term to describe one rainfall
# field. NOTE for report/UX honesty: one CHIRPS pixel is ~3,000 ha, so
# any catchment materially smaller than that is sub-pixel and its
# "rainfall" is really a regional value — that is what the
# `rainfall_sub_pixel` resolution flag exists to disclose.
_CHIRPS_SCALE_METERS = 5000
_CHIRPS_MAX_PIXELS = 1e9

# Sentinel-2 native 10 m for the optical indices. Note B11 (SWIR1, used by
# MNDWI and NDMI) is natively 20 m, so those indices carry 20 m effective
# resolution despite being reduced at 10 m.
_INDEX_SCALE_METERS = 10

# JRC Global Surface Water native 30 m (Landsat).
_JRC_SCALE_METERS = 30

# Named so provenance records (app/services/provenance/lineage.py) can
# import the values this module actually uses rather than restating them.

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

# `_monthly_periods`, `_CLOUD_PROBABILITY_THRESHOLD`,
# `_CLOUD_PROBABILITY_COLLECTION`, and `_SENTINEL2_COLLECTION` are
# re-exported under their original module-private names above (tickets
# M1-002, M1-005) so every existing
# `from app.services.satellite.gee_provider import _monthly_periods`-style
# import keeps working unmodified. The canonical definitions now live in
# `_gee_common.py`, shared with `GEEHydrologyProvider`'s MNDWI branch —
# new code should import from `_gee_common` directly rather than through
# here.


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

        period_payload = [{"start": p_start.isoformat(), "end": p_end.isoformat()} for p_start, p_end in periods]

        def _compute_period(period) -> ee.Feature:
            period = ee.Dictionary(period)
            period_start = ee.Date(period.get("start"))
            period_end = ee.Date(period.get("end"))
            month_images = joined.filterDate(period_start, period_end)
            composite = month_images.map(_mask_clouds_and_compute_index).mean()
            stats = composite.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region, scale=_INDEX_SCALE_METERS, maxPixels=1e9
            )
            # The real Sentinel-2 acquisition dates that fed this month's
            # composite (M2B P9 — Blueprint §08 data lineage): each image's
            # own system:time_start, formatted server-side so a single
            # getInfo() below still returns everything in one round trip.
            def _format_scene_date(millis):
                return ee.Date(millis).format("YYYY-MM-dd")

            scene_dates = month_images.aggregate_array("system:time_start").map(_format_scene_date)
            return ee.Feature(
                None,
                {
                    "period_start": period_start.format("YYYY-MM-dd"),
                    # Guarded lookup: a month with NO scenes at all produces
                    # a band-less composite, so reduceRegion returns an
                    # EMPTY dictionary and a bare .get() throws server-side
                    # ("Dictionary does not contain key"). Note .get(key,
                    # default) can't express this — the Python client prunes
                    # a None default from the call, and any other default
                    # would fabricate a reading. The If(contains) guard
                    # yields null, which flows into the existing
                    # skip-this-month path (_parse_monthly_features). Found
                    # live in M2A P4 — see get_rainfall_series.
                    "value": ee.Algorithms.If(
                        stats.contains("index_value"), stats.get("index_value"), None
                    ),
                    "scene_count": month_images.size(),
                    "scene_dates": scene_dates,
                },
            )

        features = fetch_mapped_features(
            period_payload,
            lambda batch: ee.FeatureCollection(ee.List(batch).map(_compute_period)),
            description="get_index_time_series",
        )
        return self._parse_monthly_features(features, periods)

    def get_daily_rainfall_series(self, geometry_geojson: dict, start: date, end: date) -> list[MonthlyValue]:
        region = ee.Geometry(geometry_geojson)
        chirps = ee.ImageCollection(_CHIRPS_COLLECTION).filterBounds(region).filterDate(
            start.isoformat(), end.isoformat()
        )

        # One server-side reduction per day, returned in a single round
        # trip. Mapping reduceRegion over ~1,100 daily images (a 3-year
        # window) the way get_rainfall_series() does per-month would issue
        # the same number of reductions but is expressed here as a single
        # FeatureCollection getInfo() so it stays one request, not one per
        # day.
        def _daily_value(image: ee.Image) -> ee.Feature:
            image = ee.Image(image)
            stats = image.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=_CHIRPS_SCALE_METERS,
                maxPixels=_CHIRPS_MAX_PIXELS,
            )
            # Same guarded lookup get_rainfall_series() documents at
            # length: a band-less/unpublished image yields an empty
            # dictionary and a bare .get() throws server-side.
            return ee.Feature(
                None,
                {
                    # The image's own acquisition date, formatted
                    # server-side so the whole series still returns in one
                    # getInfo(). Needed to attribute each storm's runoff to
                    # a water year.
                    "day": image.date().format("YYYY-MM-dd"),
                    "value": ee.Algorithms.If(stats.contains("precipitation"), stats.get("precipitation"), None),
                },
            )

        features = with_ee_retry(
            lambda: ee.FeatureCollection(chirps.map(_daily_value)).getInfo(),
            description="get_daily_rainfall_series",
        )["features"]

        # Days the product never published are dropped, not zero-filled —
        # a zero would be a fabricated dry day, which for a runoff sum is
        # not a harmless default (it silently lowers total runoff).
        # Negative values are CHIRPS's own no-data convention.
        depths = [
            MonthlyValue(period_start=date.fromisoformat(props["day"]), value=value)
            for feature in features
            if (props := feature["properties"]) is not None
            and (value := props.get("value")) is not None
            and value >= 0
        ]
        if not depths:
            logger.warning(
                "daily_rainfall_series_empty",
                extra={"period_start": start.isoformat(), "period_end": end.isoformat()},
            )
        return depths

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
            stats = month_total.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region, scale=_CHIRPS_SCALE_METERS, maxPixels=1e9
            )
            # Guarded lookup — REAL bug found during M2A P4's live E2E:
            # CHIRPS publishes with a multi-week lag, so the lookback
            # window's most recent month can have zero published images.
            # An empty collection's sum() is a band-less image, reduceRegion
            # then returns an EMPTY dictionary, and a bare .get() throws
            # server-side, failing the whole report job. .get(key, default)
            # can't express "default to null" (the Python client prunes a
            # None default from the call, and any non-null default would
            # fabricate a rainfall reading). The If(contains) guard yields
            # null, so the unpublished month is skipped by
            # _parse_monthly_features exactly like a fully cloud-masked
            # month — the already-designed sparse-data path (the confidence
            # score accounts for missing months by construction).
            return ee.Feature(
                None,
                {
                    "period_start": period_start.format("YYYY-MM-dd"),
                    "value": ee.Algorithms.If(
                        stats.contains("precipitation"), stats.get("precipitation"), None
                    ),
                },
            )

        features = with_ee_retry(
            lambda: ee.FeatureCollection(period_dicts.map(_compute_period)).getInfo(),
            description="get_rainfall_series",
        )["features"]
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
                    reducer=ee.Reducer.mean(), geometry=region, scale=_CHIRPS_SCALE_METERS, maxPixels=1e9
                )
                # Same empty-month guard as get_rainfall_series; the
                # climatology's mean reducer simply averages over the
                # years that do have data.
                return ee.Algorithms.If(stats.contains("precipitation"), stats.get("precipitation"), None)

            yearly_totals = years.map(_year_total)
            normal = ee.List(yearly_totals).reduce(ee.Reducer.mean())
            return ee.Feature(None, {"month": month, "normal": normal})

        features = with_ee_retry(
            lambda: ee.FeatureCollection(months.map(_month_normal)).getInfo(),
            description="get_rainfall_climatology",
        )["features"]
        climatology: dict[int, float] = {}
        for feature in features:
            props = feature["properties"]
            normal = props.get("normal")
            if normal is not None:
                climatology[int(props["month"])] = float(normal)
        return climatology

    def get_water_history(self, geometry_geojson: dict) -> WaterHistorySummary:
        """Mean JRC water occurrence over the WHOLE polygon, 0-100.

        CORRECTED 6 Sep 2026 — the previous read was biased high twice
        over, and this number feeds flood-exposure risk directly.

        The JRC occurrence band has two properties a plain
        `reduceRegion(ee.Reducer.mean())` gets wrong, both documented in
        Google's own catalog entry for this collection:

        1. Pixels where water was NEVER detected are MASKED, not zero. A
           plain mean therefore averages only over pixels that have been
           water at some point and ignores all the dry land in the
           polygon. `.unmask(0)` restores dry pixels as the zero they are.
        2. The band is its own mask weight ("the mask value for the
           occurrence band is equal to the band value"), and Earth Engine
           reducers are mask-weighted — so `mean()` computed
           sum(x^2)/sum(x) rather than the mean. `.unweighted()` removes
           that.

        Measured on live polygons before the fix (old -> corrected):
        Manjara reservoir edge 7.58 -> 0.04; a Maski-area square
        23.29 -> 0.00; Ujani reservoir edge 82.57 -> 35.19. The last sat
        just under the 85 floor-rule threshold that forces an assessment
        to HIGH. The bias is worst exactly where it matters most — a
        farm containing a little water — and vanishes only for a polygon
        with no water at all, where the old null fell back to 0.0 and
        happened to be right.
        """
        region = ee.Geometry(geometry_geojson)
        occurrence = ee.Image(_JRC_SURFACE_WATER).select("occurrence").unmask(0)
        stats = occurrence.reduceRegion(
            reducer=ee.Reducer.mean().unweighted(), geometry=region, scale=_JRC_SCALE_METERS, maxPixels=1e9
        )
        value = with_ee_retry(
            lambda: stats.get("occurrence").getInfo(),
            description="get_water_history",
        )

        # JRC GSW v1.4's own record: 16 Mar 1984 to 31 Dec 2021. The end
        # was previously reported as 1 Jan 2021, a year short.
        return WaterHistorySummary(
            occurrence_percent=float(value) if value is not None else 0.0,
            period_start=date(1984, 3, 16),
            period_end=date(2021, 12, 31),
        )

    @staticmethod
    def _parse_monthly_features(features: list[dict], periods: list[tuple[date, date]]) -> list[IndexObservation]:
        """Converts Earth Engine's raw feature list into IndexObservation
        rows, one per requested period. A month whose reduceRegion returned
        null (no unmasked pixels — e.g. persistent monsoon cloud cover) is
        skipped entirely rather than coerced into a misleading zero.

        `scene_dates` is only present on features from get_index_time_series
        (real Sentinel-2 acquisition dates — M2B P9); get_rainfall_series's
        features never carry it, since CHIRPS is a daily gridded product
        with no discrete "scene" concept, so it defaults honestly to empty
        rather than fabricating a value."""
        observations: list[IndexObservation] = []
        for feature, (period_start, period_end) in zip(features, periods, strict=True):
            properties = feature["properties"]
            value = properties.get("value")
            if value is None:
                continue
            scene_dates = [date.fromisoformat(d) for d in properties.get("scene_dates") or []]
            observations.append(
                IndexObservation(
                    period_start=period_start,
                    period_end=period_end,
                    value=float(value),
                    source_scene_dates=scene_dates,
                )
            )
        return observations
