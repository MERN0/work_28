"""Outer-graph node: invoke the inner per-test-case subgraph once per
test-pattern row. A hard crash on any one row is caught and turned into a
flagged placeholder so the mandatory 1:1 test-pattern-to-test-case mapping
survives even a total failure on one row.

Rows are independent units of work (each gets its own fresh TestCaseState,
reading only from the shared read-only store/tools), so this CAN run them
concurrently - up to `pipeline_config.max_concurrent_test_cases` at once -
rather than strictly sequentially, and that's the single biggest lever on
wall-clock time for a requirement with many test-pattern rows (e.g. a
24-row Test Pattern was the original >25-minute case). It currently
defaults to 1 (fully sequential, one test-pattern row at a time) though -
see that field's comment in pipeline_config.py for why: real output against
the deployed backend degraded on later rows under concurrent load. Raise it
past 1 only against a deployment confirmed not to have that problem.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ..logging_utils import get_logger
from ..pipeline_config import PipelineConfig
from ..schema import TestCase
from ..state import PipelineState

_logger = get_logger(__name__)


def _run_one(test_case_graph, req, row, context) -> TestCase:
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
        return out["final_test_case"]
    except Exception as exc:  # noqa: BLE001 - deliberate hard-crash safety net
        _logger.exception("test case generation crashed: req=%s scenario=%s", req.req_id, row.scenario_id)
        return TestCase(
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


def build(test_case_graph, context_builder: Callable[[PipelineState, Any], dict], pipeline_config: PipelineConfig = None):
    max_workers = max(1, (pipeline_config.max_concurrent_test_cases if pipeline_config else 1))
    id_prefix = pipeline_config.test_case_id_prefix if pipeline_config else "TMHC_SQTC"

    def node(state: PipelineState) -> PipelineState:
        work: list[tuple[Any, Any, dict]] = []
        for req in state["requirements"]:
            rows = state.get("test_patterns", {}).get(req.req_id, [])
            context = context_builder(state, req)
            for row in rows:
                work.append((req, row, context))

        total = len(work)
        _logger.info("test_case_loop: %d test-pattern row(s) to process, max_concurrent=%d", total, max_workers)
        started = time.monotonic()

        if max_workers <= 1:
            results = [_run_one(test_case_graph, req, row, context) for req, row, context in work]
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                results = list(executor.map(lambda w: _run_one(test_case_graph, *w), work))

        test_cases: list[TestCase] = []
        for counter, (final, (req, row, _context)) in enumerate(zip(results, work), start=1):
            final.test_case_id = f"{id_prefix}_{counter}"
            final.remarks_summary = " - ".join(str(v) for v in row.fixed_values.values())
            test_cases.append(final)

        flagged = sum(1 for tc in test_cases if tc.status == "flagged")
        _logger.info(
            "test_case_loop: done in %.1fs - %d test case(s) generated, %d flagged for review",
            time.monotonic() - started, len(test_cases), flagged,
        )
        return {**state, "test_cases": test_cases}

    return node
