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


def _no_llm_call(*args, **kwargs):
    raise AssertionError("no LLM call expected for a clean fast-path row")


def test_clean_functional_and_heading_rows_fast_path_no_llm_call(monkeypatch):
    rows = [
        _row("", "Slope Assist Requirements", "Heading"),
        _row("REQ-1", "desc1", "Functional Requirement"),
    ]
    monkeypatch.setattr(requirements_extract, "run_agent_with_structured_output", _no_llm_call)

    node = requirements_extract.build(_FakeStore(rows), llm=None, tools=[], pipeline_config=PipelineConfig())
    state = node({})

    assert [r.req_id for r in state["requirements"]] == ["REQ-1"]
    assert [h.category for h in state["heading_info"]] == ["Heading"]


def test_clean_non_functional_and_configuration_rows_never_produce_test_cases(monkeypatch):
    """Only Category == 'Functional Requirement' may ever become a testable
    Requirement; every other known category (including a clean,
    non-ambiguous match) is recognized but dropped - it must not leak into
    `requirements` (test cases) or `heading_info` (agent context) either."""
    rows = [
        _row("REQ-NFR", "a non-functional requirement", "NonFunctional Requirement"),
        _row("REQ-CFG", "a configuration requirement", "Configuration Requirement"),
        _row("REQ-SEC", "a security requirement", "Security Requirement"),
    ]
    monkeypatch.setattr(requirements_extract, "run_agent_with_structured_output", _no_llm_call)

    node = requirements_extract.build(_FakeStore(rows), llm=None, tools=[], pipeline_config=PipelineConfig())
    state = node({})

    assert state["requirements"] == []
    assert state["heading_info"] == []


def test_non_functional_requirement_is_never_silently_fast_pathed_as_functional(monkeypatch):
    """Regression test for a real collision: rapidfuzz's token_sort_ratio
    scores 'Non Functional Requirement' (space-separated, not an exact
    vocabulary match) against 'Functional Requirement' at ~91.7 - above the
    old category_match_threshold=85 default, which silently turned a
    non-functional row into a testable requirement via the deterministic
    fast path. It must escalate to the LLM instead (never guessed by
    Python), and the LLM's correct answer must still exclude it from
    `requirements`."""
    rows = [_row("REQ-2", "desc2", "Non Functional Requirement")]

    escalated_inputs = []

    def _stub(llm, tools, prompt, user_input, schema, pipeline_config=None):
        escalated_inputs.append(user_input)
        return schema(rows=[{"row_index": 0, "category": "NonFunctional Requirement"}]), "stubbed"

    monkeypatch.setattr(requirements_extract, "run_agent_with_structured_output", _stub)

    node = requirements_extract.build(_FakeStore(rows), llm=None, tools=[], pipeline_config=PipelineConfig())
    state = node({})

    assert escalated_inputs, "an ambiguous non-functional category must escalate to the LLM, not be fast-pathed"
    assert state["requirements"] == []
    assert state["heading_info"] == []


def test_functional_requirement_typo_still_fast_paths(monkeypatch):
    """The stricter threshold (95) must not break genuine typo tolerance -
    only reject the specific Functional/NonFunctional collision shape."""
    rows = [_row("REQ-3", "desc3", "Functional Requirment")]  # missing 'e'
    monkeypatch.setattr(requirements_extract, "run_agent_with_structured_output", _no_llm_call)

    node = requirements_extract.build(_FakeStore(rows), llm=None, tools=[], pipeline_config=PipelineConfig())
    state = node({})

    assert [r.req_id for r in state["requirements"]] == ["REQ-3"]
