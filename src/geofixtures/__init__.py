"""GeoFixtures: deterministic geospatial test fixtures with verifiable answers."""

from ._version import __version__
from .api import describe_case, list_cases, load_policy, materialize, run_case, run_suite, validate
from .models import Limits, MaterializedCase, Outcome, Status
from .runner.policy import StrictPolicy
from .runner.protocol import Adapter, Capability, CaseView, ExecutionContext, ObservationBundle, Rejection
from .runner.results import AssertionResult, CaseResult, SuiteResult

__all__ = [
    "Adapter",
    "AssertionResult",
    "Capability",
    "CaseResult",
    "CaseView",
    "ExecutionContext",
    "Limits",
    "MaterializedCase",
    "ObservationBundle",
    "Outcome",
    "Rejection",
    "Status",
    "StrictPolicy",
    "SuiteResult",
    "__version__",
    "describe_case",
    "list_cases",
    "load_policy",
    "materialize",
    "run_case",
    "run_suite",
    "validate",
]
