"""Domain-facing contract for all satellite/climate data access.

Blueprint §06 architectural contract: business logic and the future risk
engine only ever call SatelliteDataProvider methods, described in domain
vocabulary (index, geometry, date range) — never in the vocabulary of any
specific provider (Earth Engine, Sentinel Hub, Copernicus, self-hosted).
No provider-native object (an ee.Image, an ee.FeatureCollection) is allowed
to cross this boundary; every method here returns plain typed data that
maps directly onto backend.app.models.satellite.SatelliteObservation.

This is what makes "swap the provider later without touching the risk
engine, the API, or the database" a true statement rather than aspiration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class SatelliteIndex(str, Enum):
    NDVI = "ndvi"
    MNDWI = "mndwi"
    NDMI = "ndmi"


@dataclass(frozen=True)
class IndexObservation:
    """One computed value for one period — maps 1:1 onto a
    SatelliteObservation row."""

    period_start: date
    period_end: date
    value: float
    source_scene_dates: list[date] = field(default_factory=list)


@dataclass(frozen=True)
class WaterHistorySummary:
    """Historical surface-water occurrence for a polygon (JRC Global Surface
    Water-style), used as the flood-exposure baseline per the approved risk
    methodology — see docs/DECISIONS.md."""

    occurrence_percent: float
    period_start: date
    period_end: date


class SatelliteDataProvider(ABC):
    @abstractmethod
    def get_index_time_series(
        self, geometry_geojson: dict, index: SatelliteIndex, start: date, end: date
    ) -> list[IndexObservation]:
        """NDVI / MNDWI / NDMI observations for a polygon over a date range.

        M0 proves the connection and this interface shape with a single
        period computation; monthly compositing and full Sentinel-2 QA-band
        cloud masking across many periods is M1 scope (Blueprint §10).
        """

    @abstractmethod
    def get_rainfall_series(self, geometry_geojson: dict, start: date, end: date) -> list[IndexObservation]:
        """Rainfall totals for a polygon over a date range, for the
        SPI-style anomaly used in drought scoring (Blueprint §07)."""

    @abstractmethod
    def get_water_history(self, geometry_geojson: dict) -> WaterHistorySummary:
        """Historical surface-water occurrence for a polygon — the flood
        exposure baseline for MVP (Blueprint §07)."""

    def get_sar_backscatter_series(
        self, geometry_geojson: dict, start: date, end: date
    ) -> list[IndexObservation]:
        """Reserved for post-MVP Sentinel-1 SAR flood-event detection.

        Deliberately unimplemented for M0/M1: the approved risk methodology
        (docs/DECISIONS.md) uses JRC Global Surface Water history + rainfall
        anomaly for flood exposure in the MVP. This method exists on the
        interface now so SAR can be added later as a new provider capability
        without changing SatelliteDataProvider's contract or any caller —
        an intentional, documented seam, not an unfinished feature.
        """
        raise NotImplementedError(
            "SAR backscatter series is deferred post-MVP per the approved risk methodology "
            "(docs/DECISIONS.md — Flood Exposure factor)"
        )
