from __future__ import annotations

from dataclasses import replace

import pytest

from geofixtures import describe_case, list_cases
from geofixtures import registry as registry_module
from geofixtures.models import CaseNotFoundError, CaseSpec
from geofixtures.registry import LANDFUSE_CASES, SMOKE_CASES, Registry, _collect, default_registry


def test_catalog_has_required_counts():
    cases = list_cases(["suite:canonical"])
    assert len(cases) == 36
    counts = {}
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {"vector": 8, "crs": 5, "raster": 8, "landcover": 7, "lidar": 2, "ingestion": 6}


def test_extended_suite_is_separate():
    assert len(list_cases(["suite:extended"])) == 6
    assert len(list_cases(["suite:all"])) == 42


def test_listing_generates_no_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert list_cases()
    assert not list(tmp_path.iterdir())


def test_cases_are_sorted():
    identifiers = [case["case_id"] for case in list_cases()]
    assert identifiers == sorted(identifiers)


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("vector.overlap.001", ["vector.overlap.001"]),
        ("id:vector.overlap.001", ["vector.overlap.001"]),
        ("id:crs.u*", ["crs.units.001"]),
        ("tag:saddle", ["raster.ridge_saddle.001"]),
        ("op:lidar.density", ["lidar.density.001"]),
    ],
)
def test_selectors(selector, expected):
    assert [case["case_id"] for case in list_cases([selector])] == expected


def test_category_selector():
    assert len(list_cases(["category:crs"])) == 5


def test_selectors_combine_with_or():
    assert len(list_cases(["category:crs", "tag:saddle"])) == 6


def test_commas_separate_selectors():
    assert len(list_cases(["tag:saddle,tag:depression"])) == 2


def test_named_suites_list_real_cases():
    ids = default_registry().ids()
    assert set(SMOKE_CASES) <= set(ids)
    assert set(LANDFUSE_CASES) <= set(ids)
    assert len(list_cases(["suite:smoke"])) == len(SMOKE_CASES)
    assert len(list_cases(["suite:landfuse"])) == len(LANDFUSE_CASES)


@pytest.mark.parametrize("selector", ["tag:none", "suite:none", "odd:thing", "nothing.here.001"])
def test_bad_selectors_raise(selector):
    with pytest.raises(CaseNotFoundError):
        list_cases([selector])


def test_unknown_case_raises():
    with pytest.raises(CaseNotFoundError):
        describe_case("vector.missing.001")


def test_describe_excludes_answers():
    case = describe_case("vector.overlap.001")
    assert "expected" not in case
    assert case["oracle_method"] == "analytic_geometry"
    assert case["derivation"]


def test_aliases_resolve_to_same_case():
    registry = default_registry()
    aliased = Registry(cases=registry.cases, aliases={"vector.old.001": "vector.overlap.001"})
    assert aliased.get("vector.old.001").case_id == "vector.overlap.001"


def test_duplicate_ids_are_refused():
    spec = default_registry().get("vector.overlap.001")
    assert isinstance(spec, CaseSpec)
    with pytest.raises(ValueError, match="Duplicate"):
        _collect([[spec], [spec]])


def test_every_case_states_how_its_answer_was_derived():
    for case in list_cases():
        assert len(case["derivation"]) > 40
        assert case["formats"]
        assert case["requires"]


def test_installed_packages_can_add_cases(monkeypatch):
    extra = replace(default_registry().get("vector.overlap.001"), case_id="thirdparty.demo.001")

    class EntryPoint:
        def load(self):
            return (extra,)

    monkeypatch.setattr(registry_module.metadata, "entry_points", lambda group: [EntryPoint()])
    assert "thirdparty.demo.001" in default_registry.__wrapped__().cases


def test_registry_cannot_be_edited():
    with pytest.raises(TypeError):
        default_registry().cases["vector.overlap.001"] = None
