from __future__ import annotations

import json

import jsonschema
import numpy as np
import pytest

from geofixtures import Status, list_cases, materialize, run_case, run_suite, validate
from geofixtures.io.geoparquet import read_geoparquet
from geofixtures.io.las import read_las
from geofixtures.oracles.data_integrity import semantic_feature_hash
from geofixtures.validation import load_schema

_CASES = [case["case_id"] for case in list_cases()]


@pytest.mark.parametrize("case_id", _CASES)
def test_reference_adapter_passes_and_fixture_validates(case_id, tmp_path):
    fixture = materialize(case_id, tmp_path / "fixture")
    assert validate(fixture.manifest_path).ok
    result = run_case(fixture, "reference")
    assert result.status is Status.PASS, result.failure_text()


@pytest.mark.parametrize("case_id", _CASES)
def test_generation_is_deterministic(case_id, tmp_path):
    first = materialize(case_id, tmp_path / "one", seed=7)
    second = materialize(case_id, tmp_path / "two", seed=7)
    assert first.manifest["files"] == second.manifest["files"]
    assert first.manifest["assertions"] == second.manifest["assertions"]


@pytest.mark.parametrize("case_id", _CASES)
@pytest.mark.parametrize("seed", [1, 2024])
def test_answers_hold_for_other_seeds(case_id, seed, tmp_path):
    fixture = materialize(case_id, tmp_path / "fixture", seed=seed)
    result = run_case(fixture, "reference")
    assert result.status is Status.PASS, result.failure_text()


def test_seeds_change_random_data(tmp_path):
    first = materialize("landcover.scene.rgbnir.001", tmp_path / "one", seed=1)
    second = materialize("landcover.scene.rgbnir.001", tmp_path / "two", seed=2)
    assert first.manifest["files"] != second.manifest["files"]


def test_catalog_meets_size_and_speed_budget(tmp_path):
    import time

    started = time.perf_counter()
    total = 0
    for case_id in _CASES:
        fixture = materialize(case_id, tmp_path / case_id)
        total += sum(entry["bytes"] for entry in fixture.manifest["files"])
    assert time.perf_counter() - started < 30
    assert total < 100 * 1024 * 1024


def test_every_case_declares_formats_it_writes(tmp_path):
    for case_id in _CASES:
        fixture = materialize(case_id, tmp_path / case_id)
        for item in fixture.manifest["inputs"]:
            assert item["profile"]
            assert (fixture.root / item["path"]).is_file()


def test_full_suite_is_clean_and_its_report_matches_schema():
    result = run_suite(["suite:all"])
    assert result.summary()["PASS"] == 42
    assert result.exit_code() == 0
    assert result.complete
    report = result.to_dict()
    jsonschema.validate(report, load_schema("report-v1.schema.json"))
    json.dumps(report, allow_nan=False)


def test_catalog_overlap_inputs_define_four_square_metres(tmp_path):
    fixture = materialize("vector.overlap.001", tmp_path / "fixture")
    features, _, _ = read_geoparquet(fixture.root / "input" / "features.parquet")
    (ax0, ay0), (ax1, ay1) = (c(features[0]) for c in (_low, _high))
    (bx0, by0), (bx1, by1) = (c(features[1]) for c in (_low, _high))
    assert (min(ax1, bx1) - max(ax0, bx0)) * (min(ay1, by1) - max(ay0, by0)) == 4.0


def _low(feature):
    ring = feature["geometry"]["coordinates"][0]
    return min(p[0] for p in ring), min(p[1] for p in ring)


def _high(feature):
    ring = feature["geometry"]["coordinates"][0]
    return max(p[0] for p in ring), max(p[1] for p in ring)


def test_slope_truth_matches_finite_difference_of_input(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    fixture = materialize("raster.ridge_saddle.001", tmp_path / "fixture")
    with rasterio.open(fixture.root / "input" / "dem.tif") as dem:
        z = dem.read(1).astype("float64")
    with rasterio.open(fixture.root / "truth" / "slope.tif") as truth:
        slope = truth.read(1)
    east = (z[1:-1, 2:] - z[1:-1, :-2]) / 20.0
    north = (z[2:, 1:-1] - z[:-2, 1:-1]) / 20.0
    assert np.allclose(np.hypot(east, north), slope[1:-1, 1:-1], atol=1e-4)


def test_restriction_area_differs_from_polygon_area(tmp_path):
    fixture = materialize("raster.restriction_overlay.001", tmp_path / "fixture")
    truth = json.loads((fixture.root / "truth" / "expected.json").read_text())
    assert truth == {"restricted_pixels": 400, "restricted_area_m2": 40000.0}
    assert 194.0**2 != truth["restricted_area_m2"]


def test_lidar_density_is_what_file_holds(tmp_path):
    fixture = materialize("lidar.density.001", tmp_path / "fixture")
    cloud = read_las(fixture.root / "input" / "points.las")
    assert cloud["count"] == 1600
    assert cloud["x"].max() - cloud["x"].min() <= 40.0


def test_date_gap_matches_hand_count(tmp_path):
    fixture = materialize("landcover.date_mismatch.001", tmp_path / "fixture")
    expected = next(item for item in fixture.manifest["assertions"] if item["id"] == "gap_days")
    # Seven years to 2022-09-01 with two leap days, less 78 days back to June 15.
    assert expected["expected"] == 7 * 365 + 2 - 78


def test_same_count_case_has_one_semantic_change(tmp_path):
    from geofixtures.io.geojson import read_geojson

    fixture = materialize("ingest.unchanged_count.001", tmp_path / "fixture")
    before = read_geojson(fixture.root / "input" / "before.geojson")
    after = read_geojson(fixture.root / "input" / "after.geojson")
    assert len(before) == len(after)
    assert semantic_feature_hash(before) != semantic_feature_hash(after)
    by_id = {item["properties"]["id"]: item for item in after}
    changed = [item["properties"]["id"] for item in before if item != by_id[item["properties"]["id"]]]
    assert changed == ["f3"]


def test_tampered_source_mismatches(tmp_path):
    import hashlib

    fixture = materialize("ingest.integrity.001", tmp_path / "fixture")
    source = fixture.root / "input" / "source.geojson"
    published = (fixture.root / "input" / "source.geojson.sha256").read_text().split()[0]
    assert hashlib.sha256(source.read_bytes()).hexdigest() != published


def test_truncated_image_opens_but_cannot_be_read(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.errors import RasterioIOError

    fixture = materialize("raster.truncated.001", tmp_path / "fixture")
    with rasterio.open(fixture.root / "input" / "test_imagery.tif") as dataset:
        assert dataset.count == 4
        with pytest.raises(RasterioIOError):
            dataset.read()


def test_collar_pixels_are_zero_in_every_band(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    fixture = materialize("landcover.image_collar.001", tmp_path / "fixture")
    with rasterio.open(fixture.root / "input" / "test_imagery.tif") as dataset:
        image = dataset.read()
        assert dataset.nodata is None
    assert not image[:, :, :16].any()
    assert image[:, :, 16:].all()
