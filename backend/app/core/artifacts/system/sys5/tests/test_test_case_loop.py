"""Verifies the concurrent test-case loop preserves the mandatory 1:1
test-pattern-to-test-case mapping, deterministic ID assignment order, and the
hard-crash safety net - all without a real LLM (a fake compiled subgraph
stands in for test_case_graph)."""
from __future__ import annotations

import time

from ..nodes.test_case_loop import build
from ..pipeline_config import PipelineConfig
from ..schema import Requirement, TestCase, TestPatternRow


def _requirement(req_id: str) -> Requirement:
    return Requirement(req_id=req_id, description="desc", category="Functional Requirement")


def _row(n: int, scenario: str = "s1") -> TestPatternRow:
    return TestPatternRow(test_case_no=n, scenario_id=scenario, fixed_values={"Truck Size": f"{n}t"}, variable_transitions={})


class _FakeGraph:
    """Stands in for the compiled inner subgraph: sleeps briefly (to make
    concurrency actually matter) and returns a clean TestCase keyed by the
    input row's fixed_values, so callers can verify each row's own result
    came back rather than a mixed-up one."""

    def __init__(self, fail_on: set[int] | None = None):
        self.fail_on = fail_on or set()

    def invoke(self, payload: dict) -> dict:
        row = payload["pattern_row"]
        if row.test_case_no in self.fail_on:
            raise RuntimeError(f"simulated failure for row {row.test_case_no}")
        time.sleep(0.01)
        tc = TestCase(
            test_case_id="PENDING",
            feature="Slope_Assist",
            requirement_ids=[payload["requirement"].req_id],
            description=f"row {row.test_case_no}",
            steps=[],
            status="clean",
        )
        return {"final_test_case": tc}


def _context_builder(state, req):
    return {"feature_name": "Slope_Assist"}


def test_concurrent_execution_preserves_1_to_1_mapping_and_order():
    pipeline_config = PipelineConfig(max_concurrent_test_cases=4, test_case_id_prefix="TMHC_SQTC")
    node = build(_FakeGraph(), _context_builder, pipeline_config)

    rows = [_row(n) for n in range(1, 13)]
    state = {"requirements": [_requirement("REQ-1")], "test_patterns": {"REQ-1": rows}}

    result = node(state)
    test_cases = result["test_cases"]

    assert len(test_cases) == 12  # 1:1 with the 12 input rows
    assert [tc.test_case_id for tc in test_cases] == [f"TMHC_SQTC_{i}" for i in range(1, 13)]
    assert [tc.description for tc in test_cases] == [f"row {n}" for n in range(1, 13)]
    assert all(tc.status == "clean" for tc in test_cases)


def test_sequential_mode_matches_concurrent_mode():
    rows = [_row(n) for n in range(1, 6)]
    state = {"requirements": [_requirement("REQ-1")], "test_patterns": {"REQ-1": rows}}

    seq_config = PipelineConfig(max_concurrent_test_cases=1)
    seq_result = build(_FakeGraph(), _context_builder, seq_config)(state)

    par_config = PipelineConfig(max_concurrent_test_cases=4)
    par_result = build(_FakeGraph(), _context_builder, par_config)(state)

    assert [tc.test_case_id for tc in seq_result["test_cases"]] == [tc.test_case_id for tc in par_result["test_cases"]]
    assert [tc.description for tc in seq_result["test_cases"]] == [tc.description for tc in par_result["test_cases"]]


def test_a_single_row_crash_is_flagged_not_dropped():
    pipeline_config = PipelineConfig(max_concurrent_test_cases=4)
    node = build(_FakeGraph(fail_on={2}), _context_builder, pipeline_config)

    rows = [_row(n) for n in range(1, 5)]
    state = {"requirements": [_requirement("REQ-1")], "test_patterns": {"REQ-1": rows}}

    result = node(state)
    test_cases = result["test_cases"]

    assert len(test_cases) == 4  # crash on row 2 does not drop it from output
    flagged = [tc for tc in test_cases if tc.status == "flagged"]
    assert len(flagged) == 1
    assert "simulated failure for row 2" in flagged[0].flag_reason
