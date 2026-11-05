"""Stratified point clouds over a known ground plane."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .raster import ORIGIN_X, ORIGIN_Y

GROUND = 2
HIGH_VEGETATION = 5
BUILDING = 6
Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Scene:
    """A square scene whose local origin is its lower-left corner."""

    size: float

    @property
    def west(self) -> float:
        return ORIGIN_X

    @property
    def south(self) -> float:
        return ORIGIN_Y - self.size


def stratified(rng: np.random.Generator, box: Box, density: float) -> tuple[np.ndarray, np.ndarray]:
    """Place one jittered point in each cell of a grid at the requested density."""
    step = 1.0 / np.sqrt(density)
    columns = np.arange(box[0], box[2] - 1e-9, step)
    rows = np.arange(box[1], box[3] - 1e-9, step)
    x, y = np.meshgrid(columns, rows)
    x = x.ravel() + rng.random(x.size) * step
    y = y.ravel() + rng.random(y.size) * step
    return np.minimum(x, box[2]), np.minimum(y, box[3])


def ground_plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """z = 1600 + 0.02 x + 0.01 y."""
    return 1600.0 + 0.02 * x + 0.01 * y


def outside(x: np.ndarray, y: np.ndarray, box: Box) -> np.ndarray:
    return (x < box[0]) | (x > box[2]) | (y < box[1]) | (y > box[3])


def block_points(
    rng: np.random.Generator, box: Box, density: float, height: float, code: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x, y = stratified(rng, box, density)
    return x, y, ground_plane(x, y) + height, np.full(x.size, code, dtype="uint8")
