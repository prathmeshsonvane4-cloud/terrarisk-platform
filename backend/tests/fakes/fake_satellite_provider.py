"""Deterministic in-memory SatelliteDataProvider for tests.

Proves the report generator only ever depends on the SatelliteDataProvider
interface, never on GeeProvider specifically (Blueprint §06 architectural
contract) — the same orchestrator code runs against this fake in tests and
against real Earth Engine in production, unmodified.
"""

from __future__ import annotations

from datetime import date

from app.services.satellite.gee_provider import _monthly_periods
from app.services.satellite.provider import (
    IndexObservation,
    SatelliteDataProvider,
    SatelliteIndex,
    WaterHistorySummary,
)


class FakeSatelliteDataProvider(SatelliteDataProvider):
    """Returns fixed, adjustable values so tests can construct specific
    scenarios (e.g. a drought scenario) without touching the network."""

    def __init__(
        self,
        *,
        index_values: dict[SatelliteIndex, float] = None,
        rainfall_value: float = 80.0,
        rainfall_climatology: dict[int, float] = None,
        jrc_occurrence_percent: float = 10.0,
        missing_months: set[int] = None,
    ) -> None:
        self._index_values = index_values or {
            SatelliteIndex.NDVI: 0.6,
            SatelliteIndex.MNDWI: 0.1,
            SatelliteIndex.NDMI: 0.2,
        }
        self._rainfall_value = rainfall_value
        self._rainfall_climatology = rainfall_climatology or {m: 80.0 for m in range(1, 13)}
        self._jrc_occurrence_percent = jrc_occurrence_percent
        # Zero-based period indices (within the requested range) to
        # simulate cloud-blanked / missing months.
        self._missing_months = missing_months or set()

    def get_index_time_series(
        self, geometry_geojson: dict, index: SatelliteIndex, start: date, end: date
    ) -> list[IndexObservation]:
        periods = _monthly_periods(start, end)
        value = self._index_values.get(index, 0.5)
        return [
            IndexObservation(period_start=p_start, period_end=p_end, value=value)
            for i, (p_start, p_end) in enumerate(periods)
            if i not in self._missing_months
        ]

    def get_rainfall_series(self, geometry_geojson: dict, start: date, end: date) -> list[IndexObservation]:
        periods = _monthly_periods(start, end)
        return [
            IndexObservation(period_start=p_start, period_end=p_end, value=self._rainfall_value)
            for i, (p_start, p_end) in enumerate(periods)
            if i not in self._missing_months
        ]

    def get_rainfall_climatology(self, geometry_geojson: dict) -> dict[int, float]:
        return dict(self._rainfall_climatology)

    def get_water_history(self, geometry_geojson: dict) -> WaterHistorySummary:
        return WaterHistorySummary(
            occurrence_percent=self._jrc_occurrence_percent,
            period_start=date(1984, 3, 1),
            period_end=date(2021, 1, 1),
        )
