"""Compare observed values with a case's declared expectations."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from ..models import Outcome
from ..oracles.classification import classification_scores
from ..oracles.raster import compare_rasters, transforms_match
from ..paths import resolve_inside
from .protocol import ObservationBundle
from .results import AssertionResult, jsonable

Spec = Mapping[str, Any]


def _result(spec: Spec, outcome: Outcome, observed: Any, message: str = "", **extra: Any) -> AssertionResult:
    return AssertionResult(
        assertion_id=spec["id"],
        kind=spec["kind"],
        outcome=outcome,
        observed=observed,
        expected=extra.pop("expected", spec.get("expected")),
        tolerance=extra.pop("tolerance", None),
        unit=spec.get("unit"),
        message=message,
        **extra,
    )


def _verdict(passed: bool) -> Outcome:
    return Outcome.PASS if passed else Outcome.FAIL


def _exact(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    value = jsonable(observed)
    same = value == spec["expected"] and type(value) is type(spec["expected"])
    return _result(spec, _verdict(same), value, "" if same else "Values differ")


def _set_equal(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    if not isinstance(observed, (list, tuple, set, frozenset)):
        return _result(spec, Outcome.FAIL, observed, "Observed value isn't a collection")
    expected = sorted(map(str, spec["expected"]))
    found = sorted(map(str, observed))
    extra = sorted(set(found) - set(expected))
    missing = sorted(set(expected) - set(found))
    same = found == expected
    return _result(spec, _verdict(same), found, "" if same else f"Missing {missing}, unexpected {extra}")


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key in sorted(value, key=str):
            output.update(_flatten(value[key], f"{prefix}/{key}" if prefix else str(key)))
        return output
    if isinstance(value, (list, tuple, np.ndarray)):
        output = {}
        for index, item in enumerate(value):
            output.update(_flatten(item, f"{prefix}/{index}" if prefix else str(index)))
        return output
    return {prefix: value}


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float, np.integer, np.floating))


def _number_matches(spec: Spec, observed: Any, expected: float) -> tuple[bool, str]:
    if not _is_number(observed):
        return False, f"Not a number: {observed!r}"
    value = float(observed)
    if not math.isfinite(value):
        return False, f"Non-finite value: {value}"
    absolute = spec.get("absolute_tolerance")
    relative = spec.get("relative_tolerance")
    if absolute is None and relative is None:
        return value == expected, f"{value} != {expected}"
    allowed = max(float(absolute or 0.0), float(relative or 0.0) * abs(expected))
    return abs(value - expected) <= allowed, f"|{value} - {expected}| > {allowed}"


def _numeric(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    tolerance = {
        key: spec[key] for key in ("absolute_tolerance", "relative_tolerance") if key in spec
    } or None
    if "minimum" in spec or "maximum" in spec:
        bounds = {key: spec[key] for key in ("minimum", "maximum") if key in spec}
        if not _is_number(observed):
            return _result(spec, Outcome.FAIL, observed, "Not a number", expected=bounds)
        number = float(observed)
        inside = (
            math.isfinite(number)
            and number >= float(bounds.get("minimum", -math.inf))
            and number <= float(bounds.get("maximum", math.inf))
        )
        return _result(spec, _verdict(inside), observed, "" if inside else "Outside range", expected=bounds)
    expected = _flatten(spec["expected"])
    found = _flatten(observed)
    if set(expected) != set(found):
        message = f"Keys differ: expected {sorted(expected)}, found {sorted(found)}"
        return _result(spec, Outcome.FAIL, observed, message, tolerance=tolerance)
    problems = []
    residuals = []
    for key, target in expected.items():
        matched, reason = _number_matches(spec, found[key], float(target))
        if not matched:
            problems.append(f"{key}: {reason}" if key else reason)
        if _is_number(found[key]) and math.isfinite(float(found[key])):
            residuals.append(abs(float(found[key]) - float(target)))
    metrics: dict[str, Any] = {}
    if residuals:
        metrics = {
            "max_abs_error": max(residuals),
            "rmse": math.sqrt(sum(item**2 for item in residuals) / len(residuals)),
        }
    return _result(
        spec, _verdict(not problems), observed, "; ".join(problems[:5]), tolerance=tolerance, metrics=metrics
    )


def _geometry(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    import shapely

    try:
        found = shapely.from_wkt(observed)
    except Exception as exc:
        return _result(spec, Outcome.FAIL, observed, f"Invalid WKT: {exc}")
    expected = shapely.from_wkt(spec["expected"])
    if spec.get("require_valid", True) and not found.is_valid:
        return _result(spec, Outcome.FAIL, observed, "Observed geometry is invalid")
    tolerance = float(spec.get("area_tolerance", 1e-9))
    difference = float(found.symmetric_difference(expected).area)
    return _result(
        spec,
        _verdict(difference <= tolerance),
        observed,
        "" if difference <= tolerance else f"Symmetric difference area {difference} > {tolerance}",
        tolerance=tolerance,
        metrics={"symmetric_difference_area": difference, "policy": spec.get("policy", "topological")},
    )


def _topology(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    expected = _flatten(spec["expected"])
    found = _flatten(observed)
    differences = [
        f"{key}: expected {expected.get(key)}, found {found.get(key)}"
        for key in sorted(set(expected) | set(found))
        if expected.get(key) is not found.get(key)
    ]
    return _result(spec, _verdict(not differences), observed, "; ".join(differences[:8]))


def _observed_file(observed: Any) -> Path:
    path = Path(observed)
    if not path.is_file():
        raise FileNotFoundError(f"Observed file doesn't exist: {observed}")
    return path


def _raster_metadata(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    from ..io.geotiff import read_metadata

    metadata = read_metadata(_observed_file(observed))
    expected = spec["expected"]
    problems = []
    for key, target in expected.items():
        if key == "transform":
            if not transforms_match(metadata[key], target, float(spec.get("transform_tolerance", 1e-6))):
                problems.append(f"transform: {metadata[key]} vs {target}")
        elif key == "crs":
            from pyproj import CRS

            if metadata[key] is None or CRS.from_user_input(metadata[key]) != CRS.from_user_input(target):
                problems.append(f"crs: {metadata[key]} vs {target}")
        elif metadata[key] != target:
            problems.append(f"{key}: {metadata[key]} vs {target}")
    if "allowed_values" in spec:
        import rasterio

        with rasterio.open(_observed_file(observed)) as dataset:
            present = {int(value) for value in np.unique(dataset.read(1))}
        unexpected = sorted(present - set(spec["allowed_values"]))
        if unexpected:
            problems.append(f"Unexpected pixel values: {unexpected}")
    summary = {key: metadata[key] for key in expected}
    return _result(spec, _verdict(not problems), summary, "; ".join(problems))


def _raster_values(spec: Spec, observed: Any, root: Path) -> AssertionResult:
    truth = resolve_inside(root, spec["truth"])
    optional = resolve_inside(root, spec["optional_mask"]) if "optional_mask" in spec else None
    ignored = resolve_inside(root, spec["ignore_mask"]) if "ignore_mask" in spec else None
    passed, message, metrics = compare_rasters(
        _observed_file(observed), truth, spec, optional_mask_path=optional, ignore_mask_path=ignored
    )
    return _result(
        spec,
        _verdict(passed),
        metrics,
        message,
        expected=f"Pixels of {spec['truth']}",
        tolerance=spec["absolute_tolerance"],
        source_file=spec["truth"],
        metrics=metrics,
    )


def _classification(spec: Spec, observed: Any, root: Path) -> AssertionResult:
    import rasterio

    truth_path = resolve_inside(root, spec["truth"])
    with rasterio.open(_observed_file(observed)) as predicted_ds, rasterio.open(truth_path) as truth_ds:
        aligned = (
            predicted_ds.crs == truth_ds.crs
            and predicted_ds.shape == truth_ds.shape
            and transforms_match(predicted_ds.transform, truth_ds.transform)
        )
        if not aligned:
            return _result(spec, Outcome.FAIL, str(observed), "Output isn't aligned to the truth grid")
        predicted = predicted_ds.read(1)
        truth = truth_ds.read(1)
    names = {int(key): value for key, value in spec["class_names"].items()}
    scores = classification_scores(
        truth,
        predicted,
        spec["labels"],
        names,
        ignore_values=spec["ignore_values"],
        abstain_values=spec["abstain_values"],
        zero_division=float(spec["zero_division"]),
    )
    problems = []
    for name, bounds in spec["thresholds"].items():
        value = scores[name]
        if "min" in bounds and value < bounds["min"]:
            problems.append(f"{name} {value:.4f} < {bounds['min']}")
        if "max" in bounds and value > bounds["max"]:
            problems.append(f"{name} {value:.4f} > {bounds['max']}")
    return _result(
        spec,
        _verdict(not problems),
        {name: scores[name] for name in spec["thresholds"]},
        "; ".join(problems),
        expected=spec["thresholds"],
        source_file=spec["truth"],
        metrics=scores,
    )


def _pointcloud(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    from pyproj import CRS

    from ..io.las import read_las

    cloud = read_las(_observed_file(observed))
    summary = {
        "version": cloud["version"],
        "point_format": cloud["point_format"],
        "count": cloud["count"],
        "scale": cloud["scale"],
        "crs": cloud["crs"],
        "class_counts": {
            str(key): value for key, value in sorted(Counter(cloud["classification"].tolist()).items())
        },
    }
    problems = []
    for key, target in spec["expected"].items():
        if key == "crs":
            if summary["crs"] is None or CRS.from_user_input(summary["crs"]) != CRS.from_user_input(target):
                problems.append(f"crs: {summary['crs']} vs {target}")
        elif key == "scale":
            if not np.allclose(summary["scale"], target, rtol=0.0, atol=1e-12):
                problems.append(f"scale: {summary['scale']} vs {target}")
        elif summary[key] != target:
            problems.append(f"{key}: {summary[key]} vs {target}")
    return _result(spec, _verdict(not problems), summary, "; ".join(problems))


def _schema(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    same = dict(observed) == dict(spec["expected"])
    return _result(spec, _verdict(same), observed, "" if same else "Schemas differ")


def _invariant(spec: Spec, observed: Any, _root: Path) -> AssertionResult:
    rule = spec["rule"]
    if rule == "is_true":
        holds = observed is True
    elif rule == "is_false":
        holds = observed is False
    else:
        raise ValueError(f"Unknown invariant rule: {rule}")
    return _result(
        spec, _verdict(holds), observed, "" if holds else f"Invariant {rule} doesn't hold", expected=rule
    )


_HANDLERS: dict[str, Callable[[Spec, Any, Path], AssertionResult]] = {
    "exact": _exact,
    "set_equal": _set_equal,
    "numeric": _numeric,
    "geometry_equivalent": _geometry,
    "topology_predicate": _topology,
    "raster_metadata": _raster_metadata,
    "raster_values": _raster_values,
    "classification_metrics": _classification,
    "pointcloud_metadata": _pointcloud,
    "schema": _schema,
    "invariant": _invariant,
}


def evaluate_rejection(spec: Spec, bundle: ObservationBundle) -> AssertionResult:
    """Score an expected_error assertion against the target's rejection."""
    allowed = spec.get("codes")
    if bundle.rejection is None:
        return _result(
            spec, Outcome.FAIL, None, "The target accepted input it should reject", expected=allowed
        )
    code = bundle.rejection.code
    if allowed and code not in allowed:
        return _result(spec, Outcome.FAIL, code, f"Unexpected rejection code: {code}", expected=allowed)
    return _result(spec, Outcome.EXPECTED_REJECTION, code, bundle.rejection.message, expected=allowed)


def evaluate(spec: Spec, bundle: ObservationBundle, root: Path) -> AssertionResult:
    """Evaluate one assertion against an observation bundle."""
    if spec["kind"] == "expected_error":
        return evaluate_rejection(spec, bundle)
    key = spec.get("observe", spec["id"])
    if key not in bundle.values:
        if spec.get("optional"):
            return _result(spec, Outcome.SKIP, None, f"Optional observation {key!r} wasn't provided")
        return _result(spec, Outcome.ERROR, None, f"The adapter didn't return {key!r}")
    try:
        return _HANDLERS[spec["kind"]](spec, bundle.values[key], root)
    except Exception as exc:
        return _result(spec, Outcome.ERROR, bundle.values[key], f"{type(exc).__name__}: {exc}")
