"""RFC 7946 GeoJSON. Coordinates are always WGS84 longitude, latitude."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _check_position(position: Sequence[float]) -> None:
    longitude, latitude = position[0], position[1]
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError(f"Position is outside WGS84 range: {list(position)}")


def _walk_positions(coordinates: Any) -> list[Sequence[float]]:
    if coordinates and isinstance(coordinates[0], (int, float)):
        return [coordinates]
    positions: list[Sequence[float]] = []
    for item in coordinates:
        positions.extend(_walk_positions(item))
    return positions


def write_geojson(path: Path, features: list[dict[str, Any]], *, strict: bool = True) -> None:
    """Write a FeatureCollection.

    Set strict to False only for negative cases that store bad coordinates.
    Such files are declared with a non-compliant profile in the manifest.
    """
    if strict:
        for feature in features:
            geometry = feature.get("geometry")
            if geometry is not None:
                for position in _walk_positions(geometry["coordinates"]):
                    _check_position(position)
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_geojson(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    if payload.get("type") != "FeatureCollection":
        raise ValueError("Expected a GeoJSON FeatureCollection")
    features: list[dict[str, Any]] = payload["features"]
    return features
