# GeoFixtures

Deterministic geospatial test data with known answers.

GeoFixtures generates small vector, raster, and point cloud datasets, keeps the expected results next
to them, and runs your code against them. It targets bugs that ordinary sample data misses: a
half-pixel grid shift, NoData scored as correct, slope that jumps at tile edges, a CRS label that
doesn't match the coordinates.

**Status:** pre-release. The package isn't on PyPI, and case answers haven't had an independent review.

## Install

Python 3.11 or later. Native libraries are extras:

```bash
pip install -e '.[all]'      # everything
pip install -e '.[vector]'   # GeoJSON, GeoParquet, CRS
pip install -e '.[raster]'   # GeoTIFF
pip install -e '.[lidar]'    # LAS
geofixtures doctor
```

## Usage

```bash
geofixtures list --select category:raster
geofixtures describe raster.dem.slope.001
geofixtures generate raster.dem.slope.001 --output ./tmp/slope_case
geofixtures validate ./tmp/slope_case/manifest.json
geofixtures run --select tag:topology --report results.json
geofixtures report results.json
```

```python
from geofixtures import materialize, run_case

case = materialize("vector.overlap.001", output_dir="./tmp/overlap", seed=42)
result = run_case(case, adapter="reference")
assert result.status == "PASS"
```

Selectors are `id:`, `tag:`, `category:`, `op:`, and `suite:`. The suites are `canonical`, `extended`,
`smoke`, `landfuse`, and `all`.

## Testing your own code

An adapter receives input files and returns observed values. It doesn't get the truth files.

```python
from geofixtures import Capability, ObservationBundle

class MyAdapter:
    name = "my-tool"

    def supports(self, case):
        if case.operation == "raster.slope":
            return Capability(True)
        return Capability(False, "Not implemented")

    def execute(self, context):
        output = context.work_dir / "slope.tif"
        my_tool.slope(context.input("dem"), output)
        return ObservationBundle(values={"slope": str(output)})

    def environment(self):
        return {"my_tool": my_tool.__version__}
```

```bash
geofixtures run --adapter my_package.adapter:MyAdapter --select tag:slope
```

With pytest:

```python
import pytest
from geofixtures.pytest_plugin import case_params

@pytest.mark.parametrize("case_id", case_params("tag:slope"))
def test_slope(case_id, run_fixture):
    run_fixture(case_id, adapter="my_package.adapter:MyAdapter")
```

See [examples/quickstart](examples/quickstart).

## CI

A plain run exits 0 when nothing failed, even if some cases didn't run. For a merge gate, use strict
mode:

```bash
geofixtures run --adapter my_package.adapter:MyAdapter --select tag:slope --strict --timeout 300
```

Strict mode fails on any `SKIP` or `UNSUPPORTED` case. To keep a known feature gap, list it in a policy
file with a reason:

```toml
[allow_unsupported]
"raster.grid.offset.001" = "No alignment diagnostic yet"
```

```bash
geofixtures run --select suite:landfuse --adapter landfuse --policy geofixtures-policy.toml
```

An allowed case that starts passing fails the run until it's removed from the file. The pytest
equivalents are `--geofixtures-strict` and `--geofixtures-policy`.

`--timeout` runs each case in its own process group and kills the group at the limit. `--isolate` does
the same with no limit, which also contains native crashes.

## Statuses

| Status | Meaning |
| --- | --- |
| `PASS` | Assertions ran and none failed |
| `FAIL` | An observed value broke an assertion |
| `ERROR` | The target crashed or timed out, or the fixture failed validation |
| `UNSUPPORTED` | The target lacks the feature, or an optional dependency is missing |
| `SKIP` | The adapter reported a temporary gap, such as a missing tool |

| Exit code | Meaning |
| --- | --- |
| 0 | Every executable case passed |
| 1 | An assertion failed |
| 2 | Bad invocation, corrupt fixture, runtime error, or interrupted run |
| 3 | Nothing could run |
| 4 | Strict mode found a skipped, unsupported, or stale case |

## Limitations

- Built-in answers are analytical or synthetic. A pass doesn't measure accuracy on real data.
- Land cover scenes are easy by construction. Their thresholds catch broken pipelines.
- Every case has the review status `pending_independent_review`.
- GitHub CI hasn't run yet.
- GeoPackage and LAZ aren't supported yet.

## Documentation

- [Architecture](docs/architecture.md)
- [Case catalog](docs/cases.md)
- [Fixture authoring](docs/fixture-authoring.md)
- [Oracles](docs/oracles.md)
- [Adapters](docs/adapters.md)
- [LandFuse](docs/landfuse.md)
- [Formats](docs/formats.md)
- [Reproducibility](docs/reproducibility.md)
- [Reference data policy](docs/reference-data-policy.md)
- [Compatibility](docs/compatibility.md)
- [Release checklist](docs/release-checklist.md)

## License

MIT
