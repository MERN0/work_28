"""Inner subgraph node: the single correction attempt, fed the combined issue
list from the hallucination check and/or both validation passes."""
from __future__ import annotations

from pydantic import BaseModel

from ..agents import call_llm
from ..logging_utils import get_logger
from ..prompts import get_prompt
from ..schema import TestCase, TestStep, derive_ref_kind
from ..state import TestCaseState

_logger = get_logger(__name__)


class _CorrectedTestCase(BaseModel):
    description: str
    steps: list[TestStep]


def _collect_issues(state: TestCaseState) -> list[str]:
    issues = list(state.get("issues", []))
    for key in ("pass1_result", "pass2_result"):
        result = state.get(key)
        if result and not result.passed:
            issues.extend(f"[{result.rubric}] {issue.message}" for issue in result.issues)
    return issues


def build(llm, settings, pipeline_config=None):
    def node(state: TestCaseState) -> TestCaseState:
        req = state["requirement"]
        test_case = state["test_case"]
        context = state.get("context", {})
        issues = _collect_issues(state)
        _logger.info("correcting test case: req=%s issues=%d", req.req_id, len(issues))

        prompt = get_prompt("correct", settings)
        user_input = (
            f"Requirement {req.req_id}: {req.description}\n\n"
            f"Original test case:\n{test_case.model_dump_json(indent=2)}\n\n"
            f"Issues to resolve:\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
            f"This feature's valid signals, with their real Command List candidates for SDO_Set/SDO_Verify "
            f"(pick the best-scoring candidate - never invent a CAN_* name that isn't listed here):\n"
            + "\n".join(context.get("signal_reference", [])) + "\n"
            f"Available tolerances (Config_Tol_*):\n" + "\n".join(context.get("tolerances", [])) + "\n"
            f"Selected compound commands (full step detail - use these exact names):\n"
            + "\n".join(context.get("compound_command_details", [])) + "\n"
            f"Selected library calls (use these exact bare names):\n"
            + "\n".join(context.get("library_details", []))
        )
        result = call_llm(llm, prompt, user_input, _CorrectedTestCase, pipeline_config=pipeline_config)
        # Same rule as generate.py: keyword alone determines ref_kind, never
        # trust the LLM's own answer for it.
        steps = [s.model_copy(update={"ref_kind": derive_ref_kind(s.keyword)}) for s in result.steps]

        corrected = test_case.model_copy(update={"description": result.description, "steps": steps})
        return {**state, "test_case": corrected, "issues": [], "correction_attempted": True}

    return node
