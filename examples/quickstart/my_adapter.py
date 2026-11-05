"""Tests a small overlap function against vector.overlap.001."""

from __future__ import annotations

import itertools
from pathlib import Path

import pyarrow.parquet as pq
import shapely

from geofixtures import Capability, CaseView, ExecutionContext, ObservationBundle


def overlaps(path: Path) -> dict:
    """The function under test."""
    table = pq.read_table(path)
    shapes = dict(zip(table["id"].to_pylist(), shapely.from_wkb(table["geometry"].to_pylist()), strict=True))
    pairs = {}
    for (left, a), (right, b) in itertools.combinations(sorted(shapes.items()), 2):
        common = a.intersection(b)
        if common.area > 0:
            pairs[f"{left}|{right}"] = common
    return {
        "overlap_pairs": sorted(pairs),
        "overlap_area": sum(shape.area for shape in pairs.values()),
        "union_area": shapely.union_all(list(shapes.values())).area,
        "overlap_geometry": shapely.union_all(list(pairs.values())).wkt,
    }


class OverlapAdapter:
    name = "my-overlap"

    def supports(self, case: CaseView) -> Capability:
        if case.operation == "vector.overlap":
            return Capability(True)
        return Capability(False, "Only overlap is implemented")

    def execute(self, context: ExecutionContext) -> ObservationBundle:
        return ObservationBundle(values=overlaps(context.input("features")))

    def environment(self) -> dict:
        return {"shapely": shapely.__version__}
