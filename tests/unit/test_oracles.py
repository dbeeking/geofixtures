"""Oracle tests against hand-worked values."""

from __future__ import annotations

import math

import numpy as np
import pytest

from geofixtures.oracles.analytic import (
    point_segment_distance,
    rectangle_area,
    rectangle_overlap,
    rectangle_ring,
    ring_area,
    utm_forward,
)
from geofixtures.oracles.classification import classification_scores
from geofixtures.oracles.data_integrity import canonical_json, semantic_feature_hash, sha256_file
from geofixtures.oracles.geometry import (
    multipart_remainder,
    point_in_holed_rectangle,
    polsby_popper,
    rectangle_compactness,
    rectangle_relations,
    stadium_area,
)


def test_ring_area_of_unit_square():
    assert ring_area([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]) == 1.0


def test_ring_area_of_right_triangle():
    assert abs(ring_area([[0, 0], [4, 0], [0, 3], [0, 0]])) == 6.0


def test_bowtie_signed_area_cancels():
    assert ring_area([[0, 0], [4, 4], [4, 0], [0, 4], [0, 0]]) == 0.0


def test_rectangle_overlap_matches_catalog_example():
    overlap = rectangle_overlap((0, 0, 5, 4), (3, 2, 8, 6))
    assert overlap == (3, 2, 5, 4)
    assert rectangle_area(overlap) == 4


def test_disjoint_rectangles_have_no_overlap():
    assert rectangle_overlap((0, 0, 1, 1), (2, 2, 3, 3)) is None


def test_rectangle_ring_closes():
    ring = rectangle_ring((0, 0, 2, 3))
    assert ring[0] == ring[-1]
    assert abs(ring_area(ring)) == 6


@pytest.mark.parametrize(("point", "expected"), [((3, 4), 4), ((13, 4), 5), ((-6, 8), 10), ((5, 0), 0)])
def test_point_segment_distance(point, expected):
    assert point_segment_distance(point, (0, 0), (10, 0)) == pytest.approx(expected)


def test_point_distance_to_zero_length_segment():
    assert point_segment_distance((3, 4), (0, 0), (0, 0)) == 5


def test_utm_on_central_meridian_at_equator():
    easting, northing = utm_forward(-111.0, 0.0, 12)
    assert easting == pytest.approx(500000.0, abs=1e-6)
    assert northing == pytest.approx(0.0, abs=1e-6)


def test_utm_scale_at_central_meridian():
    # One degree of latitude near the equator is about 110574 m, times k0 = 0.9996.
    _, north = utm_forward(-111.0, 1.0, 12)
    assert north == pytest.approx(110574.4 * 0.9996, abs=2.0)


def test_utm_mirrors_across_central_meridian():
    west = utm_forward(-112.0, 34.0, 12)
    east = utm_forward(-110.0, 34.0, 12)
    assert west[0] - 500000.0 == pytest.approx(500000.0 - east[0], abs=1e-6)
    assert west[1] == pytest.approx(east[1], abs=1e-6)


def test_utm_series_agrees_with_proj():
    pyproj = pytest.importorskip("pyproj")
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32612", always_xy=True)
    for longitude in (-114.0, -112.5, -111.0, -109.5, -108.0):
        for latitude in (0.0, 15.0, 31.0, 34.5, 49.0, 70.0):
            actual = transformer.transform(longitude, latitude)
            assert utm_forward(longitude, latitude, 12) == pytest.approx(actual, abs=1e-3)


def test_relations_for_shared_edge():
    result = rectangle_relations((0, 0, 2, 2), (2, 0, 4, 2))
    assert result == {
        "intersects": True,
        "disjoint": False,
        "touches": True,
        "overlaps": False,
        "within": False,
        "contains": False,
    }


def test_relations_for_crossing_rectangles():
    result = rectangle_relations((0, 0, 2, 2), (1, 1, 3, 3))
    assert result["overlaps"] and result["intersects"] and not result["touches"]


def test_relations_for_contained_rectangle():
    result = rectangle_relations((0, 0, 2, 2), (0.5, 0.5, 1.5, 1.5))
    assert result["contains"] and not result["within"] and not result["overlaps"]


def test_relations_for_equal_rectangles():
    result = rectangle_relations((0, 0, 1, 1), (0, 0, 1, 1))
    assert result["within"] and result["contains"] and not result["overlaps"]


def test_relations_agree_with_shapely():
    shapely = pytest.importorskip("shapely")
    a = (0.0, 0.0, 2.0, 2.0)
    others = [(2, 0, 4, 2), (2, 2, 3, 3), (1, 1, 3, 3), (5, 5, 6, 6), (0.5, 0.5, 1.5, 1.5), (0, 0, 2, 2)]
    for other in others:
        left, right = shapely.box(*a), shapely.box(*other)
        answer = rectangle_relations(a, other)
        assert answer["intersects"] == left.intersects(right)
        assert answer["touches"] == left.touches(right)
        assert answer["overlaps"] == left.overlaps(right)
        assert answer["within"] == left.within(right)
        assert answer["contains"] == left.contains(right)


@pytest.mark.parametrize(
    ("point", "contains", "covers", "boundary", "near"),
    [
        ((1, 1), True, True, False, False),
        ((12, 5), False, False, False, False),
        ((0, 5), False, True, True, True),
        ((5, 5), False, False, False, False),
        ((4, 5), False, True, True, True),
        ((0.0078125, 5), True, True, False, True),
    ],
)
def test_point_in_holed_rectangle(point, contains, covers, boundary, near):
    answer = point_in_holed_rectangle(point, (0, 0, 10, 10), (4, 4, 6, 6), 0.01)
    assert answer == {"contains": contains, "covers": covers, "on_boundary": boundary, "near_boundary": near}


def test_polsby_popper_of_circle_is_one():
    assert polsby_popper(math.pi, 2 * math.pi) == pytest.approx(1.0)


def test_square_compactness_is_pi_over_four():
    assert rectangle_compactness(10, 10) == pytest.approx(math.pi / 4)


def test_stadium_area():
    assert stadium_area(530.0, 30.0) == pytest.approx(31800.0 + math.pi * 900.0)


def test_multipart_remainder():
    assert multipart_remainder((0, 0, 10, 10), [(0, 0, 2, 2), (6, 0, 8, 3)]) == 90.0


_NAMES = {1: "water", 2: "bare_ground"}


def test_scores_follow_hand_count():
    truth = np.array([0] * 20 + [1] * 40 + [2] * 40)
    predicted = np.array([0] * 20 + [1] * 40 + [1] * 8 + [2] * 32)
    scores = classification_scores(truth, predicted, [1, 2], _NAMES)
    assert scores["evaluated_pixels"] == 80
    assert scores["ignored_pixels"] == 20
    assert scores["overall_accuracy"] == 0.9
    assert scores["f1.water"] == pytest.approx(10 / 11)
    assert scores["f1.bare_ground"] == pytest.approx(8 / 9)
    assert scores["macro_f1"] == pytest.approx(89 / 99)
    assert scores["iou.water"] == pytest.approx(40 / 48)
    assert scores["iou.bare_ground"] == pytest.approx(32 / 40)
    assert scores["confusion_matrix"] == [[40, 0], [8, 32]]


def test_abstaining_counts_as_miss():
    truth = np.array([1, 1, 1, 1])
    predicted = np.array([1, 0, 0, 0])
    scores = classification_scores(truth, predicted, [1], {1: "water"})
    assert scores["overall_accuracy"] == 0.25
    assert scores["abstain_fraction"] == 0.75


def test_absent_classes_stay_out_of_macro_averages():
    truth = np.array([1, 1])
    scores = classification_scores(truth, truth.copy(), [1, 2], _NAMES)
    assert scores["macro_f1"] == 1.0
    assert scores["mean_iou"] == 1.0


def test_zero_division_policy_is_applied():
    truth = np.array([1, 1])
    predicted = np.array([1, 1])
    scores = classification_scores(truth, predicted, [1, 2], _NAMES, zero_division=0.5)
    assert scores["precision.bare_ground"] == 0.5


def test_sha256_of_known_bytes(tmp_path):
    path = tmp_path / "data"
    path.write_bytes(b"abc")
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_canonical_json_sorts_keys():
    assert canonical_json({"b": 1, "a": [2]}) == '{"a":[2],"b":1}'


def _feature(identifier, x, **properties):
    return {
        "properties": {"id": identifier, **properties},
        "geometry": {"type": "Point", "coordinates": [x, 1.0]},
    }


def test_semantic_hash_ignores_feature_order():
    forward = [_feature("a", 1.0), _feature("b", 2.0)]
    assert semantic_feature_hash(forward) == semantic_feature_hash(forward[::-1])


def test_semantic_hash_ignores_rounding_noise():
    assert semantic_feature_hash([_feature("a", 1.0000001)]) == semantic_feature_hash([_feature("a", 1.0)])


def test_semantic_hash_sees_geometry_and_attributes():
    base = semantic_feature_hash([_feature("a", 1.0)])
    assert semantic_feature_hash([_feature("a", 1.001)]) != base
    assert semantic_feature_hash([_feature("a", 1.0, name="x")]) != base


def test_semantic_hash_accepts_null_geometry():
    assert semantic_feature_hash([{"properties": {"id": "a"}, "geometry": None}])
