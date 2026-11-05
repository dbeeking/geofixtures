from __future__ import annotations

import numpy as np
import pytest

from geofixtures.io.geotiff import Grid, write_geotiff


@pytest.fixture
def raster(tmp_path):
    """Return a function that writes a small band and returns its path."""
    counter = iter(range(1000))

    def write(values, *, grid=None, nodata=None, crs="EPSG:32612"):
        array = np.asarray(values)
        target = grid or Grid(array.shape[-1], array.shape[-2], 1.0, 400000.0, 3801000.0)
        path = tmp_path / f"raster_{next(counter)}.tif"
        write_geotiff(path, array, target, crs, nodata=nodata)
        return path

    return write
