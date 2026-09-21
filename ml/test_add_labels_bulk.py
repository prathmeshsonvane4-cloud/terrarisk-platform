"""Parser tests for the bulk label loader.

Every case here is a mistake that would otherwise reach the training set
silently: a swapped coordinate, a field entered twice, a sugarcane label
with no type, a crop name nobody validated.
"""

from __future__ import annotations

import pytest

from add_labels_bulk import (
    DUPLICATE_DISTANCE_M,
    Defaults,
    distance_m,
    fix_order,
    nearest_village,
    parse_line,
    parse_pairs,
    squares_overlap,
)

SHERA = "18.5527, 76.4970"


def test_reads_a_plain_point_line():
    row = parse_line(f"{SHERA} | Shera | sugarcane | plant | 2025-12-20 | owner |", 1)
    assert row.label == 1
    assert row.cane_type == "plant"
    assert row.village == "Shera"
    assert row.source == "owner"
    # A point becomes a closed square: five positions, first == last.
    assert len(row.ring) == 5 and row.ring[0] == row.ring[-1]


def test_accepts_the_shapes_a_phone_produces():
    assert parse_pairs("18.5527, 76.4970") == [(18.5527, 76.4970)]
    assert parse_pairs("18.5527,76.4970") == [(18.5527, 76.4970)]
    assert parse_pairs("18.5527° N, 76.4970° E") == [(18.5527, 76.4970)]


def test_reads_google_maps_degrees_minutes_seconds():
    """What Google Maps copies from a dropped pin. 18°33'09.8"N is
    18 + 33/60 + 9.8/3600."""
    (lat, lon), = parse_pairs("18°33'09.8\"N 76°29'49.3\"E")
    assert lat == pytest.approx(18.552722, abs=1e-6)
    assert lon == pytest.approx(76.497028, abs=1e-6)


def test_dms_written_longitude_first_is_still_read_correctly():
    """The hemisphere letter says which axis each value is, so order
    cannot be got wrong the way it can in decimal degrees."""
    (lat, lon), = parse_pairs("76°29'49.3\"E 18°33'09.8\"N")
    assert lat == pytest.approx(18.552722, abs=1e-6)
    assert lon == pytest.approx(76.497028, abs=1e-6)


def test_dms_without_seconds_is_accepted():
    (lat, lon), = parse_pairs("18°33'N 76°29'E")
    assert lat == pytest.approx(18.55, abs=1e-6)
    assert lon == pytest.approx(76.483333, abs=1e-6)


def test_southern_and_western_hemispheres_are_negative():
    (lat, lon), = parse_pairs("18°33'09.8\"S 76°29'49.3\"W")
    assert lat < 0 and lon < 0


def test_dms_with_two_latitudes_is_rejected():
    with pytest.raises(ValueError, match="same axis"):
        parse_pairs("18°33'09.8\"N 19°29'49.3\"N")


def test_dms_line_end_to_end():
    row = parse_line("18°33'09.8\"N 76°29'49.3\"E | Shera | sugarcane | plant | | owner |", 1)
    assert row.label == 1
    assert row.centre[0] == pytest.approx(18.552722, abs=1e-5)


def test_dms_corners_separated_by_semicolons():
    line = (
        "18°33'00\"N 76°29'42\"E; 18°33'02\"N 76°29'45\"E; 18°32'59\"N 76°29'46\"E"
        " | Shera | sugarcane | ratoon | | field |"
    )
    row = parse_line(line, 1)
    assert len(row.ring) == 4  # three corners, closed


def test_swapped_latitude_and_longitude_is_corrected():
    """76 is not a latitude in Maharashtra. Correcting it silently would
    be worse, so parse_line prints what it did — here we check the fix."""
    assert fix_order(76.4970, 18.5527) == (18.5527, 76.4970, True)
    # Ambiguous pairs are left exactly as given.
    assert fix_order(18.5527, 76.4970) == (18.5527, 76.4970, False)


def test_coordinate_outside_latur_is_rejected():
    with pytest.raises(ValueError, match="outside Latur"):
        parse_line("28.6139, 77.2090 | Delhi | sugarcane | plant | | |", 1)


def test_sugarcane_without_its_type_is_rejected():
    with pytest.raises(ValueError, match="plant"):
        parse_line(f"{SHERA} | Shera | sugarcane | | | |", 1)


def test_cane_type_on_a_non_cane_field_is_rejected():
    with pytest.raises(ValueError, match="only applies"):
        parse_line(f"{SHERA} | Shera | soybean | ratoon | | |", 1)


def test_unknown_crop_is_treated_as_not_sugarcane():
    row = parse_line(f"{SHERA} | Shera | tur | | | |", 1)
    assert row.label == 0


def test_local_names_for_sugarcane_are_recognised():
    for word in ("Sugarcane", "cane", "us", "ऊस"):
        assert parse_line(f"{SHERA} | Shera | {word} | ratoon | | |", 1).label == 1


def test_blank_crop_is_rejected_rather_than_assumed():
    with pytest.raises(ValueError, match="crop is required"):
        parse_line(f"{SHERA} | Shera |  | | | |", 1)


def test_village_is_required_because_it_forms_the_validation_folds():
    with pytest.raises(ValueError, match="village is required"):
        parse_line(f"{SHERA} |  | soybean | | | |", 1)


def test_four_corners_are_used_as_the_boundary():
    line = (
        "18.5502,76.4951; 18.5504,76.4958; 18.5499,76.4959; 18.5497,76.4952"
        " | Shera | sugarcane | ratoon | | field |"
    )
    row = parse_line(line, 1)
    assert len(row.ring) == 5  # closed
    assert row.centre[0] == pytest.approx(18.55005, abs=1e-4)


def test_two_points_are_rejected_as_a_line_not_a_field():
    with pytest.raises(ValueError, match="not a field"):
        parse_line("18.5502,76.4951; 18.5504,76.4958 | Shera | soybean | | | |", 1)


def test_radius_column_sets_the_square_size():
    small = parse_line(f"{SHERA} | Shera | soybean | | | | 15", 1)
    big = parse_line(f"{SHERA} | Shera | soybean | | | | 50", 1)
    small_side = distance_m((small.ring[0][1], small.ring[0][0]), (small.ring[1][1], small.ring[1][0]))
    big_side = distance_m((big.ring[0][1], big.ring[0][0]), (big.ring[1][1], big.ring[1][0]))
    assert small_side == pytest.approx(30, abs=2)
    assert big_side == pytest.approx(100, abs=3)


def test_absurd_radius_is_rejected():
    with pytest.raises(ValueError, match="out of range"):
        parse_line(f"{SHERA} | Shera | soybean | | | | 900", 1)


def test_unknown_evidence_source_is_rejected():
    with pytest.raises(ValueError, match="source"):
        parse_line(f"{SHERA} | Shera | soybean | | | guessed |", 1)


def test_distance_between_two_pins_in_the_same_field_is_below_the_duplicate_threshold():
    """The real case: the same field pinned twice on two visits. About
    20 m apart, well inside the threshold that treats them as one."""
    assert distance_m((18.5527, 76.4970), (18.55285, 76.49712)) < DUPLICATE_DISTANCE_M
    # Two genuinely different fields, ~200 m apart, are not merged.
    assert distance_m((18.5527, 76.4970), (18.5545, 76.4970)) > DUPLICATE_DISTANCE_M


def test_missing_columns_are_reported_clearly():
    with pytest.raises(ValueError, match="crop is required"):
        parse_line("18.5527, 76.4970 | Shera", 1)


def test_batch_defaults_fill_blank_columns():
    """A day's batch is usually all one kind — 'all sugarcane, planted
    December 2025' — so it is stated once instead of on every line."""
    defaults = Defaults(village="Shera", crop="sugarcane", cane_type="plant", planted="2025-12", source="field")
    row = parse_line("18.552714, 76.497026", 1, defaults)
    assert (row.village, row.crop, row.label, row.cane_type, row.planted, row.source) == (
        "Shera",
        "sugarcane",
        1,
        "plant",
        "2025-12",
        "field",
    )


def test_a_line_overrides_the_batch_default():
    defaults = Defaults(village="Shera", crop="sugarcane", cane_type="plant")
    row = parse_line("18.552714, 76.497026 | Kumbhari | soybean", 1, defaults)
    assert row.village == "Kumbhari" and row.label == 0 and row.cane_type == ""


def test_village_may_be_blank_only_when_it_will_be_looked_up():
    defaults = Defaults(crop="sugarcane", cane_type="plant")
    with pytest.raises(ValueError, match="village is required"):
        parse_line("18.552714, 76.497026", 1, defaults)
    lookup = Defaults(crop="sugarcane", cane_type="plant", auto_village=True)
    assert parse_line("18.552714, 76.497026", 1, lookup).village == ""


def test_nearest_village_is_found_with_its_distance():
    villages = [
        {"name": "Shera", "taluka": "Renapur", "lat": 18.5583, "lon": 76.4936},
        {"name": "Kumbhari", "taluka": "Renapur", "lat": 18.5400, "lon": 76.5100},
    ]
    name, taluka, metres = nearest_village((18.552714, 76.497026), villages)
    assert (name, taluka) == ("Shera", "Renapur")
    assert 400 < metres < 1200


def test_no_village_guess_is_made_from_far_away():
    villages = [{"name": "Shera", "taluka": "Renapur", "lat": 18.5583, "lon": 76.4936}]
    assert nearest_village((18.9000, 77.2000), villages) is None


def test_overlap_depends_on_the_radius_not_a_fixed_distance():
    """Two real plots here can sit 35 m apart. At the default 25 m radius
    their squares overlap and the model would read shared pixels; at 12 m
    they do not, so the second field is usable rather than discarded."""
    a, b = (18.552714, 76.497026), (18.552686, 76.497343)
    assert distance_m(a, b) == pytest.approx(33, abs=4)
    assert squares_overlap(a, 25.0, b, 25.0)
    assert not squares_overlap(a, 12.0, b, 12.0)
