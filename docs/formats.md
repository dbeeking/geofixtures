# Formats

Each manifest input states its format and profile.

| Format | Profile | Writer | Notes |
| --- | --- | --- | --- |
| GeoJSON | RFC 7946 | Standard library | WGS84 only, no `crs` member |
| GeoParquet | 1.1.0 | pyarrow | WKB geometry, PROJJSON CRS |
| GeoTIFF | 1.1 | rasterio | Uncompressed, explicit NoData |
| LAS | 1.4 point format 6 | laspy | Explicit scale, offset, CRS |

Projected vector fixtures use GeoParquet, because GeoJSON has no standard way to state a projected
CRS. `crs.axis_order.001` stores swapped axes as a negative case. Its profile records that, and writing it
needs `strict=False`.

WKB is encoded in `io/geoparquet.py`, so writing needs no geometry package. A test reads the bytes back
with shapely.

Four-band GeoTIFFs use `MINISBLACK`, so the fourth band stays a data band. With the default photometric
setting, rasterio treats band 4 as alpha, which hides zero-filled image collars.

The LAS header date is fixed so repeated generation gives identical bytes.

`tests/unit/test_formats.py` checks round trips on decoded values: geometry, CRS, numbers, nulls,
NoData, transforms, point scale and offset, and schema.

If a dependency is missing, its cases report `UNSUPPORTED`. GeoPackage, LAZ, and GeoParquet 2.0 aren't
supported yet.
