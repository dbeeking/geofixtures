"""Public Python API."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapters import load_adapter
from .environment import environment_versions
from .materialize import materialize, missing_extras
from .models import CaseNotFoundError, CaseSpec, GeoFixturesError, Limits, MaterializedCase, Status
from .offline import offline_guard
from .registry import Registry, default_registry
from .runner.execute import run_materialized
from .runner.policy import StrictPolicy, check_policy_ids, load_policy
from .runner.protocol import Adapter
from .runner.results import CaseResult, SuiteResult
from .validation import validate

__all__ = ["describe_case", "list_cases", "load_policy", "materialize", "run_case", "run_suite", "validate"]


def list_cases(
    select: Sequence[str] | None = None, *, registry: Registry | None = None
) -> list[dict[str, Any]]:
    """List case metadata without generating any data."""
    return [spec.summary() for spec in (registry or default_registry()).select(select)]


def describe_case(case_id: str, *, registry: Registry | None = None) -> dict[str, Any]:
    """Return one case's metadata."""
    return (registry or default_registry()).get(case_id).summary()


def _adapter_environment(adapter: Adapter) -> dict[str, Any]:
    try:
        return adapter.environment()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_case(
    case: str | MaterializedCase | Path,
    adapter: str | Adapter = "reference",
    *,
    seed: int | None = None,
    timeout: float | None = None,
    workspace: str | Path | None = None,
    retain_dir: str | Path | None = None,
    limits: Limits | None = None,
    offline: bool = True,
    registry: Registry | None = None,
    isolate: bool = False,
) -> CaseResult:
    """Run one case. A case ID is materialized into a temporary folder first.

    With a timeout or isolate=True, the adapter runs in its own process group, so
    it must be importable and picklable.
    """
    target = load_adapter(adapter)
    retained = Path(retain_dir) if retain_dir is not None else None
    active = registry or default_registry()
    with offline_guard(offline):
        if isinstance(case, str) and (case in active.cases or case in active.aliases):
            return _run_spec(
                active.get(case), target, seed, timeout, workspace, retained, limits, isolate, offline
            )
        if isinstance(case, str) and not Path(case).exists():
            raise CaseNotFoundError(f"Unknown case: {case}")
        return run_materialized(
            case if isinstance(case, MaterializedCase) else Path(case),
            target,
            timeout=timeout,
            retain_dir=retained,
            isolate=isolate,
            offline=offline,
        )


def _run_spec(
    spec: CaseSpec,
    adapter: Adapter,
    seed: int | None,
    timeout: float | None,
    workspace: str | Path | None,
    retain_dir: Path | None,
    limits: Limits | None,
    isolate: bool,
    offline: bool,
) -> CaseResult:
    missing = missing_extras(spec)
    if missing:
        return CaseResult(
            spec.case_id,
            spec.version,
            adapter.name,
            Status.UNSUPPORTED,
            spec.expected_status,
            reason=f"Needs optional extras: {', '.join(missing)}",
        )
    root = Path(workspace) if workspace is not None else Path(tempfile.mkdtemp(prefix="geofixtures-case-"))
    fixture_root = root / spec.case_id
    try:
        fixture = materialize(spec, fixture_root, seed=seed, limits=limits, overwrite=workspace is not None)
        return run_materialized(
            fixture, adapter, timeout=timeout, retain_dir=retain_dir, isolate=isolate, offline=offline
        )
    except GeoFixturesError as exc:
        return CaseResult(
            spec.case_id, spec.version, adapter.name, Status.ERROR, spec.expected_status, reason=str(exc)
        )
    finally:
        if workspace is None:
            shutil.rmtree(root, ignore_errors=True)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_suite(
    select: Sequence[str] | None = None,
    adapter: str | Adapter = "reference",
    *,
    seed: int | None = None,
    timeout: float | None = None,
    workspace: str | Path | None = None,
    retain_dir: str | Path | None = None,
    limits: Limits | None = None,
    offline: bool = True,
    registry: Registry | None = None,
    isolate: bool = False,
    policy: StrictPolicy | None = None,
) -> SuiteResult:
    """Run selected cases in ID order.

    A policy turns on strict mode. An interrupted run returns a result marked
    incomplete.
    """
    active = registry or default_registry()
    specs = active.select(select)
    if policy is not None:
        check_policy_ids(policy, active.ids())
    target = load_adapter(adapter)
    retained = Path(retain_dir) if retain_dir is not None else None
    result = SuiteResult(
        run_id=uuid.uuid4().hex,
        adapter=target.name,
        selectors=list(select or []),
        started_at=_timestamp(),
        finished_at="",
        complete=False,
        environment=environment_versions(),
        adapter_environment=_adapter_environment(target),
        policy=policy,
    )
    try:
        with offline_guard(offline):
            for spec in specs:
                result.cases.append(
                    _run_spec(spec, target, seed, timeout, workspace, retained, limits, isolate, offline)
                )
        result.complete = True
    except KeyboardInterrupt:
        result.complete = False
    result.finished_at = _timestamp()
    return result
