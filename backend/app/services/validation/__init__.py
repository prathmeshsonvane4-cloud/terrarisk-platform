"""Physical validation harness.

Checks that computed outputs are physically possible and plausible for
where the catchment actually is — a question distinct from, and not
answered by, the rest of the test suite's "does the code match its
specification" coverage.

The distinction is not academic. Six specification defects, including a
MOD16A2 evapotranspiration term wrong by roughly a factor of four,
passed the whole suite green: every test verified that the pipeline
executed as written, and the wrong numbers stayed plausible enough not
to look broken. Blueprint v2 Part 11 named the missing layer
("internal consistency: does the water balance close within a plausible
residual range?") and it was never built. This package is that layer.

Read `water_balance.py`'s module docstring before adding a check — in
particular for why a literal closure test against this engine is
vacuous, and what is provided instead.
"""

from app.services.validation.cross_product import relative_difference, validate_cross_product_agreement
from app.services.validation.ingestion import (
    DELIVERED_SERIES,
    SeriesExpectation,
    validate_product_is_audited,
    validate_series,
)
from app.services.validation.models import Severity, ValidationFinding, ValidationReport
from app.services.validation.products import PRODUCTS, BandSpec, ProductSpec, Verification, spec_for
from app.services.validation.water_balance import validate_water_balance
from app.services.validation.zones import (
    AgroClimaticZone,
    ZoneRanges,
    classify_zone_by_rainfall,
    classify_zone_from_normals,
    ranges_for,
)

__all__ = [
    "AgroClimaticZone",
    "BandSpec",
    "DELIVERED_SERIES",
    "PRODUCTS",
    "ProductSpec",
    "Severity",
    "SeriesExpectation",
    "ValidationFinding",
    "ValidationReport",
    "Verification",
    "ZoneRanges",
    "classify_zone_by_rainfall",
    "classify_zone_from_normals",
    "ranges_for",
    "relative_difference",
    "spec_for",
    "validate_cross_product_agreement",
    "validate_product_is_audited",
    "validate_series",
    "validate_water_balance",
]
