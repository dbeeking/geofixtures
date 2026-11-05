"""Raw-file and semantic hashes for chain-of-custody and change detection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """Serialize JSON with sorted keys and no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _round_coordinates(value: Any, digits: int) -> Any:
    if isinstance(value, (list, tuple)):
        return [_round_coordinates(item, digits) for item in value]
    return round(float(value), digits)


def semantic_feature_hash(
    features: Iterable[Mapping[str, Any]], *, id_field: str = "id", coordinate_digits: int = 6
) -> str:
    """Hash normalized features so file order and encoding don't matter.

    Features are sorted by id_field. Attribute names are sorted, coordinates are
    rounded to coordinate_digits decimal places, and the schema is included
    through the attribute names and JSON value types.
    """
    normalized = []
    for feature in features:
        geometry = feature.get("geometry")
        normalized.append(
            {
                "id": feature.get("properties", {}).get(id_field),
                "properties": feature.get("properties", {}),
                "geometry": None
                if geometry is None
                else {
                    "type": geometry["type"],
                    "coordinates": _round_coordinates(geometry["coordinates"], coordinate_digits),
                },
            }
        )
    normalized.sort(key=lambda item: str(item["id"]))
    return hashlib.sha256(canonical_json(normalized).encode("ascii")).hexdigest()
