"""Domain-facing contract for hydrology-specific data access (ET series,
watershed-scale surface-water extent).

Blueprint v2 D1: a *second*, purpose-built abstract provider interface,
separate from `app.services.satellite.provider.SatelliteDataProvider`.
Water Intelligence's rainfall needs are already served unchanged by
`SatelliteDataProvider.get_rainfall_series()` /
`get_rainfall_climatology()` (Part 9's cost estimate treats rainfall as
reused, not refetched) — this interface exists only for the genuinely new
hydrology concepts ET and surface-water extent. Bolting these onto
`SatelliteDataProvider` would force every farm-risk caller to depend on
methods it never calls, the same interface-segregation reasoning that
already shaped that file.

Same architectural contract as `SatelliteDataProvider`: a future
orchestrator (M5) only ever calls `HydrologyDataProvider` methods in
domain vocabulary (geometry, date range, method) — never in the
vocabulary of any specific data source. No provider-native object (an
`ee.Image`, an HTTP response, a raster dataset handle) is allowed to cross
this boundary; every method returns plain, frozen, JSON-serializable data.
This is what makes it possible to later implement this interface against
Google Earth Engine, CGWB, IMD rainfall, WRIS, a local raster source, or a
deterministic test fake — without changing `WaterBalanceEngine`, the API,
or the database, exactly as `SatelliteDataProvider` already does for farm
risk scoring.

D1 also names what a real implementation shares, not duplicates: a future
`GEEHydrologyProvider` reuses `gee_provider.py`'s internal helpers
(`_monthly_periods()`, the cloud-masking constant, the
`asyncio.to_thread()` wrapping convention) rather than forking them — that
reuse happens at the *implementation* layer (a later ticket), not here;
this module has zero dependency on `gee_provider.py` or on Earth Engine.

Reuses `MonthlyValue` from `app.services.risk.models` rather than
inventing a rival "one frozen dataclass, still the same style" observation
type: it is already the canonical monthly-composite-observation shape
this codebase uses (`ObservationBundle`, `WaterBalanceBundle`), and both
ET and surface-water-extent series are exactly that shape — one value (or
`None`, for a month with no usable pass) per calendar month.

CONTRACT ONLY — ticket M1-001. No implementation lives in this module: no
`ee.*` import, no HTTP client, no SQL, no caching, no business logic. A
concrete provider (GEE, and eventually CGWB/IMD/WRIS/local-raster/a test
fake) is always a *separate* class implementing this ABC — never a branch
inside it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from enum import Enum

from app.models.enums import SatelliteIndexType
from app.services.risk.models import MonthlyValue

__all__ = ["HydrologyDataProvider", "SurfaceWaterMethod", "SURFACE_WATER_METHOD_TO_INDEX_TYPE"]


class SurfaceWaterMethod(str, Enum):
    """Which detection method backs one `get_surface_water_extent_series()`
    call — provider-domain vocabulary for a method *parameter*, distinct
    from `app.models.enums.SatelliteIndexType`, which names what a result
    is cached under in `satellite_observation` (a persistence-layer
    concern, out of scope for this contract-only ticket). `COMBINED` has
    no single cache index-type of its own — see
    `SURFACE_WATER_METHOD_TO_INDEX_TYPE` below — because a combined result
    is derived from both SAR and MNDWI series, not a raw indexed
    observation.
    """

    SAR = "sar"
    MNDWI = "mndwi"
    COMBINED = "combined"


# Documents, without importing any caching/persistence code, which
# SatelliteIndexType a given SurfaceWaterMethod's raw series is cached
# under once a real implementation exists (a later ticket's concern —
# named here now so that ticket doesn't have to rediscover the mapping).
# COMBINED is intentionally absent: it composes the SAR and MNDWI series
# rather than being cached as its own index.
SURFACE_WATER_METHOD_TO_INDEX_TYPE: dict[SurfaceWaterMethod, SatelliteIndexType] = {
    SurfaceWaterMethod.SAR: SatelliteIndexType.SURFACE_WATER_SAR,
    SurfaceWaterMethod.MNDWI: SatelliteIndexType.SURFACE_WATER_MNDWI,
}


class HydrologyDataProvider(ABC):
    @abstractmethod
    def get_et_series(self, geometry_geojson: dict, start: date, end: date) -> list[MonthlyValue]:
        """Monthly actual-evapotranspiration composite for a catchment over
        a date range, one entry per calendar month, mm per period.

        Blueprint v2 D9's scale policy: implementations use MODIS MOD16A2
        at its native `scale=500` (m) — a catchment below ~25 ha (5x5
        pixels at that scale) is expected to carry the `et_sub_pixel`
        resolution flag (Part 5) rather than presenting a falsely-precise
        number; deriving and attaching that flag is the caller's/engine's
        responsibility, not this method's.

        A month with no usable composite is returned as `MonthlyValue(...,
        value=None)`, never omitted and never coerced to zero — the same
        "missing is missing" convention `SatelliteDataProvider` already
        establishes (see its `get_index_time_series()` docstring).

        Cached, once implemented, under `SatelliteIndexType.ET`.
        """

    @abstractmethod
    def get_surface_water_extent_series(
        self,
        geometry_geojson: dict,
        start: date,
        end: date,
        method: SurfaceWaterMethod,
    ) -> list[MonthlyValue]:
        """Monthly surface-water extent for a catchment over a date range,
        one entry per calendar month, expressed as the percent of the
        catchment's area classified as open water (0-100).

        `method` selects the detection approach per Part 4's "SAR primary,
        MNDWI secondary confirmation" methodology:
        - `SurfaceWaterMethod.SAR` — Sentinel-1 SAR backscatter threshold.
        - `SurfaceWaterMethod.MNDWI` — Sentinel-2 MNDWI threshold, used as
          a cross-check against the SAR series, not as the primary series.
        - `SurfaceWaterMethod.COMBINED` — an implementation-defined
          reconciliation of the SAR and MNDWI series (e.g. SAR value
          confirmed/flagged by MNDWI agreement); the exact reconciliation
          rule is deliberately left to the implementing ticket, not
          specified by this contract.

        Blueprint v2 D9's scale policy: SAR and MNDWI both use
        `scale=10` (m), matching Sentinel's native resolution — this is
        the number Part 4's 0.2-0.3 ha reliability floor is computed
        from, and the reason small farm-pond-scale water bodies are a
        named, accepted MVP limitation, not a bug. `COMBINED` has no
        single `scale` of its own; it composes two series already
        fetched at `scale=10`.

        A month with no usable composite is returned as `MonthlyValue(...,
        value=None)`, never omitted and never coerced to zero, matching
        `get_et_series()`'s convention above.

        Cached, once implemented: see `SURFACE_WATER_METHOD_TO_INDEX_TYPE`
        for the `SatelliteIndexType` each non-`COMBINED` method maps to.
        """
