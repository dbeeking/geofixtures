from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _copy(name: str, target: Path) -> Path:
    destination = target / name
    shutil.copytree(ROOT / "examples" / name, destination)
    return destination


def test_quickstart_pytest_example_runs_in_clean_folder(tmp_path):
    folder = _copy("quickstart", tmp_path)
    command = [sys.executable, "-m", "pytest", "-q", "--rootdir", str(folder), str(folder)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_quickstart_command_line_example_runs_in_clean_folder(tmp_path):
    folder = _copy("quickstart", tmp_path)
    command = [
        sys.executable,
        "-m",
        "geofixtures",
        "run",
        "--adapter",
        "my_adapter:OverlapAdapter",
        "--select",
        "vector.overlap.001",
        "--report",
        "report.json",
    ]
    environment = {**os.environ, "PYTHONPATH": str(folder)}
    result = subprocess.run(
        command, cwd=folder, env=environment, capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (folder / "report.json").is_file()


@pytest.mark.skipif(util.find_spec("landfuse") is None, reason="Needs LandFuse")
def test_landfuse_example_collects_suite(tmp_path):
    folder = _copy("landfuse", tmp_path)
    command = [sys.executable, "-m", "pytest", "-q", "--collect-only", "--rootdir", str(folder), str(folder)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "21 tests collected" in result.stdout


def test_landfuse_example_skips_without_geofixtures(tmp_path):
    folder = _copy("landfuse", tmp_path)
    (folder / "test_other.py").write_text("def test_other():\n    pass\n")
    code = (
        "import sys\n"
        "sys.modules['geofixtures'] = None\n"
        "import pytest\n"
        "raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', sys.argv[1]]))\n"
    )
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [sys.executable, "-c", code, str(folder)]
    result = subprocess.run(
        command, env=environment, capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 skipped" in result.stdout


def test_case_catalog_document_is_current():
    from render_catalog import TARGET, render

    assert TARGET.read_text() == render(), "Run python scripts/render_catalog.py"


def test_documented_commands_name_real_subcommands():
    readme = (ROOT / "README.md").read_text()
    for command in ("list", "describe", "generate", "validate", "run", "report", "doctor"):
        assert f"geofixtures {command}" in readme
