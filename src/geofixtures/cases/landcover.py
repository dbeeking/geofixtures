"""Imagery, classification, and paired-input cases."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from ..generators.raster import (
    ALTERNATE_SPECTRA,
    CLASS_NAMES,
    CRS,
    NODATA,
    SPECTRA,
    block_labels,
    location_image,
    spectral_image,
    square_grid,
)
from ..io.geotiff import GEOTIFF_PROFILE, Grid, write_geotiff
from ..models import BuildContext, CaseContent, CaseSpec, InputFile
from ._helpers import GEOTIFF, define, exact, geotiff_input, numeric, rejection, write_raster

_SIGMA = 6.0
_SCENE = 96
_BLOCK = 16
_CLASS_NAMES_JSON = {str(code): name for code, name in CLASS_NAMES.items()}
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def _write_scene(context: BuildContext, prefix: str, image: np.ndarray, grid: Grid) -> list[InputFile]:
    write_raster(context, f"{prefix}_imagery.tif", image, grid, CRS)
    terrain = np.full((grid.height, grid.width), 1500.0, dtype="float32")
    write_raster(context, f"{prefix}_terrain.tif", terrain, grid, CRS, nodata=NODATA)
    return [
        geotiff_input(f"{prefix}_imagery", f"{prefix}_imagery.tif", CRS),
        geotiff_input(f"{prefix}_terrain", f"{prefix}_terrain.tif", CRS),
    ]


def _write_labels(context: BuildContext, labels: np.ndarray, grid: Grid) -> InputFile:
    write_raster(context, "train_labels.tif", labels, grid, CRS)
    return geotiff_input("train_labels", "train_labels.tif", CRS)


def classification(
    thresholds: dict[str, dict[str, float]], truth: str = "truth/labels.tif"
) -> dict[str, Any]:
    """Build a classification assertion with every scoring policy stated."""
    return {
        "id": "prediction_scores",
        "observe": "prediction",
        "kind": "classification_metrics",
        "truth": truth,
        "labels": sorted(CLASS_NAMES),
        "class_names": _CLASS_NAMES_JSON,
        "ignore_values": [0],
        "abstain_values": [0],
        "zero_division": 0.0,
        "averaging": "macro over classes present in truth",
        "thresholds": thresholds,
    }


def _class_counts(labels: np.ndarray) -> dict[str, int]:
    return {CLASS_NAMES[code]: int(np.count_nonzero(labels == code)) for code in CLASS_NAMES}


def _build_block_scene(context: BuildContext) -> CaseContent:
    rng = context.rng
    grid = square_grid(_SCENE, 1.0)
    train = block_labels(rng, _SCENE, _BLOCK)
    test = block_labels(rng, _SCENE, _BLOCK)
    inputs = _write_scene(context, "train", spectral_image(rng, train, SPECTRA, _SIGMA), grid)
    inputs.append(_write_labels(context, train, grid))
    inputs += _write_scene(context, "test", spectral_image(rng, test, SPECTRA, _SIGMA), grid)
    write_geotiff(context.truth_path("labels.tif"), test, grid, CRS)
    return CaseContent(
        inputs=inputs,
        parameters={"tile_size": 64, "per_class_limit": 1000, "trees": 30},
        assertions=[classification({"overall_accuracy": {"min": 0.9}, "macro_f1": {"min": 0.9}})],
        truth={"class_pixels": _class_counts(test), "noise_sigma_dn": _SIGMA},
    )


def _build_three_band_image(context: BuildContext) -> CaseContent:
    size = 32
    grid = square_grid(size, 1.0)
    image = np.full((3, size, size), 100, dtype="uint8")
    write_raster(context, "imagery.tif", image, grid, CRS)
    terrain = np.full((size, size), 1500.0, dtype="float32")
    write_raster(context, "dem.tif", terrain, grid, CRS, nodata=NODATA)
    return CaseContent(
        inputs=[geotiff_input("imagery", "imagery.tif", CRS), geotiff_input("dem", "dem.tif", CRS)],
        assertions=[rejection("rejects_missing_nir", ["MISSING_BAND", "INVALID_INPUT"])],
        truth={"bands_present": 3, "bands_required": 4},
    )


def _labeled_map(context: BuildContext, name: str, role: str, values: np.ndarray, grid: Grid) -> InputFile:
    write_raster(context, name, values, grid, CRS)
    return geotiff_input(role, name, CRS)


def _build_hand_counted_mask(context: BuildContext) -> CaseContent:
    grid = square_grid(10, 1.0)
    reference = np.zeros((10, 10), dtype="uint8")
    reference[2:6] = 1
    reference[6:] = 2
    prediction = reference.copy()
    prediction[6, :8] = 1
    return CaseContent(
        inputs=[
            _labeled_map(context, "prediction.tif", "prediction", prediction, grid),
            _labeled_map(context, "reference.tif", "reference", reference, grid),
        ],
        assertions=[
            numeric("evaluated_pixels", 80, "pixels"),
            numeric("overall_accuracy", 72 / 80, "fraction", 1e-9),
            numeric("macro_f1", (10 / 11 + 8 / 9) / 2, "fraction", 1e-9),
            numeric("f1", {"water": 10 / 11, "bare_ground": 8 / 9}, "fraction", 1e-9),
        ],
        truth={
            "unlabeled_pixels": 20,
            "correct_pixels": 72,
            "wrong_pixels": 8,
            "accuracy_if_unlabeled_counted_correct": 0.92,
        },
    )


def _build_mostly_unclassified(context: BuildContext) -> CaseContent:
    size = 40
    grid = square_grid(size, 1.0)
    reference = np.ones((size, size), dtype="uint8")
    reference[size // 2 :] = 2
    prediction = np.zeros((size, size), dtype="uint8")
    prediction[:2] = reference[:2]
    classified = int(np.count_nonzero(prediction))
    fraction = classified / reference.size
    return CaseContent(
        inputs=[
            _labeled_map(context, "prediction.tif", "prediction", prediction, grid),
            _labeled_map(context, "reference.tif", "reference", reference, grid),
        ],
        assertions=[
            numeric("overall_accuracy", fraction, "fraction", 1e-9),
            numeric("coverage", fraction, "fraction", 1e-9),
            numeric("classified_pixels", classified, "pixels", optional=True),
            numeric("classified_accuracy", 1.0, "fraction", 1e-9, optional=True),
        ],
        truth={"labeled_pixels": reference.size, "classified_pixels": classified},
    )


def _build_date_mismatch(context: BuildContext) -> CaseContent:
    size = 32
    grid = square_grid(size, 1.0)
    imagery_time = "2022-06-15T18:00:00+00:00"
    terrain_time = "2015-09-01T00:00:00+00:00"
    image = np.full((4, size, size), 100, dtype="uint8")
    terrain = np.full((size, size), 1500.0, dtype="float32")
    write_raster(context, "imagery.tif", image, grid, CRS, tags={"ACQUISITION_DATETIME": imagery_time})
    write_raster(
        context,
        "dem.tif",
        terrain,
        grid,
        CRS,
        nodata=NODATA,
        tags={"ACQUISITION_DATETIME": terrain_time},
    )
    gap = datetime.strptime(imagery_time, _DATE_FORMAT) - datetime.strptime(terrain_time, _DATE_FORMAT)
    limit = int(context.parameters["max_gap_days"])
    return CaseContent(
        inputs=[
            InputFile(
                "imagery", "input/imagery.tif", "GeoTIFF", GEOTIFF_PROFILE, crs=CRS, acquired=imagery_time
            ),
            InputFile("dem", "input/dem.tif", "GeoTIFF", GEOTIFF_PROFILE, crs=CRS, acquired=terrain_time),
        ],
        parameters={"max_gap_days": limit, "date_tag": "ACQUISITION_DATETIME"},
        assertions=[numeric("gap_days", gap.days, "days"), exact("temporal_status", "MISMATCH")],
        truth={"gap_days": gap.days, "limit_days": limit},
    )


def _build_dem_pair(context: BuildContext) -> CaseContent:
    size = 32
    grid = square_grid(size, 1.0)
    write_raster(context, "imagery.tif", np.full((4, size, size), 100, dtype="uint8"), grid, CRS)
    terrain = np.full((size, size), 1500.0, dtype="float32")
    write_raster(context, "dem.tif", terrain, grid, CRS, nodata=NODATA)
    return CaseContent(
        inputs=[geotiff_input("imagery", "imagery.tif", CRS), geotiff_input("dem", "dem.tif", CRS)],
        assertions=[
            exact("pair_status", "VALID"),
            exact("terrain_source", "dem"),
            exact("canopy_height_available", False),
        ],
        truth={"terrain_source": "dem", "canopy_height_available": False},
    )


def _build_collar_scene(context: BuildContext) -> CaseContent:
    rng = context.rng
    grid = square_grid(_SCENE, 1.0)
    train = block_labels(rng, _SCENE, _BLOCK)
    test = block_labels(rng, _SCENE, _BLOCK)
    inputs = _write_scene(context, "train", spectral_image(rng, train, SPECTRA, _SIGMA), grid)
    inputs.append(_write_labels(context, train, grid))
    image = spectral_image(rng, test, SPECTRA, _SIGMA)
    collar = np.zeros(test.shape, dtype=bool)
    collar[:, :_BLOCK] = True
    image[:, collar] = 0
    inputs += _write_scene(context, "test", image, grid)
    truth_labels = np.where(collar, 0, test).astype("uint8")
    write_geotiff(context.truth_path("labels.tif"), truth_labels, grid, CRS)
    expected_collar = np.where(collar, 0, 255).astype("uint8")
    write_geotiff(context.truth_path("collar.tif"), expected_collar, grid, CRS, nodata=255)
    return CaseContent(
        inputs=inputs,
        parameters={"tile_size": 64, "per_class_limit": 1000, "trees": 30},
        assertions=[
            classification({"overall_accuracy": {"min": 0.9}, "macro_f1": {"min": 0.9}}),
            {
                "id": "collar_left_unclassified",
                "observe": "prediction",
                "kind": "raster_values",
                "truth": "truth/collar.tif",
                "absolute_tolerance": 0.0,
                "unit": "class code",
                "truth_nodata": "ignore",
                "observed_nodata_as_value": True,
            },
        ],
        truth={"collar_pixels": int(collar.sum())},
    )


def _build_two_zone_scene(context: BuildContext) -> CaseContent:
    rng = context.rng
    size = 256
    grid = square_grid(size, 1.0)
    rows = np.indices((size, size))[0]
    zone = rows >= size // 2
    train = block_labels(rng, size, _BLOCK)
    test = block_labels(rng, size, _BLOCK)

    def render(labels: np.ndarray) -> np.ndarray:
        return spectral_image(rng, labels, SPECTRA, _SIGMA, alternate=ALTERNATE_SPECTRA, alternate_mask=zone)

    inputs = _write_scene(context, "train", render(train), grid)
    inputs.append(_write_labels(context, train, grid))
    inputs += _write_scene(context, "test", render(test), grid)
    write_geotiff(context.truth_path("labels.tif"), test, grid, CRS)
    return CaseContent(
        inputs=inputs,
        parameters={"tile_size": 64, "per_class_limit": 200, "trees": 30},
        assertions=[classification({"overall_accuracy": {"min": 0.9}, "macro_f1": {"min": 0.9}})],
        truth={"zone_boundary_row": size // 2},
    )


def _build_location_proxy(context: BuildContext) -> CaseContent:
    rng = context.rng
    size = 128
    grid = square_grid(size, 1.0)
    labels = block_labels(rng, size, _BLOCK)
    write_raster(context, "imagery.tif", location_image(rng, size), grid, CRS)
    terrain = np.full((size, size), 1500.0, dtype="float32")
    write_raster(context, "terrain.tif", terrain, grid, CRS, nodata=NODATA)
    write_raster(context, "labels.tif", labels, grid, CRS)
    limit = float(context.parameters["holdout_accuracy_limit"])
    return CaseContent(
        inputs=[
            geotiff_input("imagery", "imagery.tif", CRS),
            geotiff_input("terrain", "terrain.tif", CRS),
            geotiff_input("labels", "labels.tif", CRS),
        ],
        parameters={"block_m": 32.0, "buffer_m": 8.0, "folds": 3, "per_class_limit": 2000, "trees": 30},
        assertions=[
            {
                "id": "holdout_accuracy",
                "kind": "numeric",
                "minimum": 0.0,
                "maximum": limit,
                "unit": "fraction",
            },
            {
                "id": "random_split_accuracy",
                "kind": "numeric",
                "minimum": 0.8,
                "maximum": 1.0,
                "unit": "fraction",
                "optional": True,
            },
        ],
        truth={
            "chance_accuracy": 1 / 6,
        },
    )


_BOTH = ("raster",)

CASES: tuple[CaseSpec, ...] = (
    define(
        "landcover.scene.rgbnir.001",
        "RGB and NIR scene with known classes",
        _build_block_scene,
        tags=("imagery", "classification", "synthetic"),
        operation="landcover.classify",
        oracle="synthetic_scene_labels",
        derivation="Labels are assigned before pixels exist. Each pixel is drawn from its class's spectrum plus noise of 6 "
        "DN, far smaller than the gaps between spectra.",
        requires=_BOTH,
        formats=(GEOTIFF,),
    ),
    define(
        "landcover.missing_nir.001",
        "Three-band imagery with no NIR",
        _build_three_band_image,
        tags=("imagery", "negative", "input-contract"),
        operation="landcover.pair_check",
        oracle="input_contract",
        derivation="The contract needs red, green, blue, and NIR. This file has three bands.",
        requires=_BOTH,
        formats=(GEOTIFF,),
        expected_status="rejection",
    ),
    define(
        "landcover.truth_mask.001",
        "Scoring with an unlabeled mask",
        _build_hand_counted_mask,
        tags=("classification", "metrics", "mask"),
        operation="landcover.evaluate",
        oracle="hand_counted_confusion",
        derivation="Of 100 pixels, 20 are unlabeled and 80 count. 8 of the 40 bare ground pixels are called water, so 72 are "
        "right and accuracy is 0.9. F1 is 80 / 88 for water and 64 / 72 for bare ground. Counting unlabeled "
        "pixels as correct would give 0.92.",
        requires=_BOTH,
        formats=(GEOTIFF,),
    ),
    define(
        "landcover.unknown.001",
        "Accuracy when most pixels are unclassified",
        _build_mostly_unclassified,
        tags=("classification", "metrics", "nodata", "coverage"),
        operation="landcover.evaluate",
        oracle="hand_counted_confusion",
        derivation="All 1600 pixels are labeled, and only 80 received a class, all correct. Overall accuracy and coverage "
        "are both 80 / 1600 = 0.05. Accuracy over classified pixels alone would read 1.0.",
        requires=_BOTH,
        formats=(GEOTIFF,),
    ),
    define(
        "landcover.date_mismatch.001",
        "Imagery and DEM acquired years apart",
        _build_date_mismatch,
        tags=("imagery", "temporal", "negative"),
        operation="landcover.temporal_check",
        oracle="date_arithmetic",
        derivation="2015-09-01 to 2022-06-15 is 2479 whole days, well beyond the case's limit of 365 days.",
        requires=_BOTH,
        formats=(GEOTIFF,),
        parameters={"max_gap_days": 365},
    ),
    define(
        "landcover.pair.dem.001",
        "Imagery paired with a DEM",
        _build_dem_pair,
        tags=("pairing", "imagery", "dem", "input-contract"),
        operation="landcover.pair_check",
        oracle="input_contract",
        derivation="One image plus one DEM is a valid pair. A bare-earth surface has no canopy height.",
        requires=_BOTH,
        formats=(GEOTIFF,),
    ),
    define(
        "landcover.image_collar.001",
        "Zero-filled image collar stays unclassified",
        _build_collar_scene,
        tags=("imagery", "classification", "nodata"),
        operation="landcover.classify",
        oracle="synthetic_scene_labels",
        derivation="The first 16 columns are zero in all four bands and have no NoData flag, like a scene's collar. "
        "The expected class there is 0.",
        requires=_BOTH,
        formats=(GEOTIFF,),
        canonical=False,
    ),
    define(
        "landcover.sampling_spread.001",
        "Training samples must reach the whole scene",
        _build_two_zone_scene,
        tags=("imagery", "classification", "sampling"),
        operation="landcover.classify",
        oracle="synthetic_scene_labels",
        derivation="Each class has a different spectrum on either side of the midline. A sample limit that fills up in the "
        "first tiles never sees the second zone, and half the scene is misclassified.",
        requires=_BOTH,
        formats=(GEOTIFF,),
        canonical=False,
    ),
    define(
        "landcover.spatial_leakage.001",
        "Holdout scores must not reward location",
        _build_location_proxy,
        tags=("classification", "validation", "spatial-autocorrelation"),
        operation="landcover.holdout",
        oracle="information_bound",
        derivation="Bands hold map position and noise, and classes are random 16 m blocks. A model can only memorize where "
        "each class lies, so accuracy on unseen blocks can't beat chance by much. With 6 classes, chance is 0.17.",
        requires=_BOTH,
        formats=(GEOTIFF,),
        canonical=False,
        parameters={"holdout_accuracy_limit": 0.5},
    ),
)
