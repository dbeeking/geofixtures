# Compatibility

| Platform | Python | Libraries | State |
| --- | --- | --- | --- |
| Linux x86-64 | 3.13 | numpy 2.5, rasterio 1.5, pyarrow 26, shapely 2.2, pyproj 3.8, laspy 2.7 | Tests pass |
| Linux x86-64 | 3.11 | numpy 1.26, rasterio 1.3, pyarrow 14, shapely 2.0, pyproj 3.6, laspy 2.5 | Tests pass |
| Linux x86-64 | 3.12 | numpy 2.5, rasterio 1.5, pyarrow 26, shapely 2.2, pyproj 3.8, laspy 2.7 | Tests pass |
| macOS arm64 | 3.12 | numpy 2.5, rasterio 1.5 (GDAL 3.12), pyarrow 26, shapely 2.2, pyproj 3.8, laspy 2.7 | Tests pass |
| macOS | 3.11, 3.13 | | In CI config, not run |
| Windows | | | Unsupported. Worker processes rely on POSIX process groups |

The catalog lock passes on all tested configurations.

| Target | Versions | Notes |
| --- | --- | --- |
| LandFuse | `v0.1.0` (`bb8baa5`) | Canopy cases need `pdal` |
| PDAL | 2.10.2 | Used through LandFuse |
