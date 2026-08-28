"""Outer-graph node: invoke the inner per-test-case subgraph once per
test-pattern row, sequentially (plan Decision 4). A hard crash on any one
row is caught and turned into a flagged placeholder so the mandatory 1:1
test-pattern-to-test-case mapping survives even a total failure on one row.
"""
from __future__ import annotations

from typing import Any, Callable

from ..schema import TestCase
from ..state import PipelineState


def build(test_case_graph, context_builder: Callable[[PipelineState, Any], dict]):
    def node(state: PipelineState) -> PipelineState:
        test_cases: list[TestCase] = []
        counter = 1
        for req in state["requirements"]:
            rows = state.get("test_patterns", {}).get(req.req_id, [])
            context = context_builder(state, req)
            for row in rows:
                try:
                    out = test_case_graph.invoke(
                        {
                            "requirement": req,
                            "pattern_row": row,
                            "context": context,
                            "issues": [],
                            "correction_attempted": False,
                        }
                    )
                    final = out["final_test_case"]
                except Exception as exc:  # noqa: BLE001 - deliberate hard-crash safety net
                    final = TestCase(
                        test_case_id="PENDING",
                        feature=context.get("feature_name", ""),
                        variant=req.variant,
                        requirement_ids=[req.req_id],
                        priority=req.priority,
                        description=f"ERROR generating test case for {req.req_id} (scenario {row.scenario_id})",
                        steps=[],
                        status="flagged",
                        flag_reason=f"Unhandled error during generation: {exc}",
                    )
                final.test_case_id = f"TMHC_SQTC_{counter}"
                final.remarks_summary = " - ".join(str(v) for v in row.fixed_values.values())
                test_cases.append(final)
                counter += 1
        return {**state, "test_cases": test_cases}

    return node
