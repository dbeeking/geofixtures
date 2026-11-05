"""Runner behavior for wrong, missing, and tampered results."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from geofixtures import (
    Capability,
    CaseView,
    ExecutionContext,
    ObservationBundle,
    Outcome,
    Rejection,
    Status,
    materialize,
    run_case,
    run_suite,
)
from geofixtures.adapters import load_adapter
from geofixtures.adapters.reference import ReferenceAdapter
from geofixtures.models import AdapterError, CaseNotFoundError, OfflineViolation

_OVERLAP = "vector.overlap.001"
_REJECTION = "crs.axis_order.001"
_UNCERTAIN = "crs.mislabeled.001"


class Scripted:
    """An adapter that does exactly what a test tells it to."""

    name = "scripted"

    def __init__(self, action=None, capability=None):
        self.action = action or (lambda _context: ObservationBundle())
        self.capability = capability or Capability(True)
        self.seen: list[ExecutionContext] = []

    def supports(self, case: CaseView) -> Capability:
        return self.capability

    def execute(self, context: ExecutionContext) -> ObservationBundle:
        self.seen.append(context)
        return self.action(context)

    def environment(self) -> dict:
        return {}


def test_reference_adapter_passes():
    assert run_case(_OVERLAP).status == "PASS"


def test_adapter_cannot_reach_truth_or_manifest(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    adapter = Scripted()
    run_case(fixture, adapter)
    context = adapter.seen[0]
    work_root = context.work_dir.parent
    visible = {path.name for path in work_root.rglob("*")} if work_root.exists() else set()
    assert "expected.json" not in visible and "manifest.json" not in visible
    for paths in context.inputs.values():
        for path in paths:
            assert fixture.root.resolve() not in path.resolve().parents


def test_case_view_has_no_expected_values(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    adapter = Scripted()
    run_case(fixture, adapter)
    public = adapter.seen[0].case
    assert public.case_id == _OVERLAP
    assert not hasattr(public, "assertions")
    assert not hasattr(public, "truth")


def test_adapter_that_edits_inputs_cannot_change_fixture(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")

    def vandalize(context):
        context.input("features").write_bytes(b"gone")
        return ObservationBundle()

    run_case(fixture, Scripted(vandalize))
    assert run_case(fixture, "reference").status is Status.PASS


def test_tampered_truth_stops_run(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    (fixture.root / "truth" / "expected.json").write_text('{"overlap_area_m2": 99}')
    result = run_case(fixture, "reference")
    assert result.status is Status.ERROR
    assert "validation" in result.reason
    assert not result.assertions


def test_edited_expected_value_with_stale_input_still_fails(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    manifest = json.loads(fixture.manifest_path.read_text())
    manifest["assertions"][1]["expected"] = 5.0
    fixture.manifest_path.write_text(json.dumps(manifest))
    assert run_case(fixture, "reference").status is Status.FAIL


def test_tampered_input_stops_run(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    with open(fixture.root / "input" / "features.parquet", "ab") as stream:
        stream.write(b"x")
    assert run_case(fixture, "reference").status is Status.ERROR


def test_wrong_answer_fails():
    def wrong(_context):
        values = {
            "overlap_pairs": ["A|B"],
            "overlap_area": 4.5,
            "union_area": 36.0,
            "overlap_geometry": "POINT (0 0)",
        }
        return ObservationBundle(values=values)

    result = run_case(_OVERLAP, Scripted(wrong))
    assert result.status is Status.FAIL
    failed = [item for item in result.assertions if item.outcome is Outcome.FAIL]
    assert {item.assertion_id for item in failed} == {"overlap_area", "overlap_geometry"}
    assert all(item.case_id == _OVERLAP for item in result.assertions)


def test_empty_answer_is_error_not_pass():
    assert run_case(_OVERLAP, Scripted()).status is Status.ERROR


def test_exception_is_error_not_failure():
    def explode(_context):
        raise RuntimeError("boom")

    result = run_case(_OVERLAP, Scripted(explode))
    assert result.status is Status.ERROR
    assert "boom" in result.reason


def test_supports_exception_is_error():
    class Broken(Scripted):
        def supports(self, case):
            raise RuntimeError("boom")

    assert run_case(_OVERLAP, Broken()).status is Status.ERROR


def test_unexpected_rejection_fails():
    adapter = Scripted(lambda _context: ObservationBundle(rejection=Rejection("NO")))
    result = run_case(_OVERLAP, adapter)
    assert result.status is Status.FAIL
    assert result.observed_rejection == {"code": "NO", "message": ""}


def test_accepting_bad_input_fails():
    adapter = Scripted(lambda _context: ObservationBundle(values={"position_valid": True}))
    assert run_case(_REJECTION, adapter).status is Status.FAIL


def test_declared_rejection_passes_with_its_outcome():
    adapter = Scripted(lambda _context: ObservationBundle(rejection=Rejection("AXIS_ORDER_SUSPECT")))
    result = run_case(_REJECTION, adapter)
    assert result.status is Status.PASS
    assert result.assertions[0].outcome is Outcome.EXPECTED_REJECTION


def test_rejection_with_wrong_code_fails():
    adapter = Scripted(lambda _context: ObservationBundle(rejection=Rejection("OTHER")))
    assert run_case(_REJECTION, adapter).status is Status.FAIL


def test_uncertain_case_accepts_rejection():
    adapter = Scripted(lambda _context: ObservationBundle(rejection=Rejection("BAD_CRS")))
    assert run_case(_UNCERTAIN, adapter).status is Status.PASS


def test_uncertain_case_refuses_confident_answer():
    values = {"label_consistent": True, "correction": "EPSG:32612"}
    assert run_case(_UNCERTAIN, Scripted(lambda _c: ObservationBundle(values=values))).status is Status.FAIL


def test_optional_value_missing_after_rejection_is_skipped():
    adapter = Scripted(lambda _context: ObservationBundle(rejection=Rejection("READ_FAILED")))
    result = run_case("raster.truncated.001", adapter)
    assert result.status is Status.PASS
    outcomes = {item.assertion_id: item.outcome for item in result.assertions}
    assert outcomes["partial_output_written"] is Outcome.SKIP


def test_unsupported_and_skip_are_distinct():
    no = run_case(_OVERLAP, Scripted(capability=Capability(False, "no feature")))
    later = run_case(_OVERLAP, Scripted(capability=Capability(False, "no tool", skip=True)))
    assert no.status is Status.UNSUPPORTED
    assert later.status is Status.SKIP
    assert no.reason == "no feature"


def test_case_with_only_skipped_assertions_is_not_pass(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    manifest = json.loads(fixture.manifest_path.read_text())
    for assertion in manifest["assertions"]:
        assertion["optional"] = True
    fixture.manifest_path.write_text(json.dumps(manifest))
    result = run_case(fixture, Scripted())
    assert result.status is Status.UNSUPPORTED


def test_case_with_no_assertions_is_not_pass(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    manifest = json.loads(fixture.manifest_path.read_text())
    manifest["assertions"] = []
    fixture.manifest_path.write_text(json.dumps(manifest))
    assert run_case(fixture, "reference").status is Status.UNSUPPORTED


def test_run_folders_are_removed():
    adapter = Scripted()
    run_case(_OVERLAP, adapter)
    assert not adapter.seen[0].work_dir.parent.exists()


def test_failure_artifacts_can_be_kept(tmp_path):
    def wrong(context):
        (context.work_dir / "answer.txt").write_text("x")
        return ObservationBundle(values={"overlap_area": 0.0})

    result = run_case(_OVERLAP, Scripted(wrong), retain_dir=tmp_path / "kept")
    assert (tmp_path / "kept" / _OVERLAP / "answer.txt").is_file()
    assert result.artifacts[0]["path"].endswith("answer.txt")
    assert len(result.artifacts[0]["sha256"]) == 64


def test_passing_runs_keep_nothing(tmp_path):
    run_case(_OVERLAP, "reference", retain_dir=tmp_path / "kept")
    assert not (tmp_path / "kept").exists()


def test_network_use_is_blocked_during_run():
    import socket

    def connect(_context):
        with socket.socket() as connection:
            connection.connect(("192.0.2.1", 80))
        return ObservationBundle()

    result = run_case(_OVERLAP, Scripted(connect))
    assert result.status is Status.ERROR
    assert OfflineViolation.__name__ in result.reason


def test_interrupted_suite_is_marked_incomplete():
    def interrupt(_context):
        raise KeyboardInterrupt

    class Interrupting(Scripted):
        def execute(self, context):
            raise KeyboardInterrupt

    result = run_suite(["category:crs"], Interrupting(interrupt))
    assert result.complete is False
    assert result.exit_code() == 2


def test_suite_order_is_stable():
    first = run_suite(["category:crs"])
    second = run_suite(["category:crs"])
    assert [case.case_id for case in first.cases] == sorted(case.case_id for case in first.cases)
    assert [case.case_id for case in first.cases] == [case.case_id for case in second.cases]


def test_broken_fixture_reports_its_path(tmp_path):
    (tmp_path / "manifest.json").write_text("{")
    result = run_case(tmp_path, "reference")
    assert result.status is Status.ERROR


def test_unknown_case_ids_raise():
    with pytest.raises(CaseNotFoundError):
        run_case("vector.missing.001")


def test_adapters_load_from_module_path():
    assert isinstance(load_adapter("geofixtures.adapters.reference:ReferenceAdapter"), ReferenceAdapter)


def test_adapters_load_from_entry_point_name():
    assert load_adapter("reference").name == "reference"


@pytest.mark.parametrize("name", ["nothing", "no.module:Class", "geofixtures:Missing", "module_only:"])
def test_bad_adapter_names_raise(name):
    with pytest.raises(AdapterError):
        load_adapter(name)


def test_run_case_accepts_path_string(tmp_path):
    fixture = materialize(_OVERLAP, tmp_path / "fixture")
    assert run_case(str(fixture.root), "reference").status is Status.PASS
    assert run_case(Path(fixture.manifest_path), "reference").status is Status.PASS
