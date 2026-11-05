"""Run fixtures against an installed LandFuse.

Calls LandFuse's public functions and reports what they return. Operations
LandFuse has no feature for report UNSUPPORTED.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from importlib import metadata, util
from pathlib import Path
from shutil import which
from typing import Any

import numpy as np

from ..runner.protocol import Capability, CaseView, ExecutionContext, ObservationBundle, Rejection

Values = dict[str, Any]
_SEED = 42
_DEFAULT_TILE = 512
_CHM_NODATA = -9999.0
_GAPS = {
    "raster.alignment": "LandFuse has no alignment diagnostic. It resamples terrain onto the image grid.",
    "landcover.temporal_check": "LandFuse doesn't read or compare acquisition dates.",
    "lidar.density": "LandFuse doesn't report point density.",
    "lidar.vertical_check": "LandFuse doesn't compare LiDAR heights with a DEM.",
}


def _version() -> str | None:
    try:
        return metadata.version("landfuse")
    except metadata.PackageNotFoundError:
        return None


def _modules() -> tuple[Any, Any, Any]:
    return (
        importlib.import_module("landfuse.contract"),
        importlib.import_module("landfuse.raster_ops"),
        importlib.import_module("landfuse.model"),
    )


def _scene(imagery: Path, terrain: Path, mode: str) -> Any:
    return _modules()[0].Scene(imagery, terrain, mode)


def _write_single_band(path: Path, values: np.ndarray, profile: dict[str, Any], nodata: float) -> Path:
    import rasterio

    options = {key: profile[key] for key in ("crs", "transform", "width", "height")}
    with rasterio.open(
        path, "w", driver="GTiff", count=1, dtype="float32", nodata=nodata, **options
    ) as dataset:
        dataset.write(values.astype("float32"), 1)
    return path


def _placeholder_image(dem: Path, output: Path) -> Path:
    """Write a uniform four-band image on the DEM's grid.

    LandFuse computes slope only as a model feature, so slope has to be read
    through the feature cube, and that needs an image on the same grid.
    """
    import rasterio

    with rasterio.open(dem) as source:
        options = {key: source.profile[key] for key in ("crs", "transform", "width", "height")}
        shape = (4, source.height, source.width)
    with rasterio.open(
        output, "w", driver="GTiff", count=4, dtype="uint8", photometric="MINISBLACK", **options
    ) as image:
        image.write(np.full(shape, 100, dtype="uint8"))
    return output


def _slope(context: ExecutionContext) -> Values:
    contract, raster_ops, _ = _modules()
    dem = context.input("dem")
    image = _placeholder_image(dem, context.work_dir / "placeholder.tif")
    tile = int(context.parameters.get("tile_size", _DEFAULT_TILE))
    index = contract.MODEL_FEATURES.index("terrain")
    with raster_ops.open_scene(contract.Scene(image, dem, "dem")) as (naip, terrain, _meta):
        slope = np.full((naip.height, naip.width), _CHM_NODATA, dtype="float32")
        for window in raster_ops.windows(naip, tile):
            cube, valid = raster_ops.get_features(naip, terrain, "dem", window)
            rows = slice(window.row_off, window.row_off + window.height)
            columns = slice(window.col_off, window.col_off + window.width)
            slope[rows, columns] = np.where(valid, cube[:, :, index], _CHM_NODATA)
        profile = dict(naip.profile)
    output = _write_single_band(context.work_dir / "slope.tif", slope, profile, _CHM_NODATA)
    return {"slope": str(output)}


def _coverage(context: ExecutionContext) -> Values:
    _, raster_ops, _ = _modules()
    scene = _scene(context.input("imagery"), context.input("dem"), "dem")
    with raster_ops.open_scene(scene) as (_naip, _terrain, details):
        return {"terrain_coverage_fraction": details.get("terrain_coverage_fraction")}


def _train(context: ExecutionContext) -> Path:
    _, _, model = _modules()
    scene = _scene(context.input("train_imagery"), context.input("train_terrain"), "dem")
    output = context.work_dir / "model.joblib"
    model.train(
        scene,
        context.input("train_labels"),
        output,
        seed=_SEED,
        per_class_limit=int(context.parameters.get("per_class_limit", 1000)),
        tile=int(context.parameters.get("tile_size", 64)),
        trees=int(context.parameters.get("trees", 30)),
    )
    return output


def _infer(context: ExecutionContext, model_path: Path, output: Path) -> None:
    _, _, model = _modules()
    scene = _scene(context.input("test_imagery"), context.input("test_terrain"), "dem")
    tile = int(context.parameters.get("tile_size", 64))
    model.infer(scene, model_path, output, tile=tile, trust_local_model=True)


def _classify(context: ExecutionContext) -> Values:
    output = context.work_dir / "prediction.tif"
    _infer(context, _train(context), output)
    return {"prediction": str(output)}


def _read_failure(context: ExecutionContext) -> ObservationBundle:
    from rasterio.errors import RasterioError

    output = context.work_dir / "prediction.tif"
    trained = _train(context)
    failure = None
    try:
        _infer(context, trained, output)
    except (OSError, RasterioError) as exc:
        failure = Rejection("READ_FAILED", str(exc))
    leftovers = [path for path in (output, output.with_name(output.name + ".partial")) if path.exists()]
    return ObservationBundle(values={"partial_output_written": bool(leftovers)}, rejection=failure)


def _pair_check(context: ExecutionContext) -> Values:
    _, raster_ops, _ = _modules()
    scene = _scene(context.input("imagery"), context.input("dem"), "dem")
    with raster_ops.open_scene(scene) as (_naip, _terrain, details):
        return {
            "pair_status": "VALID",
            "terrain_source": details["terrain_mode"],
            "canopy_height_available": details["terrain_mode"] == "chm",
        }


def _evaluate(context: ExecutionContext) -> Values:
    evaluation = importlib.import_module("landfuse.evaluate")
    report = evaluation.evaluate(
        context.input("prediction"), context.input("reference"), context.work_dir / "evaluation.json"
    )
    present = {
        name: scores["f1-score"]
        for name, scores in report["per_class"].items()
        if isinstance(scores, dict) and name in report["confusion_matrix_labels"] and scores["support"] > 0
    }
    values = {
        "evaluated_pixels": report["evaluated_pixels"],
        "overall_accuracy": report["pixel_accuracy"],
        "coverage": report.get("coverage"),
        "macro_f1": report.get("macro_f1", sum(present.values()) / len(present)),
        "f1": present,
    }
    if "classified_pixels" in report:
        values["classified_pixels"] = report["classified_pixels"]
        values["classified_accuracy"] = report["classified_pixel_accuracy"]
    return values


def _holdout(context: ExecutionContext) -> Values:
    contract, _, _ = _modules()
    crossval = importlib.import_module("landfuse.crossval")
    scene = _scene(context.input("imagery"), context.input("terrain"), "dem")
    item = contract.LabeledScene(scene, context.input("labels"), "scene", "scene")
    parameters = context.parameters
    report = crossval.cross_validate(
        [item],
        context.work_dir / "crossval.json",
        by="block",
        folds=int(parameters["folds"]),
        block_m=float(parameters["block_m"]),
        buffer_m=float(parameters["buffer_m"]),
        seed=_SEED,
        per_class_limit=int(parameters["per_class_limit"]),
        tile=int(parameters.get("tile_size", 64)),
        trees=int(parameters["trees"]),
    )
    return {"holdout_accuracy": report["overall_accuracy"]}


def _chm(context: ExecutionContext) -> Values:
    _, raster_ops, _ = _modules()
    lidar = importlib.import_module("landfuse.lidar")
    imagery = context.input("imagery")
    output = context.work_dir / "chm.tif"
    resolution = float(context.parameters.get("resolution_m", 1.0))
    lidar.pdal_canopy_height(str(context.input("lidar")), imagery, output, resolution_m=resolution)
    with raster_ops.open_scene(_scene(imagery, output, "chm")) as (_naip, _terrain, details):
        return {
            "pair_status": "VALID",
            "terrain_source": "lidar" if details["terrain_mode"] == "chm" else details["terrain_mode"],
            "canopy_height_available": details["terrain_mode"] == "chm",
            "chm": str(output),
            "lidar_file": str(context.input("lidar")),
        }


_OPERATIONS: dict[str, Callable[[ExecutionContext], Values | ObservationBundle]] = {
    "raster.slope": _slope,
    "raster.coverage": _coverage,
    "raster.read_failure": _read_failure,
    "landcover.classify": _classify,
    "landcover.pair_check": _pair_check,
    "landcover.evaluate": _evaluate,
    "landcover.holdout": _holdout,
    "lidar.chm": _chm,
}


class LandFuseAdapter:
    """Maps fixture operations to LandFuse's Python API."""

    name = "landfuse"

    def supports(self, case: CaseView) -> Capability:
        if util.find_spec("landfuse") is None:
            return Capability(False, "LandFuse isn't installed", skip=True)
        if case.operation in _GAPS:
            return Capability(False, _GAPS[case.operation])
        if case.operation not in _OPERATIONS:
            return Capability(False, f"LandFuse has no {case.operation} operation")
        if case.operation == "lidar.chm" and which("pdal") is None:
            return Capability(False, "The pdal command isn't installed", skip=True)
        if case.operation == "landcover.holdout" and util.find_spec("landfuse.crossval") is None:
            return Capability(False, "This LandFuse build has no spatial holdout")
        return Capability(True)

    def execute(self, context: ExecutionContext) -> ObservationBundle:
        contract = _modules()[0]
        try:
            result = _OPERATIONS[context.case.operation](context)
        except contract.LandFuseError as exc:
            return ObservationBundle(rejection=Rejection("INVALID_INPUT", str(exc)))
        return result if isinstance(result, ObservationBundle) else ObservationBundle(values=result)

    def environment(self) -> dict[str, Any]:
        return {"landfuse": _version(), "pdal": which("pdal") is not None}
