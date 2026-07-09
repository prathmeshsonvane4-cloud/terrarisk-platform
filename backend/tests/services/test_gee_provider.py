"""Integration smoke test against real Google Earth Engine — the M0
Definition of Done requires proving the adapter can fetch a real value for
one known polygon. Skips cleanly wherever GEE_PROJECT_ID /
GEE_SERVICE_ACCOUNT_JSON_PATH aren't configured (this environment, CI
without secrets) rather than failing the suite — run it locally once the
GCP walkthrough in docs/DECISIONS.md is complete.
"""

import os
from datetime import date

import pytest

from app.services.satellite.provider import SatelliteIndex

_requires_gee_credentials = pytest.mark.skipif(
    not (os.environ.get("GEE_PROJECT_ID") and os.environ.get("GEE_SERVICE_ACCOUNT_JSON_PATH")),
    reason="GEE credentials not configured — see docs/DECISIONS.md setup walkthrough",
)

# A ~1km bounding box over Latur district, Maharashtra — real cropland, used
# only to prove connectivity end-to-end, not for any product-facing report.
_SAMPLE_POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[76.45, 18.40], [76.46, 18.40], [76.46, 18.41], [76.45, 18.41], [76.45, 18.40]]],
}


@_requires_gee_credentials
def test_ndvi_time_series_returns_a_real_value():
    from app.services.satellite.gee_provider import GeeProvider

    provider = GeeProvider()
    observations = provider.get_index_time_series(
        _SAMPLE_POLYGON_GEOJSON, SatelliteIndex.NDVI, date(2025, 1, 1), date(2025, 3, 1)
    )

    assert len(observations) == 1
    assert -1.0 <= observations[0].value <= 1.0


@_requires_gee_credentials
def test_water_history_returns_a_real_value():
    from app.services.satellite.gee_provider import GeeProvider

    provider = GeeProvider()
    summary = provider.get_water_history(_SAMPLE_POLYGON_GEOJSON)

    assert 0.0 <= summary.occurrence_percent <= 100.0


def test_sar_backscatter_is_deliberately_unimplemented():
    """Not skipped by the credentials guard — this proves the deferred-SAR
    seam itself, which needs no live GEE connection."""
    from app.services.satellite.gee_provider import GeeProvider

    with pytest.raises(NotImplementedError, match="deferred post-MVP"):
        GeeProvider.get_sar_backscatter_series(
            object.__new__(GeeProvider), _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 3, 1)
        )
