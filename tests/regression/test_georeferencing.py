from __future__ import annotations

import numpy as np
import pytest

from geofixtures import ObservationBundle, Outcome
from geofixtures.io.geotiff import Grid, write_geotiff
from geofixtures.oracles.raster import compare_rasters, transforms_match
from geofixtures.runner.assertions import evaluate

rasterio = pytest.importorskip("rasterio")
_TRANSFORM = [1.0, 0.0, 400000.0, 0.0, -1.0, 3801000.0]
_RULES = {"absolute_tolerance": 0.01}


def _metadata_outcome(path, tolerance=1e-6):
    spec = {
        "id": "a",
        "kind": "raster_metadata",
        "transform_tolerance": tolerance,
        "expected": {"transform": _TRANSFORM},
    }
    return evaluate(spec, ObservationBundle(values={"a": str(path)}), None).outcome


@pytest.mark.parametrize("offset", [3.0, 0.001, 2e-5])
def test_metadata_refuses_shift_beyond_tolerance(tmp_path, offset):
    grid = Grid(4, 4, 1.0, 400000.0 + offset, 3801000.0)
    path = tmp_path / "shifted.tif"
    write_geotiff(path, np.ones((4, 4), dtype="float32"), grid, "EPSG:32612")
    assert _metadata_outcome(path) is Outcome.FAIL


def test_metadata_accepts_shift_within_tolerance(tmp_path):
    grid = Grid(4, 4, 1.0, 400000.0 + 2e-7, 3801000.0)
    path = tmp_path / "shifted.tif"
    write_geotiff(path, np.ones((4, 4), dtype="float32"), grid, "EPSG:32612")
    assert _metadata_outcome(path) is Outcome.PASS


def test_transforms_match_is_absolute():
    assert transforms_match(_TRANSFORM, _TRANSFORM)
    assert not transforms_match(_TRANSFORM, [1.0, 0.0, 400003.0, 0.0, -1.0, 3801000.0])
    assert not transforms_match(_TRANSFORM, [1.0 + 1e-5, 0.0, 400000.0, 0.0, -1.0, 3801000.0])


def test_grid_comparison_refuses_small_shift(raster):
    values = np.ones((4, 4), dtype="float32")
    shifted = Grid(4, 4, 1.0, 400000.00001, 3801000.0)
    passed, message, _ = compare_rasters(raster(values, grid=shifted), raster(values), _RULES)
    assert not passed
    assert "aligned" in message


def test_classification_refuses_small_shift(raster, tmp_path):
    labels = np.array([[1, 1], [2, 2]], dtype="uint8")
    truth = raster(labels)
    shifted = raster(labels, grid=Grid(2, 2, 1.0, 400000.00001, 3801000.0))
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
    bundle = ObservationBundle(values={"scores": str(shifted)})
    assert evaluate(spec, bundle, tmp_path).outcome is Outcome.FAIL


def _surface():
    rows, columns = np.indices((8, 8))
    return (rows * 10.0 + columns).astype("float32")


def _rotated_copy(path, degrees, truth):
    """Write the truth surface to a grid rotated about the surface's center."""
    transform = (
        rasterio.Affine.translation(400004.0, 3800996.0)
        * rasterio.Affine.rotation(degrees)
        * rasterio.Affine.scale(1.0, -1.0)
        * rasterio.Affine.translation(-4.0, -4.0)
    )
    values = np.full((8, 8), -9999.0, dtype="float32")
    for row in range(8):
        for column in range(8):
            x, y = transform * (column + 0.5, row + 0.5)
            truth_column = int(np.floor(x - 400000.0))
            truth_row = int(np.floor(3801000.0 - y))
            if 0 <= truth_row < 8 and 0 <= truth_column < 8:
                values[row, column] = truth[truth_row, truth_column]
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=8,
        height=8,
        count=1,
        dtype="float32",
        crs="EPSG:32612",
        transform=transform,
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values, 1)
    return values


@pytest.mark.parametrize("degrees", [90.0, 180.0, -90.0])
def test_map_sampling_reads_rotated_raster(raster, tmp_path, degrees):
    truth = _surface()
    observed = tmp_path / "rotated.tif"
    _rotated_copy(observed, degrees, truth)
    rules = {**_RULES, "sampling": "map_coordinates"}
    passed, message, metrics = compare_rasters(observed, raster(truth), rules)
    assert passed, message
    assert metrics["compared_pixels"] == 64


def test_map_sampling_detects_wrong_values_in_rotated_raster(raster, tmp_path):
    truth = _surface()
    observed = tmp_path / "rotated.tif"
    _rotated_copy(observed, 90.0, truth + 5.0)
    passed, message, _ = compare_rasters(observed, raster(truth), {**_RULES, "sampling": "map_coordinates"})
    assert not passed
    assert "64 pixels differ" in message


def test_map_sampling_handles_small_rotation(raster, tmp_path):
    truth = np.ones((8, 8), dtype="float32")
    observed = tmp_path / "rotated.tif"
    _rotated_copy(observed, 3.0, truth)
    rules = {**_RULES, "sampling": "map_coordinates", "max_missing_fraction": 1.0, "truth_nodata": "ignore"}
    assert compare_rasters(observed, raster(truth), rules)[0]
