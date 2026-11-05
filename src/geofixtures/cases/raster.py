"""Terrain and raster alignment cases on analytic surfaces."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..generators.raster import (
    CRS,
    NODATA,
    centered_xy,
    local_xy,
    plane_surface,
    square_grid,
)
from ..io.geotiff import Grid, write_geotiff
from ..models import BuildContext, CaseContent, CaseSpec, InputFile
from ..oracles.analytic import point_segment_distance
from ..oracles.geometry import stadium_area
from ._helpers import (
    GEOPARQUET,
    GEOTIFF,
    define,
    exact,
    geotiff_input,
    numeric,
    parquet_input,
    rejection,
    set_equal,
    write_features,
    write_raster,
)

_SIZE = 64
_PIXEL = 10.0
SLOPE_TOLERANCE = 1e-4


def _write_truth(context: BuildContext, name: str, values: np.ndarray, grid: Grid) -> str:
    write_geotiff(context.truth_path(name), values.astype("float32"), grid, CRS, nodata=NODATA)
    return f"truth/{name}"


def _slope_assertions(truth: str, grid: Grid, **rules: Any) -> list[dict[str, Any]]:
    options = {"exclude_edge_pixels": 1, "truth_nodata": "ignore", **rules}
    return [
        {
            "id": "slope_grid",
            "observe": "slope",
            "kind": "raster_metadata",
            "expected": {
                "width": grid.width,
                "height": grid.height,
                "crs": CRS,
                "transform": grid.transform_values(),
            },
        },
        {
            "id": "slope",
            "kind": "raster_values",
            "truth": truth,
            "absolute_tolerance": SLOPE_TOLERANCE,
            "unit": "rise/run",
            **options,
        },
    ]


def _slope_case(
    context: BuildContext, grid: Grid, surface: np.ndarray, slope: np.ndarray, **parameters: Any
) -> CaseContent:
    write_raster(context, "dem.tif", surface.astype("float32"), grid, CRS, nodata=NODATA)
    truth = _write_truth(context, "slope.tif", slope, grid)
    return CaseContent(
        inputs=[geotiff_input("dem", "dem.tif", CRS)],
        parameters={"edge_policy": "outer row and column excluded", **parameters},
        assertions=_slope_assertions(truth, grid),
        truth={"minimum_slope": float(slope.min()), "maximum_slope": float(slope.max())},
        tolerances={"slope": SLOPE_TOLERANCE},
    )


def _build_plane(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    return _slope_case(context, grid, plane_surface(grid), np.full((_SIZE, _SIZE), 0.05))


def _build_saddle(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    x, y = centered_xy(grid, 31.5)
    surface = 1500.0 + 0.001 * (x**2 - y**2)
    return _slope_case(context, grid, surface, 0.002 * np.hypot(x, y))


def _build_paraboloid(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    x, y = centered_xy(grid, 32.0)
    surface = 1500.0 + 0.001 * (x**2 + y**2)
    content = _slope_case(context, grid, surface, 0.002 * np.hypot(x, y))
    content.assertions.append(numeric("min_cell", [32, 32], "row, column", optional=True))
    content.truth["minimum_cell"] = [32, 32]
    return content


def _build_tile_paraboloid(context: BuildContext) -> CaseContent:
    grid = square_grid(128, 5.0)
    x, y = centered_xy(grid, 64.0)
    surface = 1500.0 + 0.001 * (x**2 + y**2)
    tile = int(context.parameters["tile_size"])
    return _slope_case(context, grid, surface, 0.002 * np.hypot(x, y), tile_size=tile)


def _build_nodata_hole(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    surface = plane_surface(grid)
    hole = np.zeros((_SIZE, _SIZE), dtype=bool)
    hole[24:40, 24:40] = True
    surface[hole] = NODATA
    write_raster(context, "dem.tif", surface, grid, CRS, nodata=NODATA)
    slope = np.where(hole, NODATA, 0.05)
    truth = _write_truth(context, "slope.tif", slope, grid)
    ring = np.zeros((_SIZE, _SIZE), dtype="uint8")
    ring[23:41, 23:41] = 1
    ring[hole] = 0
    write_geotiff(context.truth_path("hole_ring.tif"), ring, grid, CRS)
    return CaseContent(
        inputs=[geotiff_input("dem", "dem.tif", CRS)],
        parameters={"edge_policy": "outer row and column excluded"},
        assertions=_slope_assertions(
            truth, grid, truth_nodata="required", optional_mask="truth/hole_ring.tif"
        ),
        truth={"hole_pixels": int(hole.sum()), "ring_pixels": int(ring.sum())},
        tolerances={"slope": SLOPE_TOLERANCE},
    )


def _plain_image(grid: Grid) -> np.ndarray:
    return np.full((4, grid.height, grid.width), 100, dtype="uint8")


def _build_half_pixel_offset(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    shifted = grid.shifted(_PIXEL / 2, -_PIXEL / 2)
    write_raster(context, "imagery.tif", _plain_image(grid), grid, CRS)
    write_raster(context, "dem.tif", plane_surface(shifted), shifted, CRS, nodata=NODATA)
    return CaseContent(
        inputs=[geotiff_input("imagery", "imagery.tif", CRS), geotiff_input("dem", "dem.tif", CRS)],
        assertions=[
            exact("alignment", "MISALIGNED"),
            numeric("offset_pixels", [0.5, 0.5], "column, row pixels", 1e-9),
        ],
        truth={"offset_m": [_PIXEL / 2, _PIXEL / 2]},
        tolerances={"offset_pixels": 1e-9},
    )


def _build_partial_coverage(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    covered = 16
    partial = Grid(covered, _SIZE, _PIXEL, grid.origin_x, grid.origin_y)
    write_raster(context, "imagery.tif", _plain_image(grid), grid, CRS)
    write_raster(context, "dem.tif", plane_surface(partial), partial, CRS, nodata=NODATA)
    fraction = covered / _SIZE
    return CaseContent(
        inputs=[geotiff_input("imagery", "imagery.tif", CRS), geotiff_input("dem", "dem.tif", CRS)],
        assertions=[
            numeric("terrain_coverage_fraction", fraction, "fraction", 1e-6),
            exact("coverage_status", "PARTIAL", optional=True),
        ],
        truth={"terrain_coverage_fraction": fraction},
        tolerances={"fraction": 1e-6},
    )


def _map_feature(identifier: str, kind: str, coordinates: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"id": identifier},
        "geometry": {"type": kind, "coordinates": coordinates},
    }


def _build_drainage(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    west = grid.origin_x
    south = grid.origin_y - grid.height * grid.pixel
    x, y = local_xy(grid)
    channel_row = 32
    channel_y = float(y[channel_row, 0])
    surface = (1500.0 + 0.02 * np.abs(y - channel_y)).astype("float32")
    write_raster(context, "dem.tif", surface, grid, CRS, nodata=NODATA)
    start, end = (55.0, channel_y), (585.0, channel_y)
    half_width = 30.0
    points = {
        "on_line": (300.0, channel_y),
        "north_50": (300.0, channel_y + 50.0),
        "past_end": (end[0] + 30.0, channel_y + 40.0),
        "far": (300.0, channel_y + 185.0),
    }
    fields = (("id", "string"),)
    line = [[west + start[0], south + start[1]], [west + end[0], south + end[1]]]
    write_features(
        context,
        "flowline.parquet",
        [_map_feature("flowline", "LineString", line)],
        CRS,
        fields=fields,
    )
    write_features(
        context,
        "points.parquet",
        [_map_feature(name, "Point", [west + px, south + py]) for name, (px, py) in points.items()],
        CRS,
        fields=fields,
    )
    distances = {name: point_segment_distance(xy, start, end) for name, xy in points.items()}
    length = end[0] - start[0]
    area = stadium_area(length, half_width)
    return CaseContent(
        inputs=[
            geotiff_input("dem", "dem.tif", CRS),
            parquet_input("flowline", "flowline.parquet", CRS),
            parquet_input("points", "points.parquet", CRS),
        ],
        parameters={"buffer_m": half_width},
        assertions=[
            numeric("flowline_length", length, "m", 1e-6),
            numeric("distances", distances, "m", 1e-6),
            numeric("buffer_area", area, "m2", 1.0),
            set_equal("points_in_buffer", [name for name, value in distances.items() if value <= half_width]),
            numeric("corridor_row", channel_row, "row"),
        ],
        truth={"distances_m": distances, "buffer_area_m2": area, "flowline_length_m": length},
        tolerances={"buffer_area_m2": 1.0},
    )


def _build_restriction_overlay(context: BuildContext) -> CaseContent:
    grid = square_grid(_SIZE, _PIXEL)
    west = grid.origin_x
    south = grid.origin_y - grid.height * grid.pixel
    low, high = 103.0, 297.0
    write_raster(context, "base.tif", np.ones((_SIZE, _SIZE), dtype="uint8"), grid, CRS)
    ring = [
        [west + low, south + low],
        [west + high, south + low],
        [west + high, south + high],
        [west + low, south + high],
        [west + low, south + low],
    ]
    write_features(
        context,
        "restriction.parquet",
        [_map_feature("restricted", "Polygon", [ring])],
        CRS,
        fields=(("id", "string"),),
    )
    x, y = local_xy(grid)
    inside = (x > low) & (x < high) & (y > low) & (y < high)
    restricted = int(inside.sum())
    pixel_area = grid.pixel**2
    write_geotiff(context.truth_path("restricted.tif"), inside.astype("uint8"), grid, CRS)
    return CaseContent(
        inputs=[
            geotiff_input("base", "base.tif", CRS),
            parquet_input("restriction", "restriction.parquet", CRS),
        ],
        parameters={"rasterization_rule": "pixel_center"},
        assertions=[
            numeric("restricted_pixels", restricted, "pixels"),
            numeric("allowed_pixels", grid.pixels - restricted, "pixels"),
            numeric("restricted_area", restricted * pixel_area, "m2", 1e-9),
            {
                "id": "restricted_mask",
                "kind": "raster_values",
                "truth": "truth/restricted.tif",
                "absolute_tolerance": 0.0,
                "unit": "mask",
                "truth_nodata": "required",
                "optional": True,
            },
        ],
        truth={"restricted_pixels": restricted, "restricted_area_m2": restricted * pixel_area},
    )


def _build_truncated_image(context: BuildContext) -> CaseContent:
    from ..generators.raster import SPECTRA, block_labels, spectral_image

    rng = context.rng
    train_grid = square_grid(_SIZE, 1.0)
    labels = block_labels(rng, _SIZE, 16)
    write_raster(context, "train_imagery.tif", spectral_image(rng, labels, SPECTRA, 6.0), train_grid, CRS)
    flat = np.full((_SIZE, _SIZE), 1500.0, dtype="float32")
    write_raster(context, "train_terrain.tif", flat, train_grid, CRS, nodata=NODATA)
    write_raster(context, "train_labels.tif", labels, train_grid, CRS)
    size = 256
    grid = square_grid(size, 1.0)
    test_labels = block_labels(rng, size, 16)
    context.check_pixels(grid.pixels)
    image_path = context.input_path("test_imagery.tif")
    write_geotiff(image_path, spectral_image(rng, test_labels, SPECTRA, 6.0), grid, CRS, tiled=True)
    write_raster(
        context,
        "test_terrain.tif",
        np.full((size, size), 1500.0, dtype="float32"),
        grid,
        CRS,
        nodata=NODATA,
    )
    full_size = image_path.stat().st_size
    kept = int(full_size * float(context.parameters["kept_fraction"]))
    with open(image_path, "r+b") as stream:
        stream.truncate(kept)
    return CaseContent(
        inputs=[
            geotiff_input("train_imagery", "train_imagery.tif", CRS),
            geotiff_input("train_terrain", "train_terrain.tif", CRS),
            geotiff_input("train_labels", "train_labels.tif", CRS),
            InputFile("test_imagery", "input/test_imagery.tif", "GeoTIFF", "Truncated GeoTIFF 1.1", crs=CRS),
            geotiff_input("test_terrain", "test_terrain.tif", CRS),
        ],
        parameters={"tile_size": 64},
        assertions=[
            rejection("rejects_truncated_image", ["READ_FAILED"]),
            {"id": "partial_output_written", "kind": "invariant", "rule": "is_false", "optional": True},
        ],
        truth={"full_bytes": full_size, "kept_bytes": kept},
    )


_TERRAIN_FORMATS = (GEOTIFF,)

CASES: tuple[CaseSpec, ...] = (
    define(
        "raster.dem.slope.001",
        "Slope of an analytic plane",
        _build_plane,
        tags=("terrain", "slope", "analytic"),
        operation="raster.slope",
        oracle="analytic_surface",
        derivation="z = 1500 + 0.03 x + 0.04 y has gradient (0.03, 0.04), so rise over run is 0.05 everywhere. "
        "A central difference is exact on a plane. The outer row and column are excluded.",
        requires=("raster",),
        formats=_TERRAIN_FORMATS,
    ),
    define(
        "raster.ridge_saddle.001",
        "Slope across a saddle",
        _build_saddle,
        tags=("terrain", "slope", "analytic", "saddle"),
        operation="raster.slope",
        oracle="analytic_surface",
        derivation="z = 1500 + 0.001 (x2 - y2) has gradient (0.002 x, -0.002 y). A central difference is exact "
        "for a quadratic, so slope is 0.002 times the distance from the saddle.",
        requires=("raster",),
        formats=_TERRAIN_FORMATS,
    ),
    define(
        "raster.depression.001",
        "Slope around a closed depression",
        _build_paraboloid,
        tags=("terrain", "slope", "analytic", "depression"),
        operation="raster.slope",
        oracle="analytic_surface",
        derivation="z = 1500 + 0.001 (x2 + y2) has slope 0.002 r, with its minimum exactly at cell (32, 32).",
        requires=("raster",),
        formats=_TERRAIN_FORMATS,
    ),
    define(
        "raster.nodata_hole.001",
        "Slope around a NoData hole",
        _build_nodata_hole,
        tags=("terrain", "slope", "nodata"),
        operation="raster.slope",
        oracle="analytic_surface",
        derivation="The plane has slope 0.05, so a valid output next to the hole must still be 0.05. Hole pixels have no "
        "elevation and must stay NoData. The one-pixel ring around the hole may be NoData or 0.05.",
        requires=("raster",),
        formats=_TERRAIN_FORMATS,
    ),
    define(
        "raster.grid.offset.001",
        "Imagery and DEM offset by half a pixel",
        _build_half_pixel_offset,
        tags=("alignment", "negative", "imagery"),
        operation="raster.alignment",
        oracle="grid_geometry",
        derivation="The DEM origin is moved 5 m east and 5 m south on a 10 m grid, which is half a pixel on each axis.",
        requires=("raster",),
        formats=_TERRAIN_FORMATS,
    ),
    define(
        "raster.partial_coverage.001",
        "DEM covering a quarter of the image",
        _build_partial_coverage,
        tags=("alignment", "coverage", "negative"),
        operation="raster.coverage",
        oracle="grid_geometry",
        derivation="The DEM has the image's height and 16 of its 64 columns, so it covers 16 / 64 = 0.25.",
        requires=("raster",),
        formats=_TERRAIN_FORMATS,
    ),
    define(
        "raster.drainage.001",
        "Flowline distance and buffer area",
        _build_drainage,
        tags=("terrain", "drainage", "distance"),
        operation="raster.drainage",
        oracle="analytic_geometry",
        derivation="The flowline is straight and 530 m long along the valley floor. Distances are right triangles from "
        "the line or its end. A 30 m round-capped buffer covers 2 w L + pi w2 m2. The 1 m2 tolerance allows "
        "for circles drawn as polygons.",
        requires=("raster", "vector"),
        formats=(GEOTIFF, GEOPARQUET),
    ),
    define(
        "raster.restriction_overlay.001",
        "Restriction polygon over a raster",
        _build_restriction_overlay,
        tags=("overlay", "exclusion", "rasterization"),
        operation="raster.overlay",
        oracle="pixel_center_rule",
        derivation="The polygon spans 103 m to 297 m on both axes. Pixel centers fall at 5, 15, 25 m and so on, and "
        "20 of them lie inside on each axis. That gives 400 pixels, or 40000 m2, under the pixel-center rule.",
        requires=("raster", "vector"),
        formats=(GEOTIFF, GEOPARQUET),
    ),
    define(
        "raster.tile_seam.001",
        "Slope continuity across tile edges",
        _build_tile_paraboloid,
        tags=("terrain", "slope", "tiling"),
        operation="raster.slope",
        oracle="analytic_surface",
        derivation="The paraboloid's central-difference slope is exact, so a value that changes at a tile edge is an "
        "error. Tiles are 64 pixels on a 128 pixel grid.",
        requires=("raster",),
        formats=_TERRAIN_FORMATS,
        canonical=False,
        parameters={"tile_size": 64},
        overridable=("tile_size",),
    ),
    define(
        "raster.truncated.001",
        "Truncated imagery leaves no partial output",
        _build_truncated_image,
        tags=("integrity", "negative", "tiling"),
        operation="raster.read_failure",
        oracle="corruption_rule",
        derivation="The GeoTIFF loses the end of its pixel data but keeps a readable header, so failures appear only "
        "while reading tiles. The run must stop and leave no output.",
        requires=("raster",),
        formats=("Truncated GeoTIFF 1.1",),
        expected_status="rejection",
        canonical=False,
        parameters={"kept_fraction": 0.6},
    ),
)
