"""Point cloud cases over a known ground plane."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..generators.lidar import (
    BUILDING,
    GROUND,
    HIGH_VEGETATION,
    Box,
    Scene,
    block_points,
    ground_plane,
    outside,
    stratified,
)
from ..generators.raster import CRS, NODATA, local_xy, square_grid
from ..io.geotiff import Grid, write_geotiff
from ..io.las import LAS_POINT_FORMAT, LAS_VERSION, write_las
from ..models import BuildContext, CaseContent, CaseSpec, InputFile
from ._helpers import GEOTIFF, LAS, define, exact, geotiff_input, numeric, write_raster

_METRES_PER_FOOT = 0.3048
_IMAGE_FORMATS = (LAS, GEOTIFF)


def _las_input(role: str = "lidar", name: str = "points.las") -> InputFile:
    return InputFile(role, f"input/{name}", "LAS", LAS, crs=CRS)


def _inside(x: np.ndarray, y: np.ndarray, box: Box) -> np.ndarray:
    return (x >= box[0]) & (x <= box[2]) & (y >= box[1]) & (y <= box[3])


def _grown(box: Box, distance: float) -> Box:
    return (box[0] - distance, box[1] - distance, box[2] + distance, box[3] + distance)


def _write_cloud(context: BuildContext, scene: Scene, parts: list[tuple[np.ndarray, ...]]) -> int:
    x = np.concatenate([part[0] for part in parts])
    y = np.concatenate([part[1] for part in parts])
    z = np.concatenate([part[2] for part in parts])
    classes = np.concatenate([part[3] for part in parts])
    context.check_points(x.size)
    write_las(context.input_path("points.las"), scene.west + x, scene.south + y, z, classes, CRS)
    return int(x.size)


def _ground_points(
    rng: np.random.Generator, scene: Scene, density: float, *gaps: Box
) -> tuple[np.ndarray, ...]:
    x, y = stratified(rng, (0.0, 0.0, scene.size, scene.size), density)
    keep = np.ones(x.size, dtype=bool)
    for gap in gaps:
        keep &= outside(x, y, gap)
    x, y = x[keep], y[keep]
    return x, y, ground_plane(x, y), np.full(x.size, GROUND, dtype="uint8")


def _image(context: BuildContext, grid: Grid) -> InputFile:
    image = np.full((4, grid.height, grid.width), 100, dtype="uint8")
    write_raster(context, "imagery.tif", image, grid, CRS)
    return geotiff_input("imagery", "imagery.tif", CRS)


def _chm_assertions(tolerance: float, count: int, **masks: str) -> list[dict[str, Any]]:
    return [
        exact("pair_status", "VALID"),
        exact("terrain_source", "lidar"),
        exact("canopy_height_available", True),
        {
            "id": "chm",
            "kind": "raster_values",
            "truth": "truth/chm.tif",
            "absolute_tolerance": tolerance,
            "unit": "m",
            "sampling": "map_coordinates",
            "exclude_edge_pixels": 2,
            "truth_nodata": "ignore",
            **masks,
        },
        {
            "id": "lidar_header",
            "observe": "lidar_file",
            "kind": "pointcloud_metadata",
            "expected": {
                "version": LAS_VERSION,
                "point_format": LAS_POINT_FORMAT,
                "count": count,
                "crs": CRS,
            },
            "optional": True,
        },
    ]


def _build_ground_and_canopy(context: BuildContext) -> CaseContent:
    rng = context.rng
    scene = Scene(60.0)
    density = 4.0
    trees: Box = (10.0, 10.0, 30.0, 30.0)
    roof: Box = (40.0, 35.0, 52.0, 50.0)
    count = _write_cloud(
        context,
        scene,
        [
            _ground_points(rng, scene, density, roof),
            block_points(rng, trees, density, 12.0, HIGH_VEGETATION),
            block_points(rng, roof, density, 6.0, BUILDING),
        ],
    )
    grid = square_grid(60, 1.0)
    x, y = local_xy(grid)
    chm = np.zeros((60, 60), dtype="float32")
    chm[_inside(x, y, trees)] = 12.0
    chm[_inside(x, y, roof)] = 6.0
    write_geotiff(context.truth_path("chm.tif"), chm, grid, CRS, nodata=NODATA)
    band = np.zeros((60, 60), dtype="uint8")
    for box in (trees, roof):
        band[_inside(x, y, _grown(box, 3.0)) & ~_inside(x, y, _grown(box, -3.0))] = 1
    write_geotiff(context.truth_path("edge_band.tif"), band, grid, CRS)
    under_roof = _inside(x, y, _grown(roof, -3.0)).astype("uint8")
    write_geotiff(context.truth_path("roof_interior.tif"), under_roof, grid, CRS)
    return CaseContent(
        inputs=[_las_input(), _image(context, grid)],
        parameters={"resolution_m": 1.0},
        assertions=_chm_assertions(
            0.25, count, ignore_mask="truth/edge_band.tif", optional_mask="truth/roof_interior.tif"
        ),
        truth={"tree_height_m": 12.0, "roof_height_m": 6.0, "points": count},
        tolerances={"height_m": 0.25},
    )


def _build_sparse_cloud(context: BuildContext) -> CaseContent:
    scene = Scene(40.0)
    density = 1.0
    count = _write_cloud(context, scene, [_ground_points(context.rng, scene, density)])
    threshold = float(context.parameters["threshold"])
    area = scene.size**2
    actual = count / area
    return CaseContent(
        inputs=[_las_input()],
        parameters={"threshold_pts_per_m2": threshold, "footprint_m2": area},
        assertions=[
            numeric("point_count", count, "points"),
            numeric("density", actual, "points/m2", 1e-9),
            exact("density_status", "BELOW_THRESHOLD"),
        ],
        truth={"density_pts_per_m2": actual, "threshold_pts_per_m2": threshold},
    )


def _build_feet_over_metres(context: BuildContext) -> CaseContent:
    scene = Scene(40.0)
    x, y, z, classes = _ground_points(context.rng, scene, 4.0)
    write_las(
        context.input_path("points.las"), scene.west + x, scene.south + y, z / _METRES_PER_FOOT, classes, CRS
    )
    grid = square_grid(40, 1.0)
    grid_x, grid_y = local_xy(grid)
    write_raster(
        context,
        "dem.tif",
        ground_plane(grid_x, grid_y).astype("float32"),
        grid,
        CRS,
        nodata=NODATA,
    )
    ratio = 1.0 / _METRES_PER_FOOT
    return CaseContent(
        inputs=[_las_input(), geotiff_input("dem", "dem.tif", CRS)],
        assertions=[
            {
                "id": "z_ratio",
                "kind": "numeric",
                "expected": ratio,
                "unit": "ratio",
                "relative_tolerance": 1e-3,
            },
            exact("vertical_status", "MISMATCH"),
        ],
        truth={"z_ratio": ratio},
        tolerances={"relative_z_ratio": 1e-3},
    )


def _build_canopy_over_gap(context: BuildContext) -> CaseContent:
    rng = context.rng
    scene = Scene(60.0)
    density = 4.0
    canopy: Box = (15.0, 15.0, 45.0, 45.0)
    count = _write_cloud(
        context,
        scene,
        [
            _ground_points(rng, scene, density, canopy),
            block_points(rng, canopy, density, 12.0, HIGH_VEGETATION),
        ],
    )
    grid = square_grid(60, 1.0)
    x, y = local_xy(grid)
    chm = np.zeros((60, 60), dtype="float32")
    chm[_inside(x, y, canopy)] = 12.0
    write_geotiff(context.truth_path("chm.tif"), chm, grid, CRS, nodata=NODATA)
    interior = _inside(x, y, _grown(canopy, -3.0))
    band = _inside(x, y, _grown(canopy, 3.0)) & ~interior
    write_geotiff(context.truth_path("edge_band.tif"), band.astype("uint8"), grid, CRS)
    return CaseContent(
        inputs=[_las_input(), _image(context, grid)],
        parameters={"resolution_m": 1.0},
        assertions=_chm_assertions(1.5, count, ignore_mask="truth/edge_band.tif"),
        truth={"canopy_height_m": 12.0, "interior_pixels": int(interior.sum()), "points": count},
        tolerances={"height_m": 1.5},
    )


CASES: tuple[CaseSpec, ...] = (
    define(
        "landcover.pair.lidar.001",
        "Imagery paired with a LAS point cloud",
        _build_ground_and_canopy,
        tags=("pairing", "lidar", "canopy", "input-contract"),
        operation="lidar.chm",
        oracle="constructed_heights",
        derivation="Trees sit exactly 12 m and a roof exactly 6 m above z = 1600 + 0.02 x + 0.01 y. Points are stratified at "
        "4 per m2, so a cell's top can differ from the true height only by the ground's tilt within it. Cells within "
        "3 m of a block edge can mix surfaces and aren't compared. The roof interior has no ground returns, so it "
        "may be NoData. lidar.ground_gap.001 covers gap filling.",
        requires=("lidar", "raster"),
        formats=_IMAGE_FORMATS,
    ),
    define(
        "lidar.density.001",
        "Point density below a threshold",
        _build_sparse_cloud,
        tags=("lidar", "density", "negative"),
        operation="lidar.density",
        oracle="point_count",
        derivation="One point falls in each cell of a 40 by 40 grid, so 1600 points over 1600 m2 is 1 point per m2. "
        "The scenario requires 2.",
        requires=("lidar",),
        formats=(LAS,),
        parameters={"threshold": 2.0},
        overridable=("threshold",),
    ),
    define(
        "lidar.vertical_mismatch.001",
        "LAS heights in feet over a DEM in metres",
        _build_feet_over_metres,
        tags=("lidar", "vertical", "negative"),
        operation="lidar.vertical_check",
        oracle="constructed_heights",
        derivation="Ground point heights are the DEM surface divided by 0.3048, so every height ratio is 1 / 0.3048.",
        requires=("lidar", "raster"),
        formats=_IMAGE_FORMATS,
    ),
    define(
        "lidar.ground_gap.001",
        "Canopy height with no ground returns beneath",
        _build_canopy_over_gap,
        tags=("lidar", "canopy", "gaps"),
        operation="lidar.chm",
        oracle="constructed_heights",
        derivation="A 30 by 30 m canopy block has no ground returns, and its height above the plane is 12 m. The target has "
        "to interpolate ground across the gap. The 1.5 m tolerance allows for interpolating over 15 m.",
        requires=("lidar", "raster"),
        formats=_IMAGE_FORMATS,
        canonical=False,
    ),
)
