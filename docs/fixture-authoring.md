# Fixture authoring

New cases shouldn't need runner changes. Keep one case per pull request.

## Derive the answer

Work out the answer before writing code: hand geometry, a closed-form formula, or values assigned
before data is generated. Output from the software being tested can't be used as an oracle.

## Write a builder

Add a function to the matching module in `src/geofixtures/cases/`:

```python
def _build_rectangle_gap(context: BuildContext) -> CaseContent:
    a = (0.0, 0.0, 10.0, 10.0)
    b = (10.5, 0.0, 20.5, 10.0)
    write_features(context, "features.parquet", [box_feature("A", a), box_feature("B", b)], CRS, fields=_ID_FIELD)
    width = b[0] - a[2]
    gap_area = width * (a[3] - a[1])
    return CaseContent(
        inputs=[parquet_input("features", "features.parquet", CRS)],
        assertions=[numeric("gap_area", gap_area, "m2", 1e-9)],
        truth={"gap_width_m": width, "gap_area_m2": gap_area},
    )
```

- Use `context.rng` for randomness.
- Derive truth from the values written, so other seeds stay correct.
- Use `write_features`, `write_collection`, and `write_raster`. They apply size limits.
- `CaseContent.parameters` is visible to adapters. Don't put answers there.

## Register it

```python
define(
    "vector.gap.001",
    "Two polygons separated by a known gap",
    _build_rectangle_gap,
    tags=("topology", "gap", "metric-crs"),
    operation="vector.gap",
    oracle="analytic_geometry",
    derivation="The rectangles are 10 m tall and 0.5 m apart, so the strip between them is 5 m2.",
    requires=("vector",),
    formats=(GEOPARQUET,),
)
```

IDs follow `domain.subject.NNN`. Don't reuse an ID for a different meaning.

## Assertions

| Kind | Required fields |
| --- | --- |
| `exact` | `expected` |
| `set_equal` | `expected` |
| `numeric` | `expected` or `minimum`/`maximum`, `unit`. No tolerance means exact |
| `geometry_equivalent` | `expected`, `policy`, `require_valid` |
| `topology_predicate` | `expected` |
| `raster_metadata` | `expected` |
| `raster_values` | `truth`, `absolute_tolerance`, `unit`, `truth_nodata` |
| `classification_metrics` | `truth`, `labels`, `class_names`, `ignore_values`, `abstain_values`, `zero_division`, `averaging`, `thresholds` |
| `pointcloud_metadata` | `expected` |
| `schema` | `expected` |
| `expected_error` | `codes` |
| `invariant` | `rule` |

`raster_values` options:

| Option | Effect |
| --- | --- |
| `sampling` | `grid` needs exact alignment. `map_coordinates` reads the observed cell at each truth center |
| `transform_tolerance` | Absolute limit per affine term for `grid`, default `1e-6` |
| `exclude_edge_pixels` | Skips this many outer rows and columns |
| `truth_nodata` | `required` means truth NoData must stay NoData. `ignore` skips those pixels |
| `optional_mask` | Pixels may be NoData, and must match if they have a value |
| `ignore_mask` | Pixels aren't compared |
| `max_missing_fraction` | Share of required pixels allowed to be NoData |
| `observed_nodata_as_value` | Treats the NoData value as data, for class rasters where 0 is a result |

Mark an assertion `optional` only if a target can reasonably omit the value. A missing required value
gives `ERROR`.

For negative cases, set `expected_status` to `rejection`, or to `uncertain` when a refusal and an
explicit "can't tell" result are both acceptable.

## Finish

1. Add the operation to `adapters/reference.py`, written separately from the builder.
2. Add hand-worked tests for new oracle code in `tests/unit/test_oracles.py`.
3. Run `python tests/regression/update_lock.py`.
4. Run `python scripts/render_catalog.py`.
5. Run `pytest`. `test_every_case_can_fail.py` corrupts each observation and fails if the case still
   passes.
