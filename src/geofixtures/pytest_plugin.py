"""pytest helpers. Everything here also works by explicit import."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pytest


def case_params(select: Sequence[str] | str | None = None) -> list[Any]:
    """Return parametrize values with readable test IDs."""
    from .api import list_cases

    selectors = [select] if isinstance(select, str) else select
    return [pytest.param(case["case_id"], id=case["case_id"]) for case in list_cases(selectors)]


def assert_case(result: Any, policy: Any = None) -> None:
    """Fail a test with assertion detail unless the case passed.

    Without a policy, SKIP and UNSUPPORTED become pytest skips. With a policy,
    only an allowed UNSUPPORTED is skipped, and any other gap fails the test.
    """
    from .models import Status
    from .runner.policy import case_violation

    if policy is not None:
        violation = case_violation(result.case_id, result.status, result.reason, policy)
        if violation is not None:
            pytest.fail(f"{violation.case_id} {violation.rule}: {violation.message}", pytrace=False)
    if result.status in (Status.UNSUPPORTED, Status.SKIP):
        pytest.skip(f"{result.case_id}: {result.status.value} {result.reason}")
    if result.status is not Status.PASS:
        pytest.fail(result.failure_text(), pytrace=False)


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("geofixtures")
    group.addoption(
        "--geofixtures-adapter", default="reference", help="Adapter used by the run_fixture fixture"
    )
    group.addoption("--geofixtures-strict", action="store_true", help="Fail on any SKIP or UNSUPPORTED case")
    group.addoption("--geofixtures-policy", help="TOML file of allowed gaps. Implies --geofixtures-strict")


@pytest.fixture  # type: ignore[untyped-decorator,unused-ignore]
def run_fixture(request: Any, tmp_path: Any) -> Callable[..., Any]:
    """Return a function that runs a case and raises on any non-passing result."""
    from .api import load_policy, run_case
    from .runner.policy import StrictPolicy

    adapter = request.config.getoption("--geofixtures-adapter")
    path = request.config.getoption("--geofixtures-policy")
    policy = load_policy(path) if path else None
    if policy is None and request.config.getoption("--geofixtures-strict"):
        policy = StrictPolicy()

    def run(case_id: str, **options: Any) -> Any:
        options.setdefault("adapter", adapter)
        result = run_case(case_id, workspace=tmp_path, **options)
        assert_case(result, policy)
        return result

    return run


@pytest.fixture  # type: ignore[untyped-decorator,unused-ignore]
def materialized(tmp_path: Any) -> Callable[..., Any]:
    """Return a function that writes a case into the test's temporary folder."""
    from .api import materialize

    def build(case_id: str, **options: Any) -> Any:
        return materialize(case_id, tmp_path / case_id, **options)

    return build
