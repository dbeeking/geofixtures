"""Checks against the installed LandFuse.

Set GEOFIXTURES_REQUIRE_LANDFUSE=1 to fail instead of skip when LandFuse or PDAL
is missing.
"""

from __future__ import annotations

import os
import shutil
from importlib import util
from pathlib import Path

import pytest

from geofixtures import CaseView, Status, load_policy, run_case, run_suite
from geofixtures.adapters.landfuse import LandFuseAdapter

REQUIRED = os.environ.get("GEOFIXTURES_REQUIRE_LANDFUSE") == "1"

if util.find_spec("landfuse") is None:
    if REQUIRED:
        raise RuntimeError("GEOFIXTURES_REQUIRE_LANDFUSE is set, but LandFuse isn't installed")
    pytest.skip("LandFuse isn't installed", allow_module_level=True)


def _need_pdal():
    if shutil.which("pdal") is None:
        if REQUIRED:
            pytest.fail("GEOFIXTURES_REQUIRE_LANDFUSE is set, but pdal isn't installed")
        pytest.skip("Needs the pdal command")


_NO_PDAL = (
    "raster.dem.slope.001",
    "raster.ridge_saddle.001",
    "raster.depression.001",
    "raster.nodata_hole.001",
    "raster.tile_seam.001",
    "raster.truncated.001",
    "raster.partial_coverage.001",
    "landcover.scene.rgbnir.001",
    "landcover.missing_nir.001",
    "landcover.truth_mask.001",
    "landcover.unknown.001",
    "landcover.pair.dem.001",
    "landcover.image_collar.001",
    "landcover.sampling_spread.001",
    "landcover.spatial_leakage.001",
)


@pytest.mark.parametrize("case_id", _NO_PDAL)
def test_landfuse_passes(case_id):
    result = run_case(case_id, "landfuse", timeout=120)
    assert result.status is Status.PASS, result.failure_text()


@pytest.mark.parametrize("case_id", ["landcover.pair.lidar.001", "lidar.ground_gap.001"])
def test_landfuse_lidar(case_id):
    _need_pdal()
    result = run_case(case_id, "landfuse", timeout=300)
    assert result.status is Status.PASS, result.failure_text()


def test_missing_features_are_reported_as_unsupported():
    result = run_suite(["id:lidar.density.001", "id:raster.grid.offset.001", "category:vector"], "landfuse")
    assert {case.status for case in result.cases} == {Status.UNSUPPORTED}
    assert result.exit_code() == 3


def test_environment_names_version():
    assert LandFuseAdapter().environment()["landfuse"]


def _view(operation):
    return CaseView("x.y.001", operation, (), {}, ())


def test_capability_reasons_explain_gap():
    assert "resamples" in LandFuseAdapter().supports(_view("raster.alignment")).reason
    assert LandFuseAdapter().supports(_view("raster.slope")).supported


def test_no_pdal_is_skip(monkeypatch):
    monkeypatch.setattr("geofixtures.adapters.landfuse.which", lambda _name: None)
    capability = LandFuseAdapter().supports(_view("lidar.chm"))
    assert not capability.supported and capability.skip


def test_strict_run_matches_the_example_policy():
    policy = load_policy(Path(__file__).parents[2] / "examples" / "landfuse" / "geofixtures-policy.toml")
    selected = ["id:raster.dem.slope.001", *[f"id:{case_id}" for case_id in policy.allow_unsupported]]
    result = run_suite(selected, "landfuse", policy=policy)
    assert result.exit_code() == 0
    assert result.summary()["UNSUPPORTED"] == len(policy.allow_unsupported) == 4
