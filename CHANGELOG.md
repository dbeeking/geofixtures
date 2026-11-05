# Changelog

## 0.1.0 — Initial public release

This initial public release includes functionality and corrections developed during internal pre-release iterations.

### Added

- `--strict`, `--policy`, `--geofixtures-strict`, `--geofixtures-policy`, and exit code 4
- A `strict` section in reports (schema 1.1.0), with violations shown as JUnit failures
- `--isolate` for containing native crashes
- A LandFuse CI job that fails if LandFuse or PDAL is missing
- A note in plain runs when cases didn't run
- 36 canonical and 6 extended cases
- Manifests with checksums, 12 assertion kinds, reference and LandFuse adapters
- `geofixtures` command, Python API, pytest fixtures, JSON and JUnit reports

### Fixed

- The catalog lock still hashed `truth/expected.json` as raw bytes, so a last-bit math library
  difference failed `crs.transform.001` on macOS. JSON files now use decoded, rounded values.
- Stopping a worker could raise `PermissionError` on macOS, which reports EPERM for a process group
  that holds only zombies.
- Catalog lock digests rounded to fixed decimals, so a last-bit math library difference on UTM
  coordinates could fail the test on another platform. They now round to 12 significant digits.
- A socket test used a path too long for macOS, and two process tests had tight startup limits.
- `examples/landfuse/test_landfuse.py` failed at collection when GeoFixtures wasn't installed, which
  stopped LandFuse's existing test job. It now skips.
- `raster_metadata` applied a relative tolerance to transforms, so a 3 m shift passed a `1e-6` limit.
  Transform checks are now absolute.
- `map_coordinates` sampling assumed north-up grids. It now uses the inverse affine.
- Grid alignment in `raster_values` and `classification_metrics` uses `transform_tolerance`, default
  `1e-6`.
- `--timeout` left adapter threads running. Adapters now run in a worker process, and the whole process
  group is stopped at the limit.
- LandFuse docs mixed up pre-release snapshots with the public release.
- The LandFuse workflow example installed from PyPI, where the package doesn't exist.

### Changed

- The crash containment test stops its worker with SIGKILL, so macOS doesn't open a crash dialog.
- The LandFuse CI job pins `dbeeking/landfuse` at `v0.1.0` (commit `bb8baa5`), so it needs no
  repository variables.
- `docs/landfuse.md` has steps for the integration branch.
- The offline guard also blocks datagrams and name lookups, and allows loopback. It's documented as
  best-effort.
