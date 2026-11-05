"""Record the software environment for traceability."""

from __future__ import annotations

import platform
import shutil
import subprocess
from importlib import metadata
from typing import Any

from ._version import __version__

_PACKAGES = ("numpy", "jsonschema", "shapely", "pyarrow", "pyproj", "rasterio", "laspy")


def installed_version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def environment_versions() -> dict[str, Any]:
    """Return versions of Python, GeoFixtures, and available native libraries."""
    versions: dict[str, Any] = {
        "geofixtures": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    for package in _PACKAGES:
        version = installed_version(package)
        if version is not None:
            versions[package] = version
    if versions.get("rasterio"):
        import rasterio

        versions["gdal"] = rasterio.__gdal_version__
    if versions.get("pyproj"):
        import pyproj

        versions["proj"] = pyproj.__proj_version__
    return versions


def pdal_version() -> str | None:
    """Return the PDAL command-line version, or None if it isn't installed."""
    if shutil.which("pdal") is None:
        return None
    result = subprocess.run(["pdal", "--version"], capture_output=True, text=True, timeout=30, check=False)
    for token in result.stdout.split():
        if token[:1].isdigit():
            return token
    return "unknown"
