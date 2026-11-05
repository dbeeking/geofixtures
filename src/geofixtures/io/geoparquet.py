"""GeoParquet 1.1 with WKB geometry, encoded here without a geometry library."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

GEOPARQUET_VERSION = "1.1.0"
_WKB_TYPES = {
    "Point": 1,
    "LineString": 2,
    "Polygon": 3,
    "MultiPoint": 4,
    "MultiLineString": 5,
    "MultiPolygon": 6,
}
_WKB_NAMES = {value: key for key, value in _WKB_TYPES.items()}


def _encode_points(points: Sequence[Sequence[float]]) -> bytes:
    body = struct.pack("<I", len(points))
    for x, y in points:
        body += struct.pack("<dd", x, y)
    return body


def encode_wkb(geometry: dict[str, Any]) -> bytes:
    """Encode a GeoJSON-style geometry mapping as little-endian 2D WKB."""
    kind = geometry["type"]
    coordinates = geometry["coordinates"]
    header = struct.pack("<BI", 1, _WKB_TYPES[kind])
    if kind == "Point":
        return header + struct.pack("<dd", *coordinates)
    if kind == "LineString":
        return header + _encode_points(coordinates)
    if kind == "Polygon":
        body = struct.pack("<I", len(coordinates))
        for ring in coordinates:
            body += _encode_points(ring)
        return header + body
    child = {"MultiPoint": "Point", "MultiLineString": "LineString", "MultiPolygon": "Polygon"}[kind]
    body = struct.pack("<I", len(coordinates))
    for part in coordinates:
        body += encode_wkb({"type": child, "coordinates": part})
    return header + body


def _decode_points(data: bytes, offset: int) -> tuple[list[list[float]], int]:
    count = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    points = []
    for _ in range(count):
        points.append(list(struct.unpack_from("<dd", data, offset)))
        offset += 16
    return points, offset


def _decode(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    if data[offset] != 1:
        raise ValueError("Only little-endian WKB is supported")
    kind_code = struct.unpack_from("<I", data, offset + 1)[0]
    if kind_code not in _WKB_NAMES:
        raise ValueError(f"Unsupported WKB geometry type: {kind_code}")
    kind = _WKB_NAMES[kind_code]
    offset += 5
    coordinates: Any
    if kind == "Point":
        coordinates = list(struct.unpack_from("<dd", data, offset))
        offset += 16
    elif kind == "LineString":
        coordinates, offset = _decode_points(data, offset)
    elif kind == "Polygon":
        rings = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        coordinates = []
        for _ in range(rings):
            ring, offset = _decode_points(data, offset)
            coordinates.append(ring)
    else:
        parts = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        coordinates = []
        for _ in range(parts):
            child, offset = _decode(data, offset)
            coordinates.append(child["coordinates"])
    return {"type": kind, "coordinates": coordinates}, offset


def decode_wkb(data: bytes) -> dict[str, Any]:
    geometry, _ = _decode(data, 0)
    return geometry


def _flatten(coordinates: Any) -> Iterable[Sequence[float]]:
    if coordinates and isinstance(coordinates[0], (int, float)):
        yield coordinates
        return
    for item in coordinates:
        yield from _flatten(item)


def _bbox(features: list[dict[str, Any]]) -> list[float]:
    points = [p for feature in features for p in _flatten(feature["geometry"]["coordinates"])]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def write_geoparquet(
    path: Path, features: list[dict[str, Any]], crs: str, *, fields: Sequence[tuple[str, str]] = ()
) -> None:
    """Write features with attributes to a GeoParquet 1.1 file.

    fields lists (name, type) pairs, where type is string, int64, double, or bool.
    Every feature's properties should supply these names, and None becomes a null.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    from pyproj import CRS

    types = {"string": pa.string(), "int64": pa.int64(), "double": pa.float64(), "bool": pa.bool_()}
    columns = [
        pa.array([feature["properties"].get(name) for feature in features], type=types[kind])
        for name, kind in fields
    ]
    names = [name for name, _ in fields]
    columns.append(pa.array([encode_wkb(feature["geometry"]) for feature in features], type=pa.binary()))
    names.append("geometry")
    table = pa.Table.from_arrays(columns, names=names)
    metadata = {
        "version": GEOPARQUET_VERSION,
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": sorted({feature["geometry"]["type"] for feature in features}),
                "crs": CRS.from_user_input(crs).to_json_dict(),
                "bbox": _bbox(features),
            }
        },
    }
    table = table.replace_schema_metadata({b"geo": json.dumps(metadata, sort_keys=True).encode("utf-8")})
    pq.write_table(table, path, compression="zstd")


def read_geoparquet(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[tuple[str, str]]]:
    """Return features, geo metadata, and (name, arrow type) schema pairs."""
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    raw = (table.schema.metadata or {}).get(b"geo")
    if raw is None:
        raise ValueError("File has no GeoParquet geo metadata")
    metadata: dict[str, Any] = json.loads(raw)
    rows = table.to_pylist()
    features = []
    for row in rows:
        blob = row.pop("geometry")
        features.append({"type": "Feature", "properties": row, "geometry": decode_wkb(blob)})
    schema = [(field.name, str(field.type)) for field in table.schema if field.name != "geometry"]
    return features, metadata, schema
