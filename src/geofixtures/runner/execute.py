"""Run one case against an adapter and score the observations."""

from __future__ import annotations

import contextlib
import os
import pickle
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..models import AdapterError, ManifestError, MaterializedCase, Outcome, Status
from ..oracles.data_integrity import sha256_file
from ..paths import resolve_inside
from ..validation import load_manifest, validate
from .assertions import evaluate
from .protocol import Adapter, CaseView, ExecutionContext, ObservationBundle
from .results import AssertionResult, CaseResult
from .worker import ADAPTER_NAME, LOG_NAME, read_result, write_request

_STOP_GRACE_SECONDS = 2.0


def _case_view(manifest: dict[str, Any]) -> CaseView:
    return CaseView(
        case_id=manifest["case_id"],
        operation=manifest["operation"],
        tags=tuple(manifest["tags"]),
        parameters=dict(manifest["parameters"]),
        roles=tuple(item["role"] for item in manifest["inputs"]),
    )


def _peak_memory_kb() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak / 1024) if sys.platform == "darwin" else int(peak)


def _pickle_adapter(adapter: Adapter, path: Path) -> None:
    if type(adapter).__module__ == "__main__":
        raise AdapterError("An isolated adapter can't live in __main__. Move it to an importable module")
    try:
        path.write_bytes(pickle.dumps(adapter))
    except (pickle.PicklingError, AttributeError, TypeError) as exc:
        raise AdapterError(f"An isolated adapter must be importable and picklable: {exc}") from exc


def _worker_environment() -> dict[str, str]:
    """Give the worker the same import path as this process."""
    entries = [os.path.abspath(entry) for entry in sys.path]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(dict.fromkeys(entries))}


def _signal_group(process: subprocess.Popen[bytes], number: int) -> None:
    # macOS reports EPERM for a group that holds only zombies.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, number)


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop the worker and anything it started, escalating to SIGKILL."""
    _signal_group(process, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(_STOP_GRACE_SECONDS)
    _signal_group(process, signal.SIGKILL)
    process.wait()


def _log_tail(path: Path) -> str:
    lines = path.read_text(errors="replace").strip().splitlines()
    return f": {lines[-1]}" if lines else ""


def _call_in_worker(
    adapter: Adapter, context: ExecutionContext, run_dir: Path, offline: bool
) -> tuple[ObservationBundle, int | None]:
    """Run execute() in a separate process group and wait for its result."""
    _pickle_adapter(adapter, run_dir / ADAPTER_NAME)
    request = write_request(run_dir, context, offline)
    log_path = run_dir / LOG_NAME
    command = [sys.executable, "-m", "geofixtures.runner.worker", str(request)]
    with open(log_path, "wb") as log:
        process = subprocess.Popen(
            command,
            cwd=run_dir,
            env=_worker_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        process.wait(context.timeout)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Adapter exceeded the {context.timeout} second timeout and was stopped") from None
    finally:
        _stop_process_group(process)
    outcome = read_result(run_dir)
    if outcome is None:
        raise AdapterError(f"The adapter process exited with code {process.returncode}{_log_tail(log_path)}")
    if outcome.bundle is None:
        raise AdapterError(str(outcome.error))
    return outcome.bundle, outcome.peak_memory_kb


def _prepare_inputs(root: Path, manifest: dict[str, Any], work_dir: Path) -> dict[str, list[Path]]:
    """Copy inputs into the run folder so adapters can't reach truth or the fixture."""
    inputs: dict[str, list[Path]] = {}
    for item in manifest["inputs"]:
        source = resolve_inside(root, item["path"])
        target = work_dir / "input" / item["path"].split("/", 1)[-1]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        inputs.setdefault(item["role"], []).append(target)
    return inputs


def _score(manifest: dict[str, Any], bundle: ObservationBundle, root: Path) -> list[AssertionResult]:
    expected_status = manifest["expected_status"]
    case_id = manifest["case_id"]
    rejected = bundle.rejection is not None
    scored: list[AssertionResult] = []
    declared = any(spec["kind"] == "expected_error" for spec in manifest["assertions"])
    if expected_status == "rejection" and not rejected and not declared:
        scored.append(
            AssertionResult(
                "expected_rejection",
                "expected_error",
                Outcome.FAIL,
                expected="rejection",
                observed="accepted",
                message="The target accepted input it should reject",
            )
        )
    for spec in manifest["assertions"]:
        if (
            rejected
            and not spec.get("optional")
            and spec["kind"] != "expected_error"
            and spec.get("observe", spec["id"]) not in bundle.values
        ):
            if expected_status == "success":
                assert bundle.rejection is not None
                outcome = Outcome.FAIL
                message = f"Unexpected rejection {bundle.rejection.code}: {bundle.rejection.message}"
            else:
                outcome = Outcome.EXPECTED_REJECTION
                message = "The target declined to give a result, which this case allows"
            scored.append(AssertionResult(spec["id"], spec["kind"], outcome, message=message))
            continue
        scored.append(evaluate(spec, bundle, root))
    for item in scored:
        item.case_id = case_id
    return scored


def _status(scored: list[AssertionResult]) -> tuple[Status, str]:
    outcomes = {item.outcome for item in scored}
    if Outcome.ERROR in outcomes:
        return Status.ERROR, "An assertion couldn't be evaluated"
    if Outcome.FAIL in outcomes:
        return Status.FAIL, ""
    executed = outcomes & {Outcome.PASS, Outcome.EXPECTED_REJECTION}
    if not executed:
        return Status.UNSUPPORTED, "No assertion could be executed"
    return Status.PASS, ""


def _retain(work_dir: Path, retain_dir: Path, case_id: str) -> list[dict[str, str]]:
    target = retain_dir / case_id
    if target.exists():
        shutil.rmtree(target)
    output = work_dir / "output"
    shutil.copytree(output, target)
    return [
        {"path": str(path), "sha256": sha256_file(path)}
        for path in sorted(target.rglob("*"))
        if path.is_file()
    ]


def run_materialized(
    fixture: MaterializedCase | str | Path,
    adapter: Adapter,
    *,
    timeout: float | None = None,
    retain_dir: Path | None = None,
    isolate: bool = False,
    offline: bool = True,
) -> CaseResult:
    """Validate a fixture, execute the adapter, and evaluate every assertion.

    With a timeout or isolate=True, the adapter runs in its own process group.
    """
    root = fixture.root if isinstance(fixture, MaterializedCase) else Path(fixture)
    if root.is_file():
        root = root.parent
    try:
        manifest = load_manifest(root / "manifest.json")
    except ManifestError as exc:
        return CaseResult(str(root), "", adapter.name, Status.ERROR, "", reason=str(exc))
    result = CaseResult(
        case_id=str(manifest.get("case_id", root)),
        case_version=str(manifest.get("case_version", "")),
        adapter=adapter.name,
        status=Status.ERROR,
        expected_status=str(manifest.get("expected_status", "")),
        seed=manifest.get("seed"),
        fixture_root=str(root),
    )
    report = validate(root / "manifest.json")
    if not report.ok:
        result.reason = f"Fixture failed validation: {report.errors[0]}"
        return result
    view = _case_view(manifest)
    started = time.perf_counter()
    try:
        capability = adapter.supports(view)
    except Exception as exc:
        result.reason = f"Adapter supports() failed: {type(exc).__name__}: {exc}"
        return result
    if not capability.supported:
        result.status = Status.SKIP if capability.skip else Status.UNSUPPORTED
        result.reason = capability.reason
        return result
    work_dir = Path(tempfile.mkdtemp(prefix="geofixtures-run-"))
    try:
        (work_dir / "output").mkdir()
        context = ExecutionContext(
            case=view,
            inputs=_prepare_inputs(root, manifest, work_dir),
            work_dir=work_dir / "output",
            timeout=timeout,
        )
        worker_peak = None
        try:
            if isolate or timeout is not None:
                bundle, worker_peak = _call_in_worker(adapter, context, work_dir, offline)
            else:
                bundle = adapter.execute(context)
        except TimeoutError as exc:
            result.reason = str(exc)
            return result
        except AdapterError as exc:
            result.reason = f"Adapter failed: {exc}"
            return result
        except Exception as exc:
            result.reason = f"Adapter failed: {type(exc).__name__}: {exc}"
            return result
        result.peak_memory_kb = worker_peak
        result.assertions = _score(manifest, bundle, root)
        result.status, result.reason = _status(result.assertions)
        if bundle.rejection is not None:
            result.observed_rejection = {"code": bundle.rejection.code, "message": bundle.rejection.message}
        if retain_dir is not None and result.status is not Status.PASS:
            result.artifacts = _retain(work_dir, retain_dir, result.case_id)
        return result
    finally:
        result.elapsed_seconds = time.perf_counter() - started
        if result.peak_memory_kb is None:
            result.peak_memory_kb = _peak_memory_kb()
        shutil.rmtree(work_dir, ignore_errors=True)
