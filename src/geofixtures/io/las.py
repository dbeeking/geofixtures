"""LAS 1.4 point clouds with explicit scale, offset, and CRS metadata."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

LAS_VERSION = "1.4"
LAS_POINT_FORMAT = 6
LAS_PROFILE = "LAS 1.4 point format 6"
# A fixed header date keeps repeated generation byte-comparable.
_CREATION_DATE = date(2026, 1, 1)


def write_las(
    path: Path,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    classification: np.ndarray,
    crs: str | None,
    *,
    scale: float = 0.001,
) -> None:
    """Write points to an uncompressed LAS 1.4 file."""
    import laspy
    from pyproj import CRS

    header = laspy.LasHeader(point_format=LAS_POINT_FORMAT, version=LAS_VERSION)
    header.scales = np.array([scale, scale, scale])
    header.offsets = np.array([np.floor(x.min()), np.floor(y.min()), np.floor(z.min())])
    header.creation_date = _CREATION_DATE
    if crs is not None:
        header.add_crs(CRS.from_user_input(crs))
    points = laspy.LasData(header)
    points.x = x
    points.y = y
    points.z = z
    points.classification = classification.astype("uint8")
    points.write(str(path))


def read_las(path: Path) -> dict[str, Any]:
    """Return coordinates, classes, and header metadata."""
    import laspy

    with laspy.open(str(path)) as reader:
        points = reader.read()
        header = reader.header
        crs = header.parse_crs()
        return {
            "x": np.asarray(points.x, dtype="float64"),
            "y": np.asarray(points.y, dtype="float64"),
            "z": np.asarray(points.z, dtype="float64"),
            "classification": np.asarray(points.classification, dtype="uint8"),
            "version": f"{header.version.major}.{header.version.minor}",
            "point_format": int(header.point_format.id),
            "count": int(header.point_count),
            "scale": [float(value) for value in header.scales],
            "offset": [float(value) for value in header.offsets],
            "crs": crs.to_string() if crs is not None else None,
        }
