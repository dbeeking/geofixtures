"""Mutation tests: corrupting any observed value must stop a case from passing."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from geofixtures import ExecutionContext, ObservationBundle, Status, list_cases, materialize, run_case
from geofixtures.adapters.reference import ReferenceAdapter
from geofixtures.registry import default_registry

_CASES = [case["case_id"] for case in list_cases()]


def _is_raster(value: Any) -> bool:
    return isinstance(value, str) and value.endswith(".tif")


def _is_cloud(value: Any) -> bool:
    return isinstance(value, str) and value.endswith(".las")


def _shift_raster(path: str) -> None:
    import rasterio

    with rasterio.open(path, "r+") as dataset:
        band = dataset.read(1)
        nodata = dataset.nodata
        changed = band.astype("float64") + 3.0
        if nodata is not None:
            changed = np.where(band == nodata, band, changed)
        dataset.write(changed.astype(band.dtype), 1)


def _corrupt(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value * 1.5 + 1
    if isinstance(value, str):
        return "CORRUPTED"
    if isinstance(value, list):
        return (
            [*value, "extra"]
            if not value or isinstance(value[0], str)
            else [_corrupt(item) for item in value]
        )
    if isinstance(value, dict):
        return {key: _corrupt(item) for key, item in value.items()} if value else {"extra": 1}
    raise TypeError(type(value))


class Corrupting(ReferenceAdapter):
    """Returns the reference answer with one observation damaged."""

    name = "corrupting"

    def __init__(self, key: str):
        self.key = key

    def execute(self, context: ExecutionContext) -> ObservationBundle:
        bundle = super().execute(context)
        value = bundle.values[self.key]
        if _is_raster(value):
            _shift_raster(value)
        elif _is_cloud(value):
            bundle.values[self.key] = "/missing/points.las"
        elif isinstance(value, str) and value.startswith(("POLYGON", "MULTIPOLYGON")):
            bundle.values[self.key] = "POLYGON ((0 0, 9 0, 9 9, 0 9, 0 0))"
        else:
            bundle.values[self.key] = _corrupt(value)
        return bundle


def _required_keys(manifest: dict[str, Any]) -> list[str]:
    keys = []
    for assertion in manifest["assertions"]:
        if assertion["kind"] != "expected_error":
            keys.append(assertion.get("observe", assertion["id"]))
    return sorted(set(keys))


@pytest.mark.parametrize("case_id", _CASES)
def test_corrupting_any_observation_breaks_case(case_id, tmp_path):
    fixture = materialize(case_id, tmp_path / "fixture")
    assert run_case(fixture, "reference").status is Status.PASS
    keys = _required_keys(fixture.manifest)
    expected_status = fixture.manifest["expected_status"]
    if expected_status == "rejection":
        keys = [key for key in keys if key not in ("partial_output_written", "features_loaded")]
    survivors = []
    for key in keys:
        result = run_case(fixture, Corrupting(key))
        if result.status is Status.PASS:
            survivors.append(key)
    assert not survivors, f"{case_id} still passed with corrupted {survivors}"


@pytest.mark.parametrize("case_id", _CASES)
def test_dropping_all_observations_never_passes(case_id, tmp_path):
    class Silent(ReferenceAdapter):
        name = "silent"

        def execute(self, context):
            return ObservationBundle()

    assert run_case(case_id, Silent()).status is not Status.PASS


@pytest.mark.parametrize(
    "case_id",
    [case_id for case_id in _CASES if default_registry().get(case_id).expected_status == "rejection"],
)
def test_rejection_cases_refuse_accepting_target(case_id):
    class Accepting(ReferenceAdapter):
        name = "accepting"

        def execute(self, context):
            return ObservationBundle(values={"accepted": True})

    assert run_case(case_id, Accepting()).status is Status.FAIL


def test_truncated_case_rejects_for_reference_adapter(tmp_path):
    result = run_case("raster.truncated.001", "reference")
    assert result.status is Status.PASS
    assert result.observed_rejection["code"] == "READ_FAILED"
