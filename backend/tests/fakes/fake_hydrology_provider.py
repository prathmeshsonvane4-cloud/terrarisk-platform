"""Deterministic in-memory HydrologyDataProvider for tests — the
`HydrologyDataProvider` sibling of `fake_satellite_provider.py`'s
`FakeSatelliteDataProvider`, same shape and same reasoning: proves
`water_report_generator.py` only ever depends on the abstract provider
interface, never on `GEEHydrologyProvider` specifically.
"""

from __future__ import annotations

from datetime import date

from app.services.hydrology.provider import HydrologyDataProvider, SurfaceWaterMethod
from app.services.risk.models import MonthlyValue
from app.services.satellite._gee_common import monthly_periods


class FakeHydrologyDataProvider(HydrologyDataProvider):
    """Returns fixed, adjustable values so tests can construct specific
    scenarios (e.g. an all-missing-data scenario) without touching the
    network or real Earth Engine credentials."""

    def __init__(
        self,
        *,
        et_value: float | None = 60.0,
        surface_water_percent: float | None = 5.0,
        missing_months: set[int] | None = None,
    ) -> None:
        self._et_value = et_value
        self._surface_water_percent = surface_water_percent
        # Zero-based period indices (within the requested range) to
        # simulate a month with no usable retrieval — HydrologyDataProvider's
        # own contract returns MonthlyValue(value=None) for these, never an
        # omitted entry (unlike SatelliteDataProvider's IndexObservation).
        self._missing_months = missing_months or set()

    def get_et_series(self, geometry_geojson: dict, start: date, end: date) -> list[MonthlyValue]:
        periods = monthly_periods(start, end)
        return [
            MonthlyValue(period_start=p_start, value=None if i in self._missing_months else self._et_value)
            for i, (p_start, _p_end) in enumerate(periods)
        ]

    def get_surface_water_extent_series(
        self,
        geometry_geojson: dict,
        start: date,
        end: date,
        method: SurfaceWaterMethod,
    ) -> list[MonthlyValue]:
        periods = monthly_periods(start, end)
        return [
            MonthlyValue(
                period_start=p_start, value=None if i in self._missing_months else self._surface_water_percent
            )
            for i, (p_start, _p_end) in enumerate(periods)
        ]
