"""Closed-form geometry and geodesy used to derive expected values."""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]

# WGS84 ellipsoid and UTM constants.
WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
UTM_K0 = 0.9996
UTM_FALSE_EASTING = 500000.0


def ring_area(ring: Sequence[Sequence[float]]) -> float:
    """Return the unsigned planar area of a closed or open ring (shoelace formula)."""
    total = 0.0
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index][:2]
        x2, y2 = ring[(index + 1) % count][:2]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def rectangle_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    """Return the overlap of two (xmin, ymin, xmax, ymax) rectangles, or None."""
    xmin, ymin = max(a[0], b[0]), max(a[1], b[1])
    xmax, ymax = min(a[2], b[2]), min(a[3], b[3])
    if xmin >= xmax or ymin >= ymax:
        return None
    return (xmin, ymin, xmax, ymax)


def rectangle_area(box: tuple[float, float, float, float]) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def rectangle_ring(box: tuple[float, float, float, float]) -> list[list[float]]:
    """Return a closed counterclockwise ring for a rectangle."""
    xmin, ymin, xmax, ymax = box
    return [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]


def point_segment_distance(point: Point, start: Point, end: Point) -> float:
    """Return the planar distance from a point to a line segment."""
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def utm_forward(lon_deg: float, lat_deg: float, zone: int) -> tuple[float, float]:
    """Project WGS84 lon/lat to north-hemisphere UTM with the Krueger n-series.

    This is written from the published series, separately from PROJ, so it can
    act as an independent check. The series is accurate to well under a
    millimetre within a UTM zone.
    """
    flattening = WGS84_F
    n = flattening / (2 - flattening)
    rectifying_radius = WGS84_A / (1 + n) * (1 + n**2 / 4 + n**4 / 64 + n**6 / 256 + 25 * n**8 / 16384)
    alpha = (
        n / 2 - 2 * n**2 / 3 + 5 * n**3 / 16 + 41 * n**4 / 180 - 127 * n**5 / 288 + 7891 * n**6 / 37800,
        13 * n**2 / 48 - 3 * n**3 / 5 + 557 * n**4 / 1440 + 281 * n**5 / 630 - 1983433 * n**6 / 1935360,
        61 * n**3 / 240 - 103 * n**4 / 140 + 15061 * n**5 / 26880 + 167603 * n**6 / 181440,
        49561 * n**4 / 161280 - 179 * n**5 / 168 + 6601661 * n**6 / 7257600,
        34729 * n**5 / 80640 - 3418889 * n**6 / 1995840,
        212378941 * n**6 / 319334400,
    )
    central_meridian = math.radians(-183 + 6 * zone)
    lam = math.radians(lon_deg) - central_meridian
    phi = math.radians(lat_deg)
    e = math.sqrt(flattening * (2 - flattening))
    tau = math.tan(phi)
    sigma = math.sinh(e * math.atanh(e * tau / math.sqrt(1 + tau**2)))
    tau_conformal = tau * math.sqrt(1 + sigma**2) - sigma * math.sqrt(1 + tau**2)
    xi_prime = math.atan2(tau_conformal, math.cos(lam))
    eta_prime = math.asinh(math.sin(lam) / math.hypot(tau_conformal, math.cos(lam)))
    xi = xi_prime
    eta = eta_prime
    for order, coefficient in enumerate(alpha, start=1):
        xi += coefficient * math.sin(2 * order * xi_prime) * math.cosh(2 * order * eta_prime)
        eta += coefficient * math.cos(2 * order * xi_prime) * math.sinh(2 * order * eta_prime)
    return (UTM_FALSE_EASTING + UTM_K0 * rectifying_radius * eta, UTM_K0 * rectifying_radius * xi)
