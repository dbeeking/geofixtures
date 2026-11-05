"""Change detection and source integrity cases."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..generators.ingestion import cell_feature
from ..generators.vector import box_feature
from ..io.geojson import write_geojson
from ..models import BuildContext, CaseContent, CaseSpec, InputFile
from ..oracles.data_integrity import semantic_feature_hash
from ._helpers import (
    GEOPARQUET,
    RFC_GEOJSON,
    define,
    exact,
    numeric,
    parquet_input,
    rejection,
    set_equal,
    write_collection,
    write_features,
)

UTM = "EPSG:32612"


def _geojson_input(role: str, name: str) -> InputFile:
    return InputFile(role, f"input/{name}", "GeoJSON", RFC_GEOJSON, crs="EPSG:4326")


def _snapshot_inputs() -> list[InputFile]:
    return [_geojson_input("before", "before.geojson"), _geojson_input("after", "after.geojson")]


def _build_added_field(context: BuildContext) -> CaseContent:
    before = [
        box_feature(f"f{i}", (i * 20.0, 0.0, i * 20.0 + 10.0, 10.0), name=f"site {i}") for i in range(4)
    ]
    after = [
        box_feature(f"f{i}", (i * 20.0, 0.0, i * 20.0 + 10.0, 10.0), name=f"site {i}", zone_code=f"Z{i}")
        for i in range(4)
    ]
    write_features(context, "before.parquet", before, UTM, fields=(("id", "string"), ("name", "string")))
    write_features(
        context,
        "after.parquet",
        after,
        UTM,
        fields=(("id", "string"), ("name", "string"), ("zone_code", "string")),
    )
    schema = {"id": "string", "name": "string", "zone_code": "string"}
    return CaseContent(
        inputs=[parquet_input("before", "before.parquet", UTM), parquet_input("after", "after.parquet", UTM)],
        assertions=[
            set_equal("added_fields", ["zone_code"]),
            set_equal("removed_fields", []),
            set_equal("changed_ids", []),
            {"id": "after_schema", "kind": "schema", "expected": schema},
        ],
        truth={"after_schema": schema},
    )


def _build_same_count_change(context: BuildContext) -> CaseContent:
    stamp = "2025-01-01"
    before = [cell_feature(f"f{i}", i, modified=stamp) for i in range(8)]
    moved = cell_feature("f3", 3, row=1, modified=stamp)
    after = [moved if item["properties"]["id"] == "f3" else item for item in before]
    write_collection(context, "before.geojson", before)
    write_collection(context, "after.geojson", list(reversed(after)))
    return CaseContent(
        inputs=_snapshot_inputs(),
        parameters={"coordinate_digits": 6},
        assertions=[
            numeric("count_before", 8, "features"),
            numeric("count_after", 8, "features"),
            set_equal("changed_ids", ["f3"]),
            set_equal("added_ids", []),
            set_equal("deleted_ids", []),
        ],
        truth={
            "semantic_hash_before": semantic_feature_hash(before),
            "semantic_hash_after": semantic_feature_hash(after),
            "changed_ids": ["f3"],
        },
    )


def _build_deleted_feature(context: BuildContext) -> CaseContent:
    before = [cell_feature(f"f{i}", i) for i in range(10)]
    after = [item for item in before if item["properties"]["id"] != "f4"]
    write_collection(context, "before.geojson", before)
    write_collection(context, "after.geojson", after)
    return CaseContent(
        inputs=_snapshot_inputs(),
        parameters={"coordinate_digits": 6},
        assertions=[
            set_equal("deleted_ids", ["f4"]),
            set_equal("added_ids", []),
            set_equal("changed_ids", []),
        ],
        truth={"deleted": ["f4"]},
    )


def _build_lineage(context: BuildContext) -> CaseContent:
    before = [
        box_feature("A", (0.0, 0.0, 10.0, 10.0)),
        box_feature("B", (20.0, 0.0, 30.0, 10.0)),
        box_feature("C", (30.0, 0.0, 40.0, 10.0)),
        box_feature("D", (50.0, 0.0, 60.0, 10.0)),
        box_feature("E", (70.0, 0.0, 80.0, 10.0)),
    ]
    after = [
        box_feature("A1", (0.0, 0.0, 5.0, 10.0)),
        box_feature("A2", (5.0, 0.0, 10.0, 10.0)),
        box_feature("BC", (20.0, 0.0, 40.0, 10.0)),
        box_feature("D", (50.0, 0.0, 60.0, 10.0)),
        box_feature("E1", (75.0, 0.0, 85.0, 10.0)),
    ]
    fields = (("id", "string"),)
    write_features(context, "before.parquet", before, UTM, fields=fields)
    write_features(context, "after.parquet", after, UTM, fields=fields)
    return CaseContent(
        inputs=[parquet_input("before", "before.parquet", UTM), parquet_input("after", "after.parquet", UTM)],
        parameters={"match_fraction": 0.99},
        assertions=[
            set_equal("unchanged", ["D"]),
            exact("splits", {"A": ["A1", "A2"]}),
            exact("merges", {"BC": ["B", "C"]}),
            set_equal("ambiguous", ["E"]),
        ],
        truth={"lineage": {"A": ["A1", "A2"], "B": ["BC"], "C": ["BC"], "D": ["D"], "E": ["E1"]}},
    )


def _build_missing_page(context: BuildContext) -> CaseContent:
    pages, size = 5, 10
    missing = 3
    inputs: list[InputFile] = []
    index: dict[str, Any] = {"page_count": pages, "page_size": size, "feature_count": pages * size}
    context.input_path("index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    inputs.append(InputFile("index", "input/index.json", "JSON", "Source index"))
    for page in range(1, pages + 1):
        if page == missing:
            continue
        name = f"page_{page:03d}.geojson"
        features = [cell_feature(f"p{page}_{i}", i, row=page) for i in range(size)]
        write_collection(context, name, features)
        inputs.append(_geojson_input("page", name))
    return CaseContent(
        inputs=inputs,
        assertions=[
            exact("ingest_status", "PARTIAL"),
            set_equal("missing_pages", [missing]),
            numeric("received_features", (pages - 1) * size, "features"),
            numeric("expected_features", pages * size, "features"),
        ],
        truth={"missing_pages": [missing]},
    )


def _build_tampered_source(context: BuildContext) -> CaseContent:
    original = [cell_feature(f"f{i}", i) for i in range(4)]
    source = context.input_path("source.geojson")
    write_geojson(source, original)
    published = hashlib.sha256(source.read_bytes()).hexdigest()
    context.input_path("source.geojson.sha256").write_text(f"{published}  source.geojson\n")
    write_geojson(source, [*original, cell_feature("injected", 9)])
    return CaseContent(
        inputs=[
            _geojson_input("source", "source.geojson"),
            InputFile("checksum", "input/source.geojson.sha256", "Text", "SHA-256 checksum line"),
        ],
        assertions=[
            rejection("rejects_changed_source", ["CHECKSUM_MISMATCH"]),
            {"id": "features_loaded", "kind": "invariant", "rule": "is_false", "optional": True},
        ],
        truth={"published_sha256": published},
    )


_PARQUET = (GEOPARQUET,)
_GEOJSON = (RFC_GEOJSON,)

CASES: tuple[CaseSpec, ...] = (
    define(
        "ingest.schema_added.001",
        "Source adds a field",
        _build_added_field,
        tags=("ingestion", "schema", "drift"),
        operation="ingest.diff",
        oracle="constructed_change",
        derivation="The after file repeats the before file with one new column, zone_code. Nothing else changes.",
        requires=("vector",),
        formats=_PARQUET,
    ),
    define(
        "ingest.unchanged_count.001",
        "Geometry changes while the count and date hold still",
        _build_same_count_change,
        tags=("ingestion", "geometry", "drift"),
        operation="ingest.diff",
        oracle="constructed_change",
        derivation="Feature f3 moves one grid row north. The count and modified date stay equal, and the after file is "
        "in reverse order.",
        requires=("vector",),
        formats=_GEOJSON,
    ),
    define(
        "ingest.deletion.001",
        "Source deletes a feature",
        _build_deleted_feature,
        tags=("ingestion", "deletion", "drift"),
        operation="ingest.diff",
        oracle="constructed_change",
        derivation="Feature f4 is removed from a 10 feature source, and the rest are byte-for-byte the same.",
        requires=("vector",),
        formats=_GEOJSON,
    ),
    define(
        "ingest.split_merge.001",
        "Split, merged, and ambiguous lineage",
        _build_lineage,
        tags=("ingestion", "lineage", "drift"),
        operation="ingest.lineage",
        oracle="constructed_change",
        derivation="A splits into two halves and B plus C merge, with shared edges kept. D is unchanged. E1 overlaps only "
        "half of E, so that link has to be reported as ambiguous.",
        requires=("vector",),
        formats=_PARQUET,
    ),
    define(
        "ingest.pagination.001",
        "Paged source missing a page",
        _build_missing_page,
        tags=("ingestion", "pagination", "negative"),
        operation="ingest.pagination",
        oracle="constructed_change",
        derivation="The index promises 5 pages of 10 features. Page 3 isn't delivered, so 40 of 50 arrive.",
        requires=("vector",),
        formats=_GEOJSON,
    ),
    define(
        "ingest.integrity.001",
        "Source fails its published checksum",
        _build_tampered_source,
        tags=("ingestion", "integrity", "negative"),
        operation="ingest.integrity",
        oracle="sha256",
        derivation="The checksum line is computed before one feature is added to the file, so the hashes can't match.",
        requires=("vector",),
        formats=_GEOJSON,
        expected_status="rejection",
    ),
)
