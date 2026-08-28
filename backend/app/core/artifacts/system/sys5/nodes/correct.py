"""Inner subgraph node: the single correction attempt, fed the combined issue
list from the hallucination check and/or both validation passes."""
from __future__ import annotations

from pydantic import BaseModel

from ..agents import run_agent_with_structured_output
from ..prompts import get_prompt
from ..schema import TestCase, TestStep
from ..state import TestCaseState


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


def build(llm, tools: list, settings):
    def node(state: TestCaseState) -> TestCaseState:
        req = state["requirement"]
        test_case = state["test_case"]
        issues = _collect_issues(state)

        prompt = get_prompt("correct", settings)
        user_input = (
            f"Requirement {req.req_id}: {req.description}\n\n"
            f"Original test case:\n{test_case.model_dump_json(indent=2)}\n\n"
            f"Issues to resolve:\n" + "\n".join(f"- {i}" for i in issues)
        )
        result, _ = run_agent_with_structured_output(llm, tools, prompt, user_input, _CorrectedTestCase)

        corrected = test_case.model_copy(update={"description": result.description, "steps": result.steps})
        return {**state, "test_case": corrected, "issues": [], "correction_attempted": True}

    return node
