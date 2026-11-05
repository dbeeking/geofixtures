from __future__ import annotations

import numpy as np

from geofixtures.io.geotiff import Grid
from geofixtures.oracles.raster import compare_rasters

_RULES = {"absolute_tolerance": 0.01}


def _values(size=4, value=1.0):
    return np.full((size, size), value, dtype="float32")


def test_identical_rasters_pass(raster):
    passed, _, metrics = compare_rasters(raster(_values()), raster(_values()), _RULES)
    assert passed
    assert metrics["compared_pixels"] == 16
    assert metrics["max_abs_error"] == 0


def test_pixel_beyond_tolerance_fails(raster):
    changed = _values()
    changed[1, 1] = 1.5
    passed, message, metrics = compare_rasters(raster(changed), raster(_values()), _RULES)
    assert not passed
    assert "1 pixels" in message
    assert metrics["max_abs_error"] == 0.5


def test_shifted_grid_is_never_resampled(raster):
    shifted = Grid(4, 4, 1.0, 400000.5, 3801000.0)
    passed, message, _ = compare_rasters(raster(_values(), grid=shifted), raster(_values()), _RULES)
    assert not passed
    assert "aligned" in message


def test_different_shape_fails(raster):
    passed, _, metrics = compare_rasters(raster(_values(5)), raster(_values(4)), _RULES)
    assert not passed
    assert metrics["observed_shape"] == [5, 5]


def test_different_crs_fails(raster):
    passed, message, _ = compare_rasters(raster(_values(), crs="EPSG:32611"), raster(_values()), _RULES)
    assert not passed
    assert "CRS" in message


def test_missing_required_pixels_fail(raster):
    observed = _values()
    observed[0, 0] = -9999
    passed, message, _ = compare_rasters(raster(observed, nodata=-9999), raster(_values()), _RULES)
    assert not passed
    assert "no observed value" in message


def test_value_where_truth_requires_nodata_fails(raster):
    truth = _values()
    truth[0, 0] = -9999
    passed, message, metrics = compare_rasters(raster(_values()), raster(truth, nodata=-9999), _RULES)
    assert not passed
    assert "NoData" in message
    assert metrics["unexpected_valid_pixels"] == 1


def test_truth_nodata_can_be_ignored(raster):
    truth = _values()
    truth[0, 0] = -9999
    rules = {**_RULES, "truth_nodata": "ignore"}
    assert compare_rasters(raster(_values()), raster(truth, nodata=-9999), rules)[0]


def test_edge_pixels_can_be_excluded(raster):
    observed = _values(6)
    observed[0, :] = 9
    rules = {**_RULES, "exclude_edge_pixels": 1}
    assert compare_rasters(raster(observed), raster(_values(6)), rules)[0]
    observed[2, 2] = 9
    assert not compare_rasters(raster(observed), raster(_values(6)), rules)[0]


def test_optional_mask_allows_nodata_but_not_wrong_values(raster):
    mask = raster(np.array([[1, 0], [0, 0]], dtype="uint8"))
    truth = raster(_values(2))
    missing = _values(2)
    missing[0, 0] = -9999
    assert compare_rasters(raster(missing, nodata=-9999), truth, _RULES, optional_mask_path=mask)[0]
    wrong = _values(2)
    wrong[0, 0] = 5
    assert not compare_rasters(raster(wrong), truth, _RULES, optional_mask_path=mask)[0]


def test_ignore_mask_skips_pixels_entirely(raster):
    mask = raster(np.array([[1, 0], [0, 0]], dtype="uint8"))
    wrong = _values(2)
    wrong[0, 0] = 5
    assert compare_rasters(raster(wrong), raster(_values(2)), _RULES, ignore_mask_path=mask)[0]


def test_map_coordinate_sampling_handles_different_grids(raster):
    finer = Grid(8, 8, 0.5, 400000.0, 3801000.0)
    rules = {**_RULES, "sampling": "map_coordinates"}
    assert compare_rasters(raster(_values(8), grid=finer), raster(_values()), rules)[0]


def test_map_coordinate_sampling_treats_uncovered_truth_as_missing(raster):
    small = Grid(2, 4, 1.0, 400000.0, 3801000.0)
    rules = {**_RULES, "sampling": "map_coordinates"}
    observed = np.full((4, 2), 1.0, dtype="float32")
    passed, message, _ = compare_rasters(raster(observed, grid=small), raster(_values()), rules)
    assert not passed
    assert "no observed value" in message


def test_all_nodata_output_cannot_pass(raster):
    empty = _values()
    empty[:] = -9999
    rules = {**_RULES, "max_missing_fraction": 1.0}
    passed, message, _ = compare_rasters(raster(empty, nodata=-9999), raster(_values()), rules)
    assert not passed
    assert "No pixels" in message


def test_max_missing_fraction_is_honored(raster):
    observed = _values()
    observed[0, 0] = -9999
    rules = {**_RULES, "max_missing_fraction": 0.1}
    assert compare_rasters(raster(observed, nodata=-9999), raster(_values()), rules)[0]


def test_nodata_can_count_as_value(raster):
    zeros = np.zeros((2, 2), dtype="uint8")
    truth = raster(zeros, nodata=255)
    rules = {"absolute_tolerance": 0.0, "observed_nodata_as_value": True}
    assert compare_rasters(raster(zeros, nodata=0), truth, rules)[0]
    assert not compare_rasters(raster(zeros, nodata=0), truth, {"absolute_tolerance": 0.0})[0]
