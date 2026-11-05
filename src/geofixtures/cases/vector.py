"""Vector topology cases. Coordinates are metres in UTM zone 12N."""

from __future__ import annotations

from ..generators.vector import (
    box_feature,
    box_ring,
    feature,
    line_feature,
    multipolygon_wkt,
    point_feature,
    polygon_wkt,
)
from ..models import BuildContext, CaseContent, CaseSpec
from ..oracles.analytic import point_segment_distance, rectangle_area, rectangle_overlap
from ..oracles.geometry import (
    multipart_remainder,
    point_in_holed_rectangle,
    rectangle_compactness,
    rectangle_relations,
)
from ._helpers import GEOPARQUET, define, exact, numeric, parquet_input, set_equal, write_features

CRS = "EPSG:32612"
_ID_FIELD = (("id", "string"),)
_POSITION = {"position_m": 1e-9}


def _build_rectangle_overlap(context: BuildContext) -> CaseContent:
    a = (0.0, 0.0, 5.0, 4.0)
    b = (3.0, 2.0, 8.0, 6.0)
    write_features(
        context,
        "features.parquet",
        [box_feature("A", a), box_feature("B", b)],
        CRS,
        fields=_ID_FIELD,
    )
    overlap = rectangle_overlap(a, b)
    assert overlap is not None
    overlap_area = rectangle_area(overlap)
    union_area = rectangle_area(a) + rectangle_area(b) - overlap_area
    return CaseContent(
        inputs=[parquet_input("features", "features.parquet", CRS)],
        assertions=[
            set_equal("overlap_pairs", ["A|B"]),
            numeric("overlap_area", overlap_area, "m2", 1e-9),
            numeric("union_area", union_area, "m2", 1e-9),
            {
                "id": "overlap_geometry",
                "kind": "geometry_equivalent",
                "expected": polygon_wkt(box_ring(overlap)),
                "policy": "topological",
                "require_valid": True,
                "area_tolerance": 1e-9,
            },
        ],
        truth={"overlap_box": list(overlap), "overlap_area_m2": overlap_area, "union_area_m2": union_area},
        tolerances=_POSITION,
    )


def _build_rectangle_gap(context: BuildContext) -> CaseContent:
    a = (0.0, 0.0, 10.0, 10.0)
    b = (10.5, 0.0, 20.5, 10.0)
    write_features(
        context,
        "features.parquet",
        [box_feature("A", a), box_feature("B", b)],
        CRS,
        fields=_ID_FIELD,
    )
    width = b[0] - a[2]
    gap_area = width * (a[3] - a[1])
    return CaseContent(
        inputs=[parquet_input("features", "features.parquet", CRS)],
        assertions=[
            numeric("gap_area", gap_area, "m2", 1e-9),
            numeric("min_separation", width, "m", 1e-9),
            set_equal("overlap_pairs", []),
        ],
        truth={"gap_width_m": width, "gap_area_m2": gap_area},
        tolerances=_POSITION,
    )


def _build_bowtie(context: BuildContext) -> CaseContent:
    ring = [[0.0, 0.0], [4.0, 4.0], [4.0, 0.0], [0.0, 4.0], [0.0, 0.0]]
    features = [feature("bowtie", "Polygon", [ring]), box_feature("control", (10.0, 0.0, 14.0, 4.0))]
    write_features(context, "features.parquet", features, CRS, fields=_ID_FIELD)
    left = [[0.0, 0.0], [2.0, 2.0], [0.0, 4.0], [0.0, 0.0]]
    right = [[2.0, 2.0], [4.0, 4.0], [4.0, 0.0], [2.0, 2.0]]
    return CaseContent(
        inputs=[parquet_input("features", "features.parquet", CRS)],
        assertions=[
            set_equal("invalid_ids", ["bowtie"]),
            numeric("repaired_area", 8.0, "m2", 1e-9),
            exact("repaired_type", "MultiPolygon"),
            {
                "id": "repaired_geometry",
                "kind": "geometry_equivalent",
                "expected": multipolygon_wkt([left, right]),
                "policy": "repair is judged by area, not vertex order",
                "require_valid": True,
                "area_tolerance": 1e-9,
            },
        ],
        truth={"crossing_point_local": [2.0, 2.0], "repaired_area_m2": 8.0, "triangle_area_m2": 4.0},
        tolerances=_POSITION,
    )


def _build_sliver(context: BuildContext) -> CaseContent:
    features = [box_feature("sliver", (0.0, 0.0, 100.0, 0.25)), box_feature("block", (0.0, 10.0, 10.0, 20.0))]
    write_features(context, "features.parquet", features, CRS, fields=_ID_FIELD)
    scores = {"sliver": rectangle_compactness(100.0, 0.25), "block": rectangle_compactness(10.0, 10.0)}
    threshold = float(context.parameters["threshold"])
    return CaseContent(
        inputs=[parquet_input("features", "features.parquet", CRS)],
        parameters={"polsby_popper_threshold": threshold},
        assertions=[
            set_equal("sliver_ids", [name for name, score in scores.items() if score < threshold]),
            numeric("polsby_popper", scores, "ratio", 1e-9),
        ],
        truth={"polsby_popper": scores},
        tolerances={"ratio": 1e-9},
    )


def _build_holed_boundary(context: BuildContext) -> CaseContent:
    outer = (0.0, 0.0, 10.0, 10.0)
    hole = (4.0, 4.0, 6.0, 6.0)
    tolerance = 0.01
    points = {
        "inside": (1.0, 1.0),
        "outside": (12.0, 5.0),
        "edge": (0.0, 5.0),
        "hole": (5.0, 5.0),
        "hole_boundary": (4.0, 5.0),
        "near_edge": (0.0078125, 5.0),
    }
    write_features(
        context,
        "polygon.parquet",
        [feature("region", "Polygon", [box_ring(outer), box_ring(hole)])],
        CRS,
        fields=_ID_FIELD,
    )
    write_features(
        context,
        "points.parquet",
        [point_feature(name, x, y) for name, (x, y) in points.items()],
        CRS,
        fields=_ID_FIELD,
    )
    answers = {name: point_in_holed_rectangle(xy, outer, hole, tolerance) for name, xy in points.items()}
    return CaseContent(
        inputs=[
            parquet_input("polygon", "polygon.parquet", CRS),
            parquet_input("points", "points.parquet", CRS),
        ],
        parameters={"boundary_tolerance_m": tolerance},
        assertions=[
            {
                "id": predicate,
                "kind": "topology_predicate",
                "expected": {name: answer[predicate] for name, answer in answers.items()},
            }
            for predicate in ("contains", "covers", "on_boundary", "near_boundary")
        ],
        truth={"answers": answers},
        tolerances={"boundary_m": tolerance},
    )


def _build_rectangle_relations(context: BuildContext) -> CaseContent:
    boxes = {
        "A": (0.0, 0.0, 2.0, 2.0),
        "edge_neighbor": (2.0, 0.0, 4.0, 2.0),
        "corner_neighbor": (2.0, 2.0, 3.0, 3.0),
        "crossing": (1.0, 1.0, 3.0, 3.0),
        "far": (5.0, 5.0, 6.0, 6.0),
        "inner": (0.5, 0.5, 1.5, 1.5),
    }
    features = [box_feature(name, box) for name, box in boxes.items()]
    write_features(context, "features.parquet", features, CRS, fields=_ID_FIELD)
    matrix = {f"A|{name}": rectangle_relations(boxes["A"], box) for name, box in boxes.items() if name != "A"}
    return CaseContent(
        inputs=[parquet_input("features", "features.parquet", CRS)],
        parameters={"subject": "A"},
        assertions=[{"id": "relations", "kind": "topology_predicate", "expected": matrix}],
        truth={"relations": matrix},
        tolerances=_POSITION,
    )


def _build_point_line_distance(context: BuildContext) -> CaseContent:
    start, end = (0.0, 0.0), (10.0, 0.0)
    points = {"above": (3.0, 4.0), "past_end": (13.0, 4.0), "before_start": (-6.0, 8.0)}
    write_features(
        context,
        "line.parquet",
        [line_feature("line", [list(start), list(end)])],
        CRS,
        fields=_ID_FIELD,
    )
    write_features(
        context,
        "points.parquet",
        [point_feature(name, x, y) for name, (x, y) in points.items()],
        CRS,
        fields=_ID_FIELD,
    )
    distances = {name: point_segment_distance(xy, start, end) for name, xy in points.items()}
    return CaseContent(
        inputs=[parquet_input("line", "line.parquet", CRS), parquet_input("points", "points.parquet", CRS)],
        assertions=[numeric("distances", distances, "m", 1e-9)],
        truth={"distances_m": distances},
        tolerances=_POSITION,
    )


def _build_multipart_exclusion(context: BuildContext) -> CaseContent:
    study_area = (0.0, 0.0, 10.0, 10.0)
    parts = [(0.0, 0.0, 2.0, 2.0), (6.0, 0.0, 8.0, 3.0)]
    write_features(
        context,
        "study_area.parquet",
        [box_feature("study_area", study_area)],
        CRS,
        fields=_ID_FIELD,
    )
    write_features(
        context,
        "exclusion.parquet",
        [feature("exclusion", "MultiPolygon", [[box_ring(part)] for part in parts])],
        CRS,
        fields=_ID_FIELD,
    )
    excluded = sum(rectangle_area(part) for part in parts)
    remaining = multipart_remainder(study_area, parts)
    return CaseContent(
        inputs=[
            parquet_input("study_area", "study_area.parquet", CRS),
            parquet_input("exclusion", "exclusion.parquet", CRS),
        ],
        assertions=[
            numeric("part_count", len(parts), "parts"),
            numeric("exclusion_area", excluded, "m2", 1e-9),
            numeric("remaining_area", remaining, "m2", 1e-9),
        ],
        truth={"exclusion_area_m2": excluded, "remaining_area_m2": remaining},
        tolerances=_POSITION,
    )


CASES: tuple[CaseSpec, ...] = (
    define(
        "vector.overlap.001",
        "Two polygons with known overlap",
        _build_rectangle_overlap,
        tags=("topology", "overlap", "metric-crs"),
        operation="vector.overlap",
        oracle="analytic_geometry",
        derivation="A is 5 by 4 at the origin, B is 5 by 4 at (3, 2). They share x 3 to 5 and y 2 to 4, so 2 by 2 = 4 m2. "
        "Union = 20 + 20 - 4 = 36 m2.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
    define(
        "vector.gap.001",
        "Two polygons separated by a known gap",
        _build_rectangle_gap,
        tags=("topology", "gap", "metric-crs"),
        operation="vector.gap",
        oracle="analytic_geometry",
        derivation="The rectangles are 10 m tall and 0.5 m apart, so the strip between them is 0.5 by 10 = 5 m2.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
    define(
        "vector.self_intersection.001",
        "Bow-tie polygon that crosses itself",
        _build_bowtie,
        tags=("topology", "validity", "repair"),
        operation="vector.validity",
        oracle="analytic_geometry",
        derivation="The ring crosses at (2, 2), forming two triangles of base 4 and height 2. Each has area 4, "
        "so a repaired geometry covers 8 m2. The ring's signed area is 0.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
    define(
        "vector.sliver.001",
        "Sliver polygon below a compactness threshold",
        _build_sliver,
        tags=("topology", "sliver", "quality"),
        operation="vector.sliver",
        oracle="analytic_geometry",
        derivation="Polsby-Popper is 4 pi A / P squared. A 100 by 0.25 rectangle scores 4 pi 25 / 200.5 squared, "
        "about 0.0078. A 10 by 10 square scores pi / 4.",
        requires=("vector",),
        formats=(GEOPARQUET,),
        parameters={"threshold": 0.01},
        overridable=("threshold",),
    ),
    define(
        "vector.boundary.001",
        "Point-in-polygon on boundaries and holes",
        _build_holed_boundary,
        tags=("topology", "boundary", "hole", "predicate"),
        operation="vector.point_in_polygon",
        oracle="analytic_geometry",
        derivation="Each point is compared with the outer rectangle and the hole by interval tests. Contains excludes the "
        "boundary and covers includes it. The tolerance test measures distance to the nearest edge.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
    define(
        "vector.relations.001",
        "Named predicates between rectangles",
        _build_rectangle_relations,
        tags=("topology", "predicate", "intersects", "touches"),
        operation="vector.relations",
        oracle="analytic_geometry",
        derivation="For axis-aligned rectangles, shared width and height decide every predicate. Both positive means the "
        "interiors meet. Either one zero means only boundaries meet.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
    define(
        "vector.distance.001",
        "Point to line segment distances",
        _build_point_line_distance,
        tags=("distance", "metric-crs"),
        operation="vector.distance",
        oracle="analytic_geometry",
        derivation="The segment runs from (0, 0) to (10, 0). (3, 4) is 4 m from its interior. (13, 4) is a 3-4-5 triangle "
        "from the end. (-6, 8) is a 6-8-10 triangle from the start.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
    define(
        "vector.multipart.001",
        "Multipart exclusion area",
        _build_multipart_exclusion,
        tags=("topology", "multipart", "exclusion"),
        operation="vector.multipart_area",
        oracle="analytic_geometry",
        derivation="Exclusion parts are 2 by 2 and 2 by 3, 10 m2 together, inside a 100 m2 study area. 90 m2 remain. "
        "Reading only the first part would leave 96 m2.",
        requires=("vector",),
        formats=(GEOPARQUET,),
    ),
)
