# Reproducibility

Each case has a default seed, and all randomness comes from a generator created with it. `--seed` picks
another stream. Truth is derived from the written data, so answers hold for any seed.

On one machine with one set of libraries, repeated generation gives identical bytes. Across library
versions, bytes can change, so `tests/regression/catalog.lock.json` stores digests of decoded data and
answers. Numbers are rounded to 12 significant digits first, because math libraries can differ in the
last bit: `crs.transform.001` does on macOS and Linux, while every other case matched exactly. Manifests
and reports record library versions.

## Versions

| Item | Version | Changes when |
| --- | --- | --- |
| Package | 0.1.0 | Each release |
| Manifest schema | 1.0.0 | Major bump breaks older readers |
| Report schema | 1.1.0 | Major bump breaks older readers |
| Case | 1.0.0 | Data or answer changes |

A reader refuses a manifest with a different major version. A case ID keeps its meaning. A semantic
change needs a new ID or a major case version, and `Registry.aliases` can keep an old ID working.

## Reproducing a failure

```bash
geofixtures generate raster.tile_seam.001 --seed 42 --output ./case
geofixtures run --select raster.tile_seam.001 --seed 42 --adapter landfuse
```

## Building a release

```bash
python -m build
python -m venv /tmp/check
/tmp/check/bin/pip install "$(ls dist/*.whl)[all]"
/tmp/check/bin/geofixtures run --select suite:all --strict
```

## Offline runs

Generation, validation, and reference runs need no network.

`run` patches Python's socket module in the runner and in worker processes, blocking connections,
datagrams, and name lookups to other hosts. Loopback is allowed. This is best-effort: it doesn't cover
native libraries with their own network code, or programs started by an adapter, such as `pdal`.

To enforce offline execution, use a network namespace or a container with no network:

```bash
sudo unshare -n geofixtures run --select suite:all --strict
```
