"""Result models and atomic report writers."""

from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ElementTree
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .._version import REPORT_SCHEMA_VERSION
from ..models import Outcome, Status
from .policy import StrictPolicy, Violation, case_violation


def jsonable(value: Any) -> Any:
    """Convert numpy values and paths to JSON-safe types."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [jsonable(item) for item in items]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return str(value)
    return value


def jsonable_dict(value: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = jsonable(value)
    return converted


@dataclass
class AssertionResult:
    """Outcome of one assertion, with enough context to reproduce a failure."""

    assertion_id: str
    kind: str
    outcome: Outcome
    case_id: str = ""
    observed: Any = None
    expected: Any = None
    tolerance: Any = None
    unit: str | None = None
    message: str = ""
    source_file: str = "manifest.json"
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return jsonable_dict(
            {
                "assertion_id": self.assertion_id,
                "case_id": self.case_id,
                "kind": self.kind,
                "outcome": self.outcome.value,
                "observed": self.observed,
                "expected": self.expected,
                "tolerance": self.tolerance,
                "unit": self.unit,
                "message": self.message,
                "source_file": self.source_file,
                "metrics": self.metrics,
            }
        )


@dataclass
class CaseResult:
    """Outcome of one case."""

    case_id: str
    case_version: str
    adapter: str
    status: Status
    expected_status: str
    seed: int | None = None
    reason: str = ""
    assertions: list[AssertionResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    peak_memory_kb: int | None = None
    fixture_root: str = ""
    artifacts: list[dict[str, str]] = field(default_factory=list)
    observed_rejection: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable_dict(
            {
                "case_id": self.case_id,
                "case_version": self.case_version,
                "adapter": self.adapter,
                "status": self.status.value,
                "expected_status": self.expected_status,
                "seed": self.seed,
                "reason": self.reason,
                "elapsed_seconds": round(self.elapsed_seconds, 6),
                "peak_memory_kb": self.peak_memory_kb,
                "fixture_root": self.fixture_root,
                "artifacts": self.artifacts,
                "observed_rejection": self.observed_rejection,
                "assertions": [item.to_dict() for item in self.assertions],
            }
        )

    def failure_text(self) -> str:
        """Return a readable account of everything that didn't pass."""
        lines = [f"{self.case_id} {self.status.value} {self.reason}".rstrip()]
        for item in self.assertions:
            if item.outcome in (Outcome.PASS, Outcome.EXPECTED_REJECTION, Outcome.SKIP):
                continue
            lines.append(f"  {item.assertion_id} [{item.kind}] {item.outcome.value}: {item.message}")
            lines.append(f"    expected: {item.expected!r}")
            lines.append(f"    observed: {item.observed!r}")
            if item.tolerance is not None:
                lines.append(f"    tolerance: {item.tolerance!r}")
        return "\n".join(lines)


@dataclass
class SuiteResult:
    """Outcome of a run."""

    run_id: str
    adapter: str
    selectors: list[str]
    started_at: str
    finished_at: str
    complete: bool
    environment: dict[str, Any]
    adapter_environment: dict[str, Any]
    cases: list[CaseResult] = field(default_factory=list)
    policy: StrictPolicy | None = None

    def violations(self) -> list[Violation]:
        """Return strict rule breaks, or nothing for an exploratory run."""
        if self.policy is None:
            return []
        found = [case_violation(case.case_id, case.status, case.reason, self.policy) for case in self.cases]
        return [item for item in found if item is not None]

    def summary(self) -> dict[str, int]:
        counts = Counter(case.status.value for case in self.cases)
        return {status.value: counts.get(status.value, 0) for status in Status} | {"total": len(self.cases)}

    def exit_code(self) -> int:
        """Return 0 pass, 1 failed, 2 error, 3 nothing ran, or 4 strict rule broken."""
        counts = self.summary()
        if counts["ERROR"] or not self.complete:
            return 2
        if counts["FAIL"]:
            return 1
        if self.violations():
            return 4
        return 0 if counts["PASS"] else 3

    def to_dict(self) -> dict[str, Any]:
        return jsonable_dict(
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "run_id": self.run_id,
                "adapter": self.adapter,
                "selectors": self.selectors,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "complete": self.complete,
                "environment": self.environment,
                "adapter_environment": self.adapter_environment,
                "summary": self.summary(),
                "strict": {
                    "enabled": self.policy is not None,
                    "allow_unsupported": {}
                    if self.policy is None
                    else self.policy.to_dict()["allow_unsupported"],
                    "violations": [item.to_dict() for item in self.violations()],
                },
                "cases": [case.to_dict() for case in self.cases],
            }
        )


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json_report(path: str | Path, report: dict[str, Any]) -> None:
    """Write a JSON report atomically, so readers never see a truncated file."""
    _write_atomic(Path(path), json.dumps(report, indent=2, sort_keys=True) + "\n")


def junit_xml(report: dict[str, Any]) -> str:
    """Render a JSON report as JUnit XML."""
    summary = report["summary"]
    violations = {item["case_id"]: item for item in report.get("strict", {}).get("violations", [])}
    unexpected = sum(1 for item in violations.values() if item["status"] != "PASS")
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": f"geofixtures.{report['adapter']}",
            "tests": str(summary["total"]),
            "failures": str(summary["FAIL"] + len(violations)),
            "errors": str(summary["ERROR"]),
            "skipped": str(summary["SKIP"] + summary["UNSUPPORTED"] - unexpected),
            "timestamp": report["started_at"],
            "time": f"{sum(case['elapsed_seconds'] for case in report['cases']):.6f}",
        },
    )
    properties = ElementTree.SubElement(suite, "properties")
    for key in ("schema_version", "run_id", "complete"):
        ElementTree.SubElement(properties, "property", {"name": key, "value": str(report[key])})
    for key, value in sorted(report["environment"].items()):
        ElementTree.SubElement(properties, "property", {"name": f"env.{key}", "value": str(value)})
    for case in report["cases"]:
        element = ElementTree.SubElement(
            suite,
            "testcase",
            {
                "classname": case["case_id"].rsplit(".", 1)[0],
                "name": case["case_id"],
                "time": f"{case['elapsed_seconds']:.6f}",
            },
        )
        details = [
            f"{item['assertion_id']} [{item['kind']}] {item['outcome']}: {item['message']} "
            f"expected={item['expected']!r} observed={item['observed']!r} tolerance={item['tolerance']!r}"
            for item in case["assertions"]
            if item["outcome"] not in ("PASS", "EXPECTED_REJECTION", "SKIP")
        ]
        text = "\n".join(details) or case["reason"]
        if case["case_id"] in violations:
            item = violations[case["case_id"]]
            ElementTree.SubElement(element, "failure", {"message": f"strict: {item['rule']}"}).text = item[
                "message"
            ]
        elif case["status"] == "FAIL":
            ElementTree.SubElement(
                element, "failure", {"message": case["reason"] or "Assertion failed"}
            ).text = text
        elif case["status"] == "ERROR":
            ElementTree.SubElement(element, "error", {"message": case["reason"] or "Error"}).text = text
        elif case["status"] in ("SKIP", "UNSUPPORTED"):
            ElementTree.SubElement(element, "skipped", {"message": f"{case['status']}: {case['reason']}"})
    return ElementTree.tostring(suite, encoding="unicode", xml_declaration=True)


def write_junit_report(path: str | Path, report: dict[str, Any]) -> None:
    _write_atomic(Path(path), junit_xml(report) + "\n")


def observed_differences(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    """List assertions whose observed values differ between two reports.

    Two targets can pass within tolerance and return different numbers, so this
    compares observed values.
    """
    assertions = {
        (case["case_id"], item["assertion_id"]): item for case in left["cases"] for item in case["assertions"]
    }
    differences = []
    for case in right["cases"]:
        for item in case["assertions"]:
            other = assertions.get((case["case_id"], item["assertion_id"]))
            if other is not None and other["observed"] != item["observed"]:
                differences.append(
                    {
                        "case_id": case["case_id"],
                        "assertion_id": item["assertion_id"],
                        "left_adapter": left["adapter"],
                        "left_outcome": other["outcome"],
                        "left_observed": other["observed"],
                        "right_adapter": right["adapter"],
                        "right_outcome": item["outcome"],
                        "right_observed": item["observed"],
                    }
                )
    return differences


def text_report(report: dict[str, Any]) -> str:
    """Render a JSON report for a terminal."""
    lines = [f"{case['status']:<12} {case['case_id']} {case['reason']}".rstrip() for case in report["cases"]]
    summary = report["summary"]
    counts = ", ".join(f"{summary[name]} {name}" for name in ("PASS", "FAIL", "ERROR", "SKIP", "UNSUPPORTED"))
    state = "complete" if report["complete"] else "INCOMPLETE"
    lines.append(f"\nAdapter {report['adapter']}: {counts} ({state})")
    strict = report.get("strict", {})
    not_run = summary["SKIP"] + summary["UNSUPPORTED"]
    if strict.get("enabled"):
        for item in strict["violations"]:
            lines.append(f"Strict: {item['case_id']} {item['rule']}: {item['message']}")
        allowed = len(strict["allow_unsupported"])
        lines.append(f"Strict mode: {len(strict['violations'])} violations, {allowed} allowed gaps")
    elif not_run:
        lines.append(f"{not_run} of {summary['total']} cases didn't run. Use --strict to fail on this.")
    return "\n".join(lines)
