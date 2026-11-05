"""Run one adapter call in a separate process.

The parent starts this module in its own process group, so a timeout can stop
the adapter and anything it launched.
"""

from __future__ import annotations

import json
import os
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..offline import offline_guard
from .protocol import CaseView, ExecutionContext, ObservationBundle, Rejection

REQUEST_NAME = "worker_request.json"
ADAPTER_NAME = "worker_adapter.pickle"
RESULT_NAME = "worker_result.json"
LOG_NAME = "worker.log"


@dataclass(frozen=True)
class WorkerOutcome:
    """What the worker sent back."""

    bundle: ObservationBundle | None
    error: str | None
    peak_memory_kb: int | None


def write_request(run_dir: Path, context: ExecutionContext, offline: bool) -> Path:
    """Write the request file and return its path."""
    request = {
        "case": {
            "case_id": context.case.case_id,
            "operation": context.case.operation,
            "tags": list(context.case.tags),
            "parameters": context.case.parameters,
            "roles": list(context.case.roles),
        },
        "inputs": {role: [str(path) for path in paths] for role, paths in context.inputs.items()},
        "work_dir": str(context.work_dir),
        "timeout": context.timeout,
        "offline": offline,
    }
    path = run_dir / REQUEST_NAME
    path.write_text(json.dumps(request))
    return path


def _context(request: dict[str, Any]) -> ExecutionContext:
    case = request["case"]
    view = CaseView(
        case_id=case["case_id"],
        operation=case["operation"],
        tags=tuple(case["tags"]),
        parameters=case["parameters"],
        roles=tuple(case["roles"]),
    )
    inputs = {role: [Path(path) for path in paths] for role, paths in request["inputs"].items()}
    return ExecutionContext(view, inputs, Path(request["work_dir"]), request["timeout"])


def _plain(value: Any) -> Any:
    """Reduce numpy values, paths, and sets to JSON types, keeping NaN and infinity."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_plain(item) for item in sorted(value, key=str)]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    return value


def _peak_memory_kb() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak / 1024) if sys.platform == "darwin" else int(peak)


def _write_result(run_dir: Path, payload: dict[str, Any]) -> None:
    temporary = run_dir / f".{RESULT_NAME}"
    temporary.write_text(json.dumps(payload))
    os.replace(temporary, run_dir / RESULT_NAME)


def read_result(run_dir: Path) -> WorkerOutcome | None:
    """Return the worker's result, or None if it didn't finish."""
    path = run_dir / RESULT_NAME
    if not path.is_file():
        return None
    payload = json.loads(path.read_text())
    peak = payload.get("peak_memory_kb")
    if "error" in payload:
        return WorkerOutcome(None, payload["error"], peak)
    rejection = payload["rejection"]
    bundle = ObservationBundle(
        values=payload["values"],
        rejection=None if rejection is None else Rejection(rejection["code"], rejection["message"]),
        artifacts=payload["artifacts"],
    )
    return WorkerOutcome(bundle, None, peak)


def main(argv: list[str]) -> int:
    request_path = Path(argv[0])
    run_dir = request_path.parent
    request = json.loads(request_path.read_text())
    try:
        with open(run_dir / ADAPTER_NAME, "rb") as stream:
            adapter = pickle.load(stream)
        with offline_guard(request["offline"]):
            bundle = adapter.execute(_context(request))
        rejection = bundle.rejection
        payload = {
            "values": _plain(bundle.values),
            "rejection": None
            if rejection is None
            else {"code": rejection.code, "message": rejection.message},
            "artifacts": list(bundle.artifacts),
            "peak_memory_kb": _peak_memory_kb(),
        }
        _write_result(run_dir, payload)
    except Exception as exc:
        _write_result(run_dir, {"error": f"{type(exc).__name__}: {exc}", "peak_memory_kb": _peak_memory_kb()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
