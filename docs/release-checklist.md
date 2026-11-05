# Release checklist

Status for 0.1.0.

- [x] Installs from a clean environment on Python 3.11 and 3.13 (Linux)
- [x] `list`, `generate`, `validate`, `run`, and `report` work with no network
- [ ] 36 reviewed scenarios. All 36 exist, none reviewed
- [x] Each case has expected results, assertions, units or tolerances, and a valid manifest
- [x] GeoJSON, GeoTIFF, GeoParquet, and LAS round trips pass
- [x] Paired cases take a DEM or LiDAR with imagery, never both
- [x] DEM-only fixtures don't claim canopy height
- [x] Spatial errors, missing data, and partial sources fail
- [x] Cross-platform equivalence on Linux and macOS arm64
- [x] 90% statement coverage on core modules
- [ ] CI on Linux and macOS, Python 3.11 to 3.13. Workflow written, not run
- [x] pytest and command-line examples run in a clean folder
- [x] JSON and JUnit reports hold statuses, assertions, tolerances, timestamps, versions, and times
- [x] Docs separate analytical truth from annotated labels
- [x] No third-party data shipped
- [x] CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, LICENSE, changelog, and release notes present
