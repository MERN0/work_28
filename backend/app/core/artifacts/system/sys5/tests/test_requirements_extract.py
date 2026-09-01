from __future__ import annotations

from ..nodes import requirements_extract
from ..pipeline_config import PipelineConfig


class _FakeStore:
    """Minimal stand-in for InMemoryWorkbookStore: requirements_extract only
    ever calls get_requirement_rows() on the store."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_requirement_rows(self) -> list[dict]:
        return self._rows


def _row(req_id: str, description: str, category: str) -> dict:
    return {
        "Requirement ID": req_id, "Requirement Description": description, "Category": category,
        "Variant": "", "Priority": "", "Verification Method": "", "Verification Criteria": "",
        "Verification Stage": "", "Source": "", "Status": "", "Release": "",
        "Downstream Traceability": "", "Remarks": "",
    }


def test_clean_functional_and_heading_rows_classify():
    rows = [
        _row("", "Slope Assist Requirements", "Heading"),
        _row("REQ-1", "desc1", "Functional Requirement"),
    ]

    node = requirements_extract.build(_FakeStore(rows), pipeline_config=PipelineConfig())
    state = node({})

    assert [r.req_id for r in state["requirements"]] == ["REQ-1"]
    assert [h.category for h in state["heading_info"]] == ["Heading"]


def test_clean_non_functional_and_configuration_rows_never_produce_test_cases():
    """Only Category == 'Functional Requirement' may ever become a testable
    Requirement; every other known category (including a clean,
    non-ambiguous match) is recognized but dropped - it must not leak into
    `requirements` (test cases) or `heading_info` (agent context) either."""
    rows = [
        _row("REQ-NFR", "a non-functional requirement", "NonFunctional Requirement"),
        _row("REQ-CFG", "a configuration requirement", "Configuration Requirement"),
        _row("REQ-SEC", "a security requirement", "Security Requirement"),
    ]

    node = requirements_extract.build(_FakeStore(rows), pipeline_config=PipelineConfig())
    state = node({})

    assert state["requirements"] == []
    assert state["heading_info"] == []


def test_non_functional_requirement_is_never_silently_fast_pathed_as_functional():
    """Regression test for a real collision: rapidfuzz's token_sort_ratio
    scores 'Non Functional Requirement' (space-separated, not an exact
    vocabulary match) against 'Functional Requirement' at ~91.7 - above the
    old category_match_threshold=85 default, which silently turned a
    non-functional row into a testable requirement via the deterministic
    fast path. With no LLM to disambiguate, a row that doesn't cross the
    (now stricter, 95) threshold against any known category is simply
    dropped rather than guessed - it must never fast-path as Functional."""
    rows = [_row("REQ-2", "desc2", "Non Functional Requirement")]

    node = requirements_extract.build(_FakeStore(rows), pipeline_config=PipelineConfig())
    state = node({})

    assert state["requirements"] == []
    assert state["heading_info"] == []


def test_functional_requirement_typo_still_fast_paths():
    """The stricter threshold (95) must not break genuine typo tolerance -
    only reject the specific Functional/NonFunctional collision shape."""
    rows = [_row("REQ-3", "desc3", "Functional Requirment")]  # missing 'e'

    node = requirements_extract.build(_FakeStore(rows), pipeline_config=PipelineConfig())
    state = node({})

    assert [r.req_id for r in state["requirements"]] == ["REQ-3"]
