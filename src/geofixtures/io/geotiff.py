"""GeoTIFF fixtures with explicit grid, band, and NoData metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

GEOTIFF_PROFILE = "GeoTIFF 1.1"


@dataclass(frozen=True)
class Grid:
    """A north-up raster grid."""

    width: int
    height: int
    pixel: float
    origin_x: float
    origin_y: float

    @property
    def pixels(self) -> int:
        return self.width * self.height

    def centers(self) -> tuple[np.ndarray, np.ndarray]:
        """Return map X and Y of every pixel center as 2D arrays."""
        columns = self.origin_x + (np.arange(self.width) + 0.5) * self.pixel
        rows = self.origin_y - (np.arange(self.height) + 0.5) * self.pixel
        return np.meshgrid(columns, rows)

    def transform_values(self) -> list[float]:
        """Return the affine as [a, b, c, d, e, f]."""
        return [self.pixel, 0.0, self.origin_x, 0.0, -self.pixel, self.origin_y]

    def shifted(self, dx: float, dy: float) -> Grid:
        return Grid(self.width, self.height, self.pixel, self.origin_x + dx, self.origin_y + dy)

    def box(self) -> tuple[float, float, float, float]:
        return (
            self.origin_x,
            self.origin_y - self.height * self.pixel,
            self.origin_x + self.width * self.pixel,
            self.origin_y,
        )


def write_geotiff(
    path: Path,
    array: np.ndarray,
    grid: Grid,
    crs: str,
    *,
    nodata: float | None = None,
    tags: dict[str, str] | None = None,
    tiled: bool = False,
) -> None:
    """Write a 2D or 3D (bands, rows, columns) array as an uncompressed GeoTIFF."""
    import rasterio
    from rasterio.transform import from_origin

    data = array[np.newaxis, ...] if array.ndim == 2 else array
    options: dict[str, Any] = {"GEOTIFF_VERSION": "1.1"}
    if tiled:
        options.update(tiled=True, blockxsize=64, blockysize=64)
    if data.shape[0] > 1:
        options["photometric"] = "MINISBLACK"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[2],
        height=data.shape[1],
        count=data.shape[0],
        dtype=data.dtype.name,
        crs=crs,
        transform=from_origin(grid.origin_x, grid.origin_y, grid.pixel, grid.pixel),
        nodata=nodata,
        **options,
    ) as dataset:
        dataset.write(data)
        if tags:
            dataset.update_tags(**tags)


def read_metadata(path: Path) -> dict[str, Any]:
    """Return grid and type metadata from a raster."""
    import rasterio

    with rasterio.open(path) as dataset:
        return {
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "transform": [float(value) for value in list(dataset.transform)[:6]],
            "width": dataset.width,
            "height": dataset.height,
            "count": dataset.count,
            "dtype": dataset.dtypes[0],
            "nodata": dataset.nodata,
            "tags": dict(dataset.tags()),
        }
