# LandFuse example

Files to copy into the LandFuse repository:

| File | Copy to |
| --- | --- |
| `test_landfuse.py` | `tests/test_geofixtures.py` |
| `geofixtures-policy.toml` | `.github/geofixtures-policy.toml` |
| `ci.yml` | `.github/workflows/geofixtures.yml` |

`ci.yml` needs two repository variables: `GEOFIXTURES_REPOSITORY` (`owner/name`) and `GEOFIXTURES_REF`
(a tag or commit). The job fails if either one is missing, and the repository has to be public for the
install step to work.

`test_landfuse.py` skips itself when GeoFixtures isn't installed, so LandFuse's `Python tests` job is
unaffected.

See [docs/landfuse.md](../../docs/landfuse.md).
