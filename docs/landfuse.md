# LandFuse

`suite:landfuse` selects the 21 cases that apply to LandFuse. GeoFixtures stays a separate test
dependency, and LandFuse's own tests don't change.

## Local run

```bash
cd ~/Documents/GitHub/landfuse
source .venv/bin/activate
python -m pip install -e "$HOME/Documents/GitHub/geofixtures[all]"
geofixtures doctor
geofixtures run --adapter landfuse --select suite:landfuse --timeout 300 --report /tmp/landfuse-geofixtures.json
```

The two canopy cases need `pdal` (`brew install pdal`, or conda-forge). Without it they report `SKIP`.

Measured on Linux with Python 3.13, PDAL 2.10, and LandFuse `v0.1.0` (commit `bb8baa5`):

```
Adapter landfuse: 17 PASS, 0 FAIL, 0 ERROR, 0 SKIP, 4 UNSUPPORTED (complete)
4 of 21 cases didn't run. Use --strict to fail on this.
```

The result is the same on macOS 27 on Apple Silicon with Python 3.12 and PDAL 2.10.

Without PDAL: 15 `PASS`, 2 `SKIP`, 4 `UNSUPPORTED`.

## CI gate

```bash
geofixtures run --adapter landfuse --select suite:landfuse --timeout 300 \
  --policy examples/landfuse/geofixtures-policy.toml
```

This fails if PDAL is missing, if a case stops running, or if an allowed gap starts passing.
[examples/landfuse](../examples/landfuse) has the policy file, a GitHub Actions workflow, and a pytest
file to copy into LandFuse.

## Integration branch

```bash
cd ~/Documents/GitHub/landfuse
git switch -c test/geofixtures-integration
EXAMPLE="$HOME/Documents/GitHub/geofixtures/examples/landfuse"
cp "$EXAMPLE/test_landfuse.py" tests/test_geofixtures.py
cp "$EXAMPLE/geofixtures-policy.toml" .github/geofixtures-policy.toml
cp "$EXAMPLE/ci.yml" .github/workflows/geofixtures.yml
```

Set the `GEOFIXTURES_REPOSITORY` and `GEOFIXTURES_REF` repository variables in LandFuse. GeoFixtures has
to be in a public repository for the job's install step to work.

`tests/test_geofixtures.py` skips itself in LandFuse's `Python tests` job, which doesn't install
GeoFixtures. The new check is named `fixtures`. Make it required after the Linux and macOS runs pass.

## Feature gaps

The policy file allows these four cases:

| Case | Gap |
| --- | --- |
| `raster.grid.offset.001` | No alignment diagnostic. Terrain is resampled to the image grid |
| `landcover.date_mismatch.001` | Acquisition dates aren't compared |
| `lidar.density.001` | Point density isn't reported |
| `lidar.vertical_mismatch.001` | LiDAR heights aren't compared with a DEM |

When LandFuse adds one of these, map it in `adapters/landfuse.py` and remove it from the policy.

## Cases

| Case | Checks |
| --- | --- |
| `raster.dem.slope.001` | Slope of a plane |
| `raster.ridge_saddle.001`, `raster.depression.001` | Slope on curved terrain |
| `raster.nodata_hole.001` | DEM holes stay out of slope values |
| `raster.tile_seam.001` | Slope is continuous across tile edges |
| `raster.partial_coverage.001` | Terrain coverage fraction |
| `raster.truncated.001` | A damaged image stops the run and leaves no output |
| `landcover.scene.rgbnir.001` | Training and classification on a four-band scene |
| `landcover.image_collar.001` | Zero-filled collars stay unclassified |
| `landcover.sampling_spread.001` | Training samples cover the whole scene |
| `landcover.spatial_leakage.001` | Spatial holdout on position-only bands |
| `landcover.missing_nir.001` | Three-band imagery is refused |
| `landcover.truth_mask.001` | Unlabeled pixels stay out of the score |
| `landcover.unknown.001` | Unclassified pixels count as misses, and coverage is reported |
| `landcover.pair.dem.001` | A DEM doesn't report canopy height |
| `landcover.pair.lidar.001` | LAS plus imagery gives known canopy heights |
| `lidar.ground_gap.001` | Canopy heights across a gap in ground returns |

## Defects caught during development

An early snapshot from before the first public release failed eight of these cases. None of this
applies to the public 0.1.0 release, which passes all of them.

| Case | Snapshot behavior |
| --- | --- |
| `raster.nodata_hole.001` | Holes were filled with the median, so slope around them was off by up to 0.25 |
| `raster.tile_seam.001` | One-sided differences at tile edges, with errors up to 0.007 |
| `raster.partial_coverage.001` | No coverage figure |
| `raster.truncated.001` | Partial output left after a read failure |
| `landcover.image_collar.001` | All 1536 collar pixels got a class |
| `landcover.sampling_spread.001` | Samples came from the first tiles only, scoring 0.67 |
| `landcover.unknown.001` | Accuracy of 1.0 with 95% of pixels unclassified |
| `lidar.ground_gap.001` | 576 canopy pixels had no height |

## Notes

- Fixtures are synthetic. Accuracy on real imagery needs independent labels and `landfuse crossval`.
- Slope is read from LandFuse's feature cube, because slope isn't a standalone output. A placeholder
  image supplies the grid.
- Classification cases use 30 trees to stay fast.

## Debugging a failure

```bash
geofixtures describe raster.tile_seam.001
geofixtures run --adapter landfuse --select raster.tile_seam.001 --keep-failures ./failures
geofixtures generate raster.tile_seam.001 --output ./seam_case
```
