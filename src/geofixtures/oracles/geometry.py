"""Hand-checkable geometry answers. Nothing here calls a geometry engine."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .analytic import rectangle_area

Box = tuple[float, float, float, float]


def rectangle_relations(a: Box, b: Box) -> dict[str, bool]:
    """Return DE-9IM named predicates for two axis-aligned rectangles."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    intersects = width >= 0 and height >= 0
    interiors_meet = width > 0 and height > 0
    within = a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]
    contains = b[0] >= a[0] and b[1] >= a[1] and b[2] <= a[2] and b[3] <= a[3]
    return {
        "intersects": intersects,
        "disjoint": not intersects,
        "touches": intersects and not interiors_meet,
        "overlaps": interiors_meet and not within and not contains,
        "within": within,
        "contains": contains,
    }


def _distance_to_box_edge(point: tuple[float, float], box: Box) -> float:
    x, y = point
    if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
        return min(x - box[0], box[2] - x, y - box[1], box[3] - y)
    dx = max(box[0] - x, 0.0, x - box[2])
    dy = max(box[1] - y, 0.0, y - box[3])
    return math.hypot(dx, dy)


def point_in_holed_rectangle(
    point: tuple[float, float], outer: Box, hole: Box, tolerance: float
) -> dict[str, bool]:
    """Classify a point against a rectangle with a rectangular hole."""
    x, y = point
    in_outer = outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]
    in_hole_interior = hole[0] < x < hole[2] and hole[1] < y < hole[3]
    distance = min(_distance_to_box_edge(point, outer), _distance_to_box_edge(point, hole))
    on_boundary = distance == 0.0
    covered = in_outer and not in_hole_interior
    return {
        "contains": covered and not on_boundary,
        "covers": covered,
        "on_boundary": on_boundary,
        "near_boundary": distance <= tolerance,
    }


def polsby_popper(area: float, perimeter: float) -> float:
    """Return compactness: 4 pi A / P squared. A circle scores 1."""
    return 4.0 * math.pi * area / perimeter**2


def rectangle_compactness(width: float, height: float) -> float:
    return polsby_popper(width * height, 2.0 * (width + height))


def stadium_area(length: float, half_width: float) -> float:
    """Return the area of a straight segment's round-capped buffer."""
    return 2.0 * half_width * length + math.pi * half_width**2


def multipart_remainder(study_area: Box, parts: Sequence[Box]) -> float:
    """Return study area minus disjoint exclusion parts inside it."""
    return rectangle_area(study_area) - sum(rectangle_area(part) for part in parts)
