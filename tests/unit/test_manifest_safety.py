from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from geofixtures import Status, materialize, run_case, validate
from geofixtures.models import (
    LimitExceededError,
    Limits,
    ManifestError,
    MaterializedCase,
    MissingDependencyError,
    OverrideError,
    UnsafePathError,
)
from geofixtures.paths import resolve_inside
from geofixtures.validation import check_manifest_schema, load_manifest, load_schema

_CASE = "vector.overlap.001"


@pytest.fixture
def fixture(tmp_path) -> MaterializedCase:
    return materialize(_CASE, tmp_path / "case")


def _rewrite(fixture, change):
    manifest = json.loads(fixture.manifest_path.read_text())
    change(manifest)
    fixture.manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    "path", ["../outside", "/etc/passwd", "a/../../b", "", "a\\b", "..", "input/../../x"]
)
def test_unsafe_paths_are_refused(tmp_path, path):
    with pytest.raises(UnsafePathError):
        resolve_inside(tmp_path, path)


def test_symlinks_cannot_leave_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    os.symlink(secret, root / "link")
    with pytest.raises(UnsafePathError, match="escapes"):
        resolve_inside(root, "link")


def test_plain_paths_resolve(tmp_path):
    assert resolve_inside(tmp_path, "a/b.txt") == tmp_path.resolve() / "a" / "b.txt"


def test_generated_fixture_is_valid(fixture):
    assert validate(fixture.manifest_path).ok
    assert validate(fixture.root).ok


def test_manifest_holds_required_fields(fixture):
    manifest = fixture.manifest
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["truth"]["review_status"] == "pending_independent_review"
    assert manifest["license"] == {"identifier": "MIT", "redistributable": True}
    assert manifest["inputs"][0]["profile"] == "GeoParquet 1.1.0"
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])


def test_changed_input_fails_validation(fixture):
    with open(fixture.root / "input" / "features.parquet", "ab") as stream:
        stream.write(b"x")
    report = validate(fixture.manifest_path)
    assert not report.ok
    assert "Checksum mismatch" in report.errors[0]


def test_changed_truth_fails_validation(fixture):
    (fixture.root / "truth" / "expected.json").write_text("{}")
    assert any("truth/expected.json" in error for error in validate(fixture.manifest_path).errors)


def test_deleted_file_fails_validation(fixture):
    (fixture.root / "truth" / "expected.json").unlink()
    assert any("Missing file" in error for error in validate(fixture.manifest_path).errors)


def test_traversal_in_manifest_fails_validation(fixture):
    _rewrite(fixture, lambda manifest: manifest["files"].append({"path": "../x", "sha256": "0" * 64}))
    assert any("Unsafe" in error for error in validate(fixture.manifest_path).errors)


def test_unlisted_input_fails_validation(fixture):
    _rewrite(fixture, lambda manifest: manifest["inputs"][0].update(path="input/other.parquet"))
    assert any("inventory" in error for error in validate(fixture.manifest_path).errors)


def test_unlisted_truth_fails_validation(fixture):
    _rewrite(fixture, lambda manifest: manifest["truth"].update(path="truth/other.json"))
    assert any("inventory" in error for error in validate(fixture.manifest_path).errors)


def test_duplicate_assertion_ids_fail_validation(fixture):
    _rewrite(fixture, lambda manifest: manifest["assertions"].append(manifest["assertions"][0]))
    assert any("unique" in error for error in validate(fixture.manifest_path).errors)


def test_unsupported_major_version_is_refused(fixture):
    _rewrite(fixture, lambda manifest: manifest.update(schema_version="2.0.0"))
    assert "Unsupported" in validate(fixture.manifest_path).errors[0]


def test_wrong_types_are_refused(fixture):
    _rewrite(fixture, lambda manifest: manifest.update(seed="forty-two"))
    assert not validate(fixture.manifest_path).ok


def test_placeholder_hashes_are_refused(fixture):
    def change(manifest):
        manifest["files"][0]["sha256"] = "<64-hex-at-materialization>"

    _rewrite(fixture, change)
    assert not validate(fixture.manifest_path).ok


def test_malformed_json_is_reported(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{")
    assert "valid JSON" in validate(path).errors[0]


def test_non_object_manifest_is_reported(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("[]")
    assert "object" in validate(path).errors[0]


def test_missing_manifest_is_reported(tmp_path):
    assert "Missing" in validate(tmp_path / "none.json").errors[0]


def test_oversized_manifest_is_refused(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises(ManifestError, match="too large"):
        load_manifest(path)


def test_schemas_ship_in_both_locations():
    for name in ("manifest-v1.schema.json", "report-v1.schema.json"):
        top_level = Path(__file__).parents[2] / "schemas" / name
        assert json.loads(top_level.read_text()) == load_schema(name)


def test_schema_helper_lists_problems():
    assert check_manifest_schema({})


def test_existing_folders_are_protected(tmp_path):
    target = tmp_path / "case"
    target.mkdir()
    (target / "mine.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        materialize(_CASE, target)
    with pytest.raises(FileExistsError, match="isn't a GeoFixtures"):
        materialize(_CASE, target, overwrite=True)
    assert (target / "mine.txt").read_text() == "keep"


def test_overwrite_replaces_only_fixture(fixture):
    (fixture.root / "extra.txt").write_text("old")
    with pytest.raises(FileExistsError):
        materialize(_CASE, fixture.root)
    materialize(_CASE, fixture.root, overwrite=True)
    assert not (fixture.root / "extra.txt").exists()


def test_failed_generation_leaves_nothing(tmp_path):
    with pytest.raises(LimitExceededError):
        materialize("lidar.density.001", tmp_path / "case", limits=Limits(max_points=10))
    assert not list(tmp_path.iterdir())


def test_pixel_limit_stops_fixture(tmp_path):
    with pytest.raises(LimitExceededError, match="pixels"):
        materialize("raster.dem.slope.001", tmp_path / "case", limits=Limits(max_pixels=10))
    assert not list(tmp_path.iterdir())


def test_byte_limit_stops_fixture(tmp_path):
    with pytest.raises(LimitExceededError, match="bytes"):
        materialize(_CASE, tmp_path / "case", limits=Limits(max_bytes=10))
    assert not list(tmp_path.iterdir())


def test_overrides_must_be_declared(tmp_path):
    with pytest.raises(OverrideError):
        materialize(_CASE, tmp_path / "case", overrides={"width": 10})


def test_declared_overrides_keep_answers_correct(tmp_path):
    fixture = materialize("raster.tile_seam.001", tmp_path / "case", overrides={"tile_size": 32})
    assert fixture.manifest["parameters"]["tile_size"] == 32
    assert fixture.manifest["generator_parameters"]["tile_size"] == 32
    assert run_case(fixture, "reference").status is Status.PASS


def test_numeric_assertions_must_state_units(fixture):
    def change(manifest):
        del manifest["assertions"][1]["unit"]

    _rewrite(fixture, change)
    assert any("unit" in error for error in validate(fixture.manifest_path).errors)


@pytest.mark.parametrize(
    ("case_id", "kind", "field"),
    [
        ("raster.dem.slope.001", "raster_values", "absolute_tolerance"),
        ("raster.dem.slope.001", "raster_values", "truth"),
        ("landcover.scene.rgbnir.001", "classification_metrics", "zero_division"),
        ("landcover.scene.rgbnir.001", "classification_metrics", "ignore_values"),
        ("landcover.scene.rgbnir.001", "classification_metrics", "averaging"),
        ("vector.overlap.001", "geometry_equivalent", "policy"),
    ],
)
def test_assertions_must_state_their_policies(tmp_path, case_id, kind, field):
    fixture = materialize(case_id, tmp_path / "case")

    def change(manifest):
        target = next(item for item in manifest["assertions"] if item["kind"] == kind)
        del target[field]

    _rewrite(fixture, change)
    assert not validate(fixture.manifest_path).ok


def test_missing_extras_are_named(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules["geofixtures.materialize"], "missing_extras", lambda _spec: ["raster"])
    with pytest.raises(MissingDependencyError, match="geofixtures\\[raster\\]"):
        materialize(_CASE, tmp_path / "case")
