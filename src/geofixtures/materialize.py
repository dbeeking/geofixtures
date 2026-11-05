"""Write a case to disk with its manifest, truth, and file inventory."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from importlib import util
from pathlib import Path
from typing import Any

import numpy as np

from ._version import MANIFEST_SCHEMA_VERSION
from .environment import environment_versions
from .models import (
    BuildContext,
    CaseContent,
    CaseSpec,
    LimitExceededError,
    Limits,
    ManifestError,
    MaterializedCase,
    MissingDependencyError,
    OverrideError,
)
from .oracles.data_integrity import sha256_file
from .registry import Registry, default_registry
from .validation import check_manifest_schema

_EXTRA_MODULES = {
    "vector": ("pyarrow", "pyproj", "shapely"),
    "raster": ("rasterio",),
    "lidar": ("laspy", "pyproj"),
}
REVIEW_STATUS = "pending_independent_review"
CASE_LICENSE = {"identifier": "MIT", "redistributable": True}


def missing_extras(spec: CaseSpec) -> list[str]:
    """Return optional extras needed by a case that aren't importable."""
    missing = []
    for extra in spec.requires:
        if any(util.find_spec(module) is None for module in _EXTRA_MODULES[extra]):
            missing.append(extra)
    return missing


def _merged_parameters(spec: CaseSpec, overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    parameters = dict(spec.parameters)
    for name, value in (overrides or {}).items():
        if name not in spec.overridable:
            raise OverrideError(f"{spec.case_id} doesn't allow overriding {name!r}")
        parameters[name] = value
    return parameters


def _inventory(root: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
    return entries


def _manifest(
    spec: CaseSpec, seed: int, parameters: dict[str, Any], content: CaseContent, files: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "case_id": spec.case_id,
        "case_version": spec.version,
        "title": spec.title,
        "category": spec.category,
        "tags": list(spec.tags),
        "operation": spec.operation,
        "expected_status": spec.expected_status,
        "generator": {"name": spec.generator, "version": spec.generator_version},
        "seed": seed,
        "generator_parameters": parameters,
        "parameters": content.parameters,
        "inputs": [item.to_manifest() for item in content.inputs],
        "truth": {
            "method": spec.oracle_method,
            "path": "truth/expected.json",
            "review_status": REVIEW_STATUS,
            "derivation": spec.derivation,
        },
        "assertions": content.assertions,
        "tolerances": content.tolerances,
        "files": files,
        "license": CASE_LICENSE,
        "references": [],
        "environment": environment_versions(),
    }


def materialize(
    case: str | CaseSpec,
    output_dir: str | Path,
    *,
    seed: int | None = None,
    overwrite: bool = False,
    overrides: Mapping[str, Any] | None = None,
    limits: Limits | None = None,
    registry: Registry | None = None,
) -> MaterializedCase:
    """Generate a case in a staging folder, then move it into place.

    An existing output folder is left alone unless overwrite is True. Overwrite
    only replaces a folder that already holds a GeoFixtures manifest.
    """
    spec = case if isinstance(case, CaseSpec) else (registry or default_registry()).get(case)
    missing = missing_extras(spec)
    if missing:
        names = ",".join(missing)
        raise MissingDependencyError(f"{spec.case_id} needs: pip install 'geofixtures[{names}]'")
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        if not overwrite:
            raise FileExistsError(f"{target} isn't empty. Pass overwrite to replace a fixture")
        if not (target / "manifest.json").is_file():
            raise FileExistsError(f"Refusing to overwrite {target}: it isn't a GeoFixtures fixture")
    active_seed = spec.seed if seed is None else seed
    active_limits = limits or Limits()
    parameters = _merged_parameters(spec, overrides)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".geofixtures-", dir=target.parent))
    try:
        context = BuildContext(
            root=staging,
            seed=active_seed,
            parameters=parameters,
            limits=active_limits,
            rng=np.random.default_rng(active_seed),
        )
        content = spec.build(context)
        truth_file = context.truth_path("expected.json")
        truth_file.write_text(json.dumps(content.truth, indent=2, sort_keys=True) + "\n")
        files = _inventory(staging)
        total_bytes = sum(entry["bytes"] for entry in files)
        if total_bytes > active_limits.max_bytes:
            raise LimitExceededError(f"Fixture is {total_bytes} bytes, over {active_limits.max_bytes}")
        manifest = _manifest(spec, active_seed, parameters, content, files)
        errors = check_manifest_schema(manifest)
        if errors:
            raise ManifestError(f"{spec.case_id} produced an invalid manifest: {errors[0]}")
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return MaterializedCase(root=target, manifest=manifest)
