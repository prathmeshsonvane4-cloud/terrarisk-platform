"""Plain-English methodology explanations for non-technical banking staff
(Page 6, REPORT V2) plus a Python port of the dashboard's Method-tab
constants (Page 7 audit appendix, `FACTOR_DEFINITIONS` and
`ASSUMPTIONS_AND_LIMITATIONS`, previously frontend-only —
`frontend/src/features/report/method-tab.tsx`).

Every explanation here describes the real, already-implemented formula in
`app/services/risk/engine.py` — restated for a lending officer, not
invented or simplified to the point of being wrong. Where engine.py's own
docstring is the authoritative source, this module says so.
"""

from __future__ import annotations

from app.models.enums import RiskFactor

INDEX_EXPLANATIONS: dict[str, str] = {
    "NDVI": (
        "Normalized Difference Vegetation Index — a standard satellite measurement of how green and dense "
        "a crop's canopy is. Healthy, actively growing crops reflect near-infrared light strongly and absorb "
        "red light; NDVI captures that contrast as a single number. TerraRisk never compares a farm's NDVI to "
        "other farms — only to this same farm's own 3-year history, so the comparison is always fair to the "
        "specific soil, crop, and micro-climate of that field."
    ),
    "MNDWI": (
        "Modified Normalized Difference Water Index — detects standing or surface water on and around the "
        "farm (ponds, waterlogged fields, nearby water bodies). Used here as the primary signal for the Water "
        "Availability factor."
    ),
    "NDMI": (
        "Normalized Difference Moisture Index — a crop-moisture signal, distinct from soil moisture, that "
        "reflects how much water content is present in the plant canopy itself. Used as the supporting signal "
        "for Water Availability alongside MNDWI."
    ),
    "VCI": (
        "Vegetation Condition Index (Kogan, 1995) — a published, standard drought index. It places the farm's "
        "current NDVI within its own historical minimum-to-maximum range for the lookback period: 0 means this "
        "is the driest (lowest-vegetation) period this farm has shown in that window, 100 means it is the best. "
        "This is the primary signal behind the Drought Risk factor."
    ),
    "JRC Global Surface Water": (
        "A published historical record (European Commission Joint Research Centre) of how often water has "
        "been detected on this exact land parcel, based on satellite imagery going back to 1984. A high "
        "occurrence percentage means this land has a long history of seasonal or permanent flooding — it is a "
        "historical-record signal, not a live flood alert."
    ),
    "CHIRPS rainfall": (
        "A satellite-and-rain-gauge-blended daily rainfall dataset (UC Santa Barbara Climate Hazards Group), "
        "used both for the farm's actual monthly rainfall and for the 30-year long-term seasonal normal it is "
        "compared against."
    ),
}

CONFIDENCE_EXPLANATION = (
    "Confidence reflects data quality, not risk. It is the share of expected monthly satellite observations "
    "(NDVI, MNDWI, and NDMI, averaged) that were actually usable, out of the total expected across the "
    "lookback window. A month is lost when cloud cover made that month's satellite pass unusable — this is a "
    "routine, expected part of optical satellite monitoring in a monsoon climate, not a system error. A low "
    "confidence score means fewer usable months went into the assessment; it does not mean the farm is "
    "riskier. Rainfall and historical flood data are not affected by cloud cover and are not part of this "
    "calculation."
)

CLOUD_FILTERING_EXPLANATION = (
    "Before any index is calculated, each satellite image is checked for cloud cover over the farm's exact "
    "boundary. Pixels obscured by cloud are excluded rather than guessed at; if an entire month has no usable "
    "cloud-free imagery, that month is left out of the series entirely rather than filled in with an assumed "
    "value. This is why the monthly charts in this report can show fewer than the full number of expected "
    "months, and why confidence is calculated the way it is above."
)

PERCENTILE_EXPLANATION = (
    "A percentile rank answers: 'out of all the months on record for this exact farm, what share were at or "
    "below the current value?' A current NDVI at the 20th percentile means this month's vegetation reading is "
    "as low as, or lower than, only 20% of this farm's own recorded history — i.e. this is a relatively poor "
    "month for this specific field. Percentiles here are always calculated against the farm's own history, "
    "never against other farms or a regional average."
)

QUALITY_CONTROL_EXPLANATION = (
    "Every score in this report is produced by a fixed, published, rule-based calculation — the same formula "
    "runs for every farm, every time, with no manual adjustment and no machine-learning model making an "
    "opaque judgment call. The underlying formulas (VCI, percentile rank, rainfall-normal comparison) are "
    "established remote-sensing methods, not proprietary or invented for this report. Every number shown can "
    "be traced back to a real satellite observation stored against this exact farm boundary."
)

FACTOR_DEFINITIONS: dict[RiskFactor, str] = {
    RiskFactor.VEGETATION_STABILITY: (
        "How this farm's current vegetation health compares to its own three-year Sentinel-2 NDVI history — a "
        "percentile rank, not a comparison to other farms. A low percentile means the current growing season "
        "is markedly worse than this same land has shown before."
    ),
    RiskFactor.WATER_AVAILABILITY: (
        "Surface-water (MNDWI) and crop-moisture (NDMI) index readings compared against this farm's own "
        "historical range, combined with how recent rainfall compares to the long-term seasonal normal."
    ),
    RiskFactor.DROUGHT_RISK: (
        "A Vegetation Condition Index (0 = the driest year observed on this farm, 100 = the best) combined "
        "with how recent rainfall compares to the long-term seasonal normal — the approved SPI-style seasonal "
        "anomaly."
    ),
    RiskFactor.FLOOD_EXPOSURE: (
        "Historical surface-water occurrence on this exact land parcel (JRC Global Surface Water record, "
        "1984-2021) combined with recent rainfall relative to the seasonal normal."
    ),
}

# Verbatim port of ASSUMPTIONS_AND_LIMITATIONS from method-tab.tsx — same
# fixed, honest, versioned text on both the dashboard and the PDF.
ASSUMPTIONS_AND_LIMITATIONS: list[str] = [
    "Monthly compositing can hide events shorter than a month — a brief dry spell inside an otherwise normal "
    "month will not stand out on its own.",
    "Cloud cover reduces how many months are usable for the three optical indices; a low confidence score "
    "reflects data availability, not higher risk.",
    "CHIRPS rainfall data publishes with a lag of several weeks — the most recent month in the window may be "
    "unavailable and is skipped rather than estimated.",
    "The farm boundary is as drawn by the officer; boundary accuracy is the officer's responsibility, not "
    "something this assessment can verify.",
    "This score is decision support for the lending officer. The credit decision remains with the bank.",
]
