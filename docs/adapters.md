# Adapters

An adapter connects GeoFixtures to the code under test.

```python
class Adapter(Protocol):
    name: str
    def supports(self, case: CaseView) -> Capability: ...
    def execute(self, context: ExecutionContext) -> ObservationBundle: ...
    def environment(self) -> dict[str, Any]: ...
```

## supports

`CaseView` has `case_id`, `operation`, `tags`, `parameters`, and `roles`.

```python
Capability(True)                          # run the case
Capability(False, "No slope output")      # UNSUPPORTED: the feature doesn't exist
Capability(False, "pdal missing", skip=True)  # SKIP: something is temporarily missing
```

## execute

```python
context.input("dem")     # path, for a role with one file
context.inputs["page"]   # paths, for a role with several
context.has("labels")
context.parameters
context.work_dir         # write outputs here
```

```python
ObservationBundle(values={"overlap_area": 4.0})
ObservationBundle(rejection=Rejection("MISSING_BAND", "Found 3 bands"))
ObservationBundle(values={"partial_output_written": False}, rejection=Rejection("READ_FAILED"))
```

Return a `Rejection` when the target refuses an input. An uncaught exception gives `ERROR`.

Observation names come from the case's assertions. Run `geofixtures generate` and read
`manifest.json`.

## Worker processes

With `--timeout` or `--isolate`, `execute()` runs in a separate process:

- The adapter must be picklable, and its class must be importable.
- Classes defined in `__main__` or inside a function give `ERROR`.
- Values must be JSON types, numpy scalars or arrays, paths, or sets.
- Stdout and stderr go to a log file, and the last line appears in crash errors.

## Loading

```bash
geofixtures run --adapter reference
geofixtures run --adapter my_package.adapter:MyAdapter
```

```toml
[project.entry-points."geofixtures.adapters"]
mytool = "my_package.adapter:MyAdapter"
```

Keep adapters thin. If the target doesn't produce a value, report `UNSUPPORTED`.

## Comparing targets

```bash
geofixtures run --adapter one --report one.json
geofixtures run --adapter two --report two.json
geofixtures report one.json --compare two.json
```

This lists assertions whose observed values differ, including cases where both passed.
