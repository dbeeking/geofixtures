"""Validate manifests and fixture contents before any adapter runs."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema

from ._version import MANIFEST_SCHEMA_VERSION
from .models import ManifestError, UnsafePathError, ValidationReport
from .oracles.data_integrity import sha256_file
from .paths import resolve_inside

_MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def load_schema(name: str) -> dict[str, Any]:
    """Load a packaged JSON Schema."""
    text = resources.files("geofixtures").joinpath("schemas", name).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def check_manifest_schema(manifest: dict[str, Any]) -> list[str]:
    """Return schema errors using the jsonschema validator."""
    validator = jsonschema.Draft202012Validator(load_schema("manifest-v1.schema.json"))
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.absolute_path))
    return [f"{'/'.join(str(part) for part in error.absolute_path)}: {error.message}" for error in errors]


def load_manifest(path: Path) -> dict[str, Any]:
    """Read a manifest, rejecting oversized or non-object documents."""
    if not path.is_file():
        raise ManifestError(f"Missing manifest: {path}")
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ManifestError(f"Manifest is too large: {path}")
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Manifest isn't valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("Manifest must be a JSON object")
    return manifest


def _major(version: object) -> str:
    return str(version).split(".", 1)[0]


def _check_files(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors = []
    listed = set()
    for entry in manifest["files"]:
        relative = entry["path"]
        try:
            path = resolve_inside(root, relative)
        except UnsafePathError as exc:
            errors.append(str(exc))
            continue
        listed.add(relative)
        if not path.is_file():
            errors.append(f"Missing file: {relative}")
        elif sha256_file(path) != entry["sha256"]:
            errors.append(f"Checksum mismatch: {relative}")
    for item in manifest["inputs"]:
        if item["path"] not in listed:
            errors.append(f"Input isn't in the file inventory: {item['path']}")
    if manifest["truth"]["path"] not in listed:
        errors.append(f"Truth file isn't in the inventory: {manifest['truth']['path']}")
    for assertion in manifest["assertions"]:
        for key in ("truth", "optional_mask", "ignore_mask"):
            if key in assertion and assertion[key] not in listed:
                errors.append(f"{assertion['id']}: {key} file isn't in the inventory: {assertion[key]}")
    identifiers = [assertion["id"] for assertion in manifest["assertions"]]
    if len(identifiers) != len(set(identifiers)):
        errors.append("Assertion IDs must be unique")
    return errors


def validate(manifest_path: str | Path) -> ValidationReport:
    """Validate a fixture's schema, paths, checksums, and truth references."""
    path = Path(manifest_path)
    if path.is_dir():
        path = path / "manifest.json"
    try:
        manifest = load_manifest(path)
    except ManifestError as exc:
        return ValidationReport(path, (str(exc),))
    if _major(manifest.get("schema_version")) != _major(MANIFEST_SCHEMA_VERSION):
        message = f"Unsupported manifest schema version: {manifest.get('schema_version')}"
        return ValidationReport(path, (message,))
    errors = check_manifest_schema(manifest)
    if errors:
        return ValidationReport(path, tuple(errors))
    return ValidationReport(path, tuple(_check_files(path.parent, manifest)))
