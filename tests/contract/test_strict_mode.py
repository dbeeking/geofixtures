from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree

import jsonschema
import pytest

from geofixtures import Capability, ObservationBundle, Status, StrictPolicy, load_policy, run_suite
from geofixtures.adapters.reference import ReferenceAdapter
from geofixtures.cli import main
from geofixtures.models import PolicyError
from geofixtures.runner.results import junit_xml, text_report
from geofixtures.validation import load_schema

_GAP = "vector.gap.001"
_SELECT = ["id:vector.overlap.001", f"id:{_GAP}"]


class PartialAdapter(ReferenceAdapter):
    """Supports overlap only, like a target with a missing feature."""

    name = "partial"
    skip = False

    def supports(self, case):
        if case.case_id == _GAP:
            return Capability(False, "No gap report yet", skip=self.skip)
        return super().supports(case)


class SkippingAdapter(PartialAdapter):
    name = "skipping"
    skip = True


class SilentAdapter(ReferenceAdapter):
    name = "silent"

    def execute(self, context):
        return ObservationBundle()


class Unsupported(ReferenceAdapter):
    name = "unsupported"

    def supports(self, case):
        return Capability(False, "Nothing implemented")


def _allow(*ids):
    return StrictPolicy(allow_unsupported={case_id: "Not built yet" for case_id in ids})


def test_exploratory_runs_keep_their_exit_code():
    assert run_suite(_SELECT, PartialAdapter()).exit_code() == 0


def test_exploratory_text_says_cases_did_not_run():
    text = text_report(run_suite(_SELECT, PartialAdapter()).to_dict())
    assert "1 of 2 cases didn't run" in text


def test_strict_fails_on_unsupported():
    result = run_suite(_SELECT, PartialAdapter(), policy=StrictPolicy())
    assert result.exit_code() == 4
    assert [item.rule for item in result.violations()] == ["unexpected_unsupported"]


def test_strict_accepts_allowed_gap():
    result = run_suite(_SELECT, PartialAdapter(), policy=_allow(_GAP))
    assert result.exit_code() == 0
    assert not result.violations()


def test_strict_never_allows_skip():
    result = run_suite(_SELECT, SkippingAdapter(), policy=_allow(_GAP))
    assert result.exit_code() == 4
    assert [item.rule for item in result.violations()] == ["unexpected_skip"]


def test_gap_that_now_passes_must_leave_allowlist():
    result = run_suite(_SELECT, ReferenceAdapter(), policy=_allow(_GAP))
    assert result.exit_code() == 4
    assert [item.rule for item in result.violations()] == ["stale_allowance"]


def test_allowed_cases_cannot_hide_failure():
    result = run_suite([f"id:{_GAP}"], SilentAdapter(), policy=_allow(_GAP))
    assert result.cases[0].status is Status.ERROR
    assert result.exit_code() == 2


def test_failures_outrank_strict_violations():
    class Wrong(PartialAdapter):
        def execute(self, context):
            return ObservationBundle(
                values={
                    "overlap_pairs": [],
                    "overlap_area": 0.0,
                    "union_area": 0.0,
                    "overlap_geometry": "POINT (0 0)",
                }
            )

    assert run_suite(_SELECT, Wrong(), policy=StrictPolicy()).exit_code() == 1


def test_all_allowed_gaps_still_mean_nothing_ran():
    result = run_suite([f"id:{_GAP}"], Unsupported(), policy=_allow(_GAP))
    assert result.exit_code() == 3


def test_missing_extras_fail_strict(monkeypatch):
    import sys

    module = sys.modules["geofixtures.api"]
    monkeypatch.setattr(module, "missing_extras", lambda _spec: ["vector"])
    result = run_suite(_SELECT, ReferenceAdapter(), policy=StrictPolicy())
    assert result.exit_code() == 4


def test_unknown_ids_in_policy_are_refused():
    with pytest.raises(PolicyError, match="vector.typo.001"):
        run_suite(_SELECT, ReferenceAdapter(), policy=_allow("vector.typo.001"))


def test_report_records_policy():
    result = run_suite(_SELECT, PartialAdapter(), policy=_allow(_GAP))
    report = result.to_dict()
    jsonschema.validate(report, load_schema("report-v1.schema.json"))
    assert report["schema_version"] == "1.1.0"
    assert report["strict"] == {
        "enabled": True,
        "allow_unsupported": {_GAP: "Not built yet"},
        "violations": [],
    }


def test_exploratory_reports_say_strict_was_off():
    assert run_suite(_SELECT, PartialAdapter()).to_dict()["strict"]["enabled"] is False


def test_junit_marks_violations_as_failures():
    report = run_suite(_SELECT, PartialAdapter(), policy=StrictPolicy()).to_dict()
    root = ElementTree.fromstring(junit_xml(report))
    assert root.attrib["failures"] == "1"
    assert root.attrib["skipped"] == "0"
    case = next(item for item in root.findall("testcase") if item.attrib["name"] == _GAP)
    assert "unexpected_unsupported" in case.find("failure").attrib["message"]


def test_junit_keeps_allowed_gaps_as_skipped():
    report = run_suite(_SELECT, PartialAdapter(), policy=_allow(_GAP)).to_dict()
    root = ElementTree.fromstring(junit_xml(report))
    assert root.attrib["failures"] == "0"
    assert root.attrib["skipped"] == "1"


def test_junit_marks_stale_allowance_as_failure():
    report = run_suite(_SELECT, ReferenceAdapter(), policy=_allow(_GAP)).to_dict()
    root = ElementTree.fromstring(junit_xml(report))
    assert root.attrib["failures"] == "1"
    assert root.attrib["skipped"] == "0"


def test_text_report_lists_violations():
    text = text_report(run_suite(_SELECT, PartialAdapter(), policy=StrictPolicy()).to_dict())
    assert "Strict mode: 1 violations" in text
    assert _GAP in text


def _policy_file(tmp_path, text):
    path = tmp_path / "policy.toml"
    path.write_text(text)
    return path


def test_policy_file_round_trip(tmp_path):
    path = _policy_file(tmp_path, f'[allow_unsupported]\n"{_GAP}" = "Not built yet"\n')
    assert load_policy(path).allow_unsupported == {_GAP: "Not built yet"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[allow_unsupported\n", "TOML"),
        ('[allow_skip]\n"a" = "b"\n', "Unknown policy keys"),
        ('allow_unsupported = "everything"\n', "table"),
        (f'[allow_unsupported]\n"{_GAP}" = ""\n', "reason"),
        (f'[allow_unsupported]\n"{_GAP}" = 1\n', "reason"),
    ],
)
def test_bad_policy_files_are_refused(tmp_path, text, message):
    with pytest.raises(PolicyError, match=message):
        load_policy(_policy_file(tmp_path, text))


def test_cli_strict_exit_code(tmp_path, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "strict_adapters", sys.modules[__name__])
    arguments = [
        "run",
        "--select",
        _SELECT[0],
        "--select",
        _SELECT[1],
        "--adapter",
        "strict_adapters:PartialAdapter",
    ]
    assert main(arguments) == 0
    assert main([*arguments, "--strict"]) == 4
    policy = _policy_file(tmp_path, f'[allow_unsupported]\n"{_GAP}" = "Not built yet"\n')
    report = tmp_path / "report.json"
    assert main([*arguments, "--policy", str(policy), "--report", str(report)]) == 0
    assert json.loads(report.read_text())["strict"]["enabled"] is True


def test_cli_rejects_bad_policy(tmp_path):
    policy = _policy_file(tmp_path, f'[allow_unsupported]\n"{_GAP}" = ""\n')
    assert main(["run", "--select", _SELECT[0], "--policy", str(policy)]) == 2
    assert main(["run", "--select", _SELECT[0], "--policy", str(tmp_path / "none.toml")]) == 2


def test_cli_report_keeps_strict_failures_visible(tmp_path, capsys):
    report = tmp_path / "report.json"
    assert main(["run", "--select", _SELECT[0], "--report", str(report), "--strict"]) == 0
    capsys.readouterr()
    assert main(["report", str(report)]) == 0
    assert "Strict mode: 0 violations" in capsys.readouterr().out


def test_old_reports_still_render(tmp_path, capsys):
    report = run_suite(_SELECT, ReferenceAdapter()).to_dict()
    del report["strict"]
    path = tmp_path / "old.json"
    path.write_text(json.dumps(report))
    assert main(["report", str(path)]) == 0
    assert main(["report", str(path), "--format", "junit"]) == 0
