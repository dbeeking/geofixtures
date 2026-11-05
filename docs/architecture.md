# Architecture

```
registry -> materialize -> manifest, inputs, truth
                               |
                  adapter runs on a copy of the inputs
                               |
                  observations -> assertions -> report
```

| Module | Purpose |
| --- | --- |
| `registry.py` | Case list, selectors, suites |
| `cases/` | Case definitions by domain |
| `generators/` | Coordinates, surfaces, images, point clouds |
| `oracles/` | Expected values and comparisons |
| `io/` | GeoJSON, GeoParquet, GeoTIFF, LAS |
| `materialize.py` | Writes a fixture to a staging folder, then renames it |
| `validation.py` | Schema, path, checksum, and truth reference checks |
| `runner/` | Adapter protocol, execution, assertions, reports, strict policy, worker process |
| `adapters/` | Reference and LandFuse adapters |

## Layering

`tests/contract/test_architecture.py` checks these rules:

- Generators, oracles, I/O, and cases don't import adapters or the runner.
- Generators and oracles don't import each other.
- `oracles/analytic.py` and `oracles/geometry.py` use no geometry library.
- The reference adapter doesn't import oracles or cases.

Adapters get copies of the inputs in a run folder. They don't get the fixture path, manifest, or
truth files.

## Execution

Every run validates the fixture first. A changed input or truth file gives `ERROR`, and no assertion
runs.

With no timeout, `execute()` runs in the current process. With `--timeout` or `--isolate`, the runner
pickles the adapter and starts `geofixtures.runner.worker` in a new session. At the timeout it sends
SIGTERM to the process group, waits two seconds, and sends SIGKILL. The group is also cleared after a
normal exit, so child processes don't outlive a case.

A worker that exits without a result gives `ERROR`, with the exit code and the last line of its log.
A process that starts its own session leaves the group and isn't stopped.

Reports are written to a temporary file and renamed. An interrupted suite stops its worker, reports
`complete: false`, and exits with code 2.

## Differences from the specification

- Cases live in `src/geofixtures/cases/` so they install with the wheel.
- Six extended cases were added.
- The LandFuse adapter ships with the package.
- The spec's "LiDAR and paired inputs" domain has IDs starting with `lidar.` and `landcover.pair.`, so
  `category:landcover` returns seven canonical cases and `category:lidar` returns two.
- `list_cases` and `describe_case` return dictionaries. Other API calls return dataclasses.
