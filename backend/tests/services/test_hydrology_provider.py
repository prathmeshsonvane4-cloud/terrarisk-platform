"""Contract tests for the HydrologyDataProvider ABC (ticket M1-001).

No GEE, no network, no database — this file proves the *interface*, not
any implementation. A minimal in-file fake stands in for a real provider
so "a well-formed subclass can be instantiated and called" is exercised
without depending on a shared fakes/fake_hydrology_provider.py, which is
scoped to a later ticket (Section 4 of the Implementation Plan) once a
real orchestrator actually needs one.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app.models.enums import SatelliteIndexType
from app.services.hydrology.provider import (
    SURFACE_WATER_METHOD_TO_INDEX_TYPE,
    HydrologyDataProvider,
    SurfaceWaterMethod,
)
from app.services.risk.models import MonthlyValue


class _FullHydrologyDataProvider(HydrologyDataProvider):
    """Implements every abstract method — the minimal "this ABC is
    actually usable" proof."""

    def get_et_series(self, geometry_geojson: dict, start: date, end: date) -> list[MonthlyValue]:
        return [MonthlyValue(period_start=start, value=60.0)]

    def get_surface_water_extent_series(
        self, geometry_geojson: dict, start: date, end: date, method: SurfaceWaterMethod
    ) -> list[MonthlyValue]:
        return [MonthlyValue(period_start=start, value=5.0)]


class _PartialHydrologyDataProvider(HydrologyDataProvider):
    """Implements only one of the two abstract methods — must remain
    uninstantiable, proving the ABC actually enforces its full contract
    rather than being abstract in name only."""

    def get_et_series(self, geometry_geojson: dict, start: date, end: date) -> list[MonthlyValue]:
        return []


class TestAbcEnforcement:
    def test_cannot_instantiate_the_abc_directly(self):
        with pytest.raises(TypeError, match="abstract"):
            HydrologyDataProvider()

    def test_a_subclass_missing_a_method_cannot_be_instantiated(self):
        with pytest.raises(TypeError, match="abstract"):
            _PartialHydrologyDataProvider()

    def test_a_subclass_implementing_every_method_can_be_instantiated(self):
        provider = _FullHydrologyDataProvider()
        assert isinstance(provider, HydrologyDataProvider)


class TestMethodSignatures:
    def test_get_et_series_signature(self):
        sig = inspect.signature(HydrologyDataProvider.get_et_series)
        assert list(sig.parameters) == ["self", "geometry_geojson", "start", "end"]

    def test_get_surface_water_extent_series_signature(self):
        sig = inspect.signature(HydrologyDataProvider.get_surface_water_extent_series)
        assert list(sig.parameters) == ["self", "geometry_geojson", "start", "end", "method"]

    def test_both_methods_are_marked_abstract(self):
        assert getattr(HydrologyDataProvider.get_et_series, "__isabstractmethod__", False) is True
        assert (
            getattr(HydrologyDataProvider.get_surface_water_extent_series, "__isabstractmethod__", False)
            is True
        )


class TestExpectedSubclassBehavior:
    def test_get_et_series_returns_a_list_of_monthly_value(self):
        provider = _FullHydrologyDataProvider()
        result = provider.get_et_series({}, date(2024, 1, 1), date(2024, 12, 1))
        assert isinstance(result, list)
        assert all(isinstance(v, MonthlyValue) for v in result)

    def test_get_surface_water_extent_series_returns_a_list_of_monthly_value(self):
        provider = _FullHydrologyDataProvider()
        result = provider.get_surface_water_extent_series(
            {}, date(2024, 1, 1), date(2024, 12, 1), SurfaceWaterMethod.SAR
        )
        assert isinstance(result, list)
        assert all(isinstance(v, MonthlyValue) for v in result)

    def test_get_surface_water_extent_series_accepts_every_method_value(self):
        provider = _FullHydrologyDataProvider()
        for method in SurfaceWaterMethod:
            result = provider.get_surface_water_extent_series(
                {}, date(2024, 1, 1), date(2024, 12, 1), method
            )
            assert isinstance(result, list)


class TestSurfaceWaterMethodEnum:
    def test_expected_members_and_values(self):
        assert {m.value for m in SurfaceWaterMethod} == {"sar", "mndwi", "combined"}

    def test_is_a_str_enum(self):
        assert SurfaceWaterMethod.SAR == "sar"


class TestSurfaceWaterMethodToIndexTypeMapping:
    def test_sar_maps_to_the_correct_cache_index_type(self):
        assert SURFACE_WATER_METHOD_TO_INDEX_TYPE[SurfaceWaterMethod.SAR] == SatelliteIndexType.SURFACE_WATER_SAR

    def test_mndwi_maps_to_the_correct_cache_index_type(self):
        assert (
            SURFACE_WATER_METHOD_TO_INDEX_TYPE[SurfaceWaterMethod.MNDWI] == SatelliteIndexType.SURFACE_WATER_MNDWI
        )

    def test_combined_has_no_single_cache_index_type(self):
        """COMBINED composes the SAR and MNDWI series rather than being
        cached as its own raw index — its absence here is intentional,
        not an oversight."""
        assert SurfaceWaterMethod.COMBINED not in SURFACE_WATER_METHOD_TO_INDEX_TYPE
