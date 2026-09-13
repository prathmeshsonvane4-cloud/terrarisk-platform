"""Unit and scale-factor assertions at the point of ingestion.

`water_balance.py` checks the answer. This checks the inputs, one series
at a time, as soon as a provider hands them back — before they are
summed, differenced, or turned into a band.

WHY BOTH, WHEN THE DOWNSTREAM CHECK WOULD CATCH IT ANYWAY
---------------------------------------------------------
Because "the balance is implausible" does not say which term is wrong,
and in a residual-based balance every error looks like several errors.
A series-level check names the culprit: `et_monthly_mm` values with a
median of 9 mm is a specific, actionable statement about one provider
method. "Storage change is 39% of rainfall" is not.

It also catches the two error classes a downstream ratio check
structurally cannot:

- **A whole series wrong by a constant factor.** A forgotten 0.1 scale
  factor or a missed 8-day-to-monthly conversion moves every value
  together. Ratios between DIFFERENT products still shift, so the water
  balance does catch this one — but only after the fact, and only if the
  error is large enough to leave the envelope.
- **A single absurd value inside an otherwise sane series.** A 4,000 mm
  day of rainfall, or an NDVI of 12, averages away into a plausible
  monthly total and is invisible downstream. Here it is a finding.

WHAT THE BOUNDS ARE
-------------------
Hard physical or definitional limits, deliberately wide. An NDVI outside
[-1, 1] is impossible by the arithmetic of a normalised difference. A
negative rainfall depth is not a measurement. These are not the
zone-tuned envelopes in `zones.py` and must not drift into being them —
a value inside these bounds is not thereby plausible, only possible.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.validation.models import Severity, ValidationFinding, ValidationReport
from app.services.validation.products import spec_for

__all__ = [
    "SeriesExpectation",
    "DELIVERED_SERIES",
    "validate_series",
    "validate_product_is_audited",
]

# How many out-of-range values to name individually before summarising.
# A whole series wrong by a scale factor would otherwise emit one finding
# per month and bury everything else in the report.
_MAX_ITEMISED = 3


@dataclass(frozen=True)
class SeriesExpectation:
    """What a provider method promises to deliver, in the units of its
    own interface contract.

    `hard_range` is possibility, not plausibility — see the module
    docstring. `typical_median` is a soft check on the series' central
    tendency, and it is the one that catches a uniform scale error;
    None disables it for series where no honest central expectation
    exists.
    """

    name: str
    units: str
    hard_range: tuple[float, float]
    typical_median: tuple[float, float] | None = None
    source: str = ""
    median_note: str = ""


DELIVERED_SERIES: dict[str, SeriesExpectation] = {
    "et_monthly_mm": SeriesExpectation(
        name="et_monthly_mm",
        units="mm per calendar month",
        # A month cannot lose more than ~15 mm/day even in the most
        # extreme advective conditions; negative monthly ET at catchment
        # scale is not a real signal.
        hard_range=(0.0, 450.0),
        typical_median=(15.0, 200.0),
        source="HydrologyDataProvider.get_et_series contract; MOD16A2 spec",
        median_note=(
            "A median below ~15 mm/month across a full year is the signature of a missing "
            "unit conversion, not a dry catchment: it is the 8-day composite value being "
            "reported as a monthly total, or the 0.1 scale factor applied twice. This is "
            "the exact shape of the original 4x ET defect."
        ),
    ),
    "rainfall_monthly_mm": SeriesExpectation(
        name="rainfall_monthly_mm",
        units="mm per calendar month",
        hard_range=(0.0, 3000.0),
        typical_median=None,
        source="SatelliteDataProvider.get_rainfall_series contract; CHIRPS spec",
        median_note="No median expectation: a legitimate dry-season month is 0 mm.",
    ),
    "rainfall_daily_mm": SeriesExpectation(
        name="rainfall_daily_mm",
        units="mm per day",
        # Cherrapunji's daily record is ~1,560 mm; CHIRPS is a ~5.5 km
        # gridded estimate and will never approach it, but the bound is
        # set above any real value rather than at a comfortable one.
        hard_range=(0.0, 1600.0),
        typical_median=None,
        source="SatelliteDataProvider.get_daily_rainfall_series contract; CHIRPS spec",
    ),
    "surface_water_percent": SeriesExpectation(
        name="surface_water_percent",
        units="percent of catchment area",
        hard_range=(0.0, 100.0),
        typical_median=None,
        source="HydrologyDataProvider.get_surface_water_extent_series contract",
    ),
    "jrc_occurrence_percent": SeriesExpectation(
        name="jrc_occurrence_percent",
        units="percent of observations with water present",
        hard_range=(0.0, 100.0),
        typical_median=None,
        source="JRC GSW v1.4 occurrence band",
    ),
    **{
        index: SeriesExpectation(
            name=index,
            units="dimensionless normalised difference",
            # Algebraically bounded: (a-b)/(a+b) for non-negative a, b.
            hard_range=(-1.0, 1.0),
            typical_median=None,
            source="Definition of a normalised difference index",
        )
        for index in ("ndvi", "mndwi", "ndmi")
    },
}


def validate_series(
    series_key: str, values: list[float | None], *, subject: str | None = None
) -> ValidationReport:
    """Check one delivered series against its interface contract.

    `None` entries are skipped, not treated as zero — a month with no
    usable observation is missing, and this module does not get to
    reinterpret that. They are counted, so a series that is mostly
    absent is visible as such.
    """
    subject = subject or series_key
    expectation = DELIVERED_SERIES.get(series_key)
    if expectation is None:
        return ValidationReport(
            subject=subject,
            checks_run=0,
            checks_skipped=1,
            findings=[
                ValidationFinding(
                    check="series_is_known",
                    severity=Severity.WARNING,
                    subject=series_key,
                    message=(
                        f"No ingestion expectation is registered for {series_key!r}, so its "
                        "values were not checked at all. A series nobody has specified is a "
                        "series nobody has audited."
                    ),
                    expected="an entry in DELIVERED_SERIES",
                )
            ],
        )

    observed = [v for v in values if v is not None]
    missing = len(values) - len(observed)
    findings: list[ValidationFinding] = []

    if not observed:
        return ValidationReport(
            subject=subject,
            checks_run=0,
            checks_skipped=2,
            findings=[
                ValidationFinding(
                    check="series_has_values",
                    severity=Severity.INFO,
                    subject=series_key,
                    message=(
                        f"{series_key} contains no usable values ({missing} missing). "
                        "Range and median checks were skipped."
                    ),
                    expected="at least one non-null value",
                )
            ],
        )

    findings.extend(_check_hard_range(expectation, observed))
    findings.extend(_check_median(expectation, observed))

    return ValidationReport(
        subject=subject,
        findings=findings,
        checks_run=2 if expectation.typical_median else 1,
        checks_skipped=0 if expectation.typical_median else 1,
    )


def _check_hard_range(expectation: SeriesExpectation, observed: list[float]) -> list[ValidationFinding]:
    low, high = expectation.hard_range
    offenders = [v for v in observed if v < low or v > high]
    if not offenders:
        return []
    shown = ", ".join(f"{v:.3g}" for v in offenders[:_MAX_ITEMISED])
    more = f" and {len(offenders) - _MAX_ITEMISED} more" if len(offenders) > _MAX_ITEMISED else ""
    return [
        ValidationFinding(
            check="series_within_hard_range",
            severity=Severity.ERROR,
            subject=expectation.name,
            observed=offenders[0],
            message=(
                f"{len(offenders)} of {len(observed)} values in {expectation.name} fall outside "
                f"the possible range for {expectation.units}: {shown}{more}. This is a unit, "
                "scale-factor, or no-data-handling error at ingestion, not a measurement."
            ),
            expected=f"{low:g} to {high:g} {expectation.units}",
            source=expectation.source,
        )
    ]


def _check_median(expectation: SeriesExpectation, observed: list[float]) -> list[ValidationFinding]:
    """A whole series shifted by a constant factor moves its median and
    leaves its shape intact — which is why the median, not the extremes,
    is what catches a scale error."""
    if expectation.typical_median is None:
        return []
    low, high = expectation.typical_median
    ordered = sorted(observed)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    if low <= median <= high:
        return []
    direction = "below" if median < low else "above"
    return [
        ValidationFinding(
            check="series_median_plausible",
            severity=Severity.WARNING,
            subject=expectation.name,
            observed=median,
            message=(
                f"Median {expectation.name} is {median:.1f} {expectation.units}, {direction} the "
                f"typical {low:g}-{high:g} range. {expectation.median_note}"
            ),
            expected=f"median {low:g}-{high:g} {expectation.units}",
            source=expectation.source,
        )
    ]


def validate_product_is_audited(collection_id: str) -> ValidationReport:
    """Flag reading a product that is not in the registry.

    Cheap, and it is the check that would have caught this platform
    quietly acquiring a seventh data source with nobody having written
    down its units.
    """
    spec = spec_for(collection_id)
    if spec is None:
        return ValidationReport(
            subject=collection_id,
            checks_run=1,
            findings=[
                ValidationFinding(
                    check="product_is_audited",
                    severity=Severity.WARNING,
                    subject=collection_id,
                    message=(
                        f"{collection_id} is being read but has no entry in the product registry. "
                        "Its units, scale factor, valid range and no-data convention are "
                        "unrecorded, so nothing downstream can assert against them."
                    ),
                    expected="an entry in validation/products.py",
                )
            ],
        )
    findings = [
        ValidationFinding(
            check="product_has_known_defects",
            severity=Severity.WARNING,
            subject=collection_id,
            message=f"{spec.name}: {defect}",
            expected="no open defects against this product",
            source=spec.source_url,
        )
        for defect in spec.known_defects
    ]
    return ValidationReport(subject=collection_id, findings=findings, checks_run=1 + len(findings))
