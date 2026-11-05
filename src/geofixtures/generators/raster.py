"""Terrain surfaces, imagery, and class scenes."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from ..io.geotiff import Grid

CRS = "EPSG:32612"
ORIGIN_X = 400000.0
ORIGIN_Y = 3801000.0
NODATA = -9999.0
CLASS_NAMES = {
    1: "water",
    2: "bare_ground",
    3: "low_vegetation",
    4: "tall_vegetation",
    5: "built_surface",
    6: "road_or_path",
}
SPECTRA = {
    1: (20, 40, 60, 10),
    2: (170, 150, 120, 160),
    3: (70, 110, 60, 170),
    4: (30, 70, 40, 140),
    5: (150, 150, 155, 150),
    6: (110, 110, 112, 105),
}
ALTERNATE_SPECTRA = {
    1: (60, 90, 140, 30),
    2: (220, 200, 190, 210),
    3: (120, 170, 90, 230),
    4: (10, 40, 20, 90),
    5: (200, 90, 70, 120),
    6: (70, 70, 72, 60),
}


def square_grid(size: int, pixel: float) -> Grid:
    return Grid(size, size, pixel, ORIGIN_X, ORIGIN_Y)


def local_xy(grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Return pixel-center metres from the grid's lower-left corner."""
    x, y = grid.centers()
    return x - grid.origin_x, y - (grid.origin_y - grid.height * grid.pixel)


def centered_xy(grid: Grid, center: float) -> tuple[np.ndarray, np.ndarray]:
    """Return metres from pixel index (center, center), positive east and south."""
    indices = np.arange(grid.width, dtype="float64")
    x = (indices - center) * grid.pixel
    y = (np.arange(grid.height, dtype="float64") - center) * grid.pixel
    return np.meshgrid(x, y)


def plane_surface(grid: Grid) -> np.ndarray:
    """z = 1500 + 0.03 x + 0.04 y, a constant slope of 0.05."""
    x, y = local_xy(grid)
    return (1500.0 + 0.03 * x + 0.04 * y).astype("float32")


def block_labels(rng: np.random.Generator, size: int, block: int) -> np.ndarray:
    """Return a label image of square blocks using all six classes evenly."""
    count = size // block
    codes = np.resize(np.arange(1, 7, dtype="uint8"), count * count)
    rng.shuffle(codes)
    return np.kron(codes.reshape(count, count), np.ones((block, block), dtype="uint8"))


def spectral_image(
    rng: np.random.Generator,
    labels: np.ndarray,
    spectra: Mapping[int, tuple[int, int, int, int]],
    sigma: float,
    *,
    alternate: Mapping[int, tuple[int, int, int, int]] | None = None,
    alternate_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return four 8-bit bands for a label image, never all zero on real pixels."""
    image = np.zeros((4, *labels.shape), dtype="float64")
    for code, spectrum in spectra.items():
        for band, value in enumerate(spectrum):
            image[band][labels == code] = value
    if alternate is not None and alternate_mask is not None:
        for code, spectrum in alternate.items():
            selected = (labels == code) & alternate_mask
            for band, value in enumerate(spectrum):
                image[band][selected] = value
    image += rng.normal(0.0, sigma, image.shape)
    return np.clip(np.rint(image), 1, 255).astype("uint8")


def location_image(rng: np.random.Generator, size: int) -> np.ndarray:
    """Return bands that encode map position and nothing about land cover."""
    rows, columns = np.indices((size, size), dtype="float64")
    image = np.stack(
        (
            20.0 + 200.0 * columns / (size - 1),
            20.0 + 200.0 * rows / (size - 1),
            np.full((size, size), 100.0),
            np.full((size, size), 100.0),
        )
    )
    image += rng.normal(0.0, 1.0, image.shape)
    return np.clip(np.rint(image), 1, 255).astype("uint8")
