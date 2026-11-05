"""The contract between the runner and a target implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..models import AdapterError


@dataclass(frozen=True)
class Capability:
    """Whether an adapter can run a case. Skip marks a temporary condition."""

    supported: bool
    reason: str = ""
    skip: bool = False


@dataclass(frozen=True)
class Rejection:
    """Returned when the target refuses an input."""

    code: str
    message: str = ""


@dataclass
class ObservationBundle:
    """Normalized values returned by a target."""

    values: dict[str, Any] = field(default_factory=dict)
    rejection: Rejection | None = None
    artifacts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaseView:
    """Public case metadata. It excludes truth and expected values."""

    case_id: str
    operation: str
    tags: tuple[str, ...]
    parameters: dict[str, Any]
    roles: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionContext:
    """Input paths and a writable folder for one run."""

    case: CaseView
    inputs: dict[str, list[Path]]
    work_dir: Path
    timeout: float | None = None

    @property
    def parameters(self) -> dict[str, Any]:
        return self.case.parameters

    def input(self, role: str) -> Path:
        """Return the single file for a role."""
        paths = self.inputs.get(role, [])
        if len(paths) != 1:
            raise AdapterError(f"Expected one {role!r} input, found {len(paths)}")
        return paths[0]

    def has(self, role: str) -> bool:
        return bool(self.inputs.get(role))


@runtime_checkable
class Adapter(Protocol):
    """Implement this to run fixtures against your own software."""

    name: str

    def supports(self, case: CaseView) -> Capability: ...

    def execute(self, context: ExecutionContext) -> ObservationBundle: ...

    def environment(self) -> dict[str, Any]: ...
