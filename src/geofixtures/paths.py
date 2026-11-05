"""Path containment checks for fixture roots."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .models import UnsafePathError


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve a manifest path, rejecting anything outside the fixture root."""
    candidate = PurePosixPath(relative)
    if not relative or "\\" in relative or candidate.is_absolute() or ".." in candidate.parts:
        raise UnsafePathError(f"Unsafe path in manifest: {relative!r}")
    base = root.resolve()
    target = (base / candidate).resolve()
    if base != target and base not in target.parents:
        raise UnsafePathError(f"Path escapes the fixture root: {relative!r}")
    return target
