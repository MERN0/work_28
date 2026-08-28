"""Inner subgraph nodes: the two always-run semantic validation passes
(requirement-fidelity and engineering-plausibility - two distinct rubrics,
per plan §E)."""
from __future__ import annotations

from ..agents import run_agent_with_structured_output
from ..prompts import get_prompt
from ..schema import ValidationResult
from ..state import TestCaseState


def _build(rubric_stage: str, result_key: str, llm, tools: list, settings):
    def node(state: TestCaseState) -> TestCaseState:
        req = state["requirement"]
        test_case = state["test_case"]
        prompt = get_prompt(rubric_stage, settings)
        user_input = (
            f"Requirement {req.req_id}: {req.description}\n"
            f"Verification Criteria: {req.verification_criteria}\n\n"
            f"Test case under review:\n{test_case.model_dump_json(indent=2)}"
        )
        result, _ = run_agent_with_structured_output(llm, tools, prompt, user_input, ValidationResult)
        return {**state, result_key: result}

    return node


def build_pass1(llm, tools: list, settings):
    return _build("validate_pass1", "pass1_result", llm, tools, settings)


def build_pass2(llm, tools: list, settings):
    return _build("validate_pass2", "pass2_result", llm, tools, settings)
