"""Small helpers shared by case definitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from ..io.geojson import write_geojson
from ..io.geoparquet import write_geoparquet
from ..io.geotiff import Grid, write_geotiff
from ..models import BuildContext, CaseContent, CaseSpec, InputFile

GEOPARQUET = "GeoParquet 1.1.0"
RFC_GEOJSON = "RFC 7946 GeoJSON"
GEOTIFF = "GeoTIFF 1.1"
LAS = "LAS 1.4 point format 6"


def define(
    case_id: str,
    title: str,
    build: Callable[[BuildContext], CaseContent],
    *,
    tags: tuple[str, ...],
    operation: str,
    oracle: str,
    derivation: str,
    requires: tuple[str, ...],
    formats: tuple[str, ...],
    expected_status: str = "success",
    canonical: bool = True,
    parameters: Mapping[str, Any] | None = None,
    overridable: tuple[str, ...] = (),
) -> CaseSpec:
    """Create a CaseSpec. The generator name is taken from the builder."""
    return CaseSpec(
        case_id=case_id,
        version="1.0.0",
        title=title,
        category={"ingest": "ingestion"}.get(case_id.split(".", 1)[0], case_id.split(".", 1)[0]),
        tags=tags,
        generator=build.__name__.removeprefix("_build_"),
        generator_version="1.0.0",
        operation=operation,
        build=build,
        oracle_method=oracle,
        derivation=derivation,
        requires=requires,
        formats=formats,
        expected_status=expected_status,
        canonical=canonical,
        parameters=dict(parameters or {}),
        overridable=overridable,
    )


def exact(identifier: str, expected: Any, **extra: Any) -> dict[str, Any]:
    return {"id": identifier, "kind": "exact", "expected": expected, **extra}


def set_equal(identifier: str, expected: list[Any], **extra: Any) -> dict[str, Any]:
    return {"id": identifier, "kind": "set_equal", "expected": expected, **extra}


def numeric(
    identifier: str, expected: Any, unit: str, tolerance: float | None = None, **extra: Any
) -> dict[str, Any]:
    """Build a numeric assertion. No tolerance means an exact comparison."""
    assertion = {"id": identifier, "kind": "numeric", "expected": expected, "unit": unit, **extra}
    if tolerance is not None:
        assertion["absolute_tolerance"] = tolerance
    return assertion


def rejection(identifier: str, codes: list[str]) -> dict[str, Any]:
    return {"id": identifier, "kind": "expected_error", "codes": codes}


def parquet_input(role: str, name: str, crs: str) -> InputFile:
    return InputFile(role, f"input/{name}", "GeoParquet", GEOPARQUET, crs=crs)


def geotiff_input(role: str, name: str, crs: str, acquired: str | None = None) -> InputFile:
    return InputFile(role, f"input/{name}", "GeoTIFF", GEOTIFF, crs=crs, acquired=acquired)


def write_features(
    context: BuildContext,
    name: str,
    features: list[dict[str, Any]],
    crs: str,
    *,
    fields: Sequence[tuple[str, str]] = (),
) -> None:
    """Write an input GeoParquet file after checking the feature limit."""
    context.check_features(len(features))
    write_geoparquet(context.input_path(name), features, crs, fields=fields)


def write_collection(
    context: BuildContext, name: str, features: list[dict[str, Any]], *, strict: bool = True
) -> None:
    """Write an input GeoJSON file after checking the feature limit."""
    context.check_features(len(features))
    write_geojson(context.input_path(name), features, strict=strict)


def write_raster(
    context: BuildContext, name: str, array: np.ndarray, grid: Grid, crs: str, **options: Any
) -> None:
    """Write an input GeoTIFF after checking the pixel limit."""
    context.check_pixels(grid.pixels)
    write_geotiff(context.input_path(name), array, grid, crs, **options)
