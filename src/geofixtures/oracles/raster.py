"""Pixel comparison with explicit alignment, NoData, and edge rules."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


def _band(path: Path, *, nodata_as_value: bool = False) -> tuple[np.ndarray, np.ndarray, Any, Any]:
    """Read band 1 as floats with a validity mask.

    With nodata_as_value, a pixel holding the NoData value counts as a real
    value. Classified rasters need this when 0 means both NoData and a class.
    """
    import rasterio

    with rasterio.open(path) as dataset:
        masked = dataset.read(1, masked=True)
        values = np.asarray(masked.data, dtype="float64")
        valid = np.isfinite(values)
        if not nodata_as_value:
            valid &= ~np.ma.getmaskarray(masked)
        return values, valid, dataset.transform, dataset.crs


def _centers(transform: Any, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    rows, columns = np.indices(shape)
    x = transform.c + (columns + 0.5) * transform.a + (rows + 0.5) * transform.b
    y = transform.f + (columns + 0.5) * transform.d + (rows + 0.5) * transform.e
    return x, y


def _sample(
    values: np.ndarray, valid: np.ndarray, transform: Any, x: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Read the observed cell containing each coordinate, with no interpolation.

    The inverse affine handles rotated and flipped grids.
    """
    inverse = ~transform
    columns = np.floor(inverse.a * x + inverse.b * y + inverse.c).astype("int64")
    rows = np.floor(inverse.d * x + inverse.e * y + inverse.f).astype("int64")
    inside = (rows >= 0) & (rows < values.shape[0]) & (columns >= 0) & (columns < values.shape[1])
    sampled = np.full(x.shape, np.nan)
    sampled_valid = np.zeros(x.shape, dtype=bool)
    sampled[inside] = values[rows[inside], columns[inside]]
    sampled_valid[inside] = valid[rows[inside], columns[inside]]
    return sampled, sampled_valid


def transforms_match(left: Any, right: Any, tolerance: float = 1e-6) -> bool:
    """Compare two affine transforms term by term, in absolute units."""
    return all(abs(a - b) <= tolerance for a, b in zip(tuple(left)[:6], tuple(right)[:6], strict=True))


def compare_rasters(
    observed_path: Path,
    truth_path: Path,
    rules: Mapping[str, Any],
    *,
    optional_mask_path: Path | None = None,
    ignore_mask_path: Path | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Compare an observed raster with a truth raster.

    With grid sampling, the rasters must align exactly. With map_coordinates
    sampling, truth pixel centers are looked up in the observed cell that holds
    them. Values are never interpolated.

    A pixel in the optional mask may be NoData but must match if it has a value.
    A pixel in the ignore mask isn't compared at all.
    """
    raw = bool(rules.get("observed_nodata_as_value", False))
    observed, observed_valid, observed_transform, observed_crs = _band(observed_path, nodata_as_value=raw)
    truth, truth_valid, truth_transform, truth_crs = _band(truth_path)
    if observed_crs != truth_crs:
        return False, f"CRS differs: {observed_crs} vs {truth_crs}", {}
    sampling = rules.get("sampling", "grid")
    if sampling == "grid":
        tolerance = float(rules.get("transform_tolerance", 1e-6))
        if observed.shape != truth.shape or not transforms_match(
            observed_transform, truth_transform, tolerance
        ):
            return (
                False,
                "Observed raster isn't aligned to the truth grid",
                {
                    "observed_shape": list(observed.shape),
                    "truth_shape": list(truth.shape),
                },
            )
    else:
        x, y = _centers(truth_transform, truth.shape)
        observed, observed_valid = _sample(observed, observed_valid, observed_transform, x, y)

    optional = np.zeros(truth.shape, dtype=bool)
    if optional_mask_path is not None:
        optional = _band(optional_mask_path)[0] > 0
    edge = int(rules.get("exclude_edge_pixels", 0))
    compared = np.ones(truth.shape, dtype=bool)
    if ignore_mask_path is not None:
        compared &= _band(ignore_mask_path)[0] == 0
    if edge:
        compared[:edge, :] = compared[-edge:, :] = False
        compared[:, :edge] = compared[:, -edge:] = False

    truth_policy = rules.get("truth_nodata", "required")
    unexpected_valid = 0
    if truth_policy == "required":
        unexpected_valid = int(np.count_nonzero(compared & ~truth_valid & observed_valid & ~optional))
    missing = compared & truth_valid & ~observed_valid & ~optional
    both = compared & truth_valid & observed_valid
    errors = np.abs(observed[both] - truth[both])
    tolerance = float(rules["absolute_tolerance"])
    metrics: dict[str, Any] = {
        "compared_pixels": int(both.sum()),
        "missing_pixels": int(missing.sum()),
        "unexpected_valid_pixels": unexpected_valid,
        "max_abs_error": float(errors.max()) if errors.size else None,
        "mean_abs_error": float(errors.mean()) if errors.size else None,
        "rmse": float(np.sqrt(np.mean(errors**2))) if errors.size else None,
    }
    if not errors.size:
        return False, "No pixels could be compared", metrics
    allowed_missing = float(rules.get("max_missing_fraction", 0.0))
    required_pixels = int((compared & truth_valid & ~optional).sum())
    if required_pixels and missing.sum() / required_pixels > allowed_missing:
        return False, f"{int(missing.sum())} required pixels have no observed value", metrics
    if unexpected_valid:
        return False, f"{unexpected_valid} NoData pixels have observed values", metrics
    bad = int(np.count_nonzero(errors > tolerance))
    if bad:
        return False, f"{bad} pixels differ by more than {tolerance}", metrics
    return True, "", metrics
