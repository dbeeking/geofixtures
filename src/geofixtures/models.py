"""Typed models shared by the registry, materializer, runner, and adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np


class Status(StrEnum):
    """Normalized case status."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


class Outcome(StrEnum):
    """Normalized assertion outcome."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"
    EXPECTED_REJECTION = "EXPECTED_REJECTION"


class GeoFixturesError(Exception):
    """Base class for library errors."""


class CaseNotFoundError(GeoFixturesError):
    """The requested case ID or selector matched nothing."""


class ManifestError(GeoFixturesError):
    """A manifest or fixture failed validation."""


class UnsafePathError(ManifestError):
    """A path escaped the fixture root."""


class LimitExceededError(GeoFixturesError):
    """A generator request exceeded a resource limit."""


class OverrideError(GeoFixturesError):
    """A parameter override was invalid or would change a case's meaning."""


class MissingDependencyError(GeoFixturesError):
    """An optional dependency needed by a case is not installed."""


class OfflineViolation(GeoFixturesError):
    """Code attempted a network connection during an offline run."""


class AdapterError(GeoFixturesError):
    """An adapter could not be loaded or broke the adapter contract."""


class PolicyError(GeoFixturesError):
    """A strict policy file is invalid."""


@dataclass(frozen=True)
class Limits:
    """Upper bounds applied while generating a fixture."""

    max_features: int = 100_000
    max_pixels: int = 25_000_000
    max_points: int = 2_000_000
    max_bytes: int = 512 * 1024 * 1024


@dataclass(frozen=True)
class InputFile:
    """One input file and the role it plays in a case."""

    role: str
    path: str
    format: str
    profile: str
    crs: str | None = None
    acquired: str | None = None

    def to_manifest(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "role": self.role,
            "path": self.path,
            "format": self.format,
            "profile": self.profile,
        }
        if self.crs is not None:
            entry["crs"] = self.crs
        if self.acquired is not None:
            entry["acquired"] = self.acquired
        return entry


@dataclass
class CaseContent:
    """Everything a case builder returns after writing its files."""

    inputs: list[InputFile]
    assertions: list[dict[str, Any]]
    truth: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    tolerances: dict[str, float] = field(default_factory=dict)


@dataclass
class BuildContext:
    """Paths, seed, and limits given to a case builder."""

    root: Path
    seed: int
    parameters: dict[str, Any]
    limits: Limits
    rng: np.random.Generator

    def input_path(self, name: str) -> Path:
        path = self.root / "input" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def truth_path(self, name: str) -> Path:
        path = self.root / "truth" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def check_features(self, count: int) -> None:
        if count > self.limits.max_features:
            raise LimitExceededError(f"{count} features exceeds the limit of {self.limits.max_features}")

    def check_pixels(self, count: int) -> None:
        if count > self.limits.max_pixels:
            raise LimitExceededError(f"{count} pixels exceeds the limit of {self.limits.max_pixels}")

    def check_points(self, count: int) -> None:
        if count > self.limits.max_points:
            raise LimitExceededError(f"{count} points exceeds the limit of {self.limits.max_points}")


@dataclass(frozen=True)
class CaseSpec:
    """A versioned test scenario. Cases are immutable once published."""

    case_id: str
    version: str
    title: str
    category: str
    tags: tuple[str, ...]
    generator: str
    generator_version: str
    operation: str
    build: Callable[[BuildContext], CaseContent]
    oracle_method: str
    derivation: str
    requires: tuple[str, ...]
    formats: tuple[str, ...]
    expected_status: str = "success"
    seed: int = 42
    parameters: Mapping[str, Any] = field(default_factory=dict)
    overridable: tuple[str, ...] = ()
    canonical: bool = True

    def summary(self) -> dict[str, Any]:
        """Return registry metadata without generating any data."""
        return {
            "case_id": self.case_id,
            "case_version": self.version,
            "title": self.title,
            "category": self.category,
            "tags": list(self.tags),
            "operation": self.operation,
            "expected_status": self.expected_status,
            "formats": list(self.formats),
            "requires": list(self.requires),
            "oracle_method": self.oracle_method,
            "derivation": self.derivation,
            "generator": {"name": self.generator, "version": self.generator_version},
            "default_seed": self.seed,
            "overridable_parameters": list(self.overridable),
            "canonical": self.canonical,
        }


@dataclass(frozen=True)
class MaterializedCase:
    """A case written to disk."""

    root: Path
    manifest: dict[str, Any]

    @property
    def case_id(self) -> str:
        return str(self.manifest["case_id"])

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"


@dataclass(frozen=True)
class ValidationReport:
    """Result of validating a materialized fixture."""

    manifest_path: Path
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors
