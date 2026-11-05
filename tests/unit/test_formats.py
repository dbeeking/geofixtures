"""Round-trip tests on decoded values."""

from __future__ import annotations

import json

import numpy as np
import pytest

from geofixtures.io.geojson import read_geojson, write_geojson
from geofixtures.io.geoparquet import decode_wkb, encode_wkb, read_geoparquet, write_geoparquet
from geofixtures.io.geotiff import GEOTIFF_PROFILE, Grid, read_metadata, write_geotiff
from geofixtures.io.las import read_las, write_las


def _point(x, y):
    return {
        "type": "Feature",
        "properties": {"id": "a"},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def test_geojson_round_trip(tmp_path):
    path = tmp_path / "a.geojson"
    write_geojson(path, [_point(-112.0, 34.0)])
    assert read_geojson(path)[0]["geometry"]["coordinates"] == [-112.0, 34.0]
    payload = json.loads(path.read_text())
    assert payload["type"] == "FeatureCollection"
    assert "crs" not in payload


def test_geojson_refuses_positions_outside_wgs84(tmp_path):
    with pytest.raises(ValueError, match="WGS84"):
        write_geojson(tmp_path / "a.geojson", [_point(400000.0, 3800000.0)])


def test_geojson_can_hold_bad_coordinates(tmp_path):
    path = tmp_path / "a.geojson"
    write_geojson(path, [_point(33.0, -112.0)], strict=False)
    assert read_geojson(path)


def test_geojson_reader_requires_collection(tmp_path):
    path = tmp_path / "a.geojson"
    path.write_text('{"type": "Feature"}')
    with pytest.raises(ValueError, match="FeatureCollection"):
        read_geojson(path)


_GEOMETRIES = [
    {"type": "Point", "coordinates": [1.0, 2.0]},
    {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
    {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 0.0]],
            [[2.0, 1.0], [3.0, 1.0], [3.0, 2.0], [2.0, 1.0]],
        ],
    },
    {
        "type": "MultiPolygon",
        "coordinates": [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]],
    },
]


@pytest.mark.parametrize("geometry", _GEOMETRIES, ids=lambda item: item["type"])
def test_wkb_round_trip(geometry):
    assert decode_wkb(encode_wkb(geometry)) == geometry


@pytest.mark.parametrize("geometry", _GEOMETRIES, ids=lambda item: item["type"])
def test_wkb_matches_shapely(geometry):
    shapely = pytest.importorskip("shapely")
    from shapely.geometry import shape

    assert shapely.from_wkb(encode_wkb(geometry)).equals(shape(geometry))


def test_geoparquet_round_trip_keeps_crs_nulls_and_types(tmp_path):
    pytest.importorskip("pyarrow")
    from pyproj import CRS

    path = tmp_path / "a.parquet"
    features = [
        {"type": "Feature", "properties": {"id": "a", "value": 1.5, "count": 2}, "geometry": _GEOMETRIES[0]},
        {"type": "Feature", "properties": {"id": "b", "value": None, "count": 3}, "geometry": _GEOMETRIES[0]},
    ]
    fields = (("id", "string"), ("value", "double"), ("count", "int64"))
    write_geoparquet(path, features, "EPSG:32612", fields=fields)
    loaded, metadata, schema = read_geoparquet(path)
    assert [item["properties"]["value"] for item in loaded] == [1.5, None]
    assert loaded[0]["geometry"] == _GEOMETRIES[0]
    assert metadata["version"] == "1.1.0"
    assert metadata["primary_column"] == "geometry"
    column = metadata["columns"]["geometry"]
    assert column["encoding"] == "WKB"
    assert column["geometry_types"] == ["Point"]
    assert CRS.from_json_dict(column["crs"]) == CRS.from_epsg(32612)
    assert column["bbox"] == [1.0, 2.0, 1.0, 2.0]
    assert schema == [("id", "string"), ("value", "double"), ("count", "int64")]


def test_geoparquet_reader_requires_geo_metadata(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    path = tmp_path / "plain.parquet"
    pq.write_table(pa.table({"id": ["a"]}), path)
    with pytest.raises(ValueError, match="geo metadata"):
        read_geoparquet(path)


def test_geotiff_round_trip_keeps_grid_nodata_and_values(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    path = tmp_path / "a.tif"
    grid = Grid(3, 2, 10.0, 400000.0, 3801000.0)
    values = np.arange(6, dtype="float32").reshape(2, 3)
    write_geotiff(path, values, grid, "EPSG:32612", nodata=-9999.0, tags={"NOTE": "x"})
    details = read_metadata(path)
    assert details["crs"] == "EPSG:32612"
    assert details["transform"] == grid.transform_values()
    assert (details["width"], details["height"], details["count"]) == (3, 2, 1)
    assert details["dtype"] == "float32"
    assert details["nodata"] == -9999.0
    assert details["tags"]["NOTE"] == "x"
    with rasterio.open(path) as dataset:
        assert np.array_equal(dataset.read(1), values)


def test_geotiff_uses_declared_version(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    path = tmp_path / "a.tif"
    write_geotiff(path, np.zeros((2, 2), dtype="uint8"), Grid(2, 2, 1.0, 0.0, 0.0), "EPSG:32612")
    assert GEOTIFF_PROFILE == "GeoTIFF 1.1"
    with rasterio.open(path) as dataset:
        assert dataset.driver == "GTiff"


def test_four_band_images_have_no_alpha_band(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    path = tmp_path / "a.tif"
    write_geotiff(path, np.ones((4, 2, 2), dtype="uint8"), Grid(2, 2, 1.0, 0.0, 0.0), "EPSG:32612")
    with rasterio.open(path) as dataset:
        assert dataset.colorinterp[3].name != "alpha"


def test_grid_geometry():
    grid = Grid(2, 2, 10.0, 100.0, 200.0)
    x, y = grid.centers()
    assert x.tolist() == [[105.0, 115.0], [105.0, 115.0]]
    assert y.tolist() == [[195.0, 195.0], [185.0, 185.0]]
    assert grid.box() == (100.0, 180.0, 120.0, 200.0)
    assert grid.shifted(5.0, -5.0).origin_x == 105.0
    assert grid.pixels == 4


def test_las_round_trip_keeps_scale_offset_crs_and_classes(tmp_path):
    pytest.importorskip("laspy")
    path = tmp_path / "a.las"
    x = np.array([400000.25, 400001.5])
    y = np.array([3800000.125, 3800001.0])
    z = np.array([1600.5, 1612.75])
    write_las(path, x, y, z, np.array([2, 5]), "EPSG:32612")
    cloud = read_las(path)
    assert cloud["version"] == "1.4"
    assert cloud["point_format"] == 6
    assert cloud["count"] == 2
    assert cloud["scale"] == [0.001, 0.001, 0.001]
    assert cloud["offset"] == [400000.0, 3800000.0, 1600.0]
    assert np.allclose(cloud["x"], x, atol=1e-3)
    assert np.allclose(cloud["z"], z, atol=1e-3)
    assert cloud["classification"].tolist() == [2, 5]
    assert "32612" in cloud["crs"]


def test_las_can_omit_crs(tmp_path):
    pytest.importorskip("laspy")
    path = tmp_path / "a.las"
    values = np.array([1.0, 2.0])
    write_las(path, values, values, values, np.array([2, 2]), None)
    assert read_las(path)["crs"] is None
