"""Reference implementations used to verify GeoFixtures itself.

Each operation uses shapely, pyproj, rasterio, laspy, or numpy directly. This
module doesn't import the oracles or read truth files.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Callable
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

from ..runner.protocol import Capability, CaseView, ExecutionContext, ObservationBundle, Rejection

Values = dict[str, Any]
INSUFFICIENT = "INSUFFICIENT_INFORMATION"
_UNITS = {"foot": 1.0 / 0.3048, "US survey foot": 3937.0 / 1200.0, "metre": 1.0}
_PROTOTYPE_TILE = 16


def _read_parquet(path: Path) -> tuple[dict[str, Any], Any]:
    """Return {id: geometry} and the arrow table."""
    import pyarrow.parquet as pq
    import shapely

    table = pq.read_table(path)
    identifiers = table.column("id").to_pylist()
    geometries = shapely.from_wkb(table.column("geometry").to_pylist())
    return dict(zip(identifiers, geometries, strict=True)), table


def _parquet_crs(table: Any) -> Any:
    from pyproj import CRS

    geo = json.loads(table.schema.metadata[b"geo"])
    return CRS.from_json_dict(geo["columns"][geo["primary_column"]]["crs"])


def _read_geojson(path: Path) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = json.loads(path.read_text())["features"]
    return features


def _overlap(context: ExecutionContext) -> Values:
    import shapely

    shapes, _ = _read_parquet(context.input("features"))
    pairs = []
    overlap_area = 0.0
    shared = None
    for (left, a), (right, b) in itertools.combinations(sorted(shapes.items()), 2):
        common = a.intersection(b)
        if common.area > 0:
            pairs.append(f"{left}|{right}")
            overlap_area += common.area
            shared = common
    return {
        "overlap_pairs": pairs,
        "overlap_area": overlap_area,
        "union_area": shapely.union_all(list(shapes.values())).area,
        "overlap_geometry": None if shared is None else shared.wkt,
    }


def _gap(context: ExecutionContext) -> Values:
    import shapely

    shapes, _ = _read_parquet(context.input("features"))
    union = shapely.union_all(list(shapes.values()))
    values = _overlap(context)
    pairs = itertools.combinations(shapes.values(), 2)
    return {
        "gap_area": union.envelope.area - union.area,
        "min_separation": min(a.distance(b) for a, b in pairs),
        "overlap_pairs": values["overlap_pairs"],
    }


def _validity(context: ExecutionContext) -> Values:
    import shapely

    shapes, _ = _read_parquet(context.input("features"))
    invalid = {name: shape for name, shape in shapes.items() if not shape.is_valid}
    repaired = shapely.union_all([shapely.make_valid(shape) for shape in invalid.values()])
    return {
        "invalid_ids": sorted(invalid),
        "repaired_area": repaired.area,
        "repaired_type": repaired.geom_type,
        "repaired_geometry": repaired.wkt,
    }


def _sliver(context: ExecutionContext) -> Values:
    shapes, _ = _read_parquet(context.input("features"))
    threshold = context.parameters["polsby_popper_threshold"]
    scores = {name: 4 * math.pi * shape.area / shape.length**2 for name, shape in shapes.items()}
    return {
        "polsby_popper": scores,
        "sliver_ids": [name for name, score in scores.items() if score < threshold],
    }


def _point_in_polygon(context: ExecutionContext) -> Values:
    polygons, _ = _read_parquet(context.input("polygon"))
    points, _ = _read_parquet(context.input("points"))
    polygon = next(iter(polygons.values()))
    tolerance = context.parameters["boundary_tolerance_m"]
    return {
        "contains": {name: bool(polygon.contains(point)) for name, point in points.items()},
        "covers": {name: bool(polygon.covers(point)) for name, point in points.items()},
        "on_boundary": {name: bool(polygon.boundary.intersects(point)) for name, point in points.items()},
        "near_boundary": {
            name: polygon.boundary.distance(point) <= tolerance for name, point in points.items()
        },
    }


def _relations(context: ExecutionContext) -> Values:
    shapes, _ = _read_parquet(context.input("features"))
    subject_name = context.parameters["subject"]
    subject = shapes[subject_name]
    matrix = {}
    for name, other in shapes.items():
        if name != subject_name:
            matrix[f"{subject_name}|{name}"] = {
                "intersects": subject.intersects(other),
                "disjoint": subject.disjoint(other),
                "touches": subject.touches(other),
                "overlaps": subject.overlaps(other),
                "within": subject.within(other),
                "contains": subject.contains(other),
            }
    return {"relations": matrix}


def _distance(context: ExecutionContext) -> Values:
    lines, _ = _read_parquet(context.input("line"))
    points, _ = _read_parquet(context.input("points"))
    line = next(iter(lines.values()))
    return {"distances": {name: line.distance(point) for name, point in points.items()}}


def _multipart(context: ExecutionContext) -> Values:
    study, _ = _read_parquet(context.input("study_area"))
    exclusions, _ = _read_parquet(context.input("exclusion"))
    area = next(iter(study.values()))
    exclusion = next(iter(exclusions.values()))
    return {
        "part_count": len(exclusion.geoms),
        "exclusion_area": exclusion.area,
        "remaining_area": area.difference(exclusion).area,
    }


def _transform(context: ExecutionContext) -> Values:
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", context.parameters["target_crs"], always_xy=True)
    projected = {}
    for item in _read_geojson(context.input("controls")):
        projected[item["properties"]["id"]] = list(transformer.transform(*item["geometry"]["coordinates"]))
    return {"projected": projected}


def _validate_labels(context: ExecutionContext) -> Values:
    shapes, table = _read_parquet(context.input("features"))
    crs = _parquet_crs(table)
    bounds = [shape.bounds for shape in shapes.values()]
    in_range = True
    if crs.is_geographic:
        in_range = all(
            abs(b[0]) <= 180 and abs(b[2]) <= 180 and abs(b[1]) <= 90 and abs(b[3]) <= 90 for b in bounds
        )
    return {"label_consistent": in_range, "correction": "NOT_NEEDED" if in_range else INSUFFICIENT}


def _validate_position(context: ExecutionContext) -> ObservationBundle:
    for item in _read_geojson(context.input("features")):
        first, second = item["geometry"]["coordinates"][:2]
        if abs(second) > 90:
            if abs(first) <= 90 and abs(second) <= 180:
                return ObservationBundle(
                    rejection=Rejection("AXIS_ORDER_SUSPECT", f"Latitude {second} is out of range")
                )
            return ObservationBundle(rejection=Rejection("COORDINATE_OUT_OF_RANGE", str([first, second])))
    return ObservationBundle(values={"position_valid": True})


def _unit_check(context: ExecutionContext) -> Values:
    lines, table = _read_parquet(context.input("lines"))
    declared = _parquet_crs(table).axis_info[0].unit_conversion_factor
    controls = context.parameters["control_distances_m"]
    ratios = {name: lines[name].length / distance for name, distance in controls.items()}
    detected = {name: INSUFFICIENT for name in lines}
    for name, ratio in ratios.items():
        for unit, value in _UNITS.items():
            if abs(ratio - value) <= 1e-7 * value:
                detected[name] = unit
    consistent = all(abs(ratio * declared - 1.0) <= 1e-6 for ratio in ratios.values())
    return {"unit_ratio": ratios, "detected_unit": detected, "declared_unit_consistent": consistent}


def _vertical_compare(context: ExecutionContext) -> Values:
    states = {}
    for role in ("reference", "candidate"):
        _, table = _read_parquet(context.input(role))
        crs = _parquet_crs(table)
        states[role] = "SPECIFIED" if crs.is_vertical or crs.is_compound else "UNSPECIFIED"
    comparable = all(state == "SPECIFIED" for state in states.values())
    return {"vertical_state": states, "comparison": "COMPARABLE" if comparable else INSUFFICIENT}


def _read_elevation(path: Path) -> tuple[np.ndarray, dict[str, Any], tuple[float, float]]:
    import rasterio

    with rasterio.open(path) as dataset:
        band = dataset.read(1, masked=True).astype("float64").filled(np.nan)
        return band, dict(dataset.profile), (dataset.res[0], dataset.res[1])


def _write_band(
    path: Path, values: np.ndarray, profile: dict[str, Any], dtype: str, nodata: float | None
) -> Path:
    import rasterio

    options = {key: profile[key] for key in ("crs", "transform", "width", "height")}
    with rasterio.open(path, "w", driver="GTiff", count=1, dtype=dtype, nodata=nodata, **options) as dataset:
        dataset.write(values.astype(dtype), 1)
    return path


def _slope(context: ExecutionContext) -> Values:
    surface, profile, (xres, yres) = _read_elevation(context.input("dem"))
    east = (surface[1:-1, 2:] - surface[1:-1, :-2]) / (2 * xres)
    north = (surface[:-2, 1:-1] - surface[2:, 1:-1]) / (2 * yres)
    slope = np.full(surface.shape, -9999.0)
    inner = np.hypot(east, north)
    slope[1:-1, 1:-1] = np.where(np.isfinite(inner), inner, -9999.0)
    output = _write_band(context.work_dir / "slope.tif", slope, profile, "float32", -9999.0)
    row, column = np.unravel_index(np.nanargmin(surface), surface.shape)
    return {"slope": str(output), "min_cell": [int(row), int(column)]}


def _alignment(context: ExecutionContext) -> Values:
    import rasterio

    with rasterio.open(context.input("imagery")) as image, rasterio.open(context.input("dem")) as dem:
        columns = (dem.transform.c - image.transform.c) / image.transform.a
        rows = (dem.transform.f - image.transform.f) / image.transform.e
    aligned = abs(columns - round(columns)) < 1e-6 and abs(rows - round(rows)) < 1e-6
    return {"alignment": "ALIGNED" if aligned else "MISALIGNED", "offset_pixels": [columns, rows]}


def _coverage(context: ExecutionContext) -> Values:
    import rasterio

    with rasterio.open(context.input("imagery")) as image, rasterio.open(context.input("dem")) as dem:
        width = min(image.bounds.right, dem.bounds.right) - max(image.bounds.left, dem.bounds.left)
        height = min(image.bounds.top, dem.bounds.top) - max(image.bounds.bottom, dem.bounds.bottom)
        area = (image.bounds.right - image.bounds.left) * (image.bounds.top - image.bounds.bottom)
    fraction = max(width, 0.0) * max(height, 0.0) / area
    return {
        "terrain_coverage_fraction": fraction,
        "coverage_status": "COMPLETE" if fraction >= 1.0 else "PARTIAL",
    }


def _drainage(context: ExecutionContext) -> Values:
    lines, _ = _read_parquet(context.input("flowline"))
    points, _ = _read_parquet(context.input("points"))
    line = next(iter(lines.values()))
    width = context.parameters["buffer_m"]
    buffer = line.buffer(width, quad_segs=64)
    surface, _, _ = _read_elevation(context.input("dem"))
    return {
        "flowline_length": line.length,
        "distances": {name: line.distance(point) for name, point in points.items()},
        "buffer_area": buffer.area,
        "points_in_buffer": [name for name, point in points.items() if line.distance(point) <= width],
        "corridor_row": int(np.argmax(np.bincount(np.argmin(surface, axis=0)))),
    }


def _overlay(context: ExecutionContext) -> Values:
    import rasterio
    import shapely

    polygons, _ = _read_parquet(context.input("restriction"))
    polygon = next(iter(polygons.values()))
    with rasterio.open(context.input("base")) as dataset:
        rows, columns = np.indices(dataset.shape)
        x = dataset.transform.c + (columns + 0.5) * dataset.transform.a
        y = dataset.transform.f + (rows + 0.5) * dataset.transform.e
        cell_area = abs(dataset.transform.a * dataset.transform.e)
        profile = dict(dataset.profile)
    mask = shapely.contains_xy(polygon, x.ravel(), y.ravel()).reshape(x.shape)
    restricted = int(mask.sum())
    output = _write_band(context.work_dir / "restricted.tif", mask, profile, "uint8", None)
    return {
        "restricted_pixels": restricted,
        "allowed_pixels": int(mask.size - restricted),
        "restricted_area": restricted * cell_area,
        "restricted_mask": str(output),
    }


def _read_failure(context: ExecutionContext) -> ObservationBundle:
    import rasterio
    from rasterio.errors import RasterioIOError

    try:
        with rasterio.open(context.input("test_imagery")) as dataset:
            dataset.read()
    except RasterioIOError as exc:
        return ObservationBundle(
            values={"partial_output_written": False}, rejection=Rejection("READ_FAILED", str(exc))
        )
    return ObservationBundle(values={"partial_output_written": False})


def _read_image(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    import rasterio

    with rasterio.open(path) as dataset:
        return dataset.read().astype("float64"), dict(dataset.profile)


def _prototypes(image: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return one mean spectrum per class per tile, with near-duplicates removed."""
    spectra = []
    codes = []
    for row in range(0, labels.shape[0], _PROTOTYPE_TILE):
        for column in range(0, labels.shape[1], _PROTOTYPE_TILE):
            tile = (slice(row, row + _PROTOTYPE_TILE), slice(column, column + _PROTOTYPE_TILE))
            for code in np.unique(labels[tile]):
                if code:
                    spectra.append(image[(slice(None), *tile)][:, labels[tile] == code].mean(axis=1))
                    codes.append(code)
    centers = np.array(spectra)
    _, keep = np.unique(np.round(centers / 16.0), axis=0, return_index=True)
    return centers[keep], np.array(codes)[keep]


def _classify(context: ExecutionContext) -> Values:
    train_image, _ = _read_image(context.input("train_imagery"))
    train_labels, _ = _read_image(context.input("train_labels"))
    test_image, profile = _read_image(context.input("test_imagery"))
    centers, codes = _prototypes(train_image, train_labels[0].astype("int64"))
    pixels = test_image.reshape(4, -1).T
    predicted = np.zeros(pixels.shape[0], dtype="uint8")
    usable = np.flatnonzero(pixels.any(axis=1))
    distances = ((pixels[usable, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    predicted[usable] = codes[distances.argmin(axis=1)]
    output = _write_band(
        context.work_dir / "prediction.tif", predicted.reshape(test_image.shape[1:]), profile, "uint8", None
    )
    return {"prediction": str(output)}


def _pair_check(context: ExecutionContext) -> ObservationBundle:
    import rasterio

    with rasterio.open(context.input("imagery")) as image:
        if image.count < 4:
            return ObservationBundle(
                rejection=Rejection("MISSING_BAND", f"Found {image.count} bands, need 4")
            )
    return ObservationBundle(
        values={"pair_status": "VALID", "terrain_source": "dem", "canopy_height_available": False}
    )


def _evaluate(context: ExecutionContext) -> Values:
    import rasterio

    with rasterio.open(context.input("prediction")) as dataset:
        predicted = dataset.read(1)
    with rasterio.open(context.input("reference")) as dataset:
        reference = dataset.read(1)
    labeled = reference > 0
    truth = reference[labeled]
    guess = predicted[labeled]
    correct = int(np.count_nonzero(truth == guess))
    classified = int(np.count_nonzero(guess))
    names = {1: "water", 2: "bare_ground"}
    scores = {}
    for code in np.unique(truth):
        hits = np.count_nonzero((truth == code) & (guess == code))
        denominator = np.count_nonzero(truth == code) + np.count_nonzero(guess == code)
        scores[names[int(code)]] = 2 * hits / denominator
    return {
        "evaluated_pixels": int(truth.size),
        "classified_pixels": classified,
        "overall_accuracy": correct / truth.size,
        "classified_accuracy": correct / classified,
        "coverage": classified / truth.size,
        "macro_f1": sum(scores.values()) / len(scores),
        "f1": scores,
    }


def _temporal(context: ExecutionContext) -> Values:
    import rasterio

    tag = context.parameters["date_tag"]
    moments = []
    for role in ("imagery", "dem"):
        with rasterio.open(context.input(role)) as dataset:
            moments.append(datetime.fromisoformat(dataset.tags()[tag]))
    gap = abs((moments[0] - moments[1]).days)
    within = gap <= context.parameters["max_gap_days"]
    return {"gap_days": gap, "temporal_status": "MATCHED" if within else "MISMATCH"}


def _nearest_labels(train: np.ndarray, labels: np.ndarray, test: np.ndarray) -> np.ndarray:
    guesses = [labels[((train - row) ** 2).sum(axis=1).argmin()] for row in test]
    return np.array(guesses)


def _holdout(context: ExecutionContext) -> Values:
    image, _ = _read_image(context.input("imagery"))
    labels = _read_image(context.input("labels"))[0][0]
    block = int(context.parameters["block_m"])
    buffer = int(context.parameters["buffer_m"])
    folds = int(context.parameters["folds"])
    rng = np.random.default_rng(0)
    rows, columns = np.indices(labels.shape)
    sample = rng.choice(labels.size, size=min(4000, labels.size), replace=False)
    pixels = image.reshape(4, -1).T[sample]
    truth = labels.ravel()[sample]
    y = rows.ravel()[sample]
    x = columns.ravel()[sample]
    cell_x, cell_y = x // block, y // block
    fold = (cell_x + cell_y * 2) % folds
    correct = 0
    for index in range(folds):
        test = fold == index
        train = ~test & ~_within_buffer(x, y, cell_x[test], cell_y[test], block, buffer)
        guesses = _nearest_labels(pixels[train], truth[train], pixels[test])
        correct += int(np.count_nonzero(guesses == truth[test]))
    shuffled = rng.permutation(sample.size)
    half = sample.size // 2
    guesses = _nearest_labels(pixels[shuffled[:half]], truth[shuffled[:half]], pixels[shuffled[half:]])
    return {
        "holdout_accuracy": correct / sample.size,
        "random_split_accuracy": float(np.mean(guesses == truth[shuffled[half:]])),
    }


def _within_buffer(
    x: np.ndarray, y: np.ndarray, held_x: np.ndarray, held_y: np.ndarray, block: int, buffer: int
) -> np.ndarray:
    near = np.zeros(x.shape, dtype=bool)
    for cell_x, cell_y in {(int(a), int(b)) for a, b in zip(held_x, held_y, strict=True)}:
        near |= (
            (x >= cell_x * block - buffer)
            & (x < (cell_x + 1) * block + buffer)
            & (y >= cell_y * block - buffer)
            & (y < (cell_y + 1) * block + buffer)
        )
    return near


def _read_cloud(path: Path) -> Any:
    import laspy

    return laspy.read(str(path))


def _chm(context: ExecutionContext) -> Values:
    import rasterio

    cloud = _read_cloud(context.input("lidar"))
    x, y, z = (np.asarray(axis, dtype="float64") for axis in (cloud.x, cloud.y, cloud.z))
    ground = np.asarray(cloud.classification) == 2
    design = np.column_stack((x[ground], y[ground], np.ones(int(ground.sum()))))
    plane = np.linalg.lstsq(design - [x.mean(), y.mean(), 0.0], z[ground], rcond=None)[0]
    with rasterio.open(context.input("imagery")) as image:
        if image.count < 4:
            raise ValueError("Imagery needs four bands")
        profile = dict(image.profile)
        transform = image.transform
        shape = image.shape
    rows = np.floor((y - transform.f) / transform.e).astype("int64")
    columns = np.floor((x - transform.c) / transform.a).astype("int64")
    inside = (rows >= 0) & (rows < shape[0]) & (columns >= 0) & (columns < shape[1])
    surface = np.full(shape, -np.inf)
    np.maximum.at(surface, (rows[inside], columns[inside]), z[inside])
    center_rows, center_columns = np.indices(shape)
    center_x = transform.c + (center_columns + 0.5) * transform.a
    center_y = transform.f + (center_rows + 0.5) * transform.e
    floor = plane[0] * (center_x - x.mean()) + plane[1] * (center_y - y.mean()) + plane[2]
    heights = np.where(np.isfinite(surface), np.maximum(surface - floor, 0.0), -9999.0)
    output = _write_band(context.work_dir / "chm.tif", heights, profile, "float32", -9999.0)
    return {
        "pair_status": "VALID",
        "terrain_source": "lidar",
        "canopy_height_available": True,
        "chm": str(output),
        "lidar_file": str(context.input("lidar")),
    }


def _density(context: ExecutionContext) -> Values:
    cloud = _read_cloud(context.input("lidar"))
    count = len(cloud.points)
    actual = count / context.parameters["footprint_m2"]
    low = actual < context.parameters["threshold_pts_per_m2"]
    return {
        "point_count": count,
        "density": actual,
        "density_status": "BELOW_THRESHOLD" if low else "MEETS_THRESHOLD",
    }


def _vertical_check(context: ExecutionContext) -> Values:
    import rasterio

    cloud = _read_cloud(context.input("lidar"))
    ground = np.asarray(cloud.classification) == 2
    x, y, z = (np.asarray(axis, dtype="float64")[ground] for axis in (cloud.x, cloud.y, cloud.z))
    with rasterio.open(context.input("dem")) as dataset:
        band = dataset.read(1)
        rows = np.floor((y - dataset.transform.f) / dataset.transform.e).astype("int64")
        columns = np.floor((x - dataset.transform.c) / dataset.transform.a).astype("int64")
    keep = (rows >= 0) & (rows < band.shape[0]) & (columns >= 0) & (columns < band.shape[1])
    ratio = float(np.median(z[keep] / band[rows[keep], columns[keep]]))
    return {"z_ratio": ratio, "vertical_status": "MATCHED" if abs(ratio - 1.0) < 0.01 else "MISMATCH"}


def _load_snapshot(path: Path) -> tuple[dict[str, tuple[str, dict[str, Any]]], dict[str, str]]:
    """Return {id: (rounded geometry text, attributes)} and field types."""
    import shapely
    from shapely.geometry import shape

    if path.suffix == ".parquet":
        shapes, table = _read_parquet(path)
        fields = {f.name: str(f.type) for f in table.schema if f.name != "geometry"}
        rows = {row["id"]: row for row in table.drop_columns(["geometry"]).to_pylist()}
        return (
            {
                name: (shapely.to_wkt(geometry, rounding_precision=6), rows[name])
                for name, geometry in shapes.items()
            },
            fields,
        )
    records = {}
    fields = {}
    for item in _read_geojson(path):
        geometry = shape(item["geometry"])
        records[item["properties"]["id"]] = (
            shapely.to_wkt(geometry, rounding_precision=6),
            item["properties"],
        )
        fields.update({key: type(value).__name__ for key, value in item["properties"].items()})
    return records, fields


def _diff(context: ExecutionContext) -> Values:
    before, before_fields = _load_snapshot(context.input("before"))
    after, after_fields = _load_snapshot(context.input("after"))
    shared = sorted(set(before) & set(after))
    return {
        "count_before": len(before),
        "count_after": len(after),
        "added_ids": sorted(set(after) - set(before)),
        "deleted_ids": sorted(set(before) - set(after)),
        "changed_ids": [name for name in shared if before[name][0] != after[name][0]],
        "added_fields": sorted(set(after_fields) - set(before_fields)),
        "removed_fields": sorted(set(before_fields) - set(after_fields)),
        "after_schema": after_fields,
    }


def _lineage(context: ExecutionContext) -> Values:
    before, _ = _read_parquet(context.input("before"))
    after, _ = _read_parquet(context.input("after"))
    match = context.parameters["match_fraction"]
    links = [(old, new, a.intersection(b).area) for old, a in before.items() for new, b in after.items()]
    links = [link for link in links if link[2] > 0]
    splits: dict[str, list[str]] = {}
    merges: dict[str, list[str]] = {}
    unchanged, ambiguous = [], []
    for old, shape in before.items():
        parts = [link for link in links if link[0] == old]
        covered = sum(link[2] for link in parts) / shape.area
        contained = all(link[2] / after[link[1]].area >= match for link in parts)
        if len(parts) == 1 and covered >= match and contained:
            unchanged.append(old)
        elif len(parts) > 1 and covered >= match and contained:
            splits[old] = sorted(link[1] for link in parts)
    for new, shape in after.items():
        parts = [link for link in links if link[1] == new]
        covered = sum(link[2] for link in parts) / shape.area
        if (
            len(parts) > 1
            and covered >= match
            and all(link[2] / before[link[0]].area >= match for link in parts)
        ):
            merges[new] = sorted(link[0] for link in parts)
    merged = {name for names in merges.values() for name in names}
    for old in before:
        if old not in unchanged and old not in splits and old not in merged:
            ambiguous.append(old)
    return {"unchanged": unchanged, "splits": splits, "merges": merges, "ambiguous": ambiguous}


def _pagination(context: ExecutionContext) -> Values:
    index = json.loads(context.input("index").read_text())
    pages = context.inputs.get("page", [])
    received = {int(path.stem.rsplit("_", 1)[1]) for path in pages}
    missing = sorted(set(range(1, index["page_count"] + 1)) - received)
    features = sum(len(_read_geojson(path)) for path in pages)
    return {
        "ingest_status": "PARTIAL" if missing else "COMPLETE",
        "missing_pages": missing,
        "received_features": features,
        "expected_features": index["feature_count"],
    }


def _integrity(context: ExecutionContext) -> ObservationBundle:
    published = context.input("checksum").read_text().split()[0]
    actual = hashlib.sha256(context.input("source").read_bytes()).hexdigest()
    if actual != published:
        return ObservationBundle(
            values={"features_loaded": False},
            rejection=Rejection("CHECKSUM_MISMATCH", f"{actual} != {published}"),
        )
    return ObservationBundle(values={"features_loaded": True})


_OPERATIONS: dict[str, Callable[[ExecutionContext], Values | ObservationBundle]] = {
    "vector.overlap": _overlap,
    "vector.gap": _gap,
    "vector.validity": _validity,
    "vector.sliver": _sliver,
    "vector.point_in_polygon": _point_in_polygon,
    "vector.relations": _relations,
    "vector.distance": _distance,
    "vector.multipart_area": _multipart,
    "crs.transform": _transform,
    "crs.validate_labels": _validate_labels,
    "crs.validate_position": _validate_position,
    "crs.unit_check": _unit_check,
    "crs.vertical_compare": _vertical_compare,
    "raster.slope": _slope,
    "raster.alignment": _alignment,
    "raster.coverage": _coverage,
    "raster.drainage": _drainage,
    "raster.overlay": _overlay,
    "raster.read_failure": _read_failure,
    "landcover.classify": _classify,
    "landcover.pair_check": _pair_check,
    "landcover.evaluate": _evaluate,
    "landcover.temporal_check": _temporal,
    "landcover.holdout": _holdout,
    "lidar.chm": _chm,
    "lidar.density": _density,
    "lidar.vertical_check": _vertical_check,
    "ingest.diff": _diff,
    "ingest.lineage": _lineage,
    "ingest.pagination": _pagination,
    "ingest.integrity": _integrity,
}


class ReferenceAdapter:
    """Runs every built-in case with direct library calls."""

    name = "reference"

    def supports(self, case: CaseView) -> Capability:
        if case.operation in _OPERATIONS:
            return Capability(True)
        return Capability(False, f"No reference implementation for {case.operation}")

    def execute(self, context: ExecutionContext) -> ObservationBundle:
        result = _OPERATIONS[context.case.operation](context)
        return result if isinstance(result, ObservationBundle) else ObservationBundle(values=result)

    def environment(self) -> dict[str, Any]:
        versions: dict[str, Any] = {}
        for package in ("shapely", "pyproj", "rasterio", "laspy", "pyarrow", "numpy"):
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                versions[package] = None
        return versions
