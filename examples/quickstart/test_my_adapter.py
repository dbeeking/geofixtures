import pytest
from my_adapter import OverlapAdapter

from geofixtures.pytest_plugin import case_params


@pytest.mark.parametrize("case_id", case_params("vector.overlap.001"))
def test_overlap(case_id, run_fixture):
    run_fixture(case_id, adapter=OverlapAdapter())
