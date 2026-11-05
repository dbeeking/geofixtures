from __future__ import annotations

import subprocess
import sys
import textwrap

from geofixtures import Status
from geofixtures.pytest_plugin import assert_case, case_params

_DIRECT_TEST = textwrap.dedent(
    """
    import pytest
    from geofixtures import run_case
    from geofixtures.pytest_plugin import assert_case, case_params

    @pytest.mark.parametrize("case_id", case_params("category:crs"))
    def test_case(case_id):
        assert_case(run_case(case_id, "reference"))
    """
)

_PLUGIN_TEST = textwrap.dedent(
    """
    def test_runs_case(run_fixture):
        assert run_fixture("vector.overlap.001").status == "PASS"

    def test_writes_case(materialized):
        assert materialized("vector.gap.001").manifest_path.is_file()
    """
)


def _pytest(tmp_path, source, *arguments):
    path = tmp_path / "test_generated.py"
    path.write_text(source)
    command = [sys.executable, "-m", "pytest", "-q", str(path), "--rootdir", str(tmp_path), *arguments]
    return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)


def test_case_params_use_readable_ids():
    assert [item.id for item in case_params("tag:saddle")] == ["raster.ridge_saddle.001"]


def test_explicit_import_works_without_plugin(tmp_path):
    result = _pytest(tmp_path, _DIRECT_TEST, "-p", "no:geofixtures")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "5 passed" in result.stdout


def test_plugin_fixtures_work(tmp_path):
    result = _pytest(tmp_path, _PLUGIN_TEST)
    assert result.returncode == 0, result.stdout + result.stderr


def test_plugin_failures_are_descriptive(tmp_path):
    source = textwrap.dedent(
        """
        from geofixtures import Capability, ObservationBundle

        class Wrong:
            name = "wrong"
            def supports(self, case):
                return Capability(True)
            def execute(self, context):
                return ObservationBundle(values={"overlap_pairs": [], "overlap_area": 9.0, "union_area": 1.0})
            def environment(self):
                return {}

        def test_wrong(run_fixture):
            run_fixture("vector.overlap.001", adapter=Wrong())
        """
    )
    result = _pytest(tmp_path, source)
    assert result.returncode == 1
    assert "overlap_area" in result.stdout
    assert "expected: 4.0" in result.stdout


def test_unsupported_cases_skip(tmp_path):
    source = textwrap.dedent(
        """
        from geofixtures import Capability, ObservationBundle

        class Never:
            name = "never"
            def supports(self, case):
                return Capability(False, "Not implemented")
            def execute(self, context):
                return ObservationBundle()
            def environment(self):
                return {}

        def test_never(run_fixture):
            run_fixture("vector.overlap.001", adapter=Never())
        """
    )
    result = _pytest(tmp_path, source)
    assert result.returncode == 0
    assert "1 skipped" in result.stdout


_GAP_TEST = textwrap.dedent(
    """
    from geofixtures import Capability, ObservationBundle

    class Never:
        name = "never"
        def supports(self, case):
            return Capability(False, "Not implemented")
        def execute(self, context):
            return ObservationBundle()
        def environment(self):
            return {}

    def test_never(run_fixture):
        run_fixture("vector.overlap.001", adapter=Never())
    """
)


def test_strict_turns_gap_into_failure(tmp_path):
    result = _pytest(tmp_path, _GAP_TEST, "--geofixtures-strict")
    assert result.returncode == 1
    assert "unexpected_unsupported" in result.stdout


def test_policy_allows_listed_gap(tmp_path):
    policy = tmp_path / "policy.toml"
    policy.write_text('[allow_unsupported]\n"vector.overlap.001" = "Not built yet"\n')
    result = _pytest(tmp_path, _GAP_TEST, "--geofixtures-policy", str(policy))
    assert result.returncode == 0
    assert "1 skipped" in result.stdout


def test_policy_fails_stale_allowance(tmp_path):
    policy = tmp_path / "policy.toml"
    policy.write_text('[allow_unsupported]\n"vector.overlap.001" = "Not built yet"\n')
    source = 'def test_case(run_fixture):\n    run_fixture("vector.overlap.001")\n'
    result = _pytest(tmp_path, source, "--geofixtures-policy", str(policy))
    assert result.returncode == 1
    assert "stale_allowance" in result.stdout


def test_assert_case_accepts_pass():
    class Passed:
        case_id = "x"
        status = Status.PASS
        reason = ""

    assert_case(Passed())


def test_adapter_option_is_registered(tmp_path):
    result = _pytest(tmp_path, "def test_nothing():\n    pass\n", "--geofixtures-adapter", "reference")
    assert result.returncode == 0
