"""Snapshots of a small source dataset, before and after an update."""

from __future__ import annotations

from typing import Any

LONGITUDE = -112.5
LATITUDE = 34.5
CELL = 0.01


def cell_feature(identifier: str, column: int, row: int = 0, **properties: Any) -> dict[str, Any]:
    """Return a small WGS84 square addressed by grid cell."""
    west = LONGITUDE + column * CELL
    south = LATITUDE + row * CELL
    east = west + CELL / 2
    north = south + CELL / 2
    return {
        "type": "Feature",
        "properties": {"id": identifier, **properties},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
        },
    }
