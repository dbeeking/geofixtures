"""Write docs/cases.md from the case registry."""

from __future__ import annotations

from pathlib import Path

from geofixtures import list_cases

TARGET = Path(__file__).parents[1] / "docs" / "cases.md"
_TITLES = {
    "vector": "Vector topology",
    "crs": "CRS and units",
    "raster": "Raster and terrain",
    "landcover": "Imagery and classification",
    "lidar": "LiDAR",
    "ingestion": "Data engineering",
}


def render() -> str:
    lines = [
        "# Case catalog",
        "",
        "This file comes from `scripts/render_catalog.py`. Don't edit it by hand.",
        "",
        "Canonical cases make up the 36 case release catalog. Extended cases are extra checks that",
        "run with `--select suite:extended` or `--select suite:all`.",
        "",
    ]
    cases = list_cases()
    for category, title in _TITLES.items():
        lines += [f"## {title}", ""]
        for case in cases:
            if case["category"] != category:
                continue
            kind = "canonical" if case["canonical"] else "extended"
            lines += [
                f"### `{case['case_id']}`",
                "",
                f"{case['title']} ({kind}).",
                "",
                f"- Operation: `{case['operation']}`",
                f"- Expected status: `{case['expected_status']}`",
                f"- Oracle: `{case['oracle_method']}`",
                f"- Formats: {', '.join(case['formats'])}",
                f"- Needs: {', '.join(case['requires'])}",
                f"- Tags: {', '.join(case['tags'])}",
                f"- How the answer is known: {case['derivation']}",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    TARGET.write_text(render())
