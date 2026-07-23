"""REPORT V2 — Farm Intelligence page cartography helpers (north arrow,
scale bar, coordinate label). Pure math + a PIL smoke test; no network.
"""

from __future__ import annotations

from PIL import Image

from app.services.reporting.map_snapshot import (
    _centroid,
    _pick_scale_bar_length_m,
    annotate_cartography,
    web_mercator_meters_per_pixel,
)

_KILLARI_RING = [(76.588, 18.070), (76.593, 18.070), (76.593, 18.0735), (76.588, 18.0735), (76.588, 18.070)]


def test_centroid_is_the_mean_of_ring_vertices():
    lon, lat = _centroid([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    assert lon == 1.0
    assert lat == 1.0


def test_meters_per_pixel_shrinks_as_zoom_increases():
    coarse = web_mercator_meters_per_pixel(latitude=18.07, zoom=10)
    fine = web_mercator_meters_per_pixel(latitude=18.07, zoom=17)
    assert fine < coarse
    assert fine > 0


def test_meters_per_pixel_accounts_for_latitude():
    equator = web_mercator_meters_per_pixel(latitude=0.0, zoom=15)
    high_latitude = web_mercator_meters_per_pixel(latitude=60.0, zoom=15)
    assert high_latitude < equator  # Mercator compresses distance toward the poles


def test_scale_bar_picks_a_round_number_that_fits():
    # ~1 meter/pixel, max 200px available -> should pick a round number <= 200m.
    length = _pick_scale_bar_length_m(meters_per_pixel=1.0, max_bar_px=200.0)
    assert length in (10, 20, 25, 50, 100, 200)
    assert length <= 200


def test_scale_bar_never_exceeds_the_available_pixel_budget():
    for mpp in (0.5, 2.0, 10.0, 50.0, 500.0):
        length_m = _pick_scale_bar_length_m(meters_per_pixel=mpp, max_bar_px=220.0)
        assert length_m / mpp <= 220.0


def test_annotate_cartography_produces_a_valid_image_without_crashing():
    original_bytes = Image.new("RGB", (1200, 700), "#334455").tobytes()
    image = Image.new("RGB", (1200, 700), "#334455")
    annotated = annotate_cartography(image, _KILLARI_RING, meters_per_pixel=2.5)
    assert annotated.size == (1200, 700)
    # A real annotation was drawn, not a no-op — pixel data changed somewhere.
    assert annotated.tobytes() != original_bytes
