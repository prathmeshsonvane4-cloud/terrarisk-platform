"""Registry of every remote-sensing product this platform reads.

One place recording, per product and per band: units, scale factor,
valid range, no-data convention, native resolution, compositing window,
temporal coverage, and known geographic limitations.

WHY A REGISTRY RATHER THAN COMMENTS AT EACH CALL SITE
-----------------------------------------------------
Those comments already exist and they are good ones. They are also
unenforceable, unreachable from a report, and — as this file's own audit
found — capable of being confidently wrong. A registry can be asserted
against at ingestion (`ingestion.py`), rendered into a report's lineage
section, and reviewed as a single artifact by someone who does not read
Python.

EVERY ENTRY CARRIES ITS VERIFICATION STATUS
-------------------------------------------
`verified_against` records where a spec was actually checked, and
`verified_on` when. An entry copied from this codebase's own comments and
never independently confirmed says so. That distinction matters: two of
the defects listed below were found precisely because a code comment
stated a product convention that the catalog does not.

FINDINGS FROM THE 6 SEP 2026 AUDIT — recorded here, not only in a doc.
Outcomes are stated per finding; see `docs/GEE_Product_Audit_2026.md`
for the live measurements behind them.

1. **JRC occurrence is read with the wrong reducer** (HIGH). Google's own
   catalog warns: "The mask value for the occurrence band is equal to
   the band value... so the dataset is double-counting the partial
   occurrence." Two compounding consequences for
   `GeeProvider.get_water_history()`, which calls a plain
   `reduceRegion(ee.Reducer.mean())`:
     a. Never-water pixels are MASKED, not zero — so the mean is taken
        over pixels that have been water at some point, not over the
        polygon. A farm that is 1% permanent canal and 99% dry field
        returns ~100, not ~1.
     b. Reducers are mask-weighted, and here the weight IS the value, so
        the result is sum(x^2)/sum(x) rather than the mean of x — biased
        high again, on top of (a).
   That number is used directly as flood-exposure risk
   (`risk/engine.py`), and at >= 85 it trips the floor rule and forces
   the whole assessment to HIGH. Fix: `.unmask(0)` then
   `ee.Reducer.mean().unweighted()`.
   **FIXED.** Measured before the fix, old -> corrected: Manjara
   reservoir edge 7.58 -> 0.04, a Maski-area square 23.29 -> 0.00,
   Ujani reservoir edge 82.57 -> 35.19.

2. **JRC temporal coverage is misstated** (LOW). `get_water_history()`
   reports `period_end = 1 Jan 2021`; v1.4 runs to **31 Dec 2021**. A
   provenance error, not a numeric one — which is exactly the class of
   error item 5 exists to eliminate. **FIXED.**

3. **MOD16A2 fill masking is slightly loose, and its stated reason is
   wrong** (LOW). The code masks `ET < 32761`, commented as excluding
   "reserved codes above 32761". The catalog says those codes "are
   excluded from Earth Engine assets" already — so that guard is mostly
   redundant. What it does NOT exclude is 32701-32760, which is outside
   the documented valid range (-32767 to 32700). Correct bound is
   `<= 32700`. **FIXED.**

4. **CHIRPS no-data is guarded on the daily path and not on the monthly
   or climatology paths** (MEDIUM, unconfirmed). `get_daily_rainfall_series`
   filters `value >= 0`, commented "Negative values are CHIRPS's own
   no-data convention." `get_rainfall_series` and
   `get_rainfall_climatology` call `.sum()` over the month with no such
   guard. If a no-data pixel is ever present and unmasked, monthly P and
   the 30-year climatology are corrupted while the daily runoff term
   stays clean — two numbers from one product disagreeing by
   construction. The GEE catalog page does not document the no-data
   convention either way.
   **CHECKED, NOT PRESENT.** 1,096 daily images over Latur and Raichur
   (Jun 2023 - Jun 2026): zero negative pixels, fully unmasked. The
   asymmetry is latent, not live, over the deployment area, and no code
   was changed for it. If it ever does appear, `validate_series`'s hard
   range on `rainfall_monthly_mm` fails loudly on the negative total —
   which is the guard that actually matters. Re-check on any new
   geography.

5. **CHIRPS is sampled at 5000 m against a 5566 m native grid** (LOW).
   Not wrong — `scale` is a resampling request, not a resolution claim —
   but it means every rainfall figure is resampled rather than read
   natively, and nothing in the report says so.

6. **No DEM product is read anywhere** (MEDIUM). `resolution_flags`
   advertises `high_relief_terrain` in the ORM docstring and the public
   API schema, and Blueprint v2 Part 4/Part 9 risk #10 require it for
   the SAR terrain caveat. `_derive_resolution_flags()` takes area only
   and can never emit it. The API documents a disclosure the system
   cannot make.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

__all__ = [
    "BandSpec",
    "ProductSpec",
    "Verification",
    "PRODUCTS",
    "spec_for",
]


class Verification(str, Enum):
    """How much weight a spec entry can carry."""

    # Checked against the Earth Engine data catalog page for this exact
    # collection id, on the date recorded.
    CATALOG = "catalog"
    # Taken from this codebase's own comments and NOT independently
    # confirmed. Treat as a hypothesis about the product, not a fact.
    CODE_COMMENT = "code_comment"
    # Known to be incomplete — an open question, recorded rather than
    # guessed at.
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class BandSpec:
    band: str
    units: str
    # Multiply the stored value by this to reach `units`. 1.0 means the
    # stored value is already in those units.
    scale_factor: float = 1.0
    offset: float = 0.0
    valid_range: tuple[float, float] | None = None
    no_data: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ProductSpec:
    collection_id: str
    name: str
    # Native pixel size in metres — the product's own, never the `scale`
    # this codebase happens to request.
    native_resolution_m: float
    temporal_resolution: str
    record_start: date
    # None for an actively-updated collection.
    record_end: date | None
    bands: dict[str, BandSpec]
    compositing: str = ""
    geographic_limitations: str = ""
    verified_against: Verification = Verification.CODE_COMMENT
    verified_on: date | None = None
    source_url: str = ""
    # Open defects only — these surface as WARNINGs through
    # `validate_product_is_audited`. A fixed defect moves to
    # `resolved_defects` so the record survives without crying wolf.
    known_defects: list[str] = field(default_factory=list)
    resolved_defects: list[str] = field(default_factory=list)


_AUDIT_DATE = date(2026, 9, 6)

PRODUCTS: dict[str, ProductSpec] = {
    "MODIS/061/MOD16A2": ProductSpec(
        collection_id="MODIS/061/MOD16A2",
        name="MODIS Terra Net Evapotranspiration 8-Day",
        native_resolution_m=500.0,
        temporal_resolution="8-day",
        record_start=date(2001, 1, 1),
        record_end=None,
        bands={
            "ET": BandSpec(
                band="ET",
                units="mm per 8-day composite",
                scale_factor=0.1,
                valid_range=(-32767.0, 32700.0),
                no_data=(
                    "Fill codes 32761-32767 are excluded from the Earth Engine asset by "
                    "Google. Values 32701-32760 are outside the valid range and are NOT "
                    "excluded — mask at <= 32700, not < 32761."
                ),
                notes=(
                    "CUMULATIVE over the 8-day window, not a rate. The mean of a month's "
                    "composites is mm per 8 days and must be scaled by the number of windows "
                    "in the month to reach a monthly total. Getting this wrong understates "
                    "ET by roughly 4x — the original defect."
                ),
            )
        },
        compositing="Fixed 8-day windows; the last window of each calendar year is 5 or 6 days.",
        geographic_limitations=(
            "Below ~25 ha (5x5 pixels) a catchment is sub-pixel and carries no internal "
            "spatial resolution. FAO WaPOR comparisons show a systematic low bias and "
            "seasonally variable accuracy — safe for trend, not for absolute closure "
            "(Blueprint v2 Part 10, limitation 7)."
        ),
        verified_against=Verification.CATALOG,
        verified_on=_AUDIT_DATE,
        source_url="https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD16A2",
        resolved_defects=[
            "6 Sep 2026: gee_hydrology_provider.py masked at < 32761, letting 32701-32760 "
            "through as valid ET. Now masks at <= 32700.",
        ],
    ),
    "UCSB-CHG/CHIRPS/DAILY": ProductSpec(
        collection_id="UCSB-CHG/CHIRPS/DAILY",
        name="CHIRPS Daily Precipitation",
        native_resolution_m=5566.0,
        temporal_resolution="daily",
        record_start=date(1981, 1, 1),
        record_end=None,
        bands={
            "precipitation": BandSpec(
                band="precipitation",
                units="mm/day",
                scale_factor=1.0,
                valid_range=(0.0, 2000.0),
                no_data=(
                    "Not documented in the catalog. Checked directly 6 Sep 2026: no negative "
                    "and no masked pixels across 1,096 days over Latur/Raichur. The daily path "
                    "filters negatives; the monthly and climatology paths do not, which is "
                    "harmless where none occur. Re-check on any new geography."
                ),
                notes="Gauge-blended satellite estimate, not a gauge observation.",
            )
        },
        compositing="Daily images; monthly totals in this codebase are a server-side .sum().",
        geographic_limitations=(
            "One pixel is ~3,000 ha, so any smaller catchment receives a regional value with "
            "no internal resolution (`rainfall_sub_pixel` flag). Known bias in complex and "
            "orographic terrain; not gauge-corrected by default. Publishes with a multi-week "
            "lag, and the most recent month is provisional and subject to substantial upward "
            "revision."
        ),
        verified_against=Verification.CATALOG,
        verified_on=_AUDIT_DATE,
        source_url="https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHG_CHIRPS_DAILY",
        known_defects=[
            "Sampled at scale=5000 m against a 5566 m native grid; every value is resampled "
            "and nothing in the report discloses it.",
        ],
        resolved_defects=[
            "6 Sep 2026: negative/no-data guard present on the daily path only. Checked "
            "against 1,096 days over the deployment area — no such pixels exist, so no fix "
            "was applied. Latent, re-check per new geography.",
        ],
    ),
    "JRC/GSW1_4/GlobalSurfaceWater": ProductSpec(
        collection_id="JRC/GSW1_4/GlobalSurfaceWater",
        name="JRC Global Surface Water Mapping Layers v1.4",
        native_resolution_m=30.0,
        temporal_resolution="static summary over the full record",
        record_start=date(1984, 3, 16),
        record_end=date(2021, 12, 31),
        bands={
            "occurrence": BandSpec(
                band="occurrence",
                units="percent of observations in which water was present",
                scale_factor=1.0,
                valid_range=(0.0, 100.0),
                no_data=(
                    "Pixels where water was NEVER detected are masked, not zero. A plain "
                    "reduceRegion(mean) therefore averages only over pixels that have been "
                    "water at some point — never over the polygon."
                ),
                notes=(
                    "The band is its own mask: a pixel with occurrence 30 carries mask weight "
                    "30. Earth Engine reducers are mask-weighted, so mean() returns "
                    "sum(x^2)/sum(x), biased high. Correct read is .unmask(0) followed by "
                    "ee.Reducer.mean().unweighted()."
                ),
            )
        },
        compositing="4,716,475 Landsat 5/7/8 scenes, Mar 1984 - Dec 2021.",
        geographic_limitations=(
            "Measures water PRESENCE frequency, not flood proneness. A farm beside a "
            "perennial canal scores high without being flood-exposed — a semantic limit no "
            "amount of correct arithmetic fixes."
        ),
        verified_against=Verification.CATALOG,
        verified_on=_AUDIT_DATE,
        source_url="https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater",
        known_defects=[
            "Semantic, not arithmetic: occurrence measures water presence, not flood "
            "proneness, and is used directly as flood-exposure risk.",
        ],
        resolved_defects=[
            "6 Sep 2026: get_water_history() used a plain mask-weighted mean over a masked "
            "band, biased high twice over and feeding a floor rule at >= 85. Now "
            ".unmask(0) + mean().unweighted(). Measured old -> new: 7.58 -> 0.04, "
            "23.29 -> 0.00, 82.57 -> 35.19.",
            "6 Sep 2026: period_end reported as 1 Jan 2021; corrected to 31 Dec 2021.",
        ],
    ),
    "COPERNICUS/S2_SR_HARMONIZED": ProductSpec(
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        name="Sentinel-2 MSI Level-2A Surface Reflectance, harmonized",
        native_resolution_m=10.0,
        temporal_resolution="~5-day revisit (two satellites)",
        record_start=date(2017, 3, 28),
        record_end=None,
        bands={
            band: BandSpec(
                band=band,
                units="surface reflectance (dimensionless)",
                scale_factor=1e-4,
                valid_range=(0.0, 10000.0),
                no_data="0 outside the swath; cloud masking is external (s2cloudless).",
                notes=(
                    "Normalised-difference indices are invariant to a shared linear scale, so "
                    "the 1e-4 factor cancels and is never applied in this codebase. That is "
                    "correct ONLY because the harmonized collection removes the -1000 "
                    "reflectance offset introduced for scenes after 25 Jan 2022; an offset "
                    "does NOT cancel. Reading the non-harmonized collection would silently "
                    "break every index across the 2022 boundary."
                ),
            )
            for band in ("B3", "B4", "B8", "B11")
        },
        compositing="Per-scene; this codebase composites by monthly mean after cloud masking.",
        geographic_limitations=(
            "B11 is natively 20 m and is resampled to 10 m by the index math, so MNDWI and "
            "NDMI carry 20 m effective resolution despite being computed at 10 m. Over "
            "Maharashtra, July and August are routinely a total optical loss to monsoon cloud."
        ),
        verified_against=Verification.CATALOG,
        verified_on=_AUDIT_DATE,
        source_url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED",
    ),
    "COPERNICUS/S2_CLOUD_PROBABILITY": ProductSpec(
        collection_id="COPERNICUS/S2_CLOUD_PROBABILITY",
        name="Sentinel-2 cloud probability (s2cloudless)",
        native_resolution_m=10.0,
        temporal_resolution="one image per Sentinel-2 scene",
        record_start=date(2015, 6, 27),
        record_end=None,
        bands={
            "probability": BandSpec(
                band="probability",
                units="percent probability of cloud",
                scale_factor=1.0,
                valid_range=(0.0, 100.0),
                no_data="Joined to S2 by system:index; a scene with no match is dropped by the join.",
                notes=(
                    "Masked at < 20 for Service 1 indices and < 40 in the ML feature "
                    "extraction. Two thresholds against one product; neither is calibrated."
                ),
            )
        },
        verified_against=Verification.CATALOG,
        verified_on=_AUDIT_DATE,
        source_url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_CLOUD_PROBABILITY",
    ),
    "COPERNICUS/S1_GRD": ProductSpec(
        collection_id="COPERNICUS/S1_GRD",
        name="Sentinel-1 SAR GRD",
        native_resolution_m=10.0,
        temporal_resolution="~6-12 day revisit depending on latitude and orbit",
        record_start=date(2014, 10, 3),
        record_end=None,
        bands={
            polarisation: BandSpec(
                band=polarisation,
                units="dB (decibels, logarithmic)",
                scale_factor=1.0,
                valid_range=(-50.0, 10.0),
                no_data="Masked outside the swath.",
                notes=(
                    "LOGARITHMIC. Averaging dB yields the geometric mean of power, which is "
                    "always <= the arithmetic mean and biases dark — pushing borderline "
                    "pixels across a fixed water threshold. Both this codebase's SAR paths "
                    "convert to linear power before averaging and back afterwards."
                ),
            )
            for polarisation in ("VV", "VH")
        },
        compositing="Per-pass; composited monthly in linear power, not dB.",
        geographic_limitations=(
            "Fixed -15 dB water threshold is a literature default, not locally calibrated, "
            "and degrades in high-relief terrain through layover and shadow — the terrain "
            "flag meant to disclose this is specified but not implemented."
        ),
        verified_against=Verification.CATALOG,
        verified_on=_AUDIT_DATE,
        source_url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD",
    ),
}


def spec_for(collection_id: str) -> ProductSpec | None:
    """The spec for a collection, or None if this product is not in the
    registry.

    A None here is itself a finding: it means a product is being read
    that nobody has audited. Callers should surface that rather than
    proceed silently.
    """
    return PRODUCTS.get(collection_id)
