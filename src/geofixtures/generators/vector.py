"""Vector features placed at a fixed map origin."""

from __future__ import annotations

from typing import Any

EASTING = 400000.0
NORTHING = 3800000.0

Box = tuple[float, float, float, float]


def to_map(coordinates: Any) -> Any:
    """Shift local metre coordinates to map coordinates."""
    if isinstance(coordinates[0], (int, float)):
        return [EASTING + coordinates[0], NORTHING + coordinates[1]]
    return [to_map(item) for item in coordinates]


def feature(identifier: str, kind: str, coordinates: Any, **properties: Any) -> dict[str, Any]:
    """Build a feature from local coordinates."""
    return {
        "type": "Feature",
        "properties": {"id": identifier, **properties},
        "geometry": {"type": kind, "coordinates": to_map(coordinates)},
    }


def box_ring(box: Box) -> list[list[float]]:
    xmin, ymin, xmax, ymax = box
    return [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]


def box_feature(identifier: str, box: Box, **properties: Any) -> dict[str, Any]:
    return feature(identifier, "Polygon", [box_ring(box)], **properties)


def point_feature(identifier: str, x: float, y: float, **properties: Any) -> dict[str, Any]:
    return feature(identifier, "Point", [x, y], **properties)


def line_feature(identifier: str, points: list[list[float]], **properties: Any) -> dict[str, Any]:
    return feature(identifier, "LineString", points, **properties)


def _ring_text(ring: list[list[float]]) -> str:
    return "(" + ", ".join(f"{x!r} {y!r}" for x, y in to_map(ring)) + ")"


def polygon_wkt(ring: list[list[float]]) -> str:
    """Return WKT for a local ring, written without a geometry library."""
    return f"POLYGON ({_ring_text(ring)})"


def multipolygon_wkt(rings: list[list[list[float]]]) -> str:
    parts = ", ".join(f"({_ring_text(ring)})" for ring in rings)
    return f"MULTIPOLYGON ({parts})"
