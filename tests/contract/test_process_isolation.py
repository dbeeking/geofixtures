from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from tests import helpers

from geofixtures import Outcome, Status, run_case, run_suite
from geofixtures.adapters.reference import ReferenceAdapter

_CASE = "vector.overlap.001"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = open(f"/proc/{pid}/stat").read() if os.path.exists(f"/proc/{pid}/stat") else ""
    return " Z " not in stat


def _wait_until_gone(pid, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _wait_for_file(path, seconds=30.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text():
            return
        time.sleep(0.02)
    raise AssertionError(f"{path} never appeared")


def test_timeout_stops_work(tmp_path):
    marker = tmp_path / "marker"
    result = run_case(_CASE, helpers.Sleeper(marker, 1.5), timeout=0.5)
    assert result.status is Status.ERROR
    assert "stopped" in result.reason
    time.sleep(1.5)
    assert not marker.exists()


def test_timeout_stops_child_processes(tmp_path):
    pid_file = tmp_path / "pid"
    result = run_case(_CASE, helpers.ChildStarter(pid_file), timeout=8.0)
    assert result.status is Status.ERROR
    assert _wait_until_gone(int(pid_file.read_text()))


def test_children_left_behind_are_stopped_after_normal_return(tmp_path):
    pid_file = tmp_path / "pid"
    result = run_case(_CASE, helpers.BackgroundChild(pid_file), isolate=True)
    assert result.status is Status.PASS
    assert _wait_until_gone(int(pid_file.read_text()))


def test_permission_errors_from_killpg_are_tolerated(monkeypatch):
    def refuse(_group, _number):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "killpg", refuse)
    assert run_case(_CASE, "reference", isolate=True).status is Status.PASS


def test_process_ignoring_sigterm_is_killed():
    started = time.monotonic()
    result = run_case(_CASE, helpers.IgnoresTerm(), timeout=1.0)
    assert result.status is Status.ERROR
    assert time.monotonic() - started < 10


def test_results_cross_process_boundary():
    result = run_case(_CASE, "reference", timeout=60)
    assert result.status is Status.PASS
    assert {item.outcome for item in result.assertions} == {Outcome.PASS}


def test_numpy_values_cross_process_boundary():
    assert run_case(_CASE, helpers.ReportsNumpy(), isolate=True).status is Status.PASS


def test_non_finite_values_still_fail_after_crossing():
    result = run_case(_CASE, helpers.NotANumber(), isolate=True)
    assert result.status is Status.FAIL
    failed = {item.assertion_id for item in result.assertions if item.outcome is Outcome.FAIL}
    assert {"overlap_area", "union_area"} <= failed


def test_rejections_cross_process_boundary():
    result = run_case("crs.axis_order.001", helpers.Rejects(), isolate=True)
    assert result.status is Status.PASS
    assert result.observed_rejection["code"] == "AXIS_ORDER_SUSPECT"


def test_adapter_exception_is_error():
    result = run_case(_CASE, helpers.Raises(), isolate=True)
    assert result.status is Status.ERROR
    assert "boom" in result.reason


def test_exit_without_result_is_error():
    result = run_case(_CASE, helpers.Crashes(), isolate=True)
    assert result.status is Status.ERROR
    assert "code 7" in result.reason


def test_native_crash_is_contained():
    result = run_suite(["id:vector.overlap.001", "id:vector.gap.001"], helpers.KilledBySignal(), isolate=True)
    assert result.complete
    assert [case.status for case in result.cases] == [Status.ERROR, Status.ERROR]
    assert "-9" in result.cases[0].reason


def test_unserializable_observations_are_error():
    result = run_case(_CASE, helpers.BadValue(), isolate=True)
    assert result.status is Status.ERROR
    assert "serializable" in result.reason


def test_worker_output_stays_out_of_parent(capfd):
    assert run_case(_CASE, helpers.Noisy(), isolate=True).status is Status.PASS
    captured = capfd.readouterr()
    assert "progress" not in captured.out + captured.err


def test_offline_guard_runs_in_worker():
    result = run_case(_CASE, helpers.Connects(), isolate=True)
    assert result.status is Status.ERROR
    assert "OfflineViolation" in result.reason


def test_offline_can_be_disabled_in_worker():
    result = run_case(_CASE, helpers.Connects(), timeout=1.0, offline=False)
    assert result.status is Status.ERROR
    assert "OfflineViolation" not in result.reason


def test_local_adapter_classes_get_clear_error():
    class Local(ReferenceAdapter):
        pass

    result = run_case(_CASE, Local(), timeout=5)
    assert result.status is Status.ERROR
    assert "importable and picklable" in result.reason


def test_unpicklable_state_gets_clear_error():
    adapter = helpers.Sleeper("x")
    adapter.state = lambda: None
    result = run_case(_CASE, adapter, isolate=True)
    assert result.status is Status.ERROR
    assert "picklable" in result.reason


def test_adapters_in_main_get_clear_error(tmp_path):
    script = tmp_path / "script.py"
    script.write_text(
        "from geofixtures import run_case\n"
        "from geofixtures.adapters.reference import ReferenceAdapter\n"
        "class Mine(ReferenceAdapter):\n"
        "    pass\n"
        "result = run_case('vector.overlap.001', Mine(), timeout=5)\n"
        "print(result.reason)\n"
    )
    output = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    assert "__main__" in output.stdout


def test_memory_comes_from_worker():
    result = run_case(_CASE, "reference", isolate=True)
    assert result.peak_memory_kb > 0


def test_interrupting_run_stops_worker_and_marks_report(tmp_path):
    pid_file = tmp_path / "pid"
    report = tmp_path / "report.json"
    source = tmp_path / "interrupted_adapter.py"
    source.write_text(
        "from pathlib import Path\n"
        "from tests.helpers import ChildStarter\n"
        f"class Adapter(ChildStarter):\n"
        f"    def __init__(self):\n"
        f"        super().__init__({str(pid_file)!r})\n"
    )
    root = str(tmp_path)
    repository = str(Path(__file__).parents[2])
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([root, repository])}
    command = [
        sys.executable,
        "-m",
        "geofixtures",
        "run",
        "--select",
        _CASE,
        "--adapter",
        "interrupted_adapter:Adapter",
        "--timeout",
        "60",
        "--report",
        str(report),
    ]
    process = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait_for_file(pid_file)
    process.send_signal(signal.SIGINT)
    assert process.wait(15) == 2
    assert _wait_until_gone(int(pid_file.read_text()))
    assert json.loads(report.read_text())["complete"] is False


@pytest.mark.parametrize("timeout", [None, 60])
def test_outcomes_match_with_and_without_worker(timeout):
    result = run_case("raster.dem.slope.001", "reference", timeout=timeout)
    assert result.status is Status.PASS
