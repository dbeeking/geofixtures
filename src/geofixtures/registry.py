"""Immutable case registry and selection logic."""

from __future__ import annotations

import fnmatch
import importlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from types import MappingProxyType

from .models import CaseNotFoundError, CaseSpec

CASE_MODULES = ("vector", "crs", "raster", "landcover", "lidar", "ingestion")
CATEGORIES = ("vector", "crs", "raster", "landcover", "lidar", "ingestion")
SMOKE_CASES = (
    "crs.transform.001",
    "ingest.schema_added.001",
    "landcover.truth_mask.001",
    "lidar.density.001",
    "raster.dem.slope.001",
    "vector.overlap.001",
)
LANDFUSE_CASES = (
    "landcover.image_collar.001",
    "landcover.missing_nir.001",
    "landcover.pair.dem.001",
    "landcover.pair.lidar.001",
    "landcover.sampling_spread.001",
    "landcover.scene.rgbnir.001",
    "landcover.spatial_leakage.001",
    "landcover.truth_mask.001",
    "landcover.unknown.001",
    "landcover.date_mismatch.001",
    "lidar.density.001",
    "lidar.ground_gap.001",
    "lidar.vertical_mismatch.001",
    "raster.depression.001",
    "raster.dem.slope.001",
    "raster.grid.offset.001",
    "raster.nodata_hole.001",
    "raster.partial_coverage.001",
    "raster.ridge_saddle.001",
    "raster.tile_seam.001",
    "raster.truncated.001",
)


@dataclass(frozen=True)
class Registry:
    """A read-only collection of cases."""

    cases: Mapping[str, CaseSpec]
    aliases: Mapping[str, str]

    def ids(self) -> list[str]:
        return sorted(self.cases)

    def get(self, case_id: str) -> CaseSpec:
        resolved = self.aliases.get(case_id, case_id)
        if resolved not in self.cases:
            raise CaseNotFoundError(f"Unknown case: {case_id}")
        return self.cases[resolved]

    def _matches(self, spec: CaseSpec, selector: str) -> bool:
        key, separator, value = selector.partition(":")
        if not separator:
            return fnmatch.fnmatchcase(spec.case_id, selector)
        if key == "id":
            return fnmatch.fnmatchcase(spec.case_id, value)
        if key == "tag":
            return value in spec.tags
        if key == "category":
            return spec.category == value
        if key == "op":
            return fnmatch.fnmatchcase(spec.operation, value)
        if key == "suite":
            return self._in_suite(spec, value)
        raise CaseNotFoundError(f"Unknown selector type: {selector}")

    @staticmethod
    def _in_suite(spec: CaseSpec, suite: str) -> bool:
        if suite == "all":
            return True
        if suite == "canonical":
            return spec.canonical
        if suite == "extended":
            return not spec.canonical
        if suite == "smoke":
            return spec.case_id in SMOKE_CASES
        if suite == "landfuse":
            return spec.case_id in LANDFUSE_CASES
        raise CaseNotFoundError(f"Unknown suite: {suite}")

    def select(self, selectors: Sequence[str] | None = None) -> list[CaseSpec]:
        """Return matching cases sorted by ID.

        Selectors combine with OR, and one selector can hold a comma-separated list.
        """
        if not selectors:
            return [self.cases[case_id] for case_id in self.ids()]
        parts = [part.strip() for selector in selectors for part in selector.split(",") if part.strip()]
        chosen = [
            self.cases[case_id]
            for case_id in self.ids()
            if any(self._matches(self.cases[case_id], part) for part in parts)
        ]
        if not chosen:
            raise CaseNotFoundError(f"No cases match: {', '.join(parts)}")
        return chosen


def _collect(groups: Iterable[Iterable[CaseSpec]]) -> dict[str, CaseSpec]:
    cases: dict[str, CaseSpec] = {}
    for group in groups:
        for spec in group:
            if spec.case_id in cases:
                raise ValueError(f"Duplicate case ID: {spec.case_id}")
            cases[spec.case_id] = spec
    return cases


@lru_cache(maxsize=1)
def default_registry() -> Registry:
    """Build the registry from built-in modules and installed case packages."""
    groups: list[Iterable[CaseSpec]] = [
        importlib.import_module(f"geofixtures.cases.{name}").CASES for name in CASE_MODULES
    ]
    for entry_point in metadata.entry_points(group="geofixtures.cases"):
        groups.append(entry_point.load())
    return Registry(cases=MappingProxyType(_collect(groups)), aliases=MappingProxyType({}))
