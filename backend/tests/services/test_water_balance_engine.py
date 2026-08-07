"""Unit tests for the Water Balance Engine's real arithmetic (ticket
M2-002b, replacing the M2-002a/M1-001 skeleton). No database, no network,
no Earth Engine — every test constructs a WaterBalanceBundle/
WaterBalanceConfig by hand, mirroring test_risk_engine.py's exact style.

Known-input arithmetic tests use exact SCS Curve Number runoff values
independently computed (via a standalone script, not by calling any
engine helper) using the engine's own `_CURVE_NUMBER`/
`_INITIAL_ABSTRACTION_RATIO` constants and the published formula — this
is a real cross-check against a transcription error in engine.py, not a
tautology, since none of these tests call `_event_runoff_mm()` itself.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.services.hydrology.engine import (
    _CURVE_NUMBER,
    _INITIAL_ABSTRACTION_RATIO,
    _NEUTRAL_STORAGE_CHANGE_BAND,
    _band_for_storage_change,
    _event_runoff_mm,
    _series_completeness,
    _sum_or_none,
    _total_runoff_mm,
    WaterBalanceEngine,
)
from app.services.hydrology.models import WaterBalanceBundle, WaterBalanceConfig
from app.services.risk.models import MonthlyValue


def _months(n: int) -> list[date]:
    return [date(2023 + (m // 12), (m % 12) + 1, 1) for m in range(n)]


def _config(model_version: str = "caller-supplied-v1") -> WaterBalanceConfig:
    return WaterBalanceConfig(model_version=model_version)


def _bundle(
    period_start: date = date(2023, 1, 1),
    period_end: date = date(2025, 12, 1),
    rainfall_monthly: list[MonthlyValue] | None = None,
    et_monthly: list[MonthlyValue] | None = None,
    rainfall_daily: list[float] | None = None,
    resolution_flags: list[str] | None = None,
    closed_catchment_assumed: bool = True,
) -> WaterBalanceBundle:
    months = _months(36)
    resolved_rainfall = (
        rainfall_monthly if rainfall_monthly is not None else [MonthlyValue(m, 80.0) for m in months]
    )
    return WaterBalanceBundle(
        period_start=period_start,
        period_end=period_end,
        rainfall_monthly=resolved_rainfall,
        et_monthly=et_monthly if et_monthly is not None else [MonthlyValue(m, 60.0) for m in months],
        # Default: one storm event per month, at the month's full depth.
        # This is an ARITHMETIC fixture, not a physical scenario — it
        # deliberately mirrors the pre-daily-runoff behaviour so the
        # mass-balance tests below keep checking what they were written
        # to check (does P - ET - Q = dS close exactly, are missing
        # months excluded rather than zeroed) instead of silently
        # becoming assertions about the runoff timestep. The realism of
        # the timestep is covered directly, per storm event, by
        # test_water_balance_golden_dataset.py's NRCS reference class.
        rainfall_daily=rainfall_daily if rainfall_daily is not None else _month_depths(resolved_rainfall),
        resolution_flags=resolution_flags if resolution_flags is not None else [],
        closed_catchment_assumed=closed_catchment_assumed,
    )


def _month_depths(rainfall_monthly: list[MonthlyValue]) -> list[float]:
    """Each month's total as one event depth, dropping missing months —
    the same "missing is missing, never a fabricated zero" rule the
    engine's own `_valid_values()` applies."""
    return [m.value for m in rainfall_monthly if m.value is not None]


def _scs_cn_runoff(rainfall_mm: float) -> float:
    """Independent re-derivation of the published SCS-CN formula, using
    the engine's own constants — a real cross-check, not a call into
    engine.py's private helper."""
    s = (25400.0 / _CURVE_NUMBER) - 254.0
    ia = _INITIAL_ABSTRACTION_RATIO * s
    if rainfall_mm <= ia:
        return 0.0
    excess = rainfall_mm - ia
    return (excess * excess) / (excess + s)


def _series(values: list[float | None], months: int) -> list[MonthlyValue]:
    dates = _months(months)
    return [MonthlyValue(period_start=d, value=v) for d, v in zip(dates, values, strict=True)]


class TestConstruction:
    def test_engine_constructs_with_no_arguments(self):
        """Stateless, exactly like RiskEngine — no repository, session, or
        provider dependency to inject at construction time (Blueprint v2
        D4)."""
        engine = WaterBalanceEngine()
        assert engine is not None

    def test_a_single_engine_instance_is_reusable_across_calls(self):
        """"Safe to reuse a single instance across requests" is a stated
        property, not an assumption — prove two calls on the same
        instance both produce a well-formed, equal result independently."""
        engine = WaterBalanceEngine()
        bundle, config = _bundle(), _config()
        first = engine.compute(bundle, config)
        second = engine.compute(bundle, config)
        assert first == second


class TestBundleValidation:
    def test_none_bundle_is_rejected(self):
        with pytest.raises(ValueError, match="WaterBalanceBundle is required"):
            WaterBalanceEngine().compute(None, _config())

    def test_period_start_after_period_end_is_rejected(self):
        bundle = _bundle(period_start=date(2025, 1, 1), period_end=date(2023, 1, 1))
        with pytest.raises(ValueError, match="must not be after"):
            WaterBalanceEngine().compute(bundle, _config())

    def test_period_start_equal_to_period_end_is_valid(self):
        """A single-day/zero-width period is a legitimate edge case, not
        an error — only period_start strictly after period_end is
        invalid. Now that real arithmetic exists, a valid bundle produces
        a real result, not the old skeleton's NotImplementedError."""
        bundle = _bundle(period_start=date(2024, 6, 1), period_end=date(2024, 6, 1))
        result = WaterBalanceEngine().compute(bundle, _config())
        assert result.storage_change_mm is not None

    def test_non_list_rainfall_monthly_is_rejected(self):
        bundle = _bundle()
        object.__setattr__(bundle, "rainfall_monthly", "not-a-list")
        with pytest.raises(TypeError, match="rainfall_monthly"):
            WaterBalanceEngine().compute(bundle, _config())

    def test_non_list_et_monthly_is_rejected(self):
        bundle = _bundle()
        object.__setattr__(bundle, "et_monthly", "not-a-list")
        with pytest.raises(TypeError, match="et_monthly"):
            WaterBalanceEngine().compute(bundle, _config())

    def test_non_list_resolution_flags_is_rejected(self):
        bundle = _bundle()
        object.__setattr__(bundle, "resolution_flags", "not-a-list")
        with pytest.raises(TypeError, match="resolution_flags"):
            WaterBalanceEngine().compute(bundle, _config())


class TestConfigValidation:
    def test_none_config_is_rejected(self):
        with pytest.raises(ValueError, match="WaterBalanceConfig is required"):
            WaterBalanceEngine().compute(_bundle(), None)

    def test_empty_model_version_is_rejected(self):
        with pytest.raises(ValueError, match="model_version"):
            WaterBalanceEngine().compute(_bundle(), _config(model_version=""))

    def test_config_validation_runs_even_when_bundle_is_valid(self):
        """Bundle validation passing must not short-circuit config
        validation — both are checked on every call."""
        with pytest.raises(ValueError, match="model_version"):
            WaterBalanceEngine().compute(_bundle(), _config(model_version=""))


class TestNormalCase:
    """Known rainfall/ET inputs, 3 months: rainfall=100mm, ET=30mm each
    month. Verifies exact arithmetic against independently-derived
    runoff."""

    def test_exact_arithmetic(self):
        bundle = _bundle(rainfall_monthly=_series([100.0, 100.0, 100.0], 3), et_monthly=_series([30.0, 30.0, 30.0], 3))
        result = WaterBalanceEngine().compute(bundle, _config())

        expected_runoff = _scs_cn_runoff(100.0) * 3
        expected_rainfall = 300.0
        expected_et = 90.0
        expected_storage_change = expected_rainfall - expected_et - expected_runoff

        assert result.rainfall_mm == pytest.approx(expected_rainfall)
        assert result.et_mm == pytest.approx(expected_et)
        assert result.runoff_mm == pytest.approx(expected_runoff)
        assert result.storage_change_mm == pytest.approx(expected_storage_change)
        assert result.storage_change_band == _band_for_storage_change(expected_storage_change)


class TestZeroRainfall:
    def test_zero_rainfall_is_a_real_zero_not_missing_data(self):
        """A measured zero (MonthlyValue(value=0.0)) must sum to a real
        0.0, distinct from None (no data) — and produces zero runoff,
        since 0 <= Ia always."""
        bundle = _bundle(rainfall_monthly=_series([0.0, 0.0, 0.0], 3), et_monthly=_series([30.0, 30.0, 30.0], 3))
        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.rainfall_mm == 0.0
        assert result.runoff_mm == 0.0
        assert result.et_mm == pytest.approx(90.0)
        assert result.storage_change_mm == pytest.approx(-90.0)


class TestZeroEt:
    def test_zero_et_is_a_real_zero_not_missing_data(self):
        bundle = _bundle(rainfall_monthly=_series([50.0, 50.0, 50.0], 3), et_monthly=_series([0.0, 0.0, 0.0], 3))
        result = WaterBalanceEngine().compute(bundle, _config())

        expected_runoff = _scs_cn_runoff(50.0) * 3
        assert result.et_mm == 0.0
        assert result.rainfall_mm == pytest.approx(150.0)
        assert result.runoff_mm == pytest.approx(expected_runoff)
        assert result.storage_change_mm == pytest.approx(150.0 - expected_runoff)


class TestNegativeBalance:
    def test_high_et_low_rainfall_produces_a_deeply_negative_band(self):
        """Rainfall stays below the initial-abstraction threshold every
        event, so runoff is exactly 0 — an easy-to-verify-by-hand case
        with no quadratic term.

        The depth must sit under Ia, which moves with CN: Ia was 16.9 mm
        at CN=75 and is 6.28 mm at CN=89, so the original 10 mm silently
        crossed into the quadratic branch when the soil group was
        corrected. The guard below keeps that from happening quietly
        again — if a future CN raises Ia past this depth, the scenario
        gets re-chosen deliberately instead of turning into a different
        test than the one its docstring describes.
        """
        s = (25400.0 / _CURVE_NUMBER) - 254.0
        initial_abstraction_mm = _INITIAL_ABSTRACTION_RATIO * s
        assert 5.0 < initial_abstraction_mm, (
            "this scenario requires a sub-Ia rainfall depth to keep runoff exactly 0; "
            f"Ia is now {initial_abstraction_mm:.2f} mm — pick a smaller depth"
        )

        bundle = _bundle(rainfall_monthly=_series([5.0, 5.0, 5.0], 3), et_monthly=_series([200.0, 200.0, 200.0], 3))
        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.rainfall_mm == pytest.approx(15.0)
        assert result.et_mm == pytest.approx(600.0)
        assert result.runoff_mm == 0.0
        assert result.storage_change_mm == pytest.approx(-585.0)
        assert result.storage_change_band == StorageChangeBand.MUCH_BELOW_NORMAL


class TestPositiveBalance:
    def test_high_rainfall_zero_et_produces_a_strongly_positive_band(self):
        """Six events rather than two, because SCS-CN bounds how much a
        single event can contribute to storage: as P grows,
        Q -> P - Ia - S, so (P - Q) asymptotes to Ia + S = 1.2 * S, about
        37.7 mm per event at CN=89 no matter how heavy the storm. Two
        events therefore cannot clear the 150 mm MUCH_ABOVE_NORMAL
        threshold at all with zero ET — not a band-logic failure, a real
        property of the runoff method. At CN=75, S was 2.7x larger, so
        two events sufficed and this scenario passed.
        """
        rainfall = [300.0] * 6
        bundle = _bundle(rainfall_monthly=_series(rainfall, 6), et_monthly=_series([0.0] * 6, 6))
        result = WaterBalanceEngine().compute(bundle, _config())

        expected_runoff = _scs_cn_runoff(300.0) * 6
        expected_storage_change = 1800.0 - 0.0 - expected_runoff

        assert result.rainfall_mm == pytest.approx(1800.0)
        assert result.et_mm == 0.0
        assert result.runoff_mm == pytest.approx(expected_runoff)
        assert result.storage_change_mm == pytest.approx(expected_storage_change)
        assert result.storage_change_band == StorageChangeBand.MUCH_ABOVE_NORMAL


class TestMixedMissingMonths:
    def test_missing_months_are_excluded_from_sums_not_coerced_to_zero(self):
        """rainfall=[100, None, 100], et=[30, 30, None] — every aggregate
        must reflect only the valid entries in ITS OWN series
        independently (a missing ET month doesn't block summing
        rainfall, and vice versa)."""
        bundle = _bundle(
            rainfall_monthly=_series([100.0, None, 100.0], 3),
            et_monthly=_series([30.0, 30.0, None], 3),
        )
        result = WaterBalanceEngine().compute(bundle, _config())

        expected_runoff = _scs_cn_runoff(100.0) * 2  # only the two valid rainfall months
        assert result.rainfall_mm == pytest.approx(200.0)
        assert result.et_mm == pytest.approx(60.0)
        assert result.runoff_mm == pytest.approx(expected_runoff)
        assert result.storage_change_mm == pytest.approx(200.0 - 60.0 - expected_runoff)

    def test_empty_monthly_series_is_valid_input_producing_a_none_residual(self):
        """Missing months are a real, expected data-availability gap
        (mirrors RiskEngine's "missing months are missing, never zero"
        convention) — an empty series is valid input, not an error, and
        produces None for every mm field (nothing to sum), not a
        fabricated 0.0."""
        engine = WaterBalanceEngine()
        bundle = _bundle(rainfall_monthly=[], et_monthly=[])

        result = engine.compute(bundle, _config())

        assert result.rainfall_mm is None
        assert result.et_mm is None
        assert result.runoff_mm is None
        assert result.storage_change_mm is None
        assert result.data_completeness == 0.0

    def test_all_months_missing_falls_back_to_the_neutral_band(self):
        """storage_change_band is not Optional — when the residual can't
        be computed at all, the engine returns the documented neutral
        fallback (mirrors RiskEngine's _NEUTRAL_SCORE convention), never
        raises, never guesses a real band from nothing."""
        bundle = _bundle(rainfall_monthly=_series([None, None], 2), et_monthly=_series([None, None], 2))
        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.storage_change_band == _NEUTRAL_STORAGE_CHANGE_BAND
        assert result.storage_change_band == StorageChangeBand.NORMAL


class TestSeriesCompleteness:
    def test_data_completeness_reflects_only_the_et_series(self):
        """Mirrors RiskEngine._compute_confidence()'s exact reasoning:
        ET (MODIS, fill/QC-masked) is the cloud-limited series; rainfall
        (CHIRPS) is not, and is excluded — a rainfall gap must not move
        data_completeness at all."""
        bundle = _bundle(
            rainfall_monthly=_series([None, None, None], 3),  # fully missing, irrelevant to completeness
            et_monthly=_series([30.0, 30.0, None], 3),
        )
        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.data_completeness == pytest.approx((2 / 3) * 100.0)

    def test_fully_complete_et_series_is_100_percent(self):
        bundle = _bundle(et_monthly=_series([10.0, 20.0, 30.0], 3))
        result = WaterBalanceEngine().compute(bundle, _config())
        assert result.data_completeness == pytest.approx(100.0)

    def test_fully_missing_et_series_is_zero_percent(self):
        bundle = _bundle(et_monthly=_series([None, None], 2), rainfall_monthly=_series([100.0, 100.0], 2))
        result = WaterBalanceEngine().compute(bundle, _config())
        assert result.data_completeness == 0.0


class TestResolutionFlagsPassthrough:
    """resolution_flags are computed once at catchment-creation time from
    area_ha/DEM relief (Blueprint v2 Part 5) — inputs this zero-I/O
    engine has no access to. The engine's only job is to copy them
    through untouched, never derive or invent new ones."""

    def test_flags_are_copied_through_unchanged(self):
        bundle = _bundle(resolution_flags=["rainfall_sub_pixel", "high_relief_terrain"])
        result = WaterBalanceEngine().compute(bundle, _config())
        assert result.resolution_flags == ["rainfall_sub_pixel", "high_relief_terrain"]

    def test_empty_flags_list_stays_empty(self):
        bundle = _bundle(resolution_flags=[])
        result = WaterBalanceEngine().compute(bundle, _config())
        assert result.resolution_flags == []

    def test_result_flags_are_a_copy_not_the_same_list_object(self):
        flags = ["et_sub_pixel"]
        bundle = _bundle(resolution_flags=flags)
        result = WaterBalanceEngine().compute(bundle, _config())
        result.resolution_flags.append("mutated_after_the_fact")
        assert flags == ["et_sub_pixel"]  # the bundle's own list must be unaffected

    def test_closed_catchment_assumed_is_copied_through(self):
        bundle = _bundle(closed_catchment_assumed=True)
        result = WaterBalanceEngine().compute(bundle, _config())
        assert result.closed_catchment_assumed is True


class TestCalibrationStatus:
    def test_always_uncalibrated_for_mvp(self):
        """Blueprint v2 D5: no ground-truth field data source is wired
        into any provider yet for any generic customer — always
        UNCALIBRATED, not a placeholder."""
        result = WaterBalanceEngine().compute(_bundle(), _config())
        assert result.calibration_status == CalibrationStatus.UNCALIBRATED


class TestModelVersion:
    def test_engine_has_a_model_version_class_constant(self):
        """Same convention as RiskEngine.MODEL_VERSION."""
        assert WaterBalanceEngine.MODEL_VERSION == "water-balance-engine-v1"

    def test_result_is_stamped_with_the_engines_own_model_version(self):
        result = WaterBalanceEngine().compute(_bundle(), _config())
        assert result.model_version == WaterBalanceEngine.MODEL_VERSION

    def test_the_callers_config_model_version_is_validated_but_not_echoed(self):
        """Mirrors RiskEngine.compute()'s exact asymmetry: config.model_version
        is validated (must be non-empty) but the STAMPED value always
        comes from the engine's own MODEL_VERSION, never the caller's
        string — proven here by using a deliberately different caller
        value."""
        result = WaterBalanceEngine().compute(_bundle(), _config(model_version="some-completely-different-string"))
        assert result.model_version == WaterBalanceEngine.MODEL_VERSION
        assert result.model_version != "some-completely-different-string"


class TestNumericalStabilityAndDeterminism:
    def test_same_inputs_always_produce_the_same_outputs(self):
        bundle = _bundle(rainfall_monthly=_series([73.4, 12.9, 0.0], 3), et_monthly=_series([41.2, 5.5, 60.0], 3))
        config = _config()
        engine = WaterBalanceEngine()

        results = [engine.compute(bundle, config) for _ in range(5)]

        assert all(r == results[0] for r in results)

    def test_many_small_fractional_months_sum_without_drift(self):
        """Floating-point tolerance: 36 months of fractional values summed
        must match Python's own sum() within floating-point epsilon, not
        exactly by == (accumulated float error is expected and fine)."""
        rainfall_values = [0.1 + (i * 0.0001) for i in range(36)]
        et_values = [0.05 + (i * 0.00005) for i in range(36)]
        bundle = _bundle(rainfall_monthly=_series(rainfall_values, 36), et_monthly=_series(et_values, 36))

        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.rainfall_mm == pytest.approx(sum(rainfall_values))
        assert result.et_mm == pytest.approx(sum(et_values))
        expected_runoff = sum(_scs_cn_runoff(v) for v in rainfall_values)
        assert result.runoff_mm == pytest.approx(expected_runoff)


class TestMonthlyRunoffHelper:
    """Direct unit tests for the SCS-CN formula's own boundary behavior."""

    def test_rainfall_at_or_below_initial_abstraction_produces_zero_runoff(self):
        s = (25400.0 / _CURVE_NUMBER) - 254.0
        ia = _INITIAL_ABSTRACTION_RATIO * s
        assert _event_runoff_mm(ia) == 0.0
        assert _event_runoff_mm(0.0) == 0.0

    def test_rainfall_above_initial_abstraction_produces_positive_runoff(self):
        assert _event_runoff_mm(100.0) == pytest.approx(_scs_cn_runoff(100.0))

    def test_runoff_never_exceeds_rainfall(self):
        """A physical sanity bound the SCS-CN formula itself guarantees —
        worth asserting explicitly since a transcription bug could
        silently violate it."""
        for p in [10.0, 50.0, 100.0, 500.0, 2000.0]:
            assert _event_runoff_mm(p) <= p


class TestTotalRunoffHelper:
    def test_empty_series_returns_none(self):
        assert _total_runoff_mm([]) is None

    def test_no_daily_rainfall_returns_none_rather_than_zero(self):
        # A catchment with no daily rainfall available must report runoff
        # as unknown, never as a confident 0.0 — a fabricated zero would
        # flow straight into P - ET - Q = dS and inflate storage change.
        assert _total_runoff_mm([]) is None

    def test_sums_per_event_not_per_total(self):
        # The whole point of the daily timestep: ten 20 mm days are not
        # one 200 mm storm. Summing per event must give far less runoff
        # than applying the formula once to the accumulated depth.
        ten_days = [20.0] * 10
        per_event = _total_runoff_mm(ten_days)

        assert per_event == pytest.approx(_scs_cn_runoff(20.0) * 10)
        assert per_event < _scs_cn_runoff(sum(ten_days))

    def test_days_below_initial_abstraction_contribute_no_runoff(self):
        # Drizzle days are absorbed entirely by initial abstraction, so
        # they add nothing — the behaviour that monthly aggregation
        # destroyed by rolling them into one large depth.
        s = (25400.0 / _CURVE_NUMBER) - 254.0
        ia = _INITIAL_ABSTRACTION_RATIO * s
        assert _total_runoff_mm([ia * 0.5] * 20) == pytest.approx(0.0)


class TestSumOrNoneHelper:
    def test_empty_list_returns_none(self):
        assert _sum_or_none([]) is None

    def test_all_none_returns_none(self):
        assert _sum_or_none(_series([None, None], 2)) is None

    def test_zero_is_a_real_value_not_none(self):
        assert _sum_or_none(_series([0.0], 1)) == 0.0

    def test_sums_only_valid_values(self):
        assert _sum_or_none(_series([10.0, None, 20.0], 3)) == pytest.approx(30.0)


class TestSeriesCompletenessHelper:
    def test_empty_series_is_zero(self):
        assert _series_completeness([]) == 0.0

    def test_fully_valid_series_is_one(self):
        assert _series_completeness(_series([1.0, 2.0], 2)) == 1.0

    def test_partially_valid_series_is_the_correct_fraction(self):
        assert _series_completeness(_series([1.0, None, 3.0, None], 4)) == pytest.approx(0.5)


class TestBandForStorageChange:
    """Table-driven test over every named band boundary — mirrors
    test_gee_hydrology_provider.py's TestSarThreshold-style discipline
    for a fixed, named constant."""

    @pytest.mark.parametrize(
        "storage_change_mm,expected_band",
        [
            (-1000.0, StorageChangeBand.MUCH_BELOW_NORMAL),
            (-150.0, StorageChangeBand.MUCH_BELOW_NORMAL),  # inclusive upper bound
            (-149.99, StorageChangeBand.BELOW_NORMAL),
            (-50.0, StorageChangeBand.BELOW_NORMAL),  # inclusive upper bound
            (-49.99, StorageChangeBand.NORMAL),
            (0.0, StorageChangeBand.NORMAL),
            (50.0, StorageChangeBand.NORMAL),  # inclusive upper bound
            (50.01, StorageChangeBand.ABOVE_NORMAL),
            (150.0, StorageChangeBand.ABOVE_NORMAL),  # inclusive upper bound
            (150.01, StorageChangeBand.MUCH_ABOVE_NORMAL),
            (1000.0, StorageChangeBand.MUCH_ABOVE_NORMAL),
        ],
    )
    def test_boundary_values(self, storage_change_mm, expected_band):
        assert _band_for_storage_change(storage_change_mm) == expected_band
