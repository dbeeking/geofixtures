from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from geofixtures import AssertionResult, CaseResult, Outcome, Status, SuiteResult
from geofixtures._version import REPORT_SCHEMA_VERSION
from geofixtures.models import OfflineViolation
from geofixtures.offline import offline_guard
from geofixtures.runner import results
from geofixtures.runner.results import (
    jsonable,
    junit_xml,
    observed_differences,
    text_report,
    write_json_report,
    write_junit_report,
)
from geofixtures.validation import load_schema


def _case(status, **extra):
    return CaseResult("a.b.001", "1.0.0", "demo", status, "success", **extra)


def _suite(*statuses, complete=True):
    return SuiteResult(
        run_id="r",
        adapter="demo",
        selectors=[],
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        complete=complete,
        environment={"python": "3.13"},
        adapter_environment={},
        cases=[_case(status) for status in statuses],
    )


@pytest.mark.parametrize(
    ("statuses", "code"),
    [
        ((Status.PASS,), 0),
        ((Status.PASS, Status.SKIP), 0),
        ((Status.PASS, Status.UNSUPPORTED), 0),
        ((Status.PASS, Status.FAIL), 1),
        ((Status.FAIL, Status.ERROR), 2),
        ((Status.PASS, Status.ERROR), 2),
        ((Status.SKIP, Status.UNSUPPORTED), 3),
        ((), 3),
    ],
)
def test_exit_codes(statuses, code):
    assert _suite(*statuses).exit_code() == code


def test_incomplete_runs_never_exit_clean():
    assert _suite(Status.PASS, complete=False).exit_code() == 2


def test_summary_counts_every_status():
    summary = _suite(Status.PASS, Status.FAIL).summary()
    assert summary == {"PASS": 1, "FAIL": 1, "SKIP": 0, "UNSUPPORTED": 0, "ERROR": 0, "total": 2}


def _detailed_suite():
    failing = AssertionResult(
        "area",
        "numeric",
        Outcome.FAIL,
        case_id="a.b.001",
        observed=np.float64(5.0),
        expected=4.0,
        tolerance={"absolute_tolerance": 0.1},
        unit="m2",
        message="too big",
    )
    suite = _suite()
    suite.cases = [
        _case(Status.FAIL, assertions=[failing], reason="", elapsed_seconds=0.5),
        CaseResult("a.c.001", "1.0.0", "demo", Status.ERROR, "success", reason="boom"),
        CaseResult("a.d.001", "1.0.0", "demo", Status.UNSUPPORTED, "success", reason="no"),
    ]
    return suite


def test_json_report_matches_its_schema():
    report = _detailed_suite().to_dict()
    jsonschema.validate(report, load_schema("report-v1.schema.json"))
    json.dumps(report)
    assert report["schema_version"] == REPORT_SCHEMA_VERSION


def test_junit_report_marks_each_status():
    root = ElementTree.fromstring(junit_xml(_detailed_suite().to_dict()))
    assert root.tag == "testsuite"
    assert root.attrib["tests"] == "3"
    assert root.attrib["failures"] == "1"
    assert root.attrib["errors"] == "1"
    assert root.attrib["skipped"] == "1"
    cases = {case.attrib["name"]: case for case in root.findall("testcase")}
    failure = cases["a.b.001"].find("failure")
    assert "expected=4.0" in failure.text and "observed=5.0" in failure.text
    assert cases["a.c.001"].find("error") is not None
    assert cases["a.d.001"].find("skipped") is not None
    names = {item.attrib["name"] for item in root.find("properties")}
    assert "env.python" in names and "complete" in names


def test_text_report_flags_incomplete_runs():
    assert "INCOMPLETE" in text_report(_suite(Status.PASS, complete=False).to_dict())
    assert "(complete)" in text_report(_suite(Status.PASS).to_dict())


def test_failure_text_has_reproduction_context():
    text = _detailed_suite().cases[0].failure_text()
    assert "area" in text and "expected: 4.0" in text and "tolerance" in text


def test_report_writes_are_atomic(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    write_json_report(path, {"first": True})

    def fail(_source, _target):
        raise OSError("disk full")

    monkeypatch.setattr(results.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        write_json_report(path, {"second": True})
    assert json.loads(path.read_text()) == {"first": True}
    assert [item.name for item in tmp_path.iterdir()] == ["report.json"]


def test_junit_writer_creates_parents(tmp_path):
    path = tmp_path / "deep" / "report.xml"
    write_junit_report(path, _suite(Status.PASS).to_dict())
    assert ElementTree.parse(path).getroot().tag == "testsuite"


def test_jsonable_handles_numpy_paths_sets_and_nan():
    converted = jsonable(
        {
            1: np.int64(2),
            "path": Path("/a"),
            "set": {2, 1},
            "array": np.array([1.0]),
            "nan": float("nan"),
            "inf": float("inf"),
        }
    )
    assert converted == {"1": 2, "path": "/a", "set": [1, 2], "array": [1.0], "nan": "nan", "inf": "inf"}
    json.dumps(converted, allow_nan=False)


def test_observed_differences_are_reported_even_when_both_pass():
    def report(adapter, value):
        suite = _suite()
        item = AssertionResult("area", "numeric", Outcome.PASS, observed=value)
        suite.adapter = adapter
        suite.cases = [_case(Status.PASS, assertions=[item])]
        return suite.to_dict()

    differences = observed_differences(report("one", 4.0), report("two", 4.0000001))
    assert len(differences) == 1
    assert differences[0]["left_outcome"] == differences[0]["right_outcome"] == "PASS"
    assert observed_differences(report("one", 4.0), report("two", 4.0)) == []


def test_offline_guard_blocks_and_restores():
    import socket

    original = socket.socket.connect
    with offline_guard():
        with socket.socket() as connection:
            with pytest.raises(OfflineViolation):
                connection.connect(("192.0.2.1", 80))
            with pytest.raises(OfflineViolation):
                connection.connect_ex(("192.0.2.1", 80))
    assert socket.socket.connect is original


def test_offline_guard_allows_local_sockets():
    import socket
    import tempfile

    # macOS limits socket paths to 104 bytes, and pytest's tmp_path is longer.
    with tempfile.TemporaryDirectory(dir="/tmp") as folder:
        path = f"{folder}/s"
        with socket.socket(socket.AF_UNIX) as server, offline_guard():
            server.bind(path)
            server.listen(1)
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(path)


def test_offline_guard_can_be_disabled():
    import socket

    original = socket.socket.connect
    with offline_guard(False):
        assert socket.socket.connect is original


def test_offline_guard_blocks_datagrams_and_lookups():
    import socket

    with offline_guard():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            with pytest.raises(OfflineViolation):
                connection.sendto(b"x", ("192.0.2.1", 53))
            with pytest.raises(OfflineViolation):
                connection.sendto(b"x", 0, ("192.0.2.1", 53))
        with pytest.raises(OfflineViolation):
            socket.getaddrinfo("example.com", 80)


def test_offline_guard_allows_loopback():
    import socket

    with socket.socket() as server, offline_guard():
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.socket() as client:
            client.connect(server.getsockname())
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
            datagram.sendto(b"x", ("127.0.0.1", 9))
        assert socket.getaddrinfo("localhost", 80)
