"""Compare decoded case data and answers with catalog.lock.json.

Digests use decoded values, so a library that lays out bytes differently won't
trip this test. Regenerate the lock with update_lock.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from geofixtures import list_cases, materialize
from geofixtures.cases import crs
from geofixtures.io.geojson import read_geojson
from geofixtures.io.geoparquet import read_geoparquet
from geofixtures.io.las import read_las
from geofixtures.oracles.analytic import utm_forward
from geofixtures.oracles.data_integrity import canonical_json

LOCK = Path(__file__).with_name("catalog.lock.json")
_DIGITS = 6


def _rounded(value: Any) -> Any:
    """Round to significant digits, so last-bit math library differences don't count."""
    if isinstance(value, float):
        return float(f"{value:.12g}")
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(_rounded(value)).encode()).hexdigest()


def _array_digest(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        digest.update(str(array.shape).encode())
        digest.update(np.asarray(array, dtype=array.dtype.newbyteorder("<")).tobytes())
    return digest.hexdigest()


def _file_digest(path: Path) -> str | None:
    import rasterio

    if path.suffix == ".parquet":
        features, metadata, schema = read_geoparquet(path)
        return _digest({"features": features, "schema": schema, "version": metadata["version"]})
    if path.suffix == ".geojson":
        return _digest(read_geojson(path))
    if path.suffix == ".json":
        return _digest(json.loads(path.read_text()))
    if path.suffix == ".las":
        cloud = read_las(path)
        return _array_digest(
            np.round(cloud["x"], 3), np.round(cloud["y"], 3), np.round(cloud["z"], 3), cloud["classification"]
        )
    if path.suffix == ".tif":
        if "truncated" in path.parts[-1]:
            return None
        with rasterio.open(path) as dataset:
            return _array_digest(dataset.read())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_digest(case_id: str, root: Path) -> dict[str, Any]:
    fixture = materialize(case_id, root / case_id)
    manifest = fixture.manifest
    meaning = {key: manifest[key] for key in ("assertions", "parameters", "expected_status", "operation")}
    files = {}
    for entry in manifest["files"]:
        path = fixture.root / entry["path"]
        if case_id == "raster.truncated.001" and path.name == "test_imagery.tif":
            continue
        files[entry["path"]] = _file_digest(path)
    return {
        "version": manifest["case_version"],
        "meaning": _digest(meaning),
        "truth": _digest(json.loads((fixture.root / "truth" / "expected.json").read_text())),
        "files": files,
    }


def catalog_digests() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as root:
        return {case["case_id"]: case_digest(case["case_id"], Path(root)) for case in list_cases()}


def test_digests_ignore_last_bit_differences(tmp_path):
    fixture = materialize("crs.transform.001", tmp_path / "case")
    projected = fixture.manifest["assertions"][0]["expected"]
    baseline = _digest(projected)
    for direction in (math.inf, -math.inf):
        nudged = {name: list(point) for name, point in projected.items()}
        for _ in range(8):
            nudged = {
                name: [math.nextafter(value, direction) for value in point] for name, point in nudged.items()
            }
            assert _digest(nudged) == baseline


@pytest.mark.parametrize("direction", [math.inf, -math.inf])
def test_case_digest_ignores_last_bit_differences(tmp_path, monkeypatch, direction):
    baseline = case_digest("crs.transform.001", tmp_path / "baseline")

    def nudged(longitude, latitude, zone):
        easting, northing = utm_forward(longitude, latitude, zone)
        for _ in range(8):
            easting = math.nextafter(easting, direction)
            northing = math.nextafter(northing, direction)
        return easting, northing

    monkeypatch.setattr(crs, "utm_forward", nudged)
    assert case_digest("crs.transform.001", tmp_path / "nudged") == baseline


def test_digests_see_real_change():
    assert _digest(3763640.5) != _digest(3763640.5001)


def test_published_cases_match_lock():
    locked = json.loads(LOCK.read_text())
    current = catalog_digests()
    assert set(current) == set(locked)
    changed = [case_id for case_id in current if current[case_id] != locked[case_id]]
    assert not changed, f"Bump the version of these cases and update the lock: {changed}"
