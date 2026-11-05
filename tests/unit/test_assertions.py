from __future__ import annotations

import math

import numpy as np
import pytest

from geofixtures import ObservationBundle, Outcome, Rejection
from geofixtures.runner.assertions import evaluate


def _run(spec, value, root=None):
    return evaluate(spec, ObservationBundle(values={spec.get("observe", spec["id"]): value}), root)


def _numeric(**extra):
    return {"id": "a", "kind": "numeric", "unit": "m", **extra}


def test_exact_is_type_strict():
    spec = {"id": "a", "kind": "exact", "expected": 1}
    assert _run(spec, 1).outcome is Outcome.PASS
    assert _run(spec, 1.0).outcome is Outcome.FAIL
    assert _run(spec, True).outcome is Outcome.FAIL


def test_exact_normalizes_numpy_booleans():
    spec = {"id": "a", "kind": "exact", "expected": True}
    assert _run(spec, np.True_).outcome is Outcome.PASS


def test_set_equal_ignores_order_and_reports_differences():
    spec = {"id": "a", "kind": "set_equal", "expected": ["x", "y"]}
    assert _run(spec, ["y", "x"]).outcome is Outcome.PASS
    result = _run(spec, ["x", "z"])
    assert result.outcome is Outcome.FAIL
    assert "['y']" in result.message
    assert "['z']" in result.message


def test_set_equal_sees_duplicates():
    spec = {"id": "a", "kind": "set_equal", "expected": ["x", "y"]}
    assert _run(spec, ["x", "y", "y"]).outcome is Outcome.FAIL


def test_set_equal_rejects_string():
    spec = {"id": "a", "kind": "set_equal", "expected": ["x"]}
    assert _run(spec, "x").outcome is Outcome.FAIL


def test_missing_tolerance_means_exact():
    spec = _numeric(expected=1.0)
    assert _run(spec, 1.0).outcome is Outcome.PASS
    assert _run(spec, 1.0 + 1e-12).outcome is Outcome.FAIL


def test_absolute_tolerance_edges():
    spec = _numeric(expected=10.0, absolute_tolerance=0.5)
    assert _run(spec, 10.5).outcome is Outcome.PASS
    assert _run(spec, 10.51).outcome is Outcome.FAIL


def test_relative_tolerance():
    spec = _numeric(expected=100.0, relative_tolerance=0.01)
    assert _run(spec, 101.0).outcome is Outcome.PASS
    assert _run(spec, 101.5).outcome is Outcome.FAIL


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_values_never_pass(value):
    spec = _numeric(expected=1.0, absolute_tolerance=1e9)
    assert _run(spec, value).outcome is Outcome.FAIL


@pytest.mark.parametrize("value", [None, "1.0", True, [1.0]])
def test_non_numbers_never_pass(value):
    assert _run(_numeric(expected=1.0, absolute_tolerance=1.0), value).outcome is Outcome.FAIL


def test_numeric_mappings_compare_every_key():
    spec = _numeric(expected={"a": 1.0, "b": [2.0, 3.0]}, absolute_tolerance=0.1)
    assert _run(spec, {"a": 1.05, "b": [2.0, 3.0]}).outcome is Outcome.PASS
    assert _run(spec, {"a": 1.05, "b": [2.0, 3.5]}).outcome is Outcome.FAIL
    assert _run(spec, {"a": 1.05}).outcome is Outcome.FAIL
    assert _run(spec, {"a": 1.0, "b": [2.0, 3.0], "c": 1.0}).outcome is Outcome.FAIL


def test_numeric_reports_error_metrics():
    spec = _numeric(expected={"a": 1.0, "b": 2.0}, absolute_tolerance=1.0)
    result = _run(spec, {"a": 1.5, "b": 2.0})
    assert result.metrics["max_abs_error"] == 0.5
    assert result.metrics["rmse"] == pytest.approx(math.sqrt(0.125))


@pytest.mark.parametrize(
    ("value", "outcome"), [(1.0, Outcome.PASS), (3.0, Outcome.FAIL), (-1.0, Outcome.FAIL)]
)
def test_numeric_ranges(value, outcome):
    assert _run(_numeric(minimum=0.0, maximum=2.0), value).outcome is outcome


@pytest.mark.parametrize("value", [math.nan, None, False])
def test_numeric_ranges_reject_non_numbers(value):
    assert _run(_numeric(maximum=2.0), value).outcome is Outcome.FAIL


def test_failure_carries_reproduction_context():
    result = _run(_numeric(expected=1.0, absolute_tolerance=0.1), 5.0)
    assert result.observed == 5.0
    assert result.expected == 1.0
    assert result.tolerance == {"absolute_tolerance": 0.1}
    assert result.unit == "m"
    assert result.assertion_id == "a"


def test_geometry_equivalence_ignores_vertex_order():
    pytest.importorskip("shapely")
    spec = {"id": "a", "kind": "geometry_equivalent", "expected": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"}
    assert _run(spec, "POLYGON ((1 1, 0 1, 0 0, 1 0, 1 1))").outcome is Outcome.PASS
    assert _run(spec, "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))").outcome is Outcome.FAIL


def test_geometry_rejects_invalid_shapes_and_bad_text():
    pytest.importorskip("shapely")
    spec = {"id": "a", "kind": "geometry_equivalent", "expected": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"}
    assert _run(spec, "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))").outcome is Outcome.FAIL
    assert _run(spec, "not wkt").outcome is Outcome.FAIL


def test_topology_compares_each_predicate():
    spec = {"id": "a", "kind": "topology_predicate", "expected": {"x": True, "y": False}}
    assert _run(spec, {"x": np.True_, "y": False}).outcome is Outcome.PASS
    result = _run(spec, {"x": False, "y": False})
    assert result.outcome is Outcome.FAIL
    assert "x:" in result.message
    assert _run(spec, {"x": True}).outcome is Outcome.FAIL


def test_topology_does_not_accept_truthy_values():
    spec = {"id": "a", "kind": "topology_predicate", "expected": {"x": True}}
    assert _run(spec, {"x": 1}).outcome is Outcome.FAIL


def test_schema_comparison():
    spec = {"id": "a", "kind": "schema", "expected": {"id": "string"}}
    assert _run(spec, {"id": "string"}).outcome is Outcome.PASS
    assert _run(spec, {"id": "int64"}).outcome is Outcome.FAIL


def test_invariants():
    spec = {"id": "a", "kind": "invariant", "rule": "is_false"}
    assert _run(spec, False).outcome is Outcome.PASS
    assert _run(spec, True).outcome is Outcome.FAIL
    assert _run(spec, None).outcome is Outcome.FAIL
    assert _run({"id": "a", "kind": "invariant", "rule": "is_true"}, True).outcome is Outcome.PASS


def test_unknown_invariant_is_error():
    assert _run({"id": "a", "kind": "invariant", "rule": "odd"}, True).outcome is Outcome.ERROR


def test_missing_required_observation_is_error():
    spec = {"id": "a", "kind": "exact", "expected": 1}
    assert evaluate(spec, ObservationBundle(), None).outcome is Outcome.ERROR


def test_missing_optional_observation_is_skipped():
    spec = {"id": "a", "kind": "exact", "expected": 1, "optional": True}
    assert evaluate(spec, ObservationBundle(), None).outcome is Outcome.SKIP


def test_observe_key_redirects_lookup():
    spec = {"id": "a", "observe": "b", "kind": "exact", "expected": 1}
    assert evaluate(spec, ObservationBundle(values={"b": 1}), None).outcome is Outcome.PASS


def test_expected_error_accepts_only_declared_codes():
    spec = {"id": "a", "kind": "expected_error", "codes": ["BAD"]}
    accepted = ObservationBundle(rejection=Rejection("BAD"))
    other = ObservationBundle(rejection=Rejection("OTHER"))
    assert evaluate(spec, accepted, None).outcome is Outcome.EXPECTED_REJECTION
    assert evaluate(spec, other, None).outcome is Outcome.FAIL
    assert evaluate(spec, ObservationBundle(), None).outcome is Outcome.FAIL


def test_expected_error_without_codes_accepts_any_rejection():
    spec = {"id": "a", "kind": "expected_error"}
    assert (
        evaluate(spec, ObservationBundle(rejection=Rejection("X")), None).outcome
        is Outcome.EXPECTED_REJECTION
    )


def test_raster_metadata_checks_each_field(raster, tmp_path):
    path = raster(np.ones((4, 4), dtype="float32"))
    transform = [1.0, 0.0, 400000.0, 0.0, -1.0, 3801000.0]
    spec = {
        "id": "a",
        "kind": "raster_metadata",
        "expected": {"width": 4, "height": 4, "crs": "EPSG:32612", "transform": transform},
    }
    assert _run(spec, str(path)).outcome is Outcome.PASS
    wrong = {**spec, "expected": {"width": 5, "crs": "EPSG:32611", "transform": [2.0, *transform[1:]]}}
    result = _run(wrong, str(path))
    assert result.outcome is Outcome.FAIL
    assert "width" in result.message and "crs" in result.message and "transform" in result.message


def test_raster_metadata_allowed_values(raster):
    path = raster(np.array([[0, 1], [2, 3]], dtype="uint8"))
    spec = {"id": "a", "kind": "raster_metadata", "expected": {"width": 2}, "allowed_values": [0, 1, 2]}
    result = _run(spec, str(path))
    assert result.outcome is Outcome.FAIL
    assert "[3]" in result.message


def test_missing_output_file_is_error():
    spec = {"id": "a", "kind": "raster_metadata", "expected": {"width": 2}}
    assert _run(spec, "/does/not/exist.tif").outcome is Outcome.ERROR


def test_classification_assertion(raster, tmp_path):
    truth = raster(np.array([[1, 1], [2, 2]], dtype="uint8"))
    good = raster(np.array([[1, 1], [2, 2]], dtype="uint8"))
    bad = raster(np.array([[2, 2], [1, 1]], dtype="uint8"))
    spec = {
        "id": "scores",
        "kind": "classification_metrics",
        "truth": truth.name,
        "labels": [1, 2],
        "class_names": {"1": "water", "2": "bare_ground"},
        "ignore_values": [0],
        "abstain_values": [0],
        "zero_division": 0.0,
        "thresholds": {"overall_accuracy": {"min": 0.9}, "abstain_fraction": {"max": 0.1}},
    }
    assert _run(spec, str(good), tmp_path).outcome is Outcome.PASS
    assert _run(spec, str(bad), tmp_path).outcome is Outcome.FAIL


def test_classification_requires_alignment(raster, tmp_path):
    from geofixtures.io.geotiff import Grid

    truth = raster(np.array([[1, 1], [2, 2]], dtype="uint8"))
    shifted = raster(np.array([[1, 1], [2, 2]], dtype="uint8"), grid=Grid(2, 2, 1.0, 400001.0, 3801000.0))
    spec = {
        "id": "scores",
        "kind": "classification_metrics",
        "truth": truth.name,
        "labels": [1, 2],
        "class_names": {"1": "water", "2": "bare_ground"},
        "ignore_values": [0],
        "abstain_values": [0],
        "zero_division": 0.0,
        "thresholds": {"overall_accuracy": {"min": 0.0}},
    }
    result = _run(spec, str(shifted), tmp_path)
    assert result.outcome is Outcome.FAIL
    assert "aligned" in result.message


def test_pointcloud_header_assertion(tmp_path):
    pytest.importorskip("laspy")
    from geofixtures.io.las import write_las

    path = tmp_path / "points.las"
    values = np.array([1.0, 2.0, 3.0])
    write_las(path, values + 400000, values + 3800000, values, np.array([2, 2, 5]), "EPSG:32612")
    spec = {
        "id": "a",
        "kind": "pointcloud_metadata",
        "expected": {
            "version": "1.4",
            "point_format": 6,
            "count": 3,
            "crs": "EPSG:32612",
            "scale": [0.001, 0.001, 0.001],
        },
    }
    result = _run(spec, str(path))
    assert result.outcome is Outcome.PASS
    assert result.observed["class_counts"] == {"2": 2, "5": 1}
    assert _run({**spec, "expected": {"count": 4}}, str(path)).outcome is Outcome.FAIL
    assert _run({**spec, "expected": {"scale": [0.01, 0.01, 0.01]}}, str(path)).outcome is Outcome.FAIL
    assert _run({**spec, "expected": {"crs": "EPSG:32611"}}, str(path)).outcome is Outcome.FAIL
