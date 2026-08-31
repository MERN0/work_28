"""Inner subgraph node: deterministic, cheap, structural hallucination
guardrail. Every step's target_ref must literally exist (fuzzy-matched) in
the parsed source data - this is separate from, and always runs before/after,
the two semantic validation passes (plan §C / Validation loop)."""
from __future__ import annotations

from ..logging_utils import get_logger
from ..state import TestCaseState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def build(store: InMemoryWorkbookStore, pipeline_config=None):
    threshold = pipeline_config.hallucination_match_threshold if pipeline_config else None

    def node(state: TestCaseState) -> TestCaseState:
        test_case = state["test_case"]
        bad: list[str] = []
        for step in test_case.steps:
            if step.ref_kind != "none" and step.target_ref:
                if not store.exists(step.ref_kind, step.target_ref, fuzzy_threshold=threshold):
                    bad.append(f"Step {step.step_no}: {step.ref_kind} {step.target_ref!r} was not found in the source data")
        if bad:
            _logger.warning("hallucination_check: req=%s FAILED - %s", state["requirement"].req_id, "; ".join(bad))
        return {**state, "hallucination_ok": not bad, "issues": [*state.get("issues", []), *bad]}

    return node
