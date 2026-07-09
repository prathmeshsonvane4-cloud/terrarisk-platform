"""Google Earth Engine implementation of SatelliteDataProvider.

M0 scope (Blueprint §06/§10): prove service-account authentication and the
interface shape with a real, working — but intentionally simple — single
period computation per index. Full Sentinel-2 QA-band cloud masking and
multi-period monthly compositing (needed to bridge monsoon cloud gaps) is
M1 work; this is noted inline at each method rather than silently expanded,
since scope discipline between milestones matters more than getting ahead.

No `ee.*` object is returned from any public method — everything crosses
back into plain dataclasses defined in provider.py, per the architectural
contract.
"""

from datetime import date

import ee

from app.core.config import get_settings
from app.services.satellite.provider import (
    IndexObservation,
    SatelliteDataProvider,
    SatelliteIndex,
    WaterHistorySummary,
)

_SENTINEL2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
_CHIRPS_COLLECTION = "UCSB-CHG/CHIRPS/DAILY"
_JRC_SURFACE_WATER = "JRC/GSW1_4/GlobalSurfaceWater"

# Band math per the approved methodology (docs/DECISIONS.md — Water
# Availability factor): MNDWI is the primary water-body indicator, NDMI the
# supporting crop-moisture indicator. NDVI drives vegetation stability.
_INDEX_BANDS: dict[SatelliteIndex, tuple[str, str]] = {
    SatelliteIndex.NDVI: ("B8", "B4"),  # (NIR - RED) / (NIR + RED)
    SatelliteIndex.MNDWI: ("B3", "B11"),  # (GREEN - SWIR1) / (GREEN + SWIR1)
    SatelliteIndex.NDMI: ("B8", "B11"),  # (NIR - SWIR1) / (NIR + SWIR1)
}


class GeeProvider(SatelliteDataProvider):
    _initialized = False

    def __init__(self) -> None:
        self._ensure_initialized()

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._initialized:
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

        # M0: mean composite across the whole range, no cloud-probability
        # masking yet. M1 replaces this with per-period QA-band-masked
        # composites (Blueprint §06 "Cloud masking" / "Time-series generation").
        collection = (
            ee.ImageCollection(_SENTINEL2_COLLECTION)
            .filterBounds(region)
            .filterDate(str(start), str(end))
        )

        def _compute(image: ee.Image) -> ee.Image:
            return image.normalizedDifference([numerator_band, denominator_band]).rename("index_value")

        composite = collection.map(_compute).mean()
        stats = composite.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, scale=10, maxPixels=1e9)
        value = stats.get("index_value").getInfo()

        return [
            IndexObservation(
                period_start=start,
                period_end=end,
                value=float(value) if value is not None else float("nan"),
                source_scene_dates=[],
            )
        ]

    def get_rainfall_series(self, geometry_geojson: dict, start: date, end: date) -> list[IndexObservation]:
        region = ee.Geometry(geometry_geojson)
        collection = ee.ImageCollection(_CHIRPS_COLLECTION).filterBounds(region).filterDate(str(start), str(end))
        total = collection.sum()
        stats = total.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, scale=5000, maxPixels=1e9)
        value = stats.get("precipitation").getInfo()

        return [
            IndexObservation(
                period_start=start,
                period_end=end,
                value=float(value) if value is not None else float("nan"),
                source_scene_dates=[],
            )
        ]

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
