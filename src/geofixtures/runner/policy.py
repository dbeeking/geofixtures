"""Strict run rules for CI gates."""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import PolicyError, Status


@dataclass(frozen=True)
class StrictPolicy:
    """Rules for a strict run.

    Every selected case must pass. allow_unsupported maps case IDs to the reason
    a target doesn't have that feature yet.
    """

    allow_unsupported: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"allow_unsupported": dict(sorted(self.allow_unsupported.items()))}


@dataclass(frozen=True)
class Violation:
    """A case result that a strict run doesn't accept."""

    case_id: str
    status: str
    rule: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"case_id": self.case_id, "status": self.status, "rule": self.rule, "message": self.message}


def load_policy(path: str | Path) -> StrictPolicy:
    """Read a TOML policy file with an [allow_unsupported] table."""
    try:
        with open(path, "rb") as stream:
            content = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"Policy file isn't valid TOML: {exc}") from exc
    unknown = sorted(set(content) - {"allow_unsupported"})
    if unknown:
        raise PolicyError(f"Unknown policy keys: {', '.join(unknown)}")
    allowed = content.get("allow_unsupported", {})
    if not isinstance(allowed, dict):
        raise PolicyError("allow_unsupported must be a table of case IDs and reasons")
    for case_id, reason in allowed.items():
        if not isinstance(reason, str) or not reason.strip():
            raise PolicyError(f"{case_id} needs a reason")
    return StrictPolicy(allow_unsupported=allowed)


def check_policy_ids(policy: StrictPolicy, known_ids: Iterable[str]) -> None:
    """Refuse allowances for case IDs that don't exist."""
    unknown = sorted(set(policy.allow_unsupported) - set(known_ids))
    if unknown:
        raise PolicyError(f"Policy lists unknown cases: {', '.join(unknown)}")


def case_violation(case_id: str, status: Status, reason: str, policy: StrictPolicy) -> Violation | None:
    """Return the strict rule a case result breaks, if any.

    FAIL and ERROR aren't listed here because they fail a run in every mode.
    """
    allowed = case_id in policy.allow_unsupported
    if status is Status.SKIP:
        return Violation(case_id, status.value, "unexpected_skip", reason or "The case was skipped")
    if status is Status.UNSUPPORTED and not allowed:
        message = reason or "The target doesn't support this case"
        return Violation(case_id, status.value, "unexpected_unsupported", message)
    if status is Status.PASS and allowed:
        message = "This case passes now, so remove it from the policy"
        return Violation(case_id, status.value, "stale_allowance", message)
    return None
