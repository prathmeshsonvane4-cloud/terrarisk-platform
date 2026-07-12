"""Plain-language report prose for the PDF — a deliberate Python mirror of
the dashboard's `narrative.ts` and `drivers.ts` templates.

Blueprint §08's one-artifact rule: dashboard and PDF are two views of one
payload and must never disagree. The prose templates therefore exist twice
(TypeScript for the dashboard, here for the PDF) but are pinned to each
other by tests asserting the IDENTICAL output strings on both sides
(`report-text.test.ts` <-> `test_report_text.py`). Change one, and the
other side's test tells you to change it too.

Every sentence is a fixed template over the engine's persisted outputs and
raw_inputs — an arithmetic fact, never an invented cause. A missing raw
input shortens the sentence; it never becomes a guess.
"""

from __future__ import annotations

import math

from app.models.enums import RiskBand, RiskFactor
from app.schemas.report import FactorScoreResponse, ReportResponse

FACTOR_LABELS: dict[RiskFactor, str] = {
    RiskFactor.VEGETATION_STABILITY: "Vegetation stability",
    RiskFactor.WATER_AVAILABILITY: "Water availability",
    RiskFactor.DROUGHT_RISK: "Drought risk",
    RiskFactor.FLOOD_EXPOSURE: "Flood exposure",
}

RISK_BAND_LABELS: dict[RiskBand, str] = {
    RiskBand.LOW: "Low risk",
    RiskBand.MODERATE: "Moderate risk",
    RiskBand.HIGH: "High risk",
    RiskBand.VERY_HIGH: "Very high risk",
}

_BAND_PHRASE: dict[RiskBand, str] = {
    RiskBand.LOW: "low",
    RiskBand.MODERATE: "moderate",
    RiskBand.HIGH: "high",
    RiskBand.VERY_HIGH: "very high",
}

# Blueprint §07 methodology ordering, identical to factor-order.ts.
FACTOR_ORDER: list[RiskFactor] = [
    RiskFactor.DROUGHT_RISK,
    RiskFactor.WATER_AVAILABILITY,
    RiskFactor.VEGETATION_STABILITY,
    RiskFactor.FLOOD_EXPOSURE,
]


def js_round(value: float) -> int:
    """JavaScript Math.round (half away from zero for non-negatives) —
    Python's banker's rounding would let PDF and dashboard disagree on
    every x.5 value."""
    return int(math.floor(value + 0.5))


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _percent_of_normal(ratio: float) -> str:
    return f"{js_round(ratio * 100)}% of the seasonal normal"


def ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def factor_driver_text(factor: FactorScoreResponse) -> str:
    raw = factor.raw_inputs

    if factor.factor == RiskFactor.VEGETATION_STABILITY:
        percentile = _as_number(raw.get("ndvi_percentile"))
        current = _as_number(raw.get("current_ndvi"))
        if percentile is None or current is None:
            return "Not enough usable satellite history for a vegetation comparison — a neutral score was applied."
        return (
            f"Current NDVI {current:.2f} sits at the {ordinal(js_round(percentile))} percentile "
            "of this farm's own 3-year range."
        )

    if factor.factor == RiskFactor.WATER_AVAILABILITY:
        parts: list[str] = []
        mndwi = _as_number(raw.get("mndwi_current"))
        ndmi = _as_number(raw.get("ndmi_current"))
        ratio = _as_number(raw.get("rainfall_ratio_to_normal"))
        if mndwi is not None and ndmi is not None:
            parts.append(
                f"Surface-water (MNDWI {mndwi:.2f}) and crop-moisture (NDMI {ndmi:.2f}) indices "
                "compared against this farm's own range"
            )
        if ratio is not None:
            parts.append(f"recent rainfall at {_percent_of_normal(ratio)}")
        if not parts:
            return "Not enough usable data for the water sub-signals — a neutral score was applied."
        return f"{'; '.join(parts)}."

    if factor.factor == RiskFactor.DROUGHT_RISK:
        parts = []
        vci = _as_number(raw.get("vci"))
        ratio = _as_number(raw.get("rainfall_ratio_to_normal"))
        if vci is not None:
            parts.append(f"Vegetation Condition Index at {js_round(vci)} (0 = driest year observed, 100 = best)")
        if ratio is not None:
            parts.append(f"recent rainfall at {_percent_of_normal(ratio)}")
        if not parts:
            return "Not enough usable data for the drought sub-signals — a neutral score was applied."
        return f"{'; '.join(parts)}."

    # flood_exposure
    parts = []
    jrc = _as_number(raw.get("jrc_water_occurrence_percent"))
    ratio = _as_number(raw.get("rainfall_ratio_to_normal"))
    if jrc is not None:
        parts.append(
            f"Historical surface-water occurrence on this land is {jrc:.1f}% (JRC satellite record, 1984–2021)"
        )
    if ratio is not None:
        parts.append(f"recent rainfall at {_percent_of_normal(ratio)}")
    if not parts:
        return "Not enough usable data for the flood sub-signals — a neutral score was applied."
    return f"{'; '.join(parts)}."


def _rainfall_clause(factors: list[FactorScoreResponse]) -> str | None:
    drought = next((f for f in factors if f.factor == RiskFactor.DROUGHT_RISK), None)
    ratio = _as_number(drought.raw_inputs.get("rainfall_ratio_to_normal")) if drought else None
    if ratio is None:
        return None
    percent = js_round(ratio * 100)
    if percent < 95:
        return f"recent seasonal rainfall was {percent}% of the long-term normal"
    if percent > 105:
        return f"recent seasonal rainfall was {percent}% of the long-term normal (above average)"
    return f"recent seasonal rainfall was close to the long-term normal ({percent}%)"


def report_narrative(report: ReportResponse) -> str:
    sorted_factors = sorted(report.factors, key=lambda f: f.value, reverse=True)
    highest = sorted_factors[0] if sorted_factors else None
    lowest = sorted_factors[-1] if sorted_factors else None

    sentences = [
        f"This farm shows {_BAND_PHRASE[report.overall_band]} overall climate risk "
        f"(score {js_round(report.overall_score)}/100)."
    ]

    if highest and lowest and highest.factor != lowest.factor:
        clauses = [
            f"The highest-scoring factor is {FACTOR_LABELS[highest.factor].lower()} "
            f"at {js_round(highest.value)}/100"
        ]
        rainfall = _rainfall_clause(report.factors)
        if rainfall:
            clauses.append(rainfall)
        sentences.append(f"{'; '.join(clauses)}.")
        sentences.append(f"{FACTOR_LABELS[lowest.factor]} scores lowest at {js_round(lowest.value)}/100.")

    sentences.append(
        f"Assessment confidence is {js_round(report.confidence)}%, "
        "reflecting how many usable satellite observations were available."
    )

    return " ".join(sentences)


def format_area(hectares: float) -> str:
    """Mirror of format.ts — hectares (system of record) with acres
    alongside, because Marathwada officers think in acres."""
    acres = hectares * 2.471054
    return f"{hectares:.2f} ha ({acres:.1f} acres)"
