# Oracles

| Method | Source | Example |
| --- | --- | --- |
| `analytic_geometry` | Coordinates and arithmetic | Overlap of two rectangles |
| `analytic_surface` | Derivatives of a known function | Slope of a plane |
| `transverse_mercator_series` | Sixth-order Krueger series | UTM control points |
| `constructed_heights` | Heights set while building the file | Trees 12 m above a plane |
| `constructed_change` | Edits between two snapshots | One deleted feature |
| `synthetic_scene_labels` | Classes set before pixels are drawn | Block scene |
| `hand_counted_confusion` | Counts worked out by hand | 72 of 80 correct |
| `pixel_center_rule`, `grid_geometry` | A stated rule on known coordinates | 400 restricted pixels |
| `control_distance` | Known length against file length | Feet under a metre label |
| `information_bound` | Data with no usable signal | Holdout on position-only bands |
| `range_rule`, `datum_state`, `input_contract`, `date_arithmetic`, `point_count`, `corruption_rule`, `sha256` | Deterministic rules | Latitude beyond 90 degrees |

All built-in truth is analytical or synthetic. Annotated real-world labels will use the review status
`annotated` when they're added.

## Independence

- `oracles/analytic.py` and `oracles/geometry.py` use plain arithmetic.
- The UTM series is tested against PROJ.
- `adapters/reference.py` doesn't import oracles or read truth.
- `tests/unit/test_oracles.py` uses literal hand-worked values.
- `tests/contract/test_every_case_can_fail.py` corrupts each observation.

A reference pass shows the catalog agrees with the libraries the reference adapter uses.

## Review

Each oracle needs review by someone other than its author before release. None has been reviewed, so
every manifest says `pending_independent_review`.

## Thresholds

Pass criteria are set in the case. They don't depend on which target scored best. Classification
thresholds are high because synthetic classes are well separated.
