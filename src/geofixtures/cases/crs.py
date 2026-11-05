"""CRS, axis order, unit, and vertical datum cases."""

from __future__ import annotations

from typing import Any

from ..generators.vector import EASTING, NORTHING
from ..models import BuildContext, CaseContent, CaseSpec, InputFile
from ..oracles.analytic import utm_forward
from ._helpers import (
    GEOPARQUET,
    RFC_GEOJSON,
    define,
    exact,
    numeric,
    parquet_input,
    rejection,
    write_collection,
    write_features,
)

UTM = "EPSG:32612"
INTERNATIONAL_FEET_PER_METRE = 1.0 / 0.3048
SURVEY_FEET_PER_METRE = 3937.0 / 1200.0
INSUFFICIENT = "INSUFFICIENT_INFORMATION"


def _point(identifier: str, x: float, y: float, **properties: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"id": identifier, **properties},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _build_utm_controls(context: BuildContext) -> CaseContent:
    controls = {
        "central_meridian": (-111.0, 34.0),
        "west": (-113.9, 36.1),
        "east": (-108.2, 31.4),
        "north": (-111.5, 37.0),
    }
    write_collection(
        context,
        "controls.geojson",
        [_point(name, lon, lat) for name, (lon, lat) in controls.items()],
    )
    projected = {name: list(utm_forward(lon, lat, 12)) for name, (lon, lat) in controls.items()}
    return CaseContent(
        inputs=[InputFile("controls", "input/controls.geojson", "GeoJSON", RFC_GEOJSON, crs="EPSG:4326")],
        parameters={"target_crs": UTM},
        assertions=[numeric("projected", projected, "m", 1e-3)],
        truth={"projected_m": projected},
        tolerances={"position_m": 1e-3},
    )


def _build_mislabeled(context: BuildContext) -> CaseContent:
    features = [_point("a", EASTING, NORTHING), _point("b", EASTING + 500.0, NORTHING + 500.0)]
    write_features(context, "features.parquet", features, "EPSG:4326", fields=(("id", "string"),))
    return CaseContent(
        inputs=[parquet_input("features", "features.parquet", "EPSG:4326")],
        assertions=[exact("label_consistent", False), exact("correction", INSUFFICIENT)],
        truth={
            "declared_crs": "EPSG:4326",
            "actual_crs": UTM,
        },
    )


def _build_swapped_axes(context: BuildContext) -> CaseContent:
    write_collection(context, "features.geojson", [_point("site", 33.45, -112.07)], strict=False)
    return CaseContent(
        inputs=[
            InputFile(
                "features", "input/features.geojson", "GeoJSON", "GeoJSON with swapped axes, not RFC 7946"
            )
        ],
        assertions=[rejection("rejects_swapped_axes", ["AXIS_ORDER_SUSPECT", "COORDINATE_OUT_OF_RANGE"])],
        truth={"true_longitude_latitude": [-112.07, 33.45]},
    )


def _line(identifier: str, length: float, offset: float) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"id": identifier},
        "geometry": {
            "type": "LineString",
            "coordinates": [[EASTING, NORTHING + offset], [EASTING + length, NORTHING + offset]],
        },
    }


def _build_foot_units(context: BuildContext) -> CaseContent:
    distance = 1000.0
    features = [
        _line("international", distance * INTERNATIONAL_FEET_PER_METRE, 0.0),
        _line("survey", distance * SURVEY_FEET_PER_METRE, 100.0),
        _line("uncontrolled", distance * INTERNATIONAL_FEET_PER_METRE, 200.0),
    ]
    write_features(context, "lines.parquet", features, UTM, fields=(("id", "string"),))
    return CaseContent(
        inputs=[parquet_input("lines", "lines.parquet", UTM)],
        parameters={"control_distances_m": {"international": distance, "survey": distance}},
        assertions=[
            {
                "id": "unit_ratio",
                "kind": "numeric",
                "expected": {"international": INTERNATIONAL_FEET_PER_METRE, "survey": SURVEY_FEET_PER_METRE},
                "unit": "file units per metre",
                "relative_tolerance": 1e-8,
            },
            exact(
                "detected_unit",
                {"international": "foot", "survey": "US survey foot", "uncontrolled": INSUFFICIENT},
            ),
            exact("declared_unit_consistent", False),
        ],
        truth={"declared_unit": "metre", "international_ratio": INTERNATIONAL_FEET_PER_METRE},
        tolerances={"relative_unit_ratio": 1e-8},
    )


def _build_vertical_states(context: BuildContext) -> CaseContent:
    fields = (("id", "string"), ("z_m", "double"))
    reference = [_point("control", EASTING, NORTHING, z_m=1500.0)]
    candidate = [_point("control", EASTING, NORTHING, z_m=1500.0)]
    compound = "EPSG:32612+5703"
    write_features(context, "reference.parquet", reference, compound, fields=fields)
    write_features(context, "candidate.parquet", candidate, UTM, fields=fields)
    return CaseContent(
        inputs=[
            parquet_input("reference", "reference.parquet", compound),
            parquet_input("candidate", "candidate.parquet", UTM),
        ],
        assertions=[
            exact("vertical_state", {"reference": "SPECIFIED", "candidate": "UNSPECIFIED"}),
            exact("comparison", INSUFFICIENT),
        ],
        truth={"reference_vertical_crs": "EPSG:5703", "candidate_vertical_crs": None},
    )


CASES: tuple[CaseSpec, ...] = (
    define(
        "crs.transform.001",
        "Geographic to UTM transformation",
        _build_utm_controls,
        tags=("crs", "transformation", "projection"),
        operation="crs.transform",
        oracle="transverse_mercator_series",
        derivation="Control points are projected with the sixth-order Krueger series for WGS84 UTM zone 12N, "
        "which shares no code with PROJ.",
        requires=("vector",),
        formats=(RFC_GEOJSON,),
    ),
    define(
        "crs.mislabeled.001",
        "Projected metres labeled as geographic degrees",
        _build_mislabeled,
        tags=("crs", "metadata", "negative"),
        operation="crs.validate_labels",
        oracle="range_rule",
        derivation="Geographic coordinates can't exceed 180 and 90, so a value near 400000 disproves the label. "
        "It doesn't reveal the true CRS.",
        requires=("vector",),
        formats=(GEOPARQUET,),
        expected_status="uncertain",
    ),
    define(
        "crs.axis_order.001",
        "Latitude and longitude in the wrong order",
        _build_swapped_axes,
        tags=("crs", "axis-order", "negative"),
        operation="crs.validate_position",
        oracle="range_rule",
        derivation="RFC 7946 positions are longitude, latitude. Here the second value is -112.07, which isn't a latitude.",
        requires=("vector",),
        formats=("GeoJSON with swapped axes, not RFC 7946",),
        expected_status="rejection",
    ),
    define(
        "crs.units.001",
        "Feet stored under a metre label",
        _build_foot_units,
        tags=("crs", "units", "negative"),
        operation="crs.unit_check",
        oracle="control_distance",
        derivation="Each line has a surveyed length of 1000 m. File length divided by that gives 1 / 0.3048 for the foot "
        "and 3937 / 1200 for the US survey foot. A line with no control distance can't be judged.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
    define(
        "crs.vertical_datum.001",
        "Elevation with no vertical datum",
        _build_vertical_states,
        tags=("crs", "vertical", "negative"),
        operation="crs.vertical_compare",
        oracle="datum_state",
        derivation="The reference declares NAVD88 height. The candidate has a horizontal CRS only, so its heights "
        "can't be compared.",
        requires=("vector",),
        formats=(GEOPARQUET,),
        expected_status="uncertain",
    ),
)
