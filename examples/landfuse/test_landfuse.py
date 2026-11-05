import pytest

plugin = pytest.importorskip("geofixtures.pytest_plugin")
pytest.importorskip("landfuse")


@pytest.mark.parametrize("case_id", plugin.case_params("suite:landfuse"))
def test_landfuse(case_id, run_fixture):
    run_fixture(case_id, adapter="landfuse", timeout=300)
