"""Import layering checks."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[2] / "src" / "geofixtures"


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _files(folder: str) -> list[Path]:
    return sorted((PACKAGE / folder).glob("*.py"))


@pytest.mark.parametrize("folder", ["generators", "oracles", "io", "cases"])
def test_data_layers_do_not_know_about_adapters_or_runner(folder):
    for path in _files(folder):
        for name in _imports(path):
            assert "adapters" not in name and "runner" not in name, f"{path.name} imports {name}"


def test_oracles_do_not_import_generators():
    for path in _files("oracles"):
        assert not any("generators" in name for name in _imports(path)), path.name


def test_generators_do_not_import_oracles():
    for path in _files("generators"):
        assert not any("oracles" in name for name in _imports(path)), path.name


def test_analytic_oracles_use_no_geometry_engine():
    for name in ("analytic.py", "geometry.py"):
        imports = _imports(PACKAGE / "oracles" / name)
        assert not imports & {"shapely", "pyproj", "rasterio"}


def test_reference_adapter_is_independent_of_oracles():
    path = PACKAGE / "adapters" / "reference.py"
    assert not any("oracles" in name or "cases" in name for name in _imports(path))
    source = path.read_text()
    assert "truth/" not in source and "expected.json" not in source


def test_landfuse_adapter_does_not_read_truth():
    source = (PACKAGE / "adapters" / "landfuse.py").read_text()
    assert "truth/" not in source and "expected.json" not in source


def test_core_runs_without_optional_packages_at_import_time():
    optional = {"pyarrow", "pyproj", "shapely", "rasterio", "laspy", "landfuse"}
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        for node in top_level:
            names = (
                {alias.name for alias in node.names} if isinstance(node, ast.Import) else {node.module or ""}
            )
            assert not {name.split(".")[0] for name in names} & optional, path
