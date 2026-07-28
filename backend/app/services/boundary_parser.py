"""Catchment boundary file parsing — GeoJSON, KML, and zipped Shapefile
(ticket M4-002), all converging on the same validated
`GeoJSONMultiPolygon` shape `CatchmentUploadRequest` expects. This is
the concrete implementation of Blueprint v2 D2's "one validation
boundary, two ways in": whether a catchment boundary was hand-drawn or
uploaded, both paths must end up validated through the identical
`GeoJSONMultiPolygon` schema — this module's job is only to get an
uploaded file INTO that shape; `GeoJSONMultiPolygon` itself (ticket
M4-001) still does every geometry-validity check (ring closure, vertex
count, self-intersection, zero area, coordinate range).

Deliberately placed at `app/services/boundary_parser.py`, not
`app/services/hydrology/boundary_parser.py` (the location the original
Implementation Plan sketch used): parsing an uploaded boundary file is a
generic catchment-creation concern, not a hydrology-domain one — nothing
in this module has any hydrology dependency, and nothing about it is
specific to Water Intelligence's own engines.

FORMAT SUPPORT AND WHY EACH ONE NEEDS WHAT IT NEEDS:
- **GeoJSON** (.geojson/.json): stdlib `json` only — `shapely` (already
  a dependency) is not even needed here, since this module hands raw
  coordinate structures to `GeoJSONMultiPolygon`, which does its own
  Shapely-based validation. GeoJSON is WGS84-only by RFC 7946, so no CRS
  transformation is ever needed for this format.
- **KML** (.kml): stdlib `xml.etree.ElementTree` only. KML coordinates
  are WGS84 lon/lat/optional-altitude BY THE OGC KML SPECIFICATION
  ITSELF — KML has no CRS concept to normalize at all, unlike Shapefile.
- **Shapefile** (.zip containing .shp/.shx/.dbf[/.prj]): `pyshp` (pure
  Python, no GDAL) for reading the shape geometry, `pyproj` (wraps PROJ,
  no GDAL either) for genuine CRS reprojection when the shapefile's own
  `.prj` sidecar declares something other than EPSG:4326. Both are
  deliberately NOT fiona/geopandas, which would pull in a full GDAL
  dependency this project has consistently avoided (docs/DECISIONS.md).
  **A missing `.prj` is rejected, not assumed to be WGS84** — silently
  guessing a shapefile's coordinate system is exactly the kind of
  unverified assumption this project's discipline exists to prevent;
  the caller must supply the sidecar or re-export already in WGS84.

Explicitly out of scope, per this ticket's own instructions: no
database access, no API route, no provider, no engine. This module is a
pure function from file bytes to a validated `GeoJSONMultiPolygon` (or a
raised, descriptive `BoundaryParseError`) — nothing else.
"""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
import zipfile

import pyproj
import shapefile
from pydantic import ValidationError

from app.schemas.catchment import GeoJSONMultiPolygon

_Ring = list[tuple[float, float]]
_PolygonRings = list[_Ring]
_MultiPolygonCoordinates = list[_PolygonRings]

_SUPPORTED_EXTENSIONS = (".geojson", ".json", ".kml", ".zip")


class BoundaryParseError(ValueError):
    """Raised for any problem parsing an uploaded boundary file — an
    unsupported format, malformed file content, or geometry that fails
    `GeoJSONMultiPolygon`'s own validation. Always carries a descriptive,
    caller-facing message (never a bare library exception), per this
    ticket's "return descriptive errors" requirement.
    """


def parse_boundary_file(filename: str, content: bytes) -> GeoJSONMultiPolygon:
    """Parse an uploaded boundary file into a validated
    `GeoJSONMultiPolygon`. Dispatches on `filename`'s extension —
    `.geojson`/`.json`, `.kml`, or `.zip` (a zipped Shapefile). Raises
    `BoundaryParseError` for an unsupported extension, an empty file,
    malformed file content, or geometry that fails validation.
    """
    if not content:
        raise BoundaryParseError("Uploaded file is empty")

    extension = _extension(filename)
    if extension in (".geojson", ".json"):
        coordinates = _parse_geojson(content)
    elif extension == ".kml":
        coordinates = _parse_kml(content)
    elif extension == ".zip":
        coordinates = _parse_shapefile_zip(content)
    else:
        raise BoundaryParseError(
            f"Unsupported file format '{extension or filename}' — supported formats: "
            f"{', '.join(_SUPPORTED_EXTENSIONS)}"
        )

    if not coordinates:
        raise BoundaryParseError("No polygon geometry found in the uploaded file")

    try:
        return GeoJSONMultiPolygon.model_validate({"type": "MultiPolygon", "coordinates": coordinates})
    except ValidationError as exc:
        raise BoundaryParseError(f"Parsed geometry failed validation: {exc}") from exc


def _extension(filename: str) -> str:
    return f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""


# =====================================================================
# GeoJSON
# =====================================================================


def _parse_geojson(content: bytes) -> _MultiPolygonCoordinates:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BoundaryParseError(f"GeoJSON file is not valid UTF-8: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BoundaryParseError(f"GeoJSON file is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise BoundaryParseError("GeoJSON file's top-level value must be an object")

    geometries = _extract_geojson_geometries(data)
    polygons: _MultiPolygonCoordinates = []
    for geometry in geometries:
        polygons.extend(_geojson_geometry_to_polygons(geometry))
    return polygons


def _extract_geojson_geometries(data: dict) -> list[dict]:
    """A real-world upload may be a bare Geometry, a Feature, or a
    FeatureCollection — all three are accepted. A FeatureCollection with
    more than one feature has every feature's polygon geometry combined
    into a single MultiPolygon (one catchment boundary, possibly
    authored as several separate parts in the source file) — the same
    "combine, don't reject" approach used for a multi-shape Shapefile
    below, for consistency between the two formats.
    """
    geojson_type = data.get("type")
    if geojson_type == "FeatureCollection":
        return [f["geometry"] for f in data.get("features", []) if f.get("geometry")]
    if geojson_type == "Feature":
        geometry = data.get("geometry")
        return [geometry] if geometry else []
    if geojson_type in ("Polygon", "MultiPolygon"):
        return [data]
    raise BoundaryParseError(f"Unsupported GeoJSON type '{geojson_type}'")


def _geojson_geometry_to_polygons(geometry: dict) -> _MultiPolygonCoordinates:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        return [coordinates]
    if geometry_type == "MultiPolygon":
        return coordinates
    raise BoundaryParseError(
        f"Unsupported GeoJSON geometry type '{geometry_type}' — only Polygon/MultiPolygon are supported"
    )


# =====================================================================
# KML
# =====================================================================


def _parse_kml(content: bytes) -> _MultiPolygonCoordinates:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise BoundaryParseError(f"KML file is not valid XML: {exc}") from exc

    # `{*}Polygon`: a wildcard-namespace match (Python 3.8+ ElementTree) —
    # KML files declare a namespace (commonly
    # http://www.opengis.net/kml/2.2, but versions vary), and matching
    # any namespace is more robust than hardcoding one specific URI.
    polygon_elements = root.findall(".//{*}Polygon")
    if not polygon_elements:
        raise BoundaryParseError("KML file contains no <Polygon> geometry")

    return [_kml_polygon_to_rings(element) for element in polygon_elements]


def _kml_polygon_to_rings(polygon_element: ET.Element) -> _PolygonRings:
    outer = polygon_element.find("./{*}outerBoundaryIs/{*}LinearRing/{*}coordinates")
    if outer is None or not (outer.text or "").strip():
        raise BoundaryParseError("KML <Polygon> is missing its <outerBoundaryIs> coordinates")

    rings: _PolygonRings = [_parse_kml_coordinate_text(outer.text)]
    for inner in polygon_element.findall("./{*}innerBoundaryIs/{*}LinearRing/{*}coordinates"):
        if inner.text and inner.text.strip():
            rings.append(_parse_kml_coordinate_text(inner.text))
    return rings


def _parse_kml_coordinate_text(text: str) -> _Ring:
    """KML coordinates are whitespace-separated "lon,lat[,altitude]"
    tuples (OGC KML spec) — altitude, if present, is ignored; this
    parser only produces the 2D lon/lat boundary a catchment needs."""
    ring: _Ring = []
    for tuple_str in text.split():
        parts = tuple_str.split(",")
        if len(parts) < 2:
            raise BoundaryParseError(f"Malformed KML coordinate tuple: '{tuple_str}'")
        try:
            longitude, latitude = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise BoundaryParseError(f"Malformed KML coordinate tuple: '{tuple_str}'") from exc
        ring.append((longitude, latitude))
    return ring


# =====================================================================
# Shapefile (zipped)
# =====================================================================

_WGS84 = pyproj.CRS.from_epsg(4326)


def _parse_shapefile_zip(content: bytes) -> _MultiPolygonCoordinates:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise BoundaryParseError(f"Uploaded file is not a valid zip archive: {exc}") from exc

    members_by_extension = _index_shapefile_members(archive)
    for required in (".shp", ".shx", ".dbf"):
        if required not in members_by_extension:
            raise BoundaryParseError(f"Zip archive is missing the required Shapefile component '{required}'")

    try:
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(members_by_extension[".shp"])),
            shx=io.BytesIO(archive.read(members_by_extension[".shx"])),
            dbf=io.BytesIO(archive.read(members_by_extension[".dbf"])),
        )
    except shapefile.ShapefileException as exc:
        raise BoundaryParseError(f"Could not read Shapefile: {exc}") from exc

    transformer = _build_transformer_from_prj(archive, members_by_extension)

    polygons: _MultiPolygonCoordinates = []
    for shape_record in reader.shapes():
        polygons.extend(_shapefile_shape_to_polygons(shape_record, transformer))
    return polygons


def _index_shapefile_members(archive: zipfile.ZipFile) -> dict[str, str]:
    index: dict[str, str] = {}
    for name in archive.namelist():
        extension = _extension(name)
        if extension in (".shp", ".shx", ".dbf", ".prj") and extension not in index:
            index[extension] = name
    return index


def _build_transformer_from_prj(
    archive: zipfile.ZipFile, members_by_extension: dict[str, str]
) -> pyproj.Transformer | None:
    """Returns a Transformer to EPSG:4326 if the shapefile's declared
    CRS is something else, or None if it's already WGS84 (no
    transformation needed). Deliberately raises, rather than assuming
    WGS84, when no .prj sidecar is present — see module docstring."""
    if ".prj" not in members_by_extension:
        raise BoundaryParseError(
            "Zip archive has no .prj file — the Shapefile's coordinate reference system could not be "
            "determined, and this parser will not guess it. Include the .prj sidecar, or re-export "
            "already reprojected to WGS84 (EPSG:4326)."
        )

    prj_wkt = archive.read(members_by_extension[".prj"]).decode("utf-8", errors="replace")
    try:
        source_crs = pyproj.CRS.from_wkt(prj_wkt)
    except pyproj.exceptions.CRSError as exc:
        raise BoundaryParseError(f"Could not parse the Shapefile's .prj coordinate system: {exc}") from exc

    if source_crs.equals(_WGS84):
        return None
    return pyproj.Transformer.from_crs(source_crs, _WGS84, always_xy=True)


def _shapefile_shape_to_polygons(shape_record, transformer: pyproj.Transformer | None) -> _MultiPolygonCoordinates:
    # __geo_interface__ (pyshp's own GeoJSON-shaped view of a shape)
    # already resolves Shapefile's ring-orientation convention
    # (clockwise = exterior, counter-clockwise = hole) into proper
    # GeoJSON exterior/interior ring structure — reused here rather than
    # reimplementing that convention by hand.
    geo = shape_record.__geo_interface__
    geometry_type = geo.get("type")
    if geometry_type == "Polygon":
        raw_polygons = [geo["coordinates"]]
    elif geometry_type == "MultiPolygon":
        raw_polygons = geo["coordinates"]
    else:
        raise BoundaryParseError(
            f"Unsupported Shapefile geometry type '{geometry_type}' — only Polygon/MultiPolygon are supported"
        )

    return [[_normalize_and_reproject_ring(ring, transformer) for ring in rings] for rings in raw_polygons]


def _normalize_and_reproject_ring(ring, transformer: pyproj.Transformer | None) -> _Ring:
    # PolygonZ/PolygonM shapes carry a 3rd/4th value per point — only x/y
    # are ever meaningful for a 2D catchment boundary, so every point is
    # normalized to a plain (x, y) float pair regardless of shape type.
    points = [(float(point[0]), float(point[1])) for point in ring]
    if transformer is None:
        return points
    return [tuple(transformer.transform(x, y)) for x, y in points]
