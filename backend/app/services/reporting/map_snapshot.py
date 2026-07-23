"""Static satellite snapshot of a farm boundary for the PDF report.

Server-side twin of the dashboard's read-only `ReportMap`: the SAME Esri
World Imagery tile endpoint the frontend renders (config.ts
MAP_TILE_URL), the same white boundary styling (2.5px outline, 12% white
fill), fitted with padding — so the PDF map and the dashboard map are one
visual, not two.

Fetching happens at most once per report: the endpoint caches the
finished PDF, so imagery is only pulled on the first render. On any
network failure this returns None and the PDF renders the boundary
outline on a neutral panel with an honest "imagery unavailable" note —
degraded, never fabricated.
"""

from __future__ import annotations

import io
import logging
import math

import httpx
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
# Verbatim from frontend config.ts — the license requires attribution
# wherever the imagery appears, including print.
TILE_ATTRIBUTION = "Powered by Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"

_TILE_SIZE = 256
_MAX_ZOOM = 17  # matches ReportMap's fitBounds maxZoom
_SNAPSHOT_WIDTH = 1200
_SNAPSHOT_HEIGHT = 700
_PADDING_PX = 80  # breathing room around the boundary, like fitBounds padding


def _to_global_px(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """WGS84 -> global web-mercator pixel coordinates at a zoom level."""
    scale = _TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * scale
    return x, y


def _polygon_ring(geometry: dict) -> list[tuple[float, float]]:
    coordinates = geometry.get("coordinates") or []
    ring = coordinates[0] if coordinates else []
    return [(float(lon), float(lat)) for lon, lat in ring]


def _centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    """Simple polygon centroid (mean of ring vertices) — adequate at farm
    scale for a human-readable coordinate label; not a true area-weighted
    centroid, which would be unwarranted precision here."""
    lons, lats = zip(*ring)
    return sum(lons) / len(lons), sum(lats) / len(lats)


def web_mercator_meters_per_pixel(latitude: float, zoom: int) -> float:
    """Standard Web Mercator ground-resolution formula (the same one every
    slippy-map tile client uses), latitude-corrected since Mercator
    distorts distance away from the equator — real cartographic math, not
    an approximation invented for this report."""
    return 156543.03392 * math.cos(math.radians(latitude)) / (2**zoom)


_NICE_SCALE_STEPS_M = [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000, 20000]


def _pick_scale_bar_length_m(meters_per_pixel: float, max_bar_px: float) -> float:
    """The largest 'nice' round distance whose on-screen bar still fits
    within max_bar_px — standard scale-bar convention (a round number the
    eye can use), not an exact-but-awkward pixel-derived distance."""
    max_m = meters_per_pixel * max_bar_px
    candidates = [m for m in _NICE_SCALE_STEPS_M if m <= max_m]
    return candidates[-1] if candidates else _NICE_SCALE_STEPS_M[0]


def annotate_cartography(image: Image.Image, ring: list[tuple[float, float]], meters_per_pixel: float) -> Image.Image:
    """Draws a north arrow, a real-distance scale bar, and the boundary's
    centroid coordinate label onto an already-composed map image — pure
    cartographic annotation from real geometry, never new/invented data
    (REPORT V2 — Farm Intelligence page). Works identically whether
    `image` came from real stitched tiles or the boundary-only fallback;
    only `meters_per_pixel` differs between the two callers, and mutates
    `image` in place (also returned, for chaining).
    """
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    outline = (30, 41, 59, 255)  # _INK, matching the PDF's ink color

    # North arrow — top-right corner: a filled triangle plus "N", not an
    # imported icon asset (no new binary dependency).
    arrow_cx, arrow_top = width - 55, 24
    draw.polygon(
        [(arrow_cx, arrow_top), (arrow_cx - 12, arrow_top + 34), (arrow_cx + 12, arrow_top + 34)],
        fill=(255, 255, 255, 235),
        outline=outline,
    )
    label_font = ImageFont.load_default(size=15)
    draw.text(
        (arrow_cx, arrow_top + 40), "N", fill=(255, 255, 255, 255), font=label_font,
        anchor="mm", stroke_width=2, stroke_fill=outline,
    )

    # Scale bar — bottom-left corner, a real round distance at this
    # image's actual ground resolution.
    max_bar_px = min(220.0, width * 0.22)
    bar_length_m = _pick_scale_bar_length_m(meters_per_pixel, max_bar_px)
    bar_length_px = bar_length_m / meters_per_pixel
    bar_x0, bar_y = 24.0, height - 34.0
    bar_x1 = bar_x0 + bar_length_px
    for x in (bar_x0, bar_x1):
        draw.line([(x, bar_y - 5), (x, bar_y + 5)], fill=(255, 255, 255, 255), width=3)
    draw.line([(bar_x0, bar_y), (bar_x1, bar_y)], fill=(255, 255, 255, 255), width=3)
    distance_label = f"{bar_length_m:.0f} m" if bar_length_m < 1000 else f"{bar_length_m / 1000:.0f} km"
    draw.text(
        ((bar_x0 + bar_x1) / 2, bar_y - 13), distance_label, fill=(255, 255, 255, 255), font=label_font,
        anchor="mm", stroke_width=2, stroke_fill=outline,
    )

    # Centroid coordinate label — bottom-right corner.
    centroid_lon, centroid_lat = _centroid(ring)
    lat_hemisphere = "N" if centroid_lat >= 0 else "S"
    lon_hemisphere = "E" if centroid_lon >= 0 else "W"
    coordinate_text = f"{abs(centroid_lat):.5f}°{lat_hemisphere}, {abs(centroid_lon):.5f}°{lon_hemisphere}"
    small_font = ImageFont.load_default(size=13)
    draw.text(
        (width - 16, height - 16), coordinate_text, fill=(255, 255, 255, 255), font=small_font,
        anchor="rs", stroke_width=2, stroke_fill=outline,
    )

    return image


def _fit_zoom(ring: list[tuple[float, float]]) -> int:
    """Largest zoom (<= max) at which the padded boundary fits the snapshot."""
    for zoom in range(_MAX_ZOOM, 0, -1):
        xs, ys = zip(*(_to_global_px(lon, lat, zoom) for lon, lat in ring))
        if (max(xs) - min(xs)) <= _SNAPSHOT_WIDTH - 2 * _PADDING_PX and (
            max(ys) - min(ys)
        ) <= _SNAPSHOT_HEIGHT - 2 * _PADDING_PX:
            return zoom
    return 1


def fetch_map_snapshot(geometry: dict) -> bytes | None:
    """Render the farm boundary over stitched satellite tiles; PNG bytes,
    or None when imagery cannot be fetched right now."""
    ring = _polygon_ring(geometry)
    if len(ring) < 3:
        return None

    zoom = _fit_zoom(ring)
    points = [_to_global_px(lon, lat, zoom) for lon, lat in ring]
    xs, ys = zip(*points)
    center_x, center_y = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    origin_x = center_x - _SNAPSHOT_WIDTH / 2.0
    origin_y = center_y - _SNAPSHOT_HEIGHT / 2.0

    first_tile_x = math.floor(origin_x / _TILE_SIZE)
    first_tile_y = math.floor(origin_y / _TILE_SIZE)
    last_tile_x = math.floor((origin_x + _SNAPSHOT_WIDTH) / _TILE_SIZE)
    last_tile_y = math.floor((origin_y + _SNAPSHOT_HEIGHT) / _TILE_SIZE)

    canvas = Image.new("RGB", (_SNAPSHOT_WIDTH, _SNAPSHOT_HEIGHT))
    try:
        with httpx.Client(timeout=10.0, headers={"User-Agent": "TerraRisk/0.1 report-pdf"}) as client:
            max_index = 2**zoom - 1
            for tile_x in range(first_tile_x, last_tile_x + 1):
                for tile_y in range(first_tile_y, last_tile_y + 1):
                    if not (0 <= tile_x <= max_index and 0 <= tile_y <= max_index):
                        continue
                    response = client.get(TILE_URL.format(z=zoom, y=tile_y, x=tile_x))
                    response.raise_for_status()
                    tile = Image.open(io.BytesIO(response.content)).convert("RGB")
                    canvas.paste(
                        tile,
                        (round(tile_x * _TILE_SIZE - origin_x), round(tile_y * _TILE_SIZE - origin_y)),
                    )
    except Exception:
        logger.warning("Map snapshot tile fetch failed; PDF will render without imagery", exc_info=True)
        return None

    # Boundary overlay — same styling as report-map.tsx (white 2.5px line,
    # 12% white fill), drawn on an alpha layer so the fill tints imagery.
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    pixel_ring = [(x - origin_x, y - origin_y) for x, y in points]
    draw.polygon(pixel_ring, fill=(255, 255, 255, 31))
    draw.line(pixel_ring + [pixel_ring[0]], fill=(255, 255, 255, 255), width=4, joint="curve")
    composed = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    # REPORT V2 — Farm Intelligence page: north arrow, scale bar, centroid
    # coordinate label. meters_per_pixel uses the boundary's own centroid
    # latitude (Web Mercator resolution varies with latitude).
    _, centroid_lat = _centroid(ring)
    composed = annotate_cartography(composed, ring, web_mercator_meters_per_pixel(centroid_lat, zoom))

    buffer = io.BytesIO()
    composed.save(buffer, format="PNG")
    return buffer.getvalue()
