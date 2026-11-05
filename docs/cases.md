# Case catalog

This file comes from `scripts/render_catalog.py`. Don't edit it by hand.

Canonical cases make up the 36 case release catalog. Extended cases are extra checks that
run with `--select suite:extended` or `--select suite:all`.

## Vector topology

### `vector.boundary.001`

Point-in-polygon on boundaries and holes (canonical).

- Operation: `vector.point_in_polygon`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: topology, boundary, hole, predicate
- How the answer is known: Each point is compared with the outer rectangle and the hole by interval tests. Contains excludes the boundary and covers includes it. The tolerance test measures distance to the nearest edge.

### `vector.distance.001`

Point to line segment distances (canonical).

- Operation: `vector.distance`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: distance, metric-crs
- How the answer is known: The segment runs from (0, 0) to (10, 0). (3, 4) is 4 m from its interior. (13, 4) is a 3-4-5 triangle from the end. (-6, 8) is a 6-8-10 triangle from the start.

### `vector.gap.001`

Two polygons separated by a known gap (canonical).

- Operation: `vector.gap`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: topology, gap, metric-crs
- How the answer is known: The rectangles are 10 m tall and 0.5 m apart, so the strip between them is 0.5 by 10 = 5 m2.

### `vector.multipart.001`

Multipart exclusion area (canonical).

- Operation: `vector.multipart_area`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: topology, multipart, exclusion
- How the answer is known: Exclusion parts are 2 by 2 and 2 by 3, 10 m2 together, inside a 100 m2 study area. 90 m2 remain. Reading only the first part would leave 96 m2.

### `vector.overlap.001`

Two polygons with known overlap (canonical).

- Operation: `vector.overlap`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: topology, overlap, metric-crs
- How the answer is known: A is 5 by 4 at the origin, B is 5 by 4 at (3, 2). They share x 3 to 5 and y 2 to 4, so 2 by 2 = 4 m2. Union = 20 + 20 - 4 = 36 m2.

### `vector.relations.001`

Named predicates between rectangles (canonical).

- Operation: `vector.relations`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: topology, predicate, intersects, touches
- How the answer is known: For axis-aligned rectangles, shared width and height decide every predicate. Both positive means the interiors meet. Either one zero means only boundaries meet.

### `vector.self_intersection.001`

Bow-tie polygon that crosses itself (canonical).

- Operation: `vector.validity`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: topology, validity, repair
- How the answer is known: The ring crosses at (2, 2), forming two triangles of base 4 and height 2. Each has area 4, so a repaired geometry covers 8 m2. The ring's signed area is 0.

### `vector.sliver.001`

Sliver polygon below a compactness threshold (canonical).

- Operation: `vector.sliver`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: topology, sliver, quality
- How the answer is known: Polsby-Popper is 4 pi A / P squared. A 100 by 0.25 rectangle scores 4 pi 25 / 200.5 squared, about 0.0078. A 10 by 10 square scores pi / 4.

## CRS and units

### `crs.axis_order.001`

Latitude and longitude in the wrong order (canonical).

- Operation: `crs.validate_position`
- Expected status: `rejection`
- Oracle: `range_rule`
- Formats: GeoJSON with swapped axes, not RFC 7946
- Needs: vector
- Tags: crs, axis-order, negative
- How the answer is known: RFC 7946 positions are longitude, latitude. Here the second value is -112.07, which isn't a latitude.

### `crs.mislabeled.001`

Projected metres labeled as geographic degrees (canonical).

- Operation: `crs.validate_labels`
- Expected status: `uncertain`
- Oracle: `range_rule`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: crs, metadata, negative
- How the answer is known: Geographic coordinates can't exceed 180 and 90, so a value near 400000 disproves the label. It doesn't reveal the true CRS.

### `crs.transform.001`

Geographic to UTM transformation (canonical).

- Operation: `crs.transform`
- Expected status: `success`
- Oracle: `transverse_mercator_series`
- Formats: RFC 7946 GeoJSON
- Needs: vector
- Tags: crs, transformation, projection
- How the answer is known: Control points are projected with the sixth-order Krueger series for WGS84 UTM zone 12N, which shares no code with PROJ.

### `crs.units.001`

Feet stored under a metre label (canonical).

- Operation: `crs.unit_check`
- Expected status: `success`
- Oracle: `control_distance`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: crs, units, negative
- How the answer is known: Each line has a surveyed length of 1000 m. File length divided by that gives 1 / 0.3048 for the foot and 3937 / 1200 for the US survey foot. A line with no control distance can't be judged.

### `crs.vertical_datum.001`

Elevation with no vertical datum (canonical).

- Operation: `crs.vertical_compare`
- Expected status: `uncertain`
- Oracle: `datum_state`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: crs, vertical, negative
- How the answer is known: The reference declares NAVD88 height. The candidate has a horizontal CRS only, so its heights can't be compared.

## Raster and terrain

### `raster.dem.slope.001`

Slope of an analytic plane (canonical).

- Operation: `raster.slope`
- Expected status: `success`
- Oracle: `analytic_surface`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: terrain, slope, analytic
- How the answer is known: z = 1500 + 0.03 x + 0.04 y has gradient (0.03, 0.04), so rise over run is 0.05 everywhere. A central difference is exact on a plane. The outer row and column are excluded.

### `raster.depression.001`

Slope around a closed depression (canonical).

- Operation: `raster.slope`
- Expected status: `success`
- Oracle: `analytic_surface`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: terrain, slope, analytic, depression
- How the answer is known: z = 1500 + 0.001 (x2 + y2) has slope 0.002 r, with its minimum exactly at cell (32, 32).

### `raster.drainage.001`

Flowline distance and buffer area (canonical).

- Operation: `raster.drainage`
- Expected status: `success`
- Oracle: `analytic_geometry`
- Formats: GeoTIFF 1.1, GeoParquet 1.1.0
- Needs: raster, vector
- Tags: terrain, drainage, distance
- How the answer is known: The flowline is straight and 530 m long along the valley floor. Distances are right triangles from the line or its end. A 30 m round-capped buffer covers 2 w L + pi w2 m2. The 1 m2 tolerance allows for circles drawn as polygons.

### `raster.grid.offset.001`

Imagery and DEM offset by half a pixel (canonical).

- Operation: `raster.alignment`
- Expected status: `success`
- Oracle: `grid_geometry`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: alignment, negative, imagery
- How the answer is known: The DEM origin is moved 5 m east and 5 m south on a 10 m grid, which is half a pixel on each axis.

### `raster.nodata_hole.001`

Slope around a NoData hole (canonical).

- Operation: `raster.slope`
- Expected status: `success`
- Oracle: `analytic_surface`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: terrain, slope, nodata
- How the answer is known: The plane has slope 0.05, so a valid output next to the hole must still be 0.05. Hole pixels have no elevation and must stay NoData. The one-pixel ring around the hole may be NoData or 0.05.

### `raster.partial_coverage.001`

DEM covering a quarter of the image (canonical).

- Operation: `raster.coverage`
- Expected status: `success`
- Oracle: `grid_geometry`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: alignment, coverage, negative
- How the answer is known: The DEM has the image's height and 16 of its 64 columns, so it covers 16 / 64 = 0.25.

### `raster.restriction_overlay.001`

Restriction polygon over a raster (canonical).

- Operation: `raster.overlay`
- Expected status: `success`
- Oracle: `pixel_center_rule`
- Formats: GeoTIFF 1.1, GeoParquet 1.1.0
- Needs: raster, vector
- Tags: overlay, exclusion, rasterization
- How the answer is known: The polygon spans 103 m to 297 m on both axes. Pixel centers fall at 5, 15, 25 m and so on, and 20 of them lie inside on each axis. That gives 400 pixels, or 40000 m2, under the pixel-center rule.

### `raster.ridge_saddle.001`

Slope across a saddle (canonical).

- Operation: `raster.slope`
- Expected status: `success`
- Oracle: `analytic_surface`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: terrain, slope, analytic, saddle
- How the answer is known: z = 1500 + 0.001 (x2 - y2) has gradient (0.002 x, -0.002 y). A central difference is exact for a quadratic, so slope is 0.002 times the distance from the saddle.

### `raster.tile_seam.001`

Slope continuity across tile edges (extended).

- Operation: `raster.slope`
- Expected status: `success`
- Oracle: `analytic_surface`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: terrain, slope, tiling
- How the answer is known: The paraboloid's central-difference slope is exact, so a value that changes at a tile edge is an error. Tiles are 64 pixels on a 128 pixel grid.

### `raster.truncated.001`

Truncated imagery leaves no partial output (extended).

- Operation: `raster.read_failure`
- Expected status: `rejection`
- Oracle: `corruption_rule`
- Formats: Truncated GeoTIFF 1.1
- Needs: raster
- Tags: integrity, negative, tiling
- How the answer is known: The GeoTIFF loses the end of its pixel data but keeps a readable header, so failures appear only while reading tiles. The run must stop and leave no output.

## Imagery and classification

### `landcover.date_mismatch.001`

Imagery and DEM acquired years apart (canonical).

- Operation: `landcover.temporal_check`
- Expected status: `success`
- Oracle: `date_arithmetic`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: imagery, temporal, negative
- How the answer is known: 2015-09-01 to 2022-06-15 is 2479 whole days, well beyond the case's limit of 365 days.

### `landcover.image_collar.001`

Zero-filled image collar stays unclassified (extended).

- Operation: `landcover.classify`
- Expected status: `success`
- Oracle: `synthetic_scene_labels`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: imagery, classification, nodata
- How the answer is known: The first 16 columns are zero in all four bands and have no NoData flag, like a scene's collar. The expected class there is 0.

### `landcover.missing_nir.001`

Three-band imagery with no NIR (canonical).

- Operation: `landcover.pair_check`
- Expected status: `rejection`
- Oracle: `input_contract`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: imagery, negative, input-contract
- How the answer is known: The contract needs red, green, blue, and NIR. This file has three bands.

### `landcover.pair.dem.001`

Imagery paired with a DEM (canonical).

- Operation: `landcover.pair_check`
- Expected status: `success`
- Oracle: `input_contract`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: pairing, imagery, dem, input-contract
- How the answer is known: One image plus one DEM is a valid pair. A bare-earth surface has no canopy height.

### `landcover.pair.lidar.001`

Imagery paired with a LAS point cloud (canonical).

- Operation: `lidar.chm`
- Expected status: `success`
- Oracle: `constructed_heights`
- Formats: LAS 1.4 point format 6, GeoTIFF 1.1
- Needs: lidar, raster
- Tags: pairing, lidar, canopy, input-contract
- How the answer is known: Trees sit exactly 12 m and a roof exactly 6 m above z = 1600 + 0.02 x + 0.01 y. Points are stratified at 4 per m2, so a cell's top can differ from the true height only by the ground's tilt within it. Cells within 3 m of a block edge can mix surfaces and aren't compared. The roof interior has no ground returns, so it may be NoData. lidar.ground_gap.001 covers gap filling.

### `landcover.sampling_spread.001`

Training samples must reach the whole scene (extended).

- Operation: `landcover.classify`
- Expected status: `success`
- Oracle: `synthetic_scene_labels`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: imagery, classification, sampling
- How the answer is known: Each class has a different spectrum on either side of the midline. A sample limit that fills up in the first tiles never sees the second zone, and half the scene is misclassified.

### `landcover.scene.rgbnir.001`

RGB and NIR scene with known classes (canonical).

- Operation: `landcover.classify`
- Expected status: `success`
- Oracle: `synthetic_scene_labels`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: imagery, classification, synthetic
- How the answer is known: Labels are assigned before pixels exist. Each pixel is drawn from its class's spectrum plus noise of 6 DN, far smaller than the gaps between spectra.

### `landcover.spatial_leakage.001`

Holdout scores must not reward location (extended).

- Operation: `landcover.holdout`
- Expected status: `success`
- Oracle: `information_bound`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: classification, validation, spatial-autocorrelation
- How the answer is known: Bands hold map position and noise, and classes are random 16 m blocks. A model can only memorize where each class lies, so accuracy on unseen blocks can't beat chance by much. With 6 classes, chance is 0.17.

### `landcover.truth_mask.001`

Scoring with an unlabeled mask (canonical).

- Operation: `landcover.evaluate`
- Expected status: `success`
- Oracle: `hand_counted_confusion`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: classification, metrics, mask
- How the answer is known: Of 100 pixels, 20 are unlabeled and 80 count. 8 of the 40 bare ground pixels are called water, so 72 are right and accuracy is 0.9. F1 is 80 / 88 for water and 64 / 72 for bare ground. Counting unlabeled pixels as correct would give 0.92.

### `landcover.unknown.001`

Accuracy when most pixels are unclassified (canonical).

- Operation: `landcover.evaluate`
- Expected status: `success`
- Oracle: `hand_counted_confusion`
- Formats: GeoTIFF 1.1
- Needs: raster
- Tags: classification, metrics, nodata, coverage
- How the answer is known: All 1600 pixels are labeled, and only 80 received a class, all correct. Overall accuracy and coverage are both 80 / 1600 = 0.05. Accuracy over classified pixels alone would read 1.0.

## LiDAR

### `lidar.density.001`

Point density below a threshold (canonical).

- Operation: `lidar.density`
- Expected status: `success`
- Oracle: `point_count`
- Formats: LAS 1.4 point format 6
- Needs: lidar
- Tags: lidar, density, negative
- How the answer is known: One point falls in each cell of a 40 by 40 grid, so 1600 points over 1600 m2 is 1 point per m2. The scenario requires 2.

### `lidar.ground_gap.001`

Canopy height with no ground returns beneath (extended).

- Operation: `lidar.chm`
- Expected status: `success`
- Oracle: `constructed_heights`
- Formats: LAS 1.4 point format 6, GeoTIFF 1.1
- Needs: lidar, raster
- Tags: lidar, canopy, gaps
- How the answer is known: A 30 by 30 m canopy block has no ground returns, and its height above the plane is 12 m. The target has to interpolate ground across the gap. The 1.5 m tolerance allows for interpolating over 15 m.

### `lidar.vertical_mismatch.001`

LAS heights in feet over a DEM in metres (canonical).

- Operation: `lidar.vertical_check`
- Expected status: `success`
- Oracle: `constructed_heights`
- Formats: LAS 1.4 point format 6, GeoTIFF 1.1
- Needs: lidar, raster
- Tags: lidar, vertical, negative
- How the answer is known: Ground point heights are the DEM surface divided by 0.3048, so every height ratio is 1 / 0.3048.

## Data engineering

### `ingest.deletion.001`

Source deletes a feature (canonical).

- Operation: `ingest.diff`
- Expected status: `success`
- Oracle: `constructed_change`
- Formats: RFC 7946 GeoJSON
- Needs: vector
- Tags: ingestion, deletion, drift
- How the answer is known: Feature f4 is removed from a 10 feature source, and the rest are byte-for-byte the same.

### `ingest.integrity.001`

Source fails its published checksum (canonical).

- Operation: `ingest.integrity`
- Expected status: `rejection`
- Oracle: `sha256`
- Formats: RFC 7946 GeoJSON
- Needs: vector
- Tags: ingestion, integrity, negative
- How the answer is known: The checksum line is computed before one feature is added to the file, so the hashes can't match.

### `ingest.pagination.001`

Paged source missing a page (canonical).

- Operation: `ingest.pagination`
- Expected status: `success`
- Oracle: `constructed_change`
- Formats: RFC 7946 GeoJSON
- Needs: vector
- Tags: ingestion, pagination, negative
- How the answer is known: The index promises 5 pages of 10 features. Page 3 isn't delivered, so 40 of 50 arrive.

### `ingest.schema_added.001`

Source adds a field (canonical).

- Operation: `ingest.diff`
- Expected status: `success`
- Oracle: `constructed_change`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: ingestion, schema, drift
- How the answer is known: The after file repeats the before file with one new column, zone_code. Nothing else changes.

### `ingest.split_merge.001`

Split, merged, and ambiguous lineage (canonical).

- Operation: `ingest.lineage`
- Expected status: `success`
- Oracle: `constructed_change`
- Formats: GeoParquet 1.1.0
- Needs: vector
- Tags: ingestion, lineage, drift
- How the answer is known: A splits into two halves and B plus C merge, with shared edges kept. D is unchanged. E1 overlaps only half of E, so that link has to be reported as ambiguous.

### `ingest.unchanged_count.001`

Geometry changes while the count and date hold still (canonical).

- Operation: `ingest.diff`
- Expected status: `success`
- Oracle: `constructed_change`
- Formats: RFC 7946 GeoJSON
- Needs: vector
- Tags: ingestion, geometry, drift
- How the answer is known: Feature f3 moves one grid row north. The count and modified date stay equal, and the after file is in reverse order.
