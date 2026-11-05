from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree

import pytest

from geofixtures import __version__
from geofixtures.cli import main

_CASE = "vector.overlap.001"


class AlwaysWrong:
    name = "wrong"

    def supports(self, case):
        from geofixtures import Capability

        return Capability(True)

    def execute(self, context):
        from geofixtures import ObservationBundle

        values = {
            "overlap_pairs": [],
            "overlap_area": 0.0,
            "union_area": 0.0,
            "overlap_geometry": "POINT (0 0)",
        }
        return ObservationBundle(values=values)

    def environment(self):
        return {}


class NeverSupports(AlwaysWrong):
    name = "never"

    def supports(self, case):
        from geofixtures import Capability

        return Capability(False, "Not implemented")


class Crashes(AlwaysWrong):
    name = "crashes"

    def execute(self, context):
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def importable(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "cli_adapters", sys.modules[__name__])


def test_list_as_json(capsys):
    assert main(["list", "--format", "json", "--select", "category:crs"]) == 0
    cases = json.loads(capsys.readouterr().out)
    assert len(cases) == 5


def test_list_as_text(capsys):
    assert main(["list", "--select", "tag:saddle"]) == 0
    assert "raster.ridge_saddle.001" in capsys.readouterr().out


def test_describe(capsys):
    assert main(["describe", _CASE]) == 0
    assert "analytic_geometry" in capsys.readouterr().out
    assert main(["describe", _CASE, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["case_id"] == _CASE


def test_describe_unknown_case_exits_2():
    assert main(["describe", "vector.missing.001"]) == 2


def test_generate_then_validate(tmp_path, capsys):
    target = tmp_path / "case"
    assert main(["generate", _CASE, "--output", str(target)]) == 0
    assert main(["validate", str(target / "manifest.json")]) == 0
    assert "OK" in capsys.readouterr().out


def test_generate_many(tmp_path):
    assert main(["generate", "--select", "category:crs", "--output", str(tmp_path / "all")]) == 0
    assert len(list((tmp_path / "all").iterdir())) == 5


def test_generate_refuses_existing_fixture_without_overwrite(tmp_path):
    target = tmp_path / "case"
    assert main(["generate", _CASE, "--output", str(target)]) == 0
    assert main(["generate", _CASE, "--output", str(target)]) == 2
    assert main(["generate", _CASE, "--output", str(target), "--overwrite"]) == 0


def test_generate_applies_limits(tmp_path):
    assert main(["generate", _CASE, "--output", str(tmp_path / "c"), "--max-bytes", "10"]) == 2


def test_generate_applies_feature_limit(tmp_path):
    assert main(["generate", _CASE, "--output", str(tmp_path / "c"), "--max-features", "1"]) == 2


def test_validate_reports_corruption(tmp_path, capsys):
    target = tmp_path / "case"
    main(["generate", _CASE, "--output", str(target)])
    (target / "truth" / "expected.json").write_text("{}")
    assert main(["validate", str(target)]) == 2
    assert "Checksum mismatch" in capsys.readouterr().err


def test_run_passing_exits_0(tmp_path):
    report = tmp_path / "report.json"
    assert main(["run", "--select", _CASE, "--report", str(report)]) == 0
    assert json.loads(report.read_text())["summary"]["PASS"] == 1


def test_run_failing_exits_1(capsys):
    assert main(["run", "--select", _CASE, "--adapter", "cli_adapters:AlwaysWrong"]) == 1
    assert "overlap_area" in capsys.readouterr().err


def test_run_error_exits_2():
    assert main(["run", "--select", _CASE, "--adapter", "cli_adapters:Crashes"]) == 2


def test_run_with_nothing_executable_exits_3():
    assert main(["run", "--select", _CASE, "--adapter", "cli_adapters:NeverSupports"]) == 3


def test_run_with_bad_selector_exits_2():
    assert main(["run", "--select", "tag:none"]) == 2


def test_run_with_bad_adapter_exits_2():
    assert main(["run", "--select", _CASE, "--adapter", "nothing"]) == 2


def test_bad_arguments_exit_2():
    with pytest.raises(SystemExit) as caught:
        main(["run", "--unknown"])
    assert caught.value.code == 2


def test_junit_report_from_run(tmp_path):
    report = tmp_path / "report.xml"
    assert main(["run", "--select", _CASE, "--report", str(report), "--format", "junit"]) == 0
    assert ElementTree.parse(report).getroot().attrib["tests"] == "1"


def test_run_keeps_fixtures_when_asked(tmp_path):
    assert main(["run", "--select", _CASE, "--output", str(tmp_path / "fixtures")]) == 0
    assert (tmp_path / "fixtures" / _CASE / "manifest.json").is_file()


def test_run_uses_seed_and_timeout():
    assert main(["run", "--select", _CASE, "--seed", "7", "--timeout", "60", "--no-offline"]) == 0


def test_run_keep_failures(tmp_path):
    kept = tmp_path / "kept"
    code = main(
        ["run", "--select", _CASE, "--adapter", "cli_adapters:AlwaysWrong", "--keep-failures", str(kept)]
    )
    assert code == 1
    assert (kept / _CASE).is_dir()


def test_report_renders_saved_results(tmp_path, capsys):
    results = tmp_path / "report.json"
    main(["run", "--select", _CASE, "--report", str(results)])
    capsys.readouterr()
    assert main(["report", str(results)]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["report", str(results), "--format", "junit"]) == 0
    assert "<testsuite" in capsys.readouterr().out
    assert main(["report", str(results), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["complete"] is True
    target = tmp_path / "out.txt"
    assert main(["report", str(results), "--output", str(target)]) == 0
    assert target.read_text()


def test_report_compares_two_runs(tmp_path, capsys):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    main(["run", "--select", _CASE, "--report", str(left)])
    main(["run", "--select", _CASE, "--adapter", "cli_adapters:AlwaysWrong", "--report", str(right)])
    capsys.readouterr()
    assert main(["report", str(left), "--compare", str(right)]) == 0
    differences = json.loads(capsys.readouterr().out)
    assert {item["assertion_id"] for item in differences} >= {"overlap_area", "union_area"}


def test_doctor(capsys):
    assert main(["doctor"]) == 0
    assert "python" in capsys.readouterr().out
    assert main(["doctor", "--format", "json"]) == 0
    details = json.loads(capsys.readouterr().out)
    assert details["features"]["raster"] is True


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert f"geofixtures {__version__}" in capsys.readouterr().out
