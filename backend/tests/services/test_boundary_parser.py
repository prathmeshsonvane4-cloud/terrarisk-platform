"""Tests for boundary_parser.py (ticket M4-002) — GeoJSON, KML, and
zipped Shapefile parsing, all converging on GeoJSONMultiPolygon. No
database, no network — every fixture is constructed in-memory.
"""

from __future__ import annotations

import io
import json
import zipfile

import pyproj
import pytest
import shapefile

from app.services.boundary_parser import BoundaryParseError, parse_boundary_file

_SQUARE = [[76.0, 18.0], [76.0, 18.01], [76.01, 18.01], [76.01, 18.0], [76.0, 18.0]]
_SQUARE_2 = [[77.0, 19.0], [77.0, 19.01], [77.01, 19.01], [77.01, 19.0], [77.0, 19.0]]
_HOLE = [[76.002, 18.002], [76.008, 18.002], [76.008, 18.008], [76.002, 18.008], [76.002, 18.002]]


# =====================================================================
# GeoJSON
# =====================================================================


class TestGeoJson:
    def test_valid_bare_polygon_is_parsed(self):
        content = json.dumps({"type": "Polygon", "coordinates": [_SQUARE]}).encode("utf-8")
        result = parse_boundary_file("boundary.geojson", content)
        assert result.to_shapely().is_valid

    def test_polygon_is_converted_to_a_single_part_multipolygon(self):
        content = json.dumps({"type": "Polygon", "coordinates": [_SQUARE]}).encode("utf-8")
        result = parse_boundary_file("boundary.geojson", content)
        assert len(result.coordinates) == 1  # one polygon part
        assert len(result.coordinates[0]) == 1  # one ring (exterior only, no holes)
        assert result.coordinates[0][0] == [tuple(p) for p in _SQUARE]

    def test_valid_multipolygon_is_parsed_with_all_parts_preserved(self):
        content = json.dumps({"type": "MultiPolygon", "coordinates": [[_SQUARE], [_SQUARE_2]]}).encode("utf-8")
        result = parse_boundary_file("boundary.geojson", content)
        assert len(result.coordinates) == 2

    def test_polygon_hole_is_preserved(self):
        content = json.dumps({"type": "Polygon", "coordinates": [_SQUARE, _HOLE]}).encode("utf-8")
        result = parse_boundary_file("boundary.geojson", content)
        assert len(result.coordinates[0]) == 2  # exterior + hole ring

    def test_feature_wrapping_a_polygon_is_parsed(self):
        content = json.dumps(
            {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [_SQUARE]}}
        ).encode("utf-8")
        result = parse_boundary_file("boundary.json", content)
        assert result.to_shapely().is_valid

    def test_feature_collection_combines_every_features_geometry(self):
        content = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [_SQUARE]}},
                    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [_SQUARE_2]}},
                ],
            }
        ).encode("utf-8")
        result = parse_boundary_file("boundary.geojson", content)
        assert len(result.coordinates) == 2

    def test_json_extension_is_also_accepted(self):
        content = json.dumps({"type": "Polygon", "coordinates": [_SQUARE]}).encode("utf-8")
        result = parse_boundary_file("boundary.json", content)
        assert result.to_shapely().is_valid

    def test_malformed_json_is_rejected(self):
        with pytest.raises(BoundaryParseError, match="not valid JSON"):
            parse_boundary_file("boundary.geojson", b"{not valid json")

    def test_non_object_top_level_is_rejected(self):
        with pytest.raises(BoundaryParseError, match="must be an object"):
            parse_boundary_file("boundary.geojson", b"[1, 2, 3]")

    def test_unsupported_geometry_type_is_rejected(self):
        content = json.dumps({"type": "Point", "coordinates": [76.0, 18.0]}).encode("utf-8")
        with pytest.raises(BoundaryParseError, match="Unsupported GeoJSON type"):
            parse_boundary_file("boundary.geojson", content)

    def test_geometry_that_fails_schema_validation_is_rejected_descriptively(self):
        """A self-intersecting bowtie — valid GeoJSON structure, invalid
        geometry — must be rejected by GeoJSONMultiPolygon's own
        validation, surfaced as a descriptive BoundaryParseError."""
        bowtie = [[76.0, 18.0], [76.01, 18.01], [76.01, 18.0], [76.0, 18.01], [76.0, 18.0]]
        content = json.dumps({"type": "Polygon", "coordinates": [bowtie]}).encode("utf-8")
        with pytest.raises(BoundaryParseError, match="failed validation"):
            parse_boundary_file("boundary.geojson", content)


# =====================================================================
# KML
# =====================================================================


def _kml(*polygons_xml: str) -> bytes:
    body = "".join(polygons_xml)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      {body}
    </Placemark>
  </Document>
</kml>""".encode("utf-8")


def _kml_ring_text(ring: list[list[float]]) -> str:
    return " ".join(f"{lon},{lat},0" for lon, lat in ring)


def _kml_polygon(exterior: list[list[float]], holes: list[list[list[float]]] | None = None) -> str:
    inner = "".join(
        f"<innerBoundaryIs><LinearRing><coordinates>{_kml_ring_text(h)}</coordinates></LinearRing></innerBoundaryIs>"
        for h in (holes or [])
    )
    return (
        "<Polygon>"
        f"<outerBoundaryIs><LinearRing><coordinates>{_kml_ring_text(exterior)}</coordinates></LinearRing></outerBoundaryIs>"
        f"{inner}"
        "</Polygon>"
    )


class TestKml:
    def test_valid_single_polygon_is_parsed(self):
        content = _kml(_kml_polygon(_SQUARE))
        result = parse_boundary_file("boundary.kml", content)
        assert result.to_shapely().is_valid
        assert len(result.coordinates) == 1

    def test_hole_is_preserved(self):
        content = _kml(_kml_polygon(_SQUARE, holes=[_HOLE]))
        result = parse_boundary_file("boundary.kml", content)
        assert len(result.coordinates[0]) == 2

    def test_multiple_polygons_are_combined(self):
        content = _kml(_kml_polygon(_SQUARE), _kml_polygon(_SQUARE_2))
        result = parse_boundary_file("boundary.kml", content)
        assert len(result.coordinates) == 2

    def test_altitude_component_is_ignored(self):
        """KML coordinates are lon,lat,altitude — the altitude must not
        break parsing or leak into the resulting 2D geometry."""
        content = _kml(_kml_polygon(_SQUARE))
        result = parse_boundary_file("boundary.kml", content)
        assert all(len(point) == 2 for point in result.coordinates[0][0])

    def test_malformed_xml_is_rejected(self):
        with pytest.raises(BoundaryParseError, match="not valid XML"):
            parse_boundary_file("boundary.kml", b"<kml><unclosed>")

    def test_no_polygon_element_is_rejected(self):
        content = b'<?xml version="1.0"?><kml><Document><Placemark/></Document></kml>'
        with pytest.raises(BoundaryParseError, match="no <Polygon> geometry"):
            parse_boundary_file("boundary.kml", content)

    def test_polygon_missing_outer_boundary_is_rejected(self):
        content = _kml("<Polygon></Polygon>")
        with pytest.raises(BoundaryParseError, match="outerBoundaryIs"):
            parse_boundary_file("boundary.kml", content)

    def test_malformed_coordinate_tuple_is_rejected(self):
        content = _kml("<Polygon><outerBoundaryIs><LinearRing><coordinates>not-a-coordinate</coordinates></LinearRing></outerBoundaryIs></Polygon>")
        with pytest.raises(BoundaryParseError, match="Malformed KML coordinate"):
            parse_boundary_file("boundary.kml", content)


# =====================================================================
# Shapefile
# =====================================================================


def _write_shapefile_zip(polygons: list[list[list[float]]], *, prj_wkt: str | None) -> bytes:
    shp_buf, shx_buf, dbf_buf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp_buf, shx=shx_buf, dbf=dbf_buf, shapeType=shapefile.POLYGON)
    writer.field("name", "C")
    for ring in polygons:
        writer.poly([ring])  # clockwise exterior ring, per Shapefile's own orientation convention
        writer.record("test")
    writer.close()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as archive:
        archive.writestr("boundary.shp", shp_buf.getvalue())
        archive.writestr("boundary.shx", shx_buf.getvalue())
        archive.writestr("boundary.dbf", dbf_buf.getvalue())
        if prj_wkt is not None:
            archive.writestr("boundary.prj", prj_wkt)
    return zip_buf.getvalue()


_WGS84_WKT = pyproj.CRS.from_epsg(4326).to_wkt()
_UTM43N_WKT = pyproj.CRS.from_epsg(32643).to_wkt()


class TestShapefile:
    def test_valid_wgs84_shapefile_is_parsed(self):
        content = _write_shapefile_zip([_SQUARE], prj_wkt=_WGS84_WKT)
        result = parse_boundary_file("boundary.zip", content)
        assert result.to_shapely().is_valid
        assert len(result.coordinates) == 1

    def test_multiple_shapes_are_combined_into_one_multipolygon(self):
        content = _write_shapefile_zip([_SQUARE, _SQUARE_2], prj_wkt=_WGS84_WKT)
        result = parse_boundary_file("boundary.zip", content)
        assert len(result.coordinates) == 2

    def test_crs_transformation_reprojects_a_projected_shapefile_to_wgs84(self):
        """The exact UTM 43N (EPSG:32643) coordinates for a small square
        near 75.0E/18.0N, computed independently via pyproj.Transformer
        (not by calling the parser) — a real cross-check, not a
        tautology: if boundary_parser.py's reprojection had the wrong
        source/target order, or skipped transformation entirely, this
        test would fail, since a raw UTM easting/northing (~500000,
        ~1990000) is nowhere near a valid WGS84 longitude/latitude."""
        utm_square = [
            [500000.0000, 1990185.5421],
            [500000.0000, 1991291.9038],
            [501058.5665, 1991291.9324],
            [501058.6262, 1990185.5707],
            [500000.0000, 1990185.5421],
        ]
        content = _write_shapefile_zip([utm_square], prj_wkt=_UTM43N_WKT)

        result = parse_boundary_file("boundary.zip", content)

        ring = result.coordinates[0][0]
        for longitude, latitude in ring:
            assert 74.9 <= longitude <= 75.1
            assert 17.9 <= latitude <= 18.1
        # The specific corner (75.0, 18.0) must reproject back closely.
        assert ring[0][0] == pytest.approx(75.0, abs=1e-4)
        assert ring[0][1] == pytest.approx(18.0, abs=1e-4)

    def test_already_wgs84_shapefile_is_not_transformed(self):
        content = _write_shapefile_zip([_SQUARE], prj_wkt=_WGS84_WKT)
        result = parse_boundary_file("boundary.zip", content)
        ring = result.coordinates[0][0]
        assert ring[0] == (76.0, 18.0)

    def test_missing_prj_is_rejected_not_assumed_wgs84(self):
        content = _write_shapefile_zip([_SQUARE], prj_wkt=None)
        with pytest.raises(BoundaryParseError, match=r"\.prj"):
            parse_boundary_file("boundary.zip", content)

    def test_missing_shx_component_is_rejected(self):
        shp_buf, _shx_buf, dbf_buf = io.BytesIO(), io.BytesIO(), io.BytesIO()
        writer = shapefile.Writer(shp=shp_buf, shx=io.BytesIO(), dbf=dbf_buf, shapeType=shapefile.POLYGON)
        writer.field("name", "C")
        writer.poly([_SQUARE])
        writer.record("test")
        writer.close()

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as archive:
            archive.writestr("boundary.shp", shp_buf.getvalue())
            archive.writestr("boundary.dbf", dbf_buf.getvalue())
            archive.writestr("boundary.prj", _WGS84_WKT)

        with pytest.raises(BoundaryParseError, match="missing the required Shapefile component '.shx'"):
            parse_boundary_file("boundary.zip", zip_buf.getvalue())

    def test_not_a_zip_file_is_rejected(self):
        with pytest.raises(BoundaryParseError, match="not a valid zip archive"):
            parse_boundary_file("boundary.zip", b"this is not a zip file")

    def test_unparseable_prj_content_is_rejected(self):
        content = _write_shapefile_zip([_SQUARE], prj_wkt="not a real WKT coordinate system")
        with pytest.raises(BoundaryParseError, match="Could not parse"):
            parse_boundary_file("boundary.zip", content)


# =====================================================================
# Cross-format
# =====================================================================


class TestEmptyFileAndUnsupportedFormat:
    @pytest.mark.parametrize("filename", ["boundary.geojson", "boundary.kml", "boundary.zip", "boundary.json"])
    def test_empty_content_is_rejected_for_every_supported_extension(self, filename):
        with pytest.raises(BoundaryParseError, match="empty"):
            parse_boundary_file(filename, b"")

    @pytest.mark.parametrize("filename", ["boundary.txt", "boundary.pdf", "boundary.gpx", "boundary"])
    def test_unsupported_extensions_are_rejected(self, filename):
        with pytest.raises(BoundaryParseError, match="Unsupported file format"):
            parse_boundary_file(filename, b"some content")

    def test_error_message_names_the_supported_formats(self):
        with pytest.raises(BoundaryParseError, match=r"\.geojson.*\.json.*\.kml.*\.zip"):
            parse_boundary_file("boundary.txt", b"some content")
