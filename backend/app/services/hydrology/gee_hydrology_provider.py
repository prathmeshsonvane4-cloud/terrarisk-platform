"""Google Earth Engine implementation of HydrologyDataProvider — ET series
(ticket M1-003) and surface-water extent, all three `SurfaceWaterMethod`
values (SAR: ticket M1-004; MNDWI and COMBINED: ticket M1-005). This
completes `HydrologyDataProvider`'s full MVP contract.

No `ee.*` object is returned from any public method — everything crosses
back into `MonthlyValue`, per the architectural contract
`HydrologyDataProvider`/`SatelliteDataProvider` both already establish.
"""

from __future__ import annotations

import logging
import threading
from datetime import date

import ee

from app.core.config import get_settings
from app.services.hydrology.provider import HydrologyDataProvider, SurfaceWaterMethod
from app.services.risk.models import MonthlyValue
from app.services.satellite._gee_common import (
    CLOUD_PROBABILITY_COLLECTION,
    CLOUD_PROBABILITY_THRESHOLD,
    SENTINEL2_COLLECTION,
    monthly_periods,
)

logger = logging.getLogger(__name__)

_MODIS_ET_COLLECTION = "MODIS/061/MOD16A2"
_ET_BAND = "ET"

# MOD16A2's own documented scale factor: the band is stored as an integer,
# actual mm/8-day-composite = stored_value * 0.1 — omitting this makes
# every reading exactly 10x too small, not just imprecise.
_ET_SCALE_FACTOR = 0.1

# MOD16A2's compositing period. Each image is a CUMULATIVE total for its
# 8-day window (mm/8 days), NOT a rate per day and NOT a monthly total —
# so the mean of a month's composites is "average mm per 8-day window,"
# which is roughly a quarter of the month's actual ET.
#
# This was a real production defect, not a hypothetical: get_et_series()
# returned that bare mean while its own interface contract
# (HydrologyDataProvider.get_et_series, "mm per period") promises a
# monthly total. Raichur reports came back at ~123 mm/yr actual ET
# against a physically expected ~450-500 mm/yr for a semi-arid Deccan
# agricultural catchment. Because the engine closes P - ET - Q = dS, the
# ~330 mm/yr of missing ET did not disappear — it was silently
# reattributed to storage change, inflating the headline recharge number
# and pushing catchments into "above normal" recharge bands they had no
# physical claim to.
_ET_COMPOSITE_DAYS = 8.0

# MOD16A2's own documented fill-value convention: valid ET is 0-32700;
# 32761 (and the reserved codes above it — water/urban/snow/gap-filled/
# etc.) mark a pixel with no valid retrieval for that 8-day composite.
# This is a per-product QC convention, not the s2cloudless probability
# mask the optical indices use — MODIS ET has no comparable cloud-
# probability side channel to threshold against.
_ET_FILL_VALUE_THRESHOLD = 32761

# Blueprint v2 D9's explicit, named scale policy for this index — MODIS
# MOD16A2's own native pixel size, not a tunable. A catchment below ~25 ha
# (5x5 pixels at this scale) is expected to carry the `et_sub_pixel`
# resolution flag (Part 5) — deriving that flag is the engine's/caller's
# responsibility (a later ticket), not this provider's.
_ET_SCALE_METERS = 500
_ET_MAX_PIXELS = 1e9

_SENTINEL1_GRD_COLLECTION = "COPERNICUS/S1_GRD"
_SAR_VV_BAND = "VV"

# Fixed VV backscatter threshold (dB) for water classification — a pixel's
# monthly-mean VV composite below this value is classified open water.
# A commonly used literature default for Sentinel-1 GRD water detection
# (e.g. Twele et al. 2016's SAR flood-mapping threshold), NOT locally
# calibrated against Indian catchments. This is a deliberate, NAMED MVP
# limitation per Blueprint v2 Part 4/Part 9 (risk #10) and Part 13's
# roadmap — a fixed global threshold degrades in high-relief terrain
# (incidence-angle sensitivity, layover/shadow) independent of catchment
# size; terrain-aware, locally-adaptive thresholding is explicitly named
# future work, not something this ticket silently presents as precise.
_SAR_VV_WATER_THRESHOLD_DB = -15.0

# Blueprint v2 D9's explicit, named scale policy for this index —
# Sentinel's own native pixel size, not a tunable. This is the number
# Part 4's 0.2-0.3 ha reliability floor is computed from; sub-pixel-scale
# features (many Indian farm ponds) are a separately named limitation,
# not something this provider tries to resolve.
_SURFACE_WATER_SCALE_METERS = 10
_SURFACE_WATER_MAX_PIXELS = 1e9

# MNDWI band math (docs/DECISIONS.md — Water Availability factor, and
# gee_provider.py's own _INDEX_BANDS[SatelliteIndex.MNDWI]): (GREEN -
# SWIR1) / (GREEN + SWIR1). Duplicated here as two short string constants
# rather than importing gee_provider.py's private _INDEX_BANDS dict —
# that dict is keyed by SatelliteIndex, a SatelliteDataProvider-specific
# enum this module has no reason to depend on; two Sentinel-2 band-name
# literals are not the kind of logic ticket M1-002/M1-005's "don't
# duplicate" concern is about.
_MNDWI_GREEN_BAND = "B3"
_MNDWI_SWIR1_BAND = "B11"

# Standard MNDWI water-classification threshold (Xu, 2006's modified
# NDWI): a pixel is classified water when its MNDWI composite exceeds
# this value. Like the SAR threshold above, this is a widely used
# literature default, NOT locally calibrated against Indian catchments —
# the same named-limitation discipline applies (Blueprint v2 Part 4/9).
_MNDWI_WATER_THRESHOLD = 0.0

# A coarse water-presence/absence cutoff used ONLY to compute the
# SAR/MNDWI agreement signal for SurfaceWaterMethod.COMBINED's QA log
# (Blueprint v2 Part 9's "do surface-water and MNDWI/SAR agree
# directionally" internal-consistency check) — never used to alter the
# reported extent percentage itself. 1% is deliberately generous: this
# signal only needs to distinguish "some open water visible this month"
# from "none," not agree on a precise area.
_WATER_PRESENCE_PERCENT_THRESHOLD = 1.0


class GEEHydrologyProvider(HydrologyDataProvider):
    """Stateless — mirrors `GeeProvider`'s own contract exactly: no
    instance state beyond the class-level lazy-init flag, safe to
    construct fresh per request/background task.

    Initializes against a SEPARATE Earth Engine service-account credential
    from `GeeProvider` (`settings.gee_hydrology_project_id` /
    `gee_hydrology_service_account_json_path`, not
    `gee_project_id`/`gee_service_account_json_path`) — Blueprint v2 D9's
    quota-isolation decision, so a Water Intelligence usage spike cannot
    degrade Service 1's GEE SLA. The thread-safe check-lock-recheck
    initialization shape below is a deliberate duplicate of
    `GeeProvider._ensure_initialized()`, not a bug: the two providers
    initialize against different credentials, so the *logic* can't be
    shared verbatim the way `_monthly_periods()`/the cloud-masking
    constant were in ticket M1-002 — only the *pattern* is mirrored, per
    that ticket's own convention.
    """

    _initialized = False
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
            if not settings.gee_hydrology_project_id or not settings.gee_hydrology_service_account_json_path:
                raise RuntimeError(
                    "GEE_HYDROLOGY_PROJECT_ID and GEE_HYDROLOGY_SERVICE_ACCOUNT_JSON_PATH must be set to "
                    "use GEEHydrologyProvider — a credential separate from Service 1's GeeProvider, per "
                    "Blueprint v2 D9's quota-isolation decision "
                    "(docs/Water_Intelligence_Service_Blueprint.md)."
                )
            credentials = ee.ServiceAccountCredentials(
                email=None, key_file=settings.gee_hydrology_service_account_json_path
            )
            ee.Initialize(credentials, project=settings.gee_hydrology_project_id)
            cls._initialized = True

    def get_et_series(self, geometry_geojson: dict, start: date, end: date) -> list[MonthlyValue]:
        logger.info(
            "get_et_series_called",
            extra={"period_start": start.isoformat(), "period_end": end.isoformat()},
        )

        region = ee.Geometry(geometry_geojson)
        periods = monthly_periods(start, end)
        modis_et = ee.ImageCollection(_MODIS_ET_COLLECTION).filterBounds(region).select(_ET_BAND)

        period_dicts = ee.List(
            [
                {
                    "start": p_start.isoformat(),
                    "end": p_end.isoformat(),
                    # How many 8-day MOD16A2 windows this calendar month
                    # spans (~3.9 for a 31-day month). Multiplying the
                    # month's AVERAGE 8-day composite by this converts
                    # "mm per 8-day window" into the monthly total the
                    # interface contract actually promises.
                    #
                    # Scaling the mean, rather than .sum()-ing the
                    # composites, is deliberate: _mask_fill_values() masks
                    # no-retrieval pixels, so a straight sum silently
                    # undercounts any month where some composites are
                    # masked (exactly the cloudy monsoon months that
                    # matter most here). Scaling the mean of whatever
                    # composites DID retrieve treats a partially-observed
                    # month as representative rather than as partially
                    # zero — the same "missing is missing, never a
                    # fabricated zero" convention this module already
                    # applies elsewhere.
                    "windows": (p_end - p_start).days / _ET_COMPOSITE_DAYS,
                }
                for p_start, p_end in periods
            ]
        )

        def _mask_fill_values(image: ee.Image) -> ee.Image:
            return image.updateMask(image.lt(_ET_FILL_VALUE_THRESHOLD))

        def _compute_period(period) -> ee.Feature:
            period = ee.Dictionary(period)
            period_start = ee.Date(period.get("start"))
            period_end = ee.Date(period.get("end"))
            windows = ee.Number(period.get("windows"))
            month_images = modis_et.filterDate(period_start, period_end).map(_mask_fill_values)

            def _compute_et_value():
                composite = month_images.mean()
                stats = composite.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=region,
                    scale=_ET_SCALE_METERS,
                    maxPixels=_ET_MAX_PIXELS,
                )
                # Guarded lookup — same pattern GeeProvider.get_index_time_series()
                # and get_rainfall_series() already use: a month where every
                # retained pixel across all composites is masked still has a
                # real ET band (just no valid pixel anywhere in the region),
                # so reduceRegion returns an EMPTY dictionary and a bare
                # .get() throws server-side. The If(contains) guard yields
                # null instead, which _parse_monthly_features() below treats
                # as a genuinely missing month, never a fabricated zero.
                #
                # `.multiply(windows)` is the 8-day -> monthly conversion
                # (see `_ET_COMPOSITE_DAYS` and the "windows" key above);
                # it must stay INSIDE the contains() guard so a month with
                # no valid retrieval still yields null rather than 0.
                return ee.Algorithms.If(
                    stats.contains(_ET_BAND),
                    ee.Number(stats.get(_ET_BAND)).multiply(windows),
                    None,
                )

            return ee.Feature(
                None,
                {
                    "period_start": period_start.format("YYYY-MM-dd"),
                    # See _run_if_images_exist's own docstring for why this
                    # guard exists at all: a month with ZERO MODIS granules
                    # (not just every pixel masked) produces a genuinely
                    # band-less composite, and reduceRegion tolerates that —
                    # but this file's own production incident proved other
                    # per-band image ops do not. Applied here defensively
                    # for consistency with the two methods below, which do
                    # have a proven crash on this exact input shape.
                    "value": self._run_if_images_exist(month_images, _compute_et_value()),
                },
            )

        features = ee.FeatureCollection(period_dicts.map(_compute_period)).getInfo()["features"]
        observations = self._parse_monthly_features(features, periods)
        self._warn_if_months_missing(observations, source="et")
        return observations

    def get_surface_water_extent_series(
        self,
        geometry_geojson: dict,
        start: date,
        end: date,
        method: SurfaceWaterMethod,
    ) -> list[MonthlyValue]:
        """Monthly surface-water extent, per catchment, expressed as a
        0-100 percent of catchment area — `HydrologyDataProvider`'s own
        documented contract. All three `SurfaceWaterMethod` values are
        implemented as of ticket M1-005:

        - `.SAR` (ticket M1-004): Sentinel-1 VV backscatter threshold.
        - `.MNDWI` (ticket M1-005): Sentinel-2 MNDWI threshold, the same
          cloud-masking workflow `GeeProvider`'s optical indices use.
        - `.COMBINED` (ticket M1-005): per Blueprint v2 Part 4's exact,
          named methodology — "SAR primary, MNDWI secondary confirmation"
          — returns the `.SAR` series unchanged (SAR IS the reported
          number) and separately fetches `.MNDWI` purely to log a
          directional agreement/disagreement signal (Blueprint v2 Part
          9's internal-consistency check). See
          `_get_combined_surface_water_extent_series()`'s own docstring
          for why this is not a blended/averaged estimate — Blueprint v2
          documents no such fusion formula, and none is invented here.
        """
        logger.info(
            "get_surface_water_extent_series_called",
            extra={"method": method.value, "period_start": start.isoformat(), "period_end": end.isoformat()},
        )
        if method == SurfaceWaterMethod.SAR:
            return self._get_sar_surface_water_extent_series(geometry_geojson, start, end)
        if method == SurfaceWaterMethod.MNDWI:
            return self._get_mndwi_surface_water_extent_series(geometry_geojson, start, end)
        if method == SurfaceWaterMethod.COMBINED:
            return self._get_combined_surface_water_extent_series(geometry_geojson, start, end)
        raise ValueError(f"Unknown SurfaceWaterMethod: {method!r}")

    def _get_sar_surface_water_extent_series(
        self, geometry_geojson: dict, start: date, end: date
    ) -> list[MonthlyValue]:
        """Sentinel-1 VV backscatter threshold — the PRIMARY surface-water
        detection method (Blueprint v2 Part 4): all-weather (no cloud
        dependency, unlike MNDWI), which is exactly why it's the reported
        number rather than MNDWI. See module-level `_SAR_VV_WATER_THRESHOLD_DB`
        for the threshold's own named limitation."""
        region = ee.Geometry(geometry_geojson)
        periods = monthly_periods(start, end)
        sentinel1_vv = (
            ee.ImageCollection(_SENTINEL1_GRD_COLLECTION)
            .filterBounds(region)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", _SAR_VV_BAND))
            .select(_SAR_VV_BAND)
        )

        period_dicts = ee.List(
            [{"start": p_start.isoformat(), "end": p_end.isoformat()} for p_start, p_end in periods]
        )

        def _compute_period(period) -> ee.Feature:
            period = ee.Dictionary(period)
            period_start = ee.Date(period.get("start"))
            period_end = ee.Date(period.get("end"))
            month_images = sentinel1_vv.filterDate(period_start, period_end)

            def _compute_water_percent():
                # Monthly-mean VV composite, then classified against the
                # fixed threshold — smooths single-scene speckle noise
                # before thresholding, rather than thresholding every scene
                # and averaging binary masks (either is defensible; this
                # matches get_et_series()'s own "composite first, reduce
                # second" shape so every method here reads the same way).
                composite = month_images.mean()
                is_water = composite.lt(_SAR_VV_WATER_THRESHOLD_DB).rename("is_water")
                stats = is_water.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=region,
                    scale=_SURFACE_WATER_SCALE_METERS,
                    maxPixels=_SURFACE_WATER_MAX_PIXELS,
                )
                # Guarded lookup — the mean of a 0/1 water mask is already
                # the water-covered fraction of the catchment (0.0-1.0);
                # *100 converts it to the 0-100 percent
                # get_surface_water_extent_series() promises. See
                # _safe_percent()'s own docstring for why "contains()
                # first" alone isn't a sufficient guard here.
                return self._safe_percent(stats, "is_water")

            return ee.Feature(
                None,
                {
                    "period_start": period_start.format("YYYY-MM-dd"),
                    # PRODUCTION INCIDENT, fixed here: a month with ZERO
                    # Sentinel-1 passes (not just a masked pixel — no
                    # granule at all) makes month_images.mean() a
                    # genuinely band-less image. Calling .lt() on it
                    # directly (the code that used to sit where
                    # _compute_water_percent() is called from below)
                    # crashed server-side with "Image.lt: If one image has
                    # no bands, the other must also have no bands. Got 0
                    # and 1." — reduceRegion tolerates a band-less image
                    # (see the ET method above), but per-band comparison
                    # ops like .lt() do not. _run_if_images_exist() checks
                    # for at least one image BEFORE any such op ever runs.
                    "value": self._run_if_images_exist(month_images, _compute_water_percent()),
                },
            )

        features = ee.FeatureCollection(period_dicts.map(_compute_period)).getInfo()["features"]
        observations = self._parse_monthly_features(features, periods, scale_factor=1.0)
        self._warn_if_months_missing(observations, source="surface_water_sar")
        return observations

    def _get_mndwi_surface_water_extent_series(
        self, geometry_geojson: dict, start: date, end: date
    ) -> list[MonthlyValue]:
        """Sentinel-2 MNDWI threshold — the SECONDARY/confirmation method
        (Blueprint v2 Part 4): optically clear, cloud-free imagery only,
        which is exactly why it is *not* the reported number for MVP — a
        monsoon-season month can be entirely cloud-blanked while SAR still
        sees through. Reuses the exact cloud-masking workflow
        `GeeProvider.get_index_time_series()` already uses (join Sentinel-2
        SR to its cloud-probability collection by `system:index`, mask at
        `_gee_common.CLOUD_PROBABILITY_THRESHOLD`), not a re-implementation
        — `_gee_common.py` is the shared source for both the threshold and
        the two collection IDs (ticket M1-005 extended it with the latter
        once a second real consumer of them existed)."""
        region = ee.Geometry(geometry_geojson)
        periods = monthly_periods(start, end)

        sentinel2 = ee.ImageCollection(SENTINEL2_COLLECTION).filterBounds(region)
        cloud_probability = ee.ImageCollection(CLOUD_PROBABILITY_COLLECTION).filterBounds(region)
        joined = ee.ImageCollection(
            ee.Join.saveFirst("cloud_probability").apply(
                primary=sentinel2,
                secondary=cloud_probability,
                condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
            )
        )

        def _mask_clouds_and_compute_mndwi(image: ee.Image) -> ee.Image:
            image = ee.Image(image)
            probability = ee.Image(image.get("cloud_probability")).select("probability")
            clear_mask = probability.lt(CLOUD_PROBABILITY_THRESHOLD)
            return (
                image.updateMask(clear_mask)
                .normalizedDifference([_MNDWI_GREEN_BAND, _MNDWI_SWIR1_BAND])
                .rename("mndwi")
            )

        period_dicts = ee.List(
            [{"start": p_start.isoformat(), "end": p_end.isoformat()} for p_start, p_end in periods]
        )

        def _compute_period(period) -> ee.Feature:
            period = ee.Dictionary(period)
            period_start = ee.Date(period.get("start"))
            period_end = ee.Date(period.get("end"))
            # Gated on the RAW joined collection, before
            # _mask_clouds_and_compute_mndwi runs: .map() over zero images
            # is always safe (the callback — including its own .normalizedDifference()
            # call — is simply never invoked), but if there are zero images
            # to begin with, the mapped-then-.mean() composite has no bands
            # at all, and .gt() below would hit the same class of crash SAR
            # had. Checking size() on the pre-map collection catches that
            # case before _mask_clouds_and_compute_mndwi (and its own
            # .normalizedDifference()) ever runs, not just before .gt().
            month_images = joined.filterDate(period_start, period_end)

            def _compute_water_percent():
                # Same "composite first, reduce second" shape as SAR above
                # and get_et_series(): mean the cloud-masked MNDWI values
                # across the month, then threshold the composite once.
                composite = month_images.map(_mask_clouds_and_compute_mndwi).mean()
                is_water = composite.gt(_MNDWI_WATER_THRESHOLD).rename("is_water")
                stats = is_water.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=region,
                    scale=_SURFACE_WATER_SCALE_METERS,
                    maxPixels=_SURFACE_WATER_MAX_PIXELS,
                )
                # Guarded lookup — see _safe_percent()'s own docstring for
                # why "contains() first" alone isn't sufficient here.
                return self._safe_percent(stats, "is_water")

            return ee.Feature(
                None,
                {
                    "period_start": period_start.format("YYYY-MM-dd"),
                    # Same class of production incident as the SAR method
                    # above, for Sentinel-2 instead of Sentinel-1: a month
                    # with zero joined images makes the composite
                    # band-less, and .gt()/.normalizedDifference() on that
                    # crash the same way .lt() did. Guarded the same way.
                    "value": self._run_if_images_exist(month_images, _compute_water_percent()),
                },
            )

        features = ee.FeatureCollection(period_dicts.map(_compute_period)).getInfo()["features"]
        observations = self._parse_monthly_features(features, periods, scale_factor=1.0)
        self._warn_if_months_missing(observations, source="surface_water_mndwi")
        return observations

    def _get_combined_surface_water_extent_series(
        self, geometry_geojson: dict, start: date, end: date
    ) -> list[MonthlyValue]:
        """SAR PRIMARY, MNDWI SECONDARY CONFIRMATION — Blueprint v2 Part
        4's exact, named methodology. This is NOT a numerically fused or
        averaged estimate: Blueprint v2 documents no blending formula, and
        ticket M1-005 is explicit that none should be invented. The
        returned series is the `.SAR` series, unchanged — SAR is all-
        weather and cloud-independent, so it is the number a program
        officer sees. MNDWI is fetched purely as a same-scene directional
        confirmation signal (Blueprint v2 Part 9's internal-consistency
        check: "do surface-water and MNDWI/SAR agree directionally?"),
        logged as a disagreement rate, never asserted to be zero and
        never used to override or adjust the SAR value.

        KNOWN LIMITATIONS (both apply to the returned SAR series, since
        that's what's actually reported): SAR's fixed VV threshold
        degrades in high-relief terrain (layover/shadow — Part 4/Part 9
        risk #10); sub-0.2-0.3 ha water bodies are below both sensors'
        reliable detection resolution (Part 4). Disagreement between SAR
        and MNDWI for a given month is itself informative — e.g. terrain
        shadow falsely reading as SAR-water where MNDWI (unaffected by
        radar geometry) disagrees — which is exactly why it's logged, not
        discarded.
        """
        sar_series = self.get_surface_water_extent_series(geometry_geojson, start, end, SurfaceWaterMethod.SAR)
        mndwi_series = self.get_surface_water_extent_series(
            geometry_geojson, start, end, SurfaceWaterMethod.MNDWI
        )
        self._log_sar_mndwi_agreement(sar_series, mndwi_series)
        return sar_series

    @staticmethod
    def _log_sar_mndwi_agreement(sar_series: list[MonthlyValue], mndwi_series: list[MonthlyValue]) -> None:
        """Logs how often SAR and MNDWI agree on water-present-or-not for
        the same calendar month, over months where both have a value.
        Never raises and never asserts zero disagreement — some
        disagreement is expected (cloud-affected MNDWI months, terrain-
        affected SAR months) and is itself a QA signal (Blueprint v2 Part
        9), not a bug to fix here."""
        comparable = [
            (sar.value > _WATER_PRESENCE_PERCENT_THRESHOLD, mndwi.value > _WATER_PRESENCE_PERCENT_THRESHOLD)
            for sar, mndwi in zip(sar_series, mndwi_series, strict=True)
            if sar.value is not None and mndwi.value is not None
        ]
        if not comparable:
            logger.info("sar_mndwi_agreement_no_comparable_months", extra={})
            return
        disagreements = sum(1 for sar_present, mndwi_present in comparable if sar_present != mndwi_present)
        logger.info(
            "sar_mndwi_agreement_checked",
            extra={
                "comparable_months": len(comparable),
                "disagreements": disagreements,
                "disagreement_rate": disagreements / len(comparable),
            },
        )

    @staticmethod
    def _run_if_images_exist(collection: ee.ImageCollection, computed_value):
        """Server-side existence guard, used by every monthly-composite
        computation in this file (production incident fix, see the SAR/
        MNDWI call sites' own comments for the exact traceback this
        prevents).

        `.mean()` (or any other reducer) over a genuinely EMPTY
        ImageCollection produces an image with ZERO bands — not a real
        band whose pixels all happen to be masked, which is a different
        and already-safe case (reduceRegion tolerates that fine; see
        get_et_series()). Calling a per-band op — `.lt()`, `.gt()`,
        `.normalizedDifference()`, or anything else that compares/combines
        band counts — directly on a band-less composite raises
        server-side: `Image.lt: If one image has no bands, the other must
        also have no bands. Got 0 and 1.` This is exactly what happened in
        production for a Sentinel-1-empty month.

        `computed_value` is passed in already constructed (`ee.*` method
        calls only build a computation graph client-side; they never
        execute anything by themselves — the earthengine-api's whole
        client/server split), and `ee.Algorithms.If` is a genuine SERVER-SIDE
        conditional: Earth Engine only evaluates whichever branch the
        condition actually selects at `.getInfo()` time, so the risky
        per-band ops inside `computed_value`'s graph are simply never
        executed when `collection` turns out to be empty — the same
        pattern this file's own `stats.contains(...)` guards already use
        for "did reduceRegion produce this key," applied one step earlier,
        to "does this collection have any images at all."
        """
        return ee.Algorithms.If(collection.size().gt(0), computed_value, None)

    @staticmethod
    def _safe_percent(stats: ee.Dictionary, key: str):
        """Null-safe read of a `reduceRegion()` result, converted to a
        0-100 percent (`*100`) — used by both SAR and MNDWI's identical
        "fraction of masked pixels -> percent" step.

        SECOND production finding from the same incident: `stats.contains(key)`
        alone is not a sufficient guard. It correctly detects "the key is
        absent entirely" (reduceRegion's documented behavior for zero
        valid pixels in the region), but a real production run surfaced a
        case where the key is PRESENT with an explicit null value instead
        — `ee.Number(null).multiply(100)` then crashes server-side with
        `Number.multiply: Parameter 'left' is required and may not be
        null.`, the same failure class as `_run_if_images_exist` fixes for
        images, one level down at the scalar/Number level. This checks
        both: the key's presence (so `.get()` itself never raises for a
        genuinely absent key) and, separately, whether the retrieved
        value is itself null, before ever calling `.multiply()` on it.

        `get_et_series()` does not need this: it returns the raw
        `stats.get(...)` value directly with no server-side arithmetic on
        it, so a null value there simply flows through to
        `_parse_monthly_features()` as JSON `null`, which the existing
        client-side `raw_value is not None` check already treats as a
        missing month — safe without this guard.
        """
        value = ee.Algorithms.If(stats.contains(key), stats.get(key), None)
        return ee.Algorithms.If(ee.Algorithms.IsEqual(value, None), None, ee.Number(value).multiply(100))

    @staticmethod
    def _warn_if_months_missing(observations: list[MonthlyValue], *, source: str) -> None:
        """Logs (never raises) whenever a freshly-parsed monthly series
        has at least one month with no usable value — no imagery that
        month, or every pixel in the region masked. Purely an
        operator-visible signal: the caller already treats a `None`
        `MonthlyValue` as a genuinely missing month (WaterBalanceEngine's/
        RechargeStressEngine's own "missing is missing" convention, and
        `_run_if_images_exist` above's whole point is to reach this `None`
        safely instead of raising) — this does not change what gets
        returned, only makes a previously-silent gap visible without
        failing the report job over it.
        """
        missing_months = [obs.period_start.isoformat() for obs in observations if obs.value is None]
        if missing_months:
            logger.warning(
                "gee_hydrology_missing_months",
                extra={"source": source, "missing_month_count": len(missing_months), "missing_months": missing_months},
            )

    @staticmethod
    def _parse_monthly_features(
        features: list[dict], periods: list[tuple[date, date]], *, scale_factor: float = _ET_SCALE_FACTOR
    ) -> list[MonthlyValue]:
        """Converts Earth Engine's raw feature list into `MonthlyValue`
        rows, one per requested period, in the same order as `periods`.
        A month whose `reduceRegion` returned null (no valid retrieval
        anywhere in that month's composite window) becomes
        `MonthlyValue(value=None)` — never omitted from the result list
        and never coerced into a misleading zero, the same "missing is
        missing" convention `GeeProvider._parse_monthly_features()`
        already establishes and both of this class's methods' own
        contracts require.

        `scale_factor` converts a raw `reduceRegion` value into the unit
        the calling method promises: MOD16A2's documented `0.1` for
        `get_et_series()` (the default, preserving this method's
        pre-M1-004 call sites unchanged), or `1.0` (no-op) for
        `get_surface_water_extent_series()`, whose SAR percentage is
        already computed server-side above.
        """
        observations: list[MonthlyValue] = []
        for feature, (period_start, _period_end) in zip(features, periods, strict=True):
            properties = feature["properties"]
            raw_value = properties.get("value")
            value = float(raw_value) * scale_factor if raw_value is not None else None
            observations.append(MonthlyValue(period_start=period_start, value=value))
        return observations
